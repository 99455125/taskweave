"""Task history views filter by run mode and ignore stale responses."""

import asyncio
import tempfile
import unittest
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page as nice_page
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.pages.history import HistoryPage
from taskweave.infrastructure.storage import uid


class HistoryPageTests(unittest.TestCase):
    def test_real_local_debug_and_execution_records_render_and_open_details(self):
        with tempfile.TemporaryDirectory() as home, Application(
            home, registry_factory="tests.test_context_targets_runtime:build_registry"
        ) as app:
            task_id = app.repo.create_task("本地历史夹具")['task_id']
            step = app.repo.save_step(task_id, {
                "name": "本地回显", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n",
                "capabilities": ["demo.echo"],
            })
            trial = app.trial_step(step['step_id'], {}, uid())
            self.assertEqual(app.coordinator.wait(trial['run_id'])['status'], 'SUCCEEDED')
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            execution = app.create_run(task_id)
            app.coordinator.start(execution['run_id'], uid())
            self.assertEqual(app.coordinator.wait(execution['run_id'])['status'], 'SUCCEEDED')

            async def render(mode):
                labels, callbacks = [], []
                button = lambda title, callback, **_kwargs: (labels.append(title), callbacks.append(callback))
                page = HistoryPage(DesktopController(app), task_id, button, AsyncMock(), AsyncMock())
                with ui.column():
                    await page.render(mode)
                self.assertIn('查看记录', labels)
                self.assertTrue(any(getattr(el, 'text', None) and ('成功' in el.text or '调试' in el.text or '正式执行' in el.text)
                                    for el in ui.context.client.elements.values()))
                await callbacks[0]()
                self.assertEqual(app.dispatch('run.get', {'run_id': trial['run_id'] if mode == 'TRIAL' else execution['run_id']})['status'], 'SUCCEEDED')

            client = Client(nice_page('/history-local-fixture'))
            try:
                async def within_client():
                    with client:
                        await render('TRIAL')
                        await render('EXECUTION')
                asyncio.run(within_client())
            finally:
                client.delete()

    def test_stale_run_list_does_not_continue_loading_history(self):
        async def scenario():
            identity = [("task-a", 1, 1)]
            controller = AsyncMock()
            controller.call.return_value = []
            page = HistoryPage(controller, "task-a", MagicMock(), MagicMock(), MagicMock(), identity=lambda: identity[0])
            fake_ui = MagicMock()
            async def run_list(*args, **kwargs):
                identity[0] = ("task-b", 2, 2)
                return []
            controller.call.side_effect = run_list
            with patch("taskweave.desktop.pages.history.ui", fake_ui):
                await page.render("EXECUTION")
            controller.call.assert_awaited_once_with("run.list", task_id="task-a")

        asyncio.run(scenario())

    def test_execution_mode_uses_task_scoped_execution_history(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                [{"run_id": "exec-a", "mode": "EXECUTION", "started_at": "today", "status": "SUCCEEDED"},
                 {"run_id": "debug-a", "mode": "TRIAL", "started_at": "yesterday", "status": "FAILED"}],
                [],
            ]
            page = HistoryPage(controller, "task-a", MagicMock(), MagicMock(), MagicMock(), identity=lambda: ("task-a", 1, 1))
            fake_ui = MagicMock()
            with patch("taskweave.desktop.pages.history.ui", fake_ui):
                await page.render("EXECUTION")
            self.assertIn("本任务执行历史", [call.args[0] for call in fake_ui.label.call_args_list if call.args])
            labels = [str(call.args[0]) for call in fake_ui.label.call_args_list if call.args]
            self.assertTrue(any("exec-a" in label or "today" in label for label in labels))
            self.assertFalse(any("yesterday" in label for label in labels))
            self.assertEqual(controller.call.await_args_list[0].args, ("run.list",))
            self.assertEqual(controller.call.await_args_list[1].args, ("step.list",))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
