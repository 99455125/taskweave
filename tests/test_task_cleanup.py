"""Task cleanup preserves configuration and isolates other tasks."""
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid


class TaskCleanupTests(unittest.TestCase):
    def test_all_runtime_data_removed_and_configuration_retained(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            tasks = []
            for name in ['清理目标', '保留任务']:
                task = app.repo.create_task(name)['task_id']
                step = app.repo.save_step(task, {'name': '输出', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"ok": True})'})
                app.confirm_step_manual(step['step_id'], step['content_hash'])
                run = app.create_run(task)
                app.coordinator.start(run['run_id'], uid())
                app.coordinator.wait(run['run_id'])
                app.coordinator.control(run['run_id'], uid(), 'abandon')
                tasks.append((task, step, run))
            task, step, run = tasks[0]
            config = app.export_task(task)
            root = app.repo.task_path(task).parent
            for relative in ['artifacts/orphan.png', 'staging/old/tmp', 'backups/old.db']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test')
            app.authoring.conversations[step['step_id']] = ['old conversation']
            app.coordinator.session_run_id = run['run_id']
            result = app.dispatch('task.clear_runs', {'task_id': task})
            self.assertEqual(result['deleted_runs'], 1)
            self.assertFalse(root.exists())
            self.assertEqual(app.export_task(task), config)
            self.assertEqual(app.repo.steps(task)[0]['validation_state'], 'VALIDATED')
            self.assertNotIn(step['step_id'], app.authoring.conversations)
            for table in ['task_runs', 'step_attempts', 'result_refs']:
                self.assertEqual(app.repo.query(f'SELECT * FROM {table} WHERE task_id=?', (task,)), [])
            self.assertTrue(app.repo.run_details(tasks[1][2]['run_id'])['results'])
            self.assertEqual(app.clear_task_runs(task)['deleted_runs'], 0)
            fresh = app.create_run(task)
            app.coordinator.start(fresh['run_id'], uid())
            self.assertEqual(app.coordinator.wait(fresh['run_id'])['status'], 'SUCCEEDED')

    def test_busy_run_rejected_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('执行中')['task_id']
            step = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.repo.execute("UPDATE task_runs SET status='RUNNING' WHERE run_id=?", (run['run_id'],))
            with self.assertRaises(TaskError) as error:
                app.clear_task_runs(task)
            self.assertEqual(error.exception.code, 'RUN_BUSY')
            self.assertEqual(app.repo.run(run['run_id'])['status'], 'RUNNING')
            app.repo.execute("UPDATE task_runs SET status='READY' WHERE run_id=?", (run['run_id'],))
