"""SettingsPage renders through explicit controller and button dependencies."""

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.settings import SettingsPage


class SettingsPageTests(unittest.TestCase):
    def test_actual_controls_update_plain_settings_draft_before_commands(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        client = Client(page_route('/plain-settings-draft'))
        controller = AsyncMock()
        controller.workspace_home = '/tmp/taskweave'
        controller.call.return_value = {'ai_request_limit_kib': 1024}
        controller.workbench_settings.return_value = {'redact_on_display': True, 'redact_for_ai': True}
        controller.model_settings.return_value = {'url': '', 'model': '', 'key_env': 'KEY'}
        buttons = {}
        def button(label, callback, **kwargs):
            buttons[label] = callback
            return ui.button(label, on_click=callback)
        async def scenario():
            with client:
                settings = SettingsPage(controller, button)
                await settings.render()
                fields = {element._props.get('label'): element for element in client.elements.values()}
                fields['完整 Chat Completions 接口地址'].value = ' local-fixture '
                fields['模型名称'].value = ' fixture '
                self.assertEqual(settings.session.draft['model'], ' fixture ')
                await buttons['保存连接']()
                controller.save_model.assert_awaited_once_with('local-fixture', 'fixture', 'KEY', None)
                fields['最大并发执行线程数'].value = 3
                await buttons['保存执行器设置']()
                controller.save_executor_max_threads.assert_awaited_once_with(3)
                old_save = buttons['保存连接']
                old_draft = settings.session
                await settings.render()
                self.assertIsNot(settings.session, old_draft)
                old_draft.draft['model'] = 'old-confirmed-model'
                await old_save()
                self.assertEqual(controller.save_model.call_args.args,
                                 ('local-fixture', 'old-confirmed-model', 'KEY', None))
                self.assertEqual(settings.session.draft['model'], '')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_navigation_callback_is_awaitable_for_workbench_button_dispatch(self):
        async def scenario():
            page = SettingsPage(AsyncMock(), MagicMock())
            controller = page.controller
            controller.workspace_home = "/tmp/taskweave"
            controller.call.return_value = {"ai_request_limit_kib": 2048}
            controller.workbench_settings.return_value = {"redact_on_display": True, "redact_for_ai": True, "executor_max_threads": 8}
            controller.model_settings.return_value = {"url": "", "model": "", "key_env": "TASKWEAVE_MODEL_API_KEY"}
            with patch("taskweave.desktop.pages.settings.ui"):
                await page.render()
            callback = page.select_section("privacy")
            self.assertTrue(inspect.isawaitable(callback))
            await callback

        asyncio.run(scenario())
    def test_render_reads_settings_from_controller_and_keeps_existing_sections(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.return_value = {"ai_request_limit_kib": 1024}
            controller.workspace_home = "/tmp/taskweave"
            controller.workbench_settings.return_value = {
                "redact_on_display": True,
                "redact_for_ai": False,
                "executor_max_threads": 4,
            }
            controller.model_settings.return_value = {
                "url": "https://example.invalid/v1/chat/completions",
                "model": "fixture",
                "key_env": "MODEL_KEY",
            }
            button = MagicMock()
            page = SettingsPage(controller, button)
            with patch("taskweave.desktop.pages.settings.ui") as fake_ui:
                await page.render()
            self.assertEqual(
                [call.args[0] for call in button.call_args_list[:5]],
                ["AI 连接与请求", '外部 AI / MCP', "脱敏设置", "执行设置", "工作空间"],
            )
            labels = [call.args[0] for call in fake_ui.label.call_args_list if call.args]
            for expected in [
                "设置", "设置分组", "AI 编写连接（可选）", "AI 请求大小",
                "脱敏", "执行器", "本地工作空间", "/tmp/taskweave",
            ]:
                self.assertIn(expected, labels)
            self.assertNotIn("总库保存配置与执行记录；每个任务的数据库保存返回结果。", labels)
            controller.call.assert_awaited_once_with("ai.settings.get")
            controller.workbench_settings.assert_awaited_once_with()
            controller.model_settings.assert_awaited_once_with()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
