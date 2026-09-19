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
