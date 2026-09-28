"""SettingsPage renders through explicit controller and button dependencies."""

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.settings import SettingsPage


class SettingsPageTests(unittest.TestCase):
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
                [call.args[0] for call in button.call_args_list[:4]],
                ["AI 连接与请求", "脱敏设置", "执行设置", "工作空间"],
            )
            labels = [call.args[0] for call in fake_ui.label.call_args_list if call.args]
            for expected in [
                "设置", "设置分组", "AI 编写连接（可选）", "AI 请求大小",
                "默认 2048 KiB，最高 4096 KiB；此值不是模型 token 上限。",
                "脱敏", "执行器", "本地工作空间", "/tmp/taskweave",
                "总库保存配置与执行记录；每个任务的数据库保存返回结果。",
            ]:
                self.assertIn(expected, labels)
            controller.call.assert_awaited_once_with("ai.settings.get")
            controller.workbench_settings.assert_awaited_once_with()
            controller.model_settings.assert_awaited_once_with()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
