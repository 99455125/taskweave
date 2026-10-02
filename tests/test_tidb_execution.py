"""Real driver and spawned step execution against a MySQL protocol fixture."""
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid
from tests.tidb_wire_fixture import MySQLFixture


class TiDBExecution(unittest.TestCase):
    def test_parameterized_query_saved_plugin_report_and_reopening(self):
        with MySQLFixture() as database, tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                app.configure_plugin('tidb', True)
                env = app.repo.save_environment('uat', {'tidb_host': '127.0.0.1', 'tidb_port': database.port, 'tidb_username': 'reader', 'tidb_password': 'secret', 'tidb_database': 'uat', 'tidb_tls': False})['environment_id']
                task = app.repo.create_task('数据库核对')['task_id']
                step = app.repo.save_step(task, {'capabilities': ['tidb.query'], 'step_content': '''async def run(ctx, inputs):
    table = await ctx.call("tidb.query", {"sql": "SELECT order_no, status FROM orders WHERE order_no=%s", "params": ["001"], "title": "订单信息"})
    report = {"passed": table["rows"][0]["status"] == "SUBMITTED", "message": "订单核对通过", "tables": [table], "query_info": table["query_info"]}
    return ctx.result(data={"order_no": "001", "verified": report["passed"], "report": report}, views=[{"title": "数据库核对", "renderer": "tidb.verification", "pointer": "/report"}])'''})
                run = app.trial_step(step['step_id'], {}, uid(), env)
                done = app.coordinator.wait(run['run_id'])
                self.assertEqual(done['status'], 'SUCCEEDED', done)
                ref = done['results'][0]
                output = app.repo.read_output(run['run_id'], step['step_id'], 'data', app.registry)
                self.assertTrue(output['verified'])
                self.assertEqual(output['report']['tables'][0]['rows'][0]['order_no'], '001')
            with Application(home) as app:
                result = app.repo.read_result(ref['result_id'], app.registry)
                self.assertEqual(result['views'][0]['renderer'], 'tidb.verification')
            self.assertFalse(database.errors, database.errors)
            self.assertIn('SET TRANSACTION READ ONLY', database.queries)
            self.assertIn("SELECT order_no, status FROM orders WHERE order_no='001'", database.queries)


"""Write SQL is explicit, bounded, parameterized and honest about commit outcomes."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from taskweave.core.validation import TaskError, validate
from taskweave_tidb import TiDBPlugin


class TiDBExecutionTests(unittest.TestCase):
    def context(self, cancelled=lambda: False):
        return SimpleNamespace(environment={'tidb_host': 'localhost', 'tidb_database': 'fixture',
            'tidb_username': 'writer', 'tidb_password': 'private', 'tidb_tls': False},
            task_parameters={}, cancelled=cancelled)

    def action(self):
        actions = TiDBPlugin().actions()
        self.assertIn('tidb.execute_sql', actions)
        return actions['tidb.execute_sql']

    def connection(self):
        cursor = MagicMock()
        cursor.description = None
        cursor.rowcount = 1
        cursor.lastrowid = 0
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection, cursor

    def test_script_binds_parameters_and_commits_only_after_all_statements(self):
        action = self.action()
        connection, cursor = self.connection()
        sql = "INSERT INTO sample(v) VALUES ('a;b'); -- 中文;说明\nUPDATE sample SET v=%s WHERE id=%s;"
        with patch('pymysql.connect', return_value=connection) as connect:
            result = asyncio.run(action.execute(self.context(), {'sql': sql,
                'statement_params': [[], ["x' OR 1=1", 7]]}))
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(cursor.execute.call_args_list[0].args, ("INSERT INTO sample(v) VALUES ('a;b')", None))
        self.assertEqual(cursor.execute.call_args_list[1].args[1], ["x' OR 1=1", 7])
        connection.begin.assert_called_once()
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once()
        self.assertFalse(connect.call_args.kwargs['autocommit'])
        self.assertEqual(result['statement_count'], 2)
        self.assertEqual(result['affected_rows'], 2)
        self.assertEqual(result['commit_state'], 'COMMITTED')
        self.assertNotIn('private', str(result))
        validate(result, action.spec.output_schema)
        self.assertEqual(action.spec.effect, 'WRITE')
        self.assertFalse(action.spec.retry_safe)

    def test_invalid_scripts_are_rejected_before_connecting(self):
        action = self.action()
        bad = [
            {'sql': 'UPDATE sample SET v=1; CREATE TABLE t(id INT)'},
            {'sql': 'BEGIN; UPDATE sample SET v=1; COMMIT'},
            {'sql': 'SELECT 1; SET autocommit=1'},
            {'sql': '/*! DROP TABLE sample */; UPDATE sample SET v=1'},
            {'sql': 'UPDATE sample SET v=1; /*T! DROP TABLE sample */'},
            {'sql': 'UPDATE sample SET v=%s', 'params': []},
            {'sql': 'UPDATE sample SET v=1; DELETE FROM sample', 'params': [1]},
            {'sql': 'UPDATE sample SET v=1; DELETE FROM sample', 'statement_params': [[]]},
            {'sql': 'UPDATE sample SET v=1', 'params': [], 'statement_params': [[]]},
            {'sql': '; -- only comment\n'},
            {'sql': 'SELECT 1;' * 101},
        ]
        with patch('pymysql.connect') as connect:
            for inputs in bad:
                with self.subTest(inputs=inputs), self.assertRaises(TaskError):
                    asyncio.run(action.execute(self.context(), inputs))
            connect.assert_not_called()

    def test_query_result_is_bounded_and_wire_converted(self):
        from decimal import Decimal
        action = self.action()
        connection, cursor = self.connection()
        cursor.description = [('value',)]
        cursor.fetchmany.return_value = [(Decimal('2.30'),), (Decimal('4.50'),)]
        with patch('pymysql.connect', return_value=connection):
            result = asyncio.run(action.execute(self.context(), {'sql': 'SELECT value FROM sample', 'max_rows': 1}))
        table = result['statements'][0]['table']
        self.assertEqual(table['rows'], [{'value': '2.30'}])
        self.assertTrue(table['truncated'])
        self.assertEqual(result['affected_rows'], 0)
        validate(result, action.spec.output_schema)

    def test_sql_error_rolls_back_entire_transaction_without_disclosing_sql(self):
        import pymysql
        action = self.action()
        connection, cursor = self.connection()
        cursor.execute.side_effect = [1, pymysql.IntegrityError(1062, 'private data')]
        with patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError) as raised:
            asyncio.run(action.execute(self.context(), {'sql': 'INSERT INTO t VALUES (1); INSERT INTO t VALUES (1)'}))
        self.assertEqual(raised.exception.code, 'TIDB_EXECUTE_FAILED')
        self.assertIn('第 2 条', str(raised.exception))
        self.assertIn('已回滚', str(raised.exception))
        self.assertNotIn('private data', str(raised.exception))
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    def test_ddl_requires_explicit_autocommit_and_reports_partial_failure(self):
        import pymysql
        action = self.action()
        connection, cursor = self.connection()
        with patch('pymysql.connect', return_value=connection) as connect:
            result = asyncio.run(action.execute(self.context(), {'sql': 'CREATE TABLE t(id INT); INSERT INTO t VALUES (1)', 'mode': 'autocommit'}))
        self.assertTrue(connect.call_args.kwargs['autocommit'])
        self.assertEqual(result['mode'], 'autocommit')
        connection.begin.assert_not_called()
        connection.commit.assert_not_called()
        connection, cursor = self.connection()
        cursor.execute.side_effect = [1, pymysql.OperationalError(2013, 'private detail')]
        with patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError) as raised:
            asyncio.run(action.execute(self.context(), {'sql': 'CREATE TABLE t(id INT); INSERT INTO t VALUES (1)', 'mode': 'autocommit'}))
        self.assertEqual(raised.exception.code, 'TIDB_EXECUTE_PARTIAL_OR_UNKNOWN')
        self.assertIn('已完成 1 条', str(raised.exception))
        self.assertIn('核对', str(raised.exception))
        connection.rollback.assert_not_called()
        connection.close.assert_called_once()

    def test_commit_or_rollback_failure_never_claims_rollback_success(self):
        import pymysql
        action = self.action()
        for phase in ('commit', 'rollback'):
            connection, cursor = self.connection()
            if phase == 'commit':
                connection.commit.side_effect = pymysql.OperationalError(2013, 'lost')
            else:
                cursor.execute.side_effect = pymysql.OperationalError(2013, 'lost')
                connection.rollback.side_effect = pymysql.OperationalError(2006, 'gone')
            with self.subTest(phase=phase), patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError) as raised:
                asyncio.run(action.execute(self.context(), {'sql': 'UPDATE t SET v=1'}))
            self.assertEqual(raised.exception.code, 'TIDB_EXECUTE_UNKNOWN')
            self.assertNotIn('已回滚', str(raised.exception))
            connection.close.assert_called_once()

    def test_cancelled_between_statements_rolls_back_and_stops(self):
        action = self.action()
        connection, cursor = self.connection()
        calls = [0]
        def cancelled():
            return calls[0] > 0
        cursor.execute.side_effect = lambda *args: calls.__setitem__(0, calls[0] + 1)
        with patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError) as raised:
            asyncio.run(action.execute(self.context(cancelled), {'sql': 'UPDATE t SET v=1; UPDATE t SET v=2'}))
        self.assertEqual(raised.exception.code, 'CANCELLED')
        self.assertEqual(cursor.execute.call_count, 1)
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_no_parameter_query_keeps_literal_percent_and_no_sql_echo(self):
        action = self.action()
        connection, cursor = self.connection()
        with patch('pymysql.connect', return_value=connection):
            result = asyncio.run(action.execute(self.context(), {'sql': "UPDATE t SET v='50%'"}))
        self.assertEqual(cursor.execute.call_args.args, ("UPDATE t SET v='50%'", None))
        self.assertNotIn('50%', str(result))

    def test_real_workers_file_binding_and_pymysql_protocol_execute_sql(self):
        import tempfile
        from pathlib import Path
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        from tests.tidb_wire_fixture import MySQLFixture
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root, MySQLFixture() as server, Application(home) as app:
            sql = "INSERT INTO sample(value) VALUES ('中文;a');\nUPDATE sample SET value='b' WHERE id=7;"
            Path(root, 'sample.sql').write_text(sql, encoding='utf-8-sig')
            for plugin in ('file', 'tidb'):
                app.configure_plugin(plugin, True)
            task = app.repo.create_task('文件到 SQL 执行')['task_id']
            values = {'file_root': root, 'tidb_host': '127.0.0.1', 'tidb_port': server.port,
                      'tidb_database': 'uat', 'tidb_username': 'writer', 'tidb_password': '', 'tidb_tls': False}
            properties = {key: {'type': 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'string', 'default': value} for key, value in values.items()}
            app.repo.update_task(task, name='文件到 SQL 执行', input_schema={'type': 'object', 'properties': properties})
            first = app.repo.save_step(task, {'name': '读取完整 SQL', 'capabilities': ['file.read'],
                'step_content': 'async def run(ctx, inputs):\n    result = await ctx.call("file.read", {"path":"sample.sql"})\n    return ctx.result(data=result)'})
            second = app.repo.save_step(task, {'name': '执行 SQL', 'capabilities': ['tidb.execute_sql'],
                'input_schema': {'type': 'object', 'properties': {'sql': {'type': 'string'}}, 'required': ['sql']},
                'bindings': {'sql': {'ref': {'source': 'step', 'step_id': first['step_id'], 'output': 'data', 'pointer': '/content'}}},
                'step_content': 'async def run(ctx, inputs):\n    result = await ctx.call("tidb.execute_sql", {"sql": inputs["sql"]})\n    return ctx.result(data=result)'})
            for step in (first, second):
                app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.coordinator.start(run['run_id'], uid())
            finished = app.coordinator.wait(run['run_id'])
            self.assertEqual(finished['status'], 'SUCCEEDED', finished['attempts'])
            saved = app.repo.read_output(run['run_id'], second['step_id'])
            self.assertEqual(saved['commit_state'], 'COMMITTED')
            self.assertEqual(saved['statement_count'], 2)
            self.assertIn("INSERT INTO sample(value) VALUES ('中文;a')", server.queries)
            self.assertIn("UPDATE sample SET value='b' WHERE id=7", server.queries)
            self.assertLess(server.queries.index('BEGIN'), server.queries.index("INSERT INTO sample(value) VALUES ('中文;a')"))
            self.assertLess(server.queries.index("UPDATE sample SET value='b' WHERE id=7"), server.queries.index('COMMIT'))
            self.assertNotIn('ROLLBACK', server.queries)
            self.assertEqual(server.errors, [])

    def test_unserializable_result_is_rejected_before_commit(self):
        action = self.action()
        connection, cursor = self.connection()
        cursor.description = [('value',)]
        cursor.fetchmany.return_value = [(float('nan'),)]
        with patch('pymysql.connect', return_value=connection), self.assertRaises(TaskError):
            asyncio.run(action.execute(self.context(), {'sql': 'SELECT value FROM sample'}))
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()

    def test_modulo_column_is_not_rewritten_as_a_parameter(self):
        action = self.action()
        connection, cursor = self.connection()
        sql = 'UPDATE sample SET value=100 % some_column'
        with patch('pymysql.connect', return_value=connection):
            asyncio.run(action.execute(self.context(), {'sql': sql}))
        self.assertEqual(cursor.execute.call_args.args, (sql, None))

    def test_driver_error_traceback_does_not_include_private_database_message(self):
        import pymysql
        import traceback
        action = self.action()
        connection, cursor = self.connection()
        cursor.execute.side_effect = pymysql.IntegrityError(1062, 'sensitive-test-record-99')
        with patch('pymysql.connect', return_value=connection):
            try:
                asyncio.run(action.execute(self.context(), {'sql': 'UPDATE sample SET value=1'}))
            except TaskError as error:
                formatted = ''.join(traceback.format_exception(error))
            else:
                self.fail('Expected write failure')
        self.assertNotIn('sensitive-test-record-99', formatted)

    def test_sql_parser_traceback_does_not_echo_sql(self):
        import traceback
        from taskweave_tidb.execution import script_plan
        marker = 'secret99'
        sql = "SELECT '" + marker
        try:
            script_plan({'sql': sql})
        except TaskError as error:
            formatted = ''.join(traceback.format_exception(error))
            self.assertTrue(error.__suppress_context__)
        else:
            self.fail('Expected malformed SQL failure')
        self.assertNotIn(marker, formatted)
