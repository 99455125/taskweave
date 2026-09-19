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
        connection = MagicMock();connection.cursor.return_value.__enter__.return_value = cursor
        with patch('pymysql.connect', return_value=connection) as connect:
            result = asyncio.run(DatabaseAction('query').execute(self.context(), {'sql': 'SELECT amount, created FROM orders WHERE order_no = %s', 'params': ["x' OR 1=1"], 'max_rows': 1, 'title': '订单'}))
        self.assertEqual(cursor.execute.call_args.args, ('SELECT amount, created FROM orders WHERE order_no = %s', ["x' OR 1=1"]))
        self.assertEqual(cursor.execute.call_args_list[0].args, ('SET TRANSACTION READ ONLY',))
        self.assertEqual(result['rows'][0]['amount'], '1.20');self.assertTrue(result['truncated'])
        self.assertEqual(result['title'], '订单');self.assertNotIn('password', result['query_info'])
        connection.rollback.assert_called_once();connection.close.assert_called_once()
        self.assertEqual(connect.call_args.kwargs['database'], 'uat')

    def test_driver_error_has_no_secret_and_closes_connection(self):
        import pymysql
        cursor = MagicMock();cursor.execute.side_effect = pymysql.OperationalError(1045, 'private-password')
        connection = MagicMock();connection.cursor.return_value.__enter__.return_value = cursor
        with patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError) as error:
            asyncio.run(DatabaseAction('query').execute(self.context(), {'sql': 'SELECT 1'}))
        self.assertNotIn('private-password', str(error.exception));connection.close.assert_called_once()

    def test_tls_schema_context_and_api_chat_contributions(self):
        cursor = MagicMock();cursor.description = [('COLUMN_NAME',)];cursor.fetchmany.return_value = [('order_no',)]
        connection = MagicMock();connection.cursor.return_value.__enter__.return_value = cursor
        with patch('pymysql.connect', return_value=connection) as connect:
            result = asyncio.run(TiDBPlugin().collect_context('tidb.schema', self.context(tidb_tls=True), {'table': 'orders'}))
        self.assertIn('order_no', result[0].content)
        self.assertEqual(cursor.execute.call_args.args[1], ['uat', 'orders'])
        self.assertTrue(connect.call_args.kwargs['ssl_verify_identity']);self.assertTrue(connect.call_args.kwargs['ssl_verify_cert'])
        registry = Registry([TiDBPlugin()])
        self.assertIn('tidb.verification', registry.views)
        contribution = TiDBPlugin().authoring(['tidb.query'])
        self.assertIn('views=', contribution.examples[0])
        self.assertIn('Web chat cannot', contribution.channel_overrides['web_chat']['instructions'])
