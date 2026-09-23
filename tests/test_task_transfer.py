"""Portable configuration preserves exported state and keeps AI imports draft."""
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.core.validation import normalize_step
from taskweave.infrastructure.storage import uid


class TaskTransfer(unittest.TestCase):
    def test_round_trip_new_ids_dependencies_and_verification(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('订单', {'type': 'object', 'properties': {'url': {'type': 'string', 'default': 'local'}}})
            first = app.repo.save_step(task['task_id'], {'name': '获取单号', 'step_description': '读取页面单号', 'step_notes': '单号必须来自页面，不得编造', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"order_no": "001"})'})
            second = app.repo.save_step(task['task_id'], {'name': '核对', 'input_schema': {'type': 'object', 'properties': {'order_no': {'type': 'string'}}}, 'bindings': {'order_no': {'ref': {'source': 'step', 'step_id': first['step_id'], 'output': 'data', 'pointer': '/order_no'}}}, 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
            app.confirm_step_manual(first['step_id'], first['content_hash'])
            package = app.dispatch('task.export', {'task_id': task['task_id']})
            self.assertNotIn('environments', package)
            imported = app.dispatch('task.import', {'package': package})
            steps = app.repo.steps(imported['task_id'])
            self.assertNotEqual(steps[0]['step_id'], first['step_id'])
            self.assertEqual(steps[0]['step_description'], '读取页面单号')
            self.assertEqual(steps[0]['step_notes'], '单号必须来自页面，不得编造')
            self.assertEqual(steps[1]['bindings']['order_no']['ref']['step_id'], steps[0]['step_id'])
            self.assertEqual([s['validation_state'] for s in steps], ['VALIDATED', 'DRAFT'])
            self.assertEqual(steps[0]['validation_source'], 'IMPORTED')
            self.assertIsNone(steps[1]['validation_source'])
            self.assertEqual(package['origin'], 'task_export')
            self.assertEqual([item['validation_state'] for item in package['steps']], ['VALIDATED', 'DRAFT'])
            self.assertEqual(app.export_task(imported['task_id']), package)
            self.assertEqual(second['validation_state'], 'DRAFT')

    def test_invalid_import_leaves_existing_tasks_unchanged(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            app.repo.create_task('已有')
            package = {'format': 'taskweave-task-2', 'origin': 'ai_generated', 'task': {'name': '坏任务'}, 'steps': [{'key': 'one', 'validation_state': 'DRAFT', 'document': {'step_content': 'import os'}}]}
            with self.assertRaises(TaskError): app.import_task(package)
            self.assertEqual([t['name'] for t in app.repo.list_tasks()], ['已有'])

    def test_ai_import_is_draft_and_rejects_claimed_validation(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            document = normalize_step({'name': 'AI步骤', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"ok": True})'})
            document = {key: value for key, value in document.items() if key not in {'step_id', 'task_id', 'position', 'content_hash', 'validation_state', 'verified_hash', 'validation_source', 'validated_environment_id'}}
            package = {'format': 'taskweave-task-2', 'origin': 'ai_generated', 'task': {'name': 'AI任务', 'description': '', 'input_schema': {'type': 'object'}}, 'steps': [{'key': 'one', 'validation_state': 'DRAFT', 'document': document}]}
            imported = app.import_task(package)
            self.assertEqual(app.repo.steps(imported['task_id'])[0]['validation_state'], 'DRAFT')
            package['steps'][0]['validation_state'] = 'VALIDATED'
            with self.assertRaises(TaskError):
                app.import_task(package)

    def test_exported_incomplete_draft_round_trips_but_ai_does_not(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('草稿')['task_id']
            app.repo.save_step(task, {'name': '未完成', 'step_content': ''})
            package = app.export_task(task)
            imported = app.import_task(package)
            step = app.repo.steps(imported['task_id'])[0]
            self.assertEqual(step['step_content'], '')
            self.assertEqual(step['validation_state'], 'DRAFT')
            package['origin'] = 'ai_generated'
            with self.assertRaises(TaskError):
                app.import_task(package)

    def test_v1_requires_reexport(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            with self.assertRaises(TaskError) as error:
                app.import_task({'format': 'taskweave-task-1'})
            self.assertIn('重新导出', str(error.exception))

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
