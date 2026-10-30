"""Driver contract, read-only enforcement, saved-report declarations and cleanup."""
import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from taskweave.plugins.registry import Registry
from taskweave.core.validation import TaskError
from taskweave_tidb import TiDBPlugin, configuration, select_sql, DatabaseAction


class TiDBTests(unittest.TestCase):
    def context(self, **overrides):
        return SimpleNamespace(environment={'tidb_host': 'localhost', 'tidb_database': 'uat', 'tidb_username': 'reader', 'tidb_password': 'secret', 'tidb_tls': False}, task_parameters=overrides, cancelled=lambda: False)

    def test_parameterized_queries_ctes_and_write_rejection(self):
        for sql in ['SELECT * FROM orders WHERE order_no = %s', 'WITH t AS (SELECT 1) SELECT * FROM t', 'SELECT "%s" AS v']:
            select_sql(sql)
        for sql in ['DELETE FROM orders', 'SELECT 1; SELECT 2', 'SELECT * FROM t FOR UPDATE', 'SELECT 1 INTO OUTFILE "/tmp/x"', 'WITH t AS (SELECT 1) DELETE FROM orders', '/* a */ UPDATE orders SET status=1']:
            with self.assertRaises(TaskError): select_sql(sql)

    def test_variables_url_and_task_override(self):
        self.assertEqual(configuration(self.context(tidb_database='dev'))['database'], 'dev')
        ctx = self.context();ctx.environment = {'tidb_connection_url': 'mysql://reader:p%40ss@db:4000/uat?ssl_verify_cert=true'}
        config = configuration(ctx)
        self.assertEqual(config['password'], 'p@ss');self.assertTrue(config['tls'])
        with self.assertRaises(TaskError): configuration(self.context(tidb_timeout_seconds=0))

    def test_query_binding_json_conversion_truncation_and_cleanup(self):
        cursor = MagicMock();cursor.description = [('amount',), ('created',)]
        cursor.fetchmany.return_value = [(Decimal('1.20'), datetime(2026, 9, 19)), (Decimal('2'), datetime(2026, 9, 19))]
        connection = MagicMock();connection.cursor.return_value = cursor
        with patch('pymysql.connect', return_value=connection) as connect:
            result = asyncio.run(DatabaseAction('query').execute(self.context(), {'sql': 'SELECT amount, created FROM orders WHERE order_no = %s', 'params': ["x' OR 1=1"], 'max_rows': 1, 'title': '记录'}))
        self.assertEqual(cursor.execute.call_args.args, ('SELECT amount, created FROM orders WHERE order_no = %s', ["x' OR 1=1"]))
        self.assertEqual(cursor.execute.call_args_list[0].args, ('SET TRANSACTION READ ONLY',))
        self.assertEqual(result['rows'][0]['amount'], '1.20');self.assertTrue(result['truncated'])
        self.assertEqual(result['title'], '记录');self.assertNotIn('password', result['query_info'])
        connection.rollback.assert_called_once();connection.close.assert_called_once()
        self.assertEqual(connect.call_args.kwargs['database'], 'uat')

    def test_driver_error_has_no_secret_and_closes_connection(self):
        import pymysql
        cursor = MagicMock();cursor.execute.side_effect = pymysql.OperationalError(1045, 'private-password')
        connection = MagicMock();connection.cursor.return_value = cursor
        with patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError) as error:
            asyncio.run(DatabaseAction('query').execute(self.context(), {'sql': 'SELECT 1'}))
        self.assertNotIn('private-password', str(error.exception));connection.close.assert_called_once()

    def test_tidb_uses_native_read_only_snapshot_without_restarting_transaction(self):
        import pymysql
        cursor = MagicMock();cursor.description = [('answer',)]
        cursor.fetchmany.return_value = [(42,)]
        # Reproduce TiDB's rejection if the old MySQL-only transaction is used.
        events=[]
        def execute(sql, *params):
            events.append(sql)
            if sql == 'SET TRANSACTION READ ONLY':
                raise pymysql.OperationalError(1235, 'function READ ONLY has only noop implementation')
        cursor.execute.side_effect = execute
        connection = MagicMock();connection.get_server_info.return_value = '8.0.11-TiDB-v8.5.4'
        connection.cursor.return_value = cursor
        connection.begin.side_effect=lambda: events.append('begin')
        with patch('pymysql.connect', return_value=connection):
            result = asyncio.run(DatabaseAction('query').execute(self.context(), {'sql':'SELECT %s AS answer','params':[42]}))
        self.assertEqual(result['rows'], [{'answer':42}])
        self.assertEqual(cursor.execute.call_args_list[0].args, ('START TRANSACTION READ ONLY AS OF TIMESTAMP TIDB_PARSE_TSO(TIDB_CURRENT_TSO())',))
        self.assertEqual(result['query_info']['transaction_mode'], 'tidb_read_only_snapshot_tso')
        # BEGIN here would end the native snapshot transaction and remove its protection.
        self.assertEqual(events,['begin','START TRANSACTION READ ONLY AS OF TIMESTAMP TIDB_PARSE_TSO(TIDB_CURRENT_TSO())','SELECT %s AS answer'])
        connection.begin.assert_called_once()
        connection.rollback.assert_called_once();connection.close.assert_called_once()

    def test_tidb_snapshot_failure_is_not_retried_without_read_only_protection(self):
        import pymysql
        cursor=MagicMock();cursor.execute.side_effect=pymysql.OperationalError(9006,'clock ahead private-password')
        connection=MagicMock();connection.get_server_info.return_value='8.0.11-TiDB-v8.5.4'
        connection.cursor.return_value=cursor
        with patch('pymysql.connect',return_value=connection), self.assertRaises(TaskError) as error:
            asyncio.run(DatabaseAction('query').execute(self.context(),{'sql':'SELECT 1'}))
        self.assertIn('9006',str(error.exception));self.assertNotIn('private-password',str(error.exception))
        self.assertEqual(cursor.execute.call_count,1)
        connection.begin.assert_called_once();connection.rollback.assert_called_once();connection.close.assert_called_once()

    def test_tidb_uses_cluster_tso_when_server_wall_clock_is_ahead(self):
        import pymysql
        cursor=MagicMock();cursor.description=[('answer',)];cursor.fetchmany.return_value=[(42,)]
        def execute(sql,*params):
            if 'NOW(' in sql:
                raise pymysql.OperationalError(1105,'cannot set read timestamp to a future time')
        cursor.execute.side_effect=execute
        connection=MagicMock();connection.get_server_info.return_value='8.0.11-TiDB-v8.5.4'
        connection.cursor.return_value=cursor
        with patch('pymysql.connect',return_value=connection):
            result=asyncio.run(DatabaseAction('query').execute(self.context(),{'sql':'SELECT 42 AS answer'}))
        self.assertEqual(result['rows'],[{'answer':42}])
        self.assertEqual(cursor.execute.call_args_list[0].args,('START TRANSACTION READ ONLY AS OF TIMESTAMP TIDB_PARSE_TSO(TIDB_CURRENT_TSO())',))

    def test_query_disconnect_is_not_masked_by_failed_cleanup(self):
        import pymysql
        for phase in ['rollback','close']:
            with self.subTest(phase=phase):
                cursor=MagicMock();cursor.execute.side_effect=pymysql.OperationalError(2013,'private query failed')
                connection=MagicMock();connection.cursor.return_value=cursor
                getattr(connection,phase).side_effect=pymysql.InterfaceError(0,'private cleanup failed')
                with patch('pymysql.connect',return_value=connection),self.assertRaises(TaskError) as error:
                    asyncio.run(DatabaseAction('query').execute(self.context(),{'sql':'SELECT 1'}))
                self.assertIn('2013',str(error.exception));self.assertNotIn('private',str(error.exception))
                self.assertTrue(any('清理' in note for note in error.exception.__notes__))
                connection.close.assert_called_once()

    def test_cleanup_failure_does_not_report_query_success(self):
        import pymysql
        cursor=MagicMock();cursor.description=[('answer',)];cursor.fetchmany.return_value=[(42,)]
        connection=MagicMock();connection.cursor.return_value=cursor
        connection.rollback.side_effect=pymysql.InterfaceError(0,'private cleanup failed')
        with patch('pymysql.connect',return_value=connection),self.assertRaises(TaskError) as error:
            asyncio.run(DatabaseAction('query').execute(self.context(),{'sql':'SELECT 42 AS answer'}))
        self.assertIn('清理',str(error.exception));self.assertNotIn('private',str(error.exception))
        connection.close.assert_called_once()

    def test_real_streaming_cursor_drain_cannot_mask_fetch_failure(self):
        import pymysql
        connection=MagicMock()
        cursor=pymysql.cursors.SSCursor(connection)
        self.addCleanup(setattr,cursor,"connection",None)
        cursor.execute=MagicMock()
        cursor.description=[('answer',)]
        cursor.fetchmany=MagicMock(side_effect=pymysql.OperationalError(2013,'private fetch failed'))
        cursor._result=SimpleNamespace(unbuffered_active=True,has_next=False,
            _finish_unbuffered_query=MagicMock(side_effect=pymysql.InterfaceError(0,'private drain failed')))
        connection._result=cursor._result
        connection.cursor.return_value=cursor
        with patch('pymysql.connect',return_value=connection),self.assertRaises(TaskError) as error:
            asyncio.run(DatabaseAction('query').execute(self.context(),{'sql':'SELECT 42 AS answer'}))
        self.assertIn('2013',str(error.exception));self.assertNotIn('private',str(error.exception))
        self.assertTrue(any('清理' in note for note in error.exception.__notes__))
        connection.rollback.assert_called_once();connection.close.assert_called_once()
        # Stop the real cursor's destructor from repeating this deliberate failure.
        cursor.connection=None

    def test_real_network_disconnect_still_closes_connection_after_cursor_attribute_error(self):
        import pymysql
        connection=pymysql.connections.Connection(defer_connect=True)
        connection.server_version='8.0.11-TiDB-v8.5.4'
        connection._current_timeout=connection._read_timeout
        connection._sock=MagicMock();connection._rfile=MagicMock()
        connection._rfile.read.side_effect=OSError('private stream disconnect')
        result=pymysql.connections.MySQLResult(connection);result.unbuffered_active=True
        connection._result=result
        cursor=pymysql.cursors.SSCursor(connection);cursor.description=[('answer',)]
        cursor._result=result;cursor._executed='SELECT 1'
        try:
            with patch('pymysql.connect',return_value=connection),patch.object(connection,'cursor',return_value=cursor),patch.object(connection,'begin'),patch.object(cursor,'execute'),self.assertRaises(TaskError) as error:
                asyncio.run(DatabaseAction('query').execute(self.context(),{'sql':'SELECT 1'}))
            self.assertIn('2013',str(error.exception));self.assertNotIn('private',str(error.exception))
            self.assertTrue(any('清理' in note for note in error.exception.__notes__))
            self.assertTrue(connection._closed)
        finally:
            cursor.connection=None;result.unbuffered_active=False
            if not connection._closed:connection.close()

    def test_tls_schema_context_and_api_chat_contributions(self):
        cursor = MagicMock();cursor.description = [('COLUMN_NAME',)];cursor.fetchmany.return_value = [('order_no',)]
        connection = MagicMock();connection.cursor.return_value = cursor
        with patch('pymysql.connect', return_value=connection) as connect:
            result = asyncio.run(TiDBPlugin().collect_context('tidb.schema', self.context(tidb_tls=True), {'table': 'orders'}))
        self.assertIn('order_no', result.items[0].content)
        self.assertEqual(result.views[0].renderer, 'tidb.table')
        self.assertEqual(cursor.execute.call_args.args[1], ['uat', 'orders'])
        self.assertTrue(connect.call_args.kwargs['ssl_verify_identity']);self.assertTrue(connect.call_args.kwargs['ssl_verify_cert'])
        registry = Registry([TiDBPlugin()])
        self.assertIn('tidb.verification', registry.views)
        contribution = TiDBPlugin().authoring(['tidb.query'])
        self.assertIn('views=', contribution.examples[0])
        self.assertIn('本渠道不能访问本地数据库', contribution.channel_overrides['web_chat']['instructions'])
