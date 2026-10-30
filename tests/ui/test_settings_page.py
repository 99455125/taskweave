"""SettingsPage renders through explicit controller and button dependencies."""

import asyncio
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.settings import SettingsPage


class SettingsPageTests(unittest.TestCase):
    def test_skill_export_uses_its_directory_independently_of_workspace_destination(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        from taskweave.integration.skill import skill_files
        client = Client(page_route('/skill-export-directory'))
        controller = AsyncMock()
        controller.workspace_home = '/tmp/taskweave'
        controller.call.return_value = {'ai_request_limit_kib': 1024}
        controller.workbench_settings.return_value = {'redact_on_display': True, 'redact_for_ai': True}
        controller.model_settings.return_value = {'url': '', 'model': '', 'key_env': 'KEY'}
        callbacks = {}

        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)

        async def scenario(root):
            with client, patch.object(ui, 'notify'):
                await SettingsPage(controller, button).render()
                fields = {el._props.get('label'): el for el in client.elements.values()}
                skill_destination = root / 'exported-skill'
                workspace_destination = root / 'future-workspace'
                fields['Skill 安装目录'].value = str(skill_destination)
                fields['新的工作空间目录'].value = str(workspace_destination)
                await callbacks['安装 / 导出 TaskWeave Skill']()
                self.assertTrue(skill_destination.is_dir(), 'Skill must be exported to its own directory')
                self.assertFalse(workspace_destination.exists())
                for name, data in skill_files().items():
                    self.assertEqual((skill_destination / name).read_bytes(), data)
                await callbacks['安装 / 导出 TaskWeave Skill']()
                controller.migrate_workspace.assert_not_awaited()
        try:
            with tempfile.TemporaryDirectory() as directory:
                asyncio.run(scenario(Path(directory)))
        finally:
            client.delete()

    def test_copy_mcp_configuration_is_awaitable_and_reports_completion(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        client = Client(page_route('/copy-mcp-settings'))
        controller = AsyncMock()
        controller.workspace_home = '/tmp/taskweave'
        controller.call.return_value = {'ai_request_limit_kib': 1024}
        controller.workbench_settings.return_value = {'redact_on_display': True, 'redact_for_ai': True}
        controller.model_settings.return_value = {'url': '', 'model': '', 'key_env': 'KEY'}
        callbacks = {}
        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)
        async def scenario():
            with client, patch.object(ui.clipboard, 'write', return_value=None) as write, patch.object(ui, 'notify') as notify:
                await SettingsPage(controller, button).render()
                await callbacks['复制 MCP 配置']()
                self.assertIn('mcpServers', write.call_args.args[0])
                self.assertIn('/tmp/taskweave', write.call_args.args[0])
                notify.assert_called_once_with('MCP 配置已复制')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_workspace_migration_waits_for_confirmation_and_keeps_destination(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        client = Client(page_route('/workspace-migration-confirmation'))
        controller = AsyncMock()
        controller.workspace_home = '/tmp/taskweave'
        controller.call.return_value = {'ai_request_limit_kib': 1024}
        controller.workbench_settings.return_value = {'redact_on_display': True, 'redact_for_ai': True}
        controller.model_settings.return_value = {'url': '', 'model': '', 'key_env': 'KEY'}
        controller.migrate_workspace.return_value = {'workspace_home': '/tmp/new-taskweave', 'restart_required': True}
        callbacks = {}

        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)

        async def decide(label):
            async def open_dialog():
                with client:
                    await callbacks['迁移工作空间']()
            pending = asyncio.create_task(open_dialog())
            await asyncio.sleep(0)
            controller.migrate_workspace.assert_not_awaited()
            dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
            control = next(el for el in dialog.descendants() if isinstance(el, ui.button) and el.text == label)
            next(event.handler for event in control._event_listeners.values() if event.type == 'click')(None)
            await pending

        async def scenario():
            with client:
                settings = SettingsPage(controller, button)
                await settings.render()
                await settings.select_section('workspace')
                destination = next(el for el in client.elements.values() if el._props.get('label') == '新的工作空间目录')
                destination.value = '/tmp/new-taskweave'
                await decide('取消')
                controller.migrate_workspace.assert_not_awaited()
                self.assertEqual(destination.value, '/tmp/new-taskweave')
                await decide('确认迁移')
                controller.migrate_workspace.assert_awaited_once_with('/tmp/new-taskweave')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

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
