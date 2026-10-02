"""Task history views filter by run mode and ignore stale responses."""

import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page as nice_page
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.pages.history import HistoryPage
from taskweave.infrastructure.storage import uid


class HistoryPageTests(unittest.TestCase):
    async def open_fixture(self, controller, identity=lambda: None):
        run = {'run_id': 'r', 'task_id': 't', 'mode': 'TRIAL', 'status': 'SUCCEEDED',
               'started_at': 'today', 'definition_json': None, 'attempts': [], 'results': []}
        original = controller.call.side_effect

        async def call(operation, **params):
            if operation == 'run.list':
                return [run]
            if operation == 'step.list':
                return []
            if operation == 'run.get':
                return run
            return await original(operation, **params)

        controller.call.side_effect = call
        page = HistoryPage(controller, 't', lambda title, cb, **kw: ui.button(title, on_click=cb),
                           AsyncMock(), AsyncMock(), identity=identity)
        await page.render()
        await self.click_handler('查看记录')()
        return next(el for el in ui.context.client.elements.values() if isinstance(el, ui.dialog))

    @staticmethod
    def click_handler(title):
        button = next(el for el in ui.context.client.elements.values()
                      if isinstance(el, ui.button) and el.text == title)
        return next(event.handler for event in button._event_listeners.values() if event.type == 'click')

    @staticmethod
    def capture_click(button, callback):
        # Keep real elements while invoking the business callbacks explicitly;
        # NiceGUI's event dispatcher otherwise schedules async callbacks.
        button.on('click', callback)
        return button

    def test_history_logs_are_explicit_bounded_paginated_and_copy_full_text(self):
        async def scenario():
            events = [{'kind': 'LongChineseLog', 'payload_json': json.dumps({'message': '完整中文日志' * 20000})}]
            controller = SimpleNamespace(call=AsyncMock(return_value=events), copy_text=AsyncMock())
            controller.call.side_effect = AsyncMock(return_value=events)
            dialog = await self.open_fixture(controller)
            self.assertTrue(dialog.value)
            self.assertNotIn('run.events', [call.args[0] for call in controller.call.await_args_list])
            await self.click_handler('查看 / 刷新日志')()
            output = next(el for el in ui.context.client.elements.values() if isinstance(el, ui.textarea))
            self.assertEqual(len(output.value), 24000)
            chunks = [output.value]
            while next(el for el in ui.context.client.elements.values()
                       if isinstance(el, ui.button) and el.text == '下一页').enabled:
                self.click_handler('下一页')()
                chunks.append(output.value)
            from taskweave.desktop.display import readable_metadata
            expected = json.dumps(readable_metadata(events, {}), ensure_ascii=False, indent=2, default=str)
            self.assertEqual(''.join(chunks), expected)
            await self.click_handler('复制完整日志')()
            controller.copy_text.assert_awaited_once_with(expected)
            self.assertFalse(any(isinstance(el, ui.code) for el in ui.context.client.elements.values()))
            self.assertEqual([call.args[0] for call in controller.call.await_args_list].count('run.events'), 1)

        client = Client(nice_page('/history-bounded-logs'))
        try:
            async def run():
                with client, patch.object(ui.button, 'on_click', self.capture_click):
                    await scenario()
            asyncio.run(run())
        finally:
            client.delete()

    def test_late_history_logs_ignore_close_or_navigation_and_duplicate_clicks(self):
        for leave in ('close', 'navigate'):
            with self.subTest(leave=leave):
                client = Client(nice_page('/history-late-' + leave))
                async def scenario():
                    entered, release = asyncio.Event(), asyncio.Event()
                    identity = [1]

                    async def events(*args, **kwargs):
                        entered.set()
                        await release.wait()
                        return [{'kind': 'MustNotRender', 'payload_json': '{}'}]

                    controller = SimpleNamespace(call=AsyncMock(side_effect=events), copy_text=AsyncMock())
                    dialog = await self.open_fixture(controller, lambda: identity[0])
                    load = self.click_handler('查看 / 刷新日志')
                    pending = asyncio.create_task(load())
                    await entered.wait()
                    await load()
                    self.assertEqual([call.args[0] for call in controller.call.await_args_list].count('run.events'), 1)
                    if leave == 'close':
                        dialog.close()
                    else:
                        identity[0] = 2
                    release.set()
                    await pending
                    self.assertFalse(any(isinstance(el, ui.textarea) for el in ui.context.client.elements.values()))

                try:
                    async def run():
                        with client, patch.object(ui.button, 'on_click', self.capture_click):
                            await scenario()
                    asyncio.run(run())
                finally:
                    client.delete()

    def test_history_log_failure_can_be_retried_without_closing_dialog(self):
        client = Client(nice_page('/history-log-failure'))
        async def scenario():
            responses = AsyncMock(side_effect=[RuntimeError('failure'), [{'kind': 'Retried'}]])
            controller = SimpleNamespace(call=AsyncMock(side_effect=responses), copy_text=AsyncMock())
            dialog = await self.open_fixture(controller)
            load = self.click_handler('查看 / 刷新日志')
            await load()
            self.assertTrue(dialog.value)
            self.assertTrue(any('日志读取失败' in str(getattr(el, 'text', ''))
                                for el in ui.context.client.elements.values()))
            await load()
            self.assertIn('Retried', next(el.value for el in ui.context.client.elements.values() if isinstance(el, ui.textarea)))
            self.assertEqual(responses.await_count, 2)

        try:
            async def run():
                with client, patch.object(ui.button, 'on_click', self.capture_click):
                    await scenario()
            asyncio.run(run())
        finally:
            client.delete()

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
                controller = DesktopController(app)
                controller.call = AsyncMock(wraps=controller.call)
                page = HistoryPage(controller, task_id, button, AsyncMock(), AsyncMock())
                with ui.column():
                    await page.render(mode)
                self.assertIn('查看记录', labels)
                self.assertTrue(any(getattr(el, 'text', None) and ('成功' in el.text or '调试' in el.text or '正式执行' in el.text)
                                    for el in ui.context.client.elements.values()))
                await callbacks[0]()
                self.assertNotIn('run.events', [call.args[0] for call in controller.call.await_args_list])
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
