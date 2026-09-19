"""Portable configuration maps dependencies and defaults imported steps to verified."""
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid


class TaskTransfer(unittest.TestCase):
    def test_round_trip_new_ids_dependencies_and_verification(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('订单', {'type': 'object', 'properties': {'url': {'type': 'string', 'default': 'local'}}})
            first = app.repo.save_step(task['task_id'], {'name': '获取单号', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"order_no": "001"})'})
            app.repo.save_step(task['task_id'], {'name': '核对', 'input_schema': {'type': 'object', 'properties': {'order_no': {'type': 'string'}}}, 'bindings': {'order_no': {'ref': {'source': 'step', 'step_id': first['step_id'], 'output': 'data', 'pointer': '/order_no'}}}, 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
            package = app.dispatch('task.export', {'task_id': task['task_id']})
            self.assertNotIn('environments', package)
            imported = app.dispatch('task.import', {'package': package})
            steps = app.repo.steps(imported['task_id'])
            self.assertNotEqual(steps[0]['step_id'], first['step_id'])
            self.assertEqual(steps[1]['bindings']['order_no']['ref']['step_id'], steps[0]['step_id'])
            self.assertTrue(all(s['validation_state'] == 'VALIDATED' and s['validation_source'] == 'MANUAL' for s in steps))
            self.assertEqual(app.export_task(imported['task_id']), package)
            run = app.create_run(imported['task_id']);app.coordinator.start(run['run_id'], uid())
            self.assertEqual(app.coordinator.wait(run['run_id'])['status'], 'SUCCEEDED')

    def test_invalid_import_leaves_existing_tasks_unchanged(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            app.repo.create_task('已有')
            package = {'format': 'taskweave-task-1', 'task': {'name': '坏任务'}, 'steps': [{'key': 'one', 'document': {'step_content': 'import os'}}]}
            with self.assertRaises(TaskError): app.import_task(package)
            self.assertEqual([t['name'] for t in app.repo.list_tasks()], ['已有'])

    def test_delete_environment_keeps_history_and_rejects_live_run(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            env = app.repo.save_environment('uat', {'url': 'local'})['environment_id']
            task = app.repo.create_task('历史')['task_id']
            step = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"ok": True})'})
            app.confirm_step_manual(step['step_id'], step['content_hash'], env)
            run = app.create_run(task, environment_id=env)
            app.coordinator.start(run['run_id'], uid());app.coordinator.wait(run['run_id'])
            with self.assertRaises(TaskError): app.delete_environment(env)
            app.coordinator.control(run['run_id'], uid(), 'abandon')
            app.delete_environment(env)
            self.assertEqual(app.repo.list_environments(), [])
            self.assertEqual(app.repo.run(run['run_id'])['environment_id'], None)
            self.assertTrue(app.repo.run_details(run['run_id'])['results'])
            self.assertEqual(app.repo.steps(task)[0]['validation_state'], 'VALIDATED')
