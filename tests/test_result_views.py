"""Display metadata survives reopening without changing dependency data."""
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid
from taskweave.core.validation import TaskError
from taskweave.core.result_views import validate_views, BUILTIN_VIEWS


class ResultViews(unittest.TestCase):
    def test_saved_views_and_dependency_output_survive_reopen(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                task = app.repo.create_task('展示')['task_id']
                step = app.repo.save_step(task, {'step_content': '''async def run(ctx, inputs):
    return ctx.result(data={"order_no": "001", "report": {"columns": [{"key": "status", "label": "状态"}], "rows": [{"status": "ok"}]}}, views=[{"title": "订单数据", "renderer": "core.table", "pointer": "/report"}])'''})
                run = app.trial_step(step['step_id'], {}, uid())
                finished = app.coordinator.wait(run['run_id'])
                self.assertEqual(finished['status'], 'SUCCEEDED', finished)
                ref = app.repo.run_details(run['run_id'])['results'][0]
                self.assertEqual(app.repo.read_output(run['run_id'], step['step_id'], 'data', app.registry)['order_no'], '001')
            with Application(home) as app:
                saved = app.repo.read_result(ref['result_id'], app.registry)
                self.assertEqual(saved['views'][0]['title'], '订单数据')
                self.assertEqual(saved['data']['report']['rows'][0]['status'], 'ok')
                self.assertEqual(saved['name'], 'data')

    def test_invalid_renderer_and_pointer_are_rejected(self):
        for view in [{'title': 'x', 'renderer': 'missing', 'pointer': ''}, {'title': 'x', 'renderer': 'core.table', 'pointer': '/missing'}]:
            with self.assertRaises(TaskError):
                validate_views({}, [view], BUILTIN_VIEWS)
