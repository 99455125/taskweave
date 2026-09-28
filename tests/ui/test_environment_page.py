"""Environment configuration stays in its own page and preserves failures."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.pages.environments import EnvironmentPage


class EnvironmentPageTests(unittest.TestCase):
    def test_set_default_updates_only_the_originating_environment_view(self):
        async def scenario():
            controller = AsyncMock()
            selected = AsyncMock()
            page = EnvironmentPage(controller, MagicMock(), AsyncMock(), selected, page_identity=lambda: ("environment", 3))
            page._render_generation = 4
            page.selected_environment_id = "env-a"
            identity = page.view_identity()
            update_view = MagicMock()

            result = await page.set_default_for_view("env-a", identity, update_view)

            self.assertTrue(result)
            selected.assert_awaited_once_with("env-a")
            update_view.assert_called_once_with()
            controller.set_default_environment.assert_awaited_once_with("env-a")

        asyncio.run(scenario())

    def test_late_default_response_does_not_update_a_new_environment_view(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            controller = AsyncMock()
            async def set_default(environment_id):
                entered.set()
                await release.wait()
            controller.set_default_environment.side_effect = set_default
            selected = AsyncMock()
            page = EnvironmentPage(controller, MagicMock(), AsyncMock(), selected, page_identity=lambda: ("environment", 3))
            page._render_generation = 4
            page.selected_environment_id = "env-a"
            identity = page.view_identity()
            update_view = MagicMock()

            pending = asyncio.create_task(page.set_default_for_view("env-a", identity, update_view))
            await entered.wait()
            page._render_generation += 1
            page.selected_environment_id = "env-b"
            release.set()

            self.assertFalse(await pending)
            selected.assert_not_awaited()
            update_view.assert_not_called()

        asyncio.run(scenario())

    def test_failed_default_keeps_existing_form_and_surfaces_original_error(self):
        async def scenario():
            controller = AsyncMock()
            controller.set_default_environment.side_effect = TaskError("FORM_INVALID", "default failed")
            repaint = AsyncMock()
            selected = AsyncMock()
            page = EnvironmentPage(controller, MagicMock(), repaint, selected, page_identity=lambda: ("environment", 3))
            page._render_generation = 4
            page.selected_environment_id = "env-a"
            identity = page.view_identity()
            update_view = MagicMock()

            with self.assertRaisesRegex(TaskError, "default failed"):
                await page.set_default_for_view("env-a", identity, update_view)

            repaint.assert_not_awaited()
            selected.assert_not_awaited()
            update_view.assert_not_called()

        asyncio.run(scenario())

    def test_render_composes_environment_list_and_selected_detail(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.return_value = [
                {"environment_id": "env-1", "name": "UAT", "public_config_json": '{"base_url":"https://uat"}', "secret_refs_json": "{}", "descriptions_json": "{}"}
            ]
            controller.default_environment.return_value = "env-1"
            page = EnvironmentPage(controller, MagicMock(), AsyncMock(), AsyncMock())
            with patch("taskweave.desktop.pages.environments.ui") as fake_ui:
                await page.render()
            self.assertIn("环境详情", [call.args[0] for call in fake_ui.label.call_args_list if call.args])
            self.assertTrue(any(call.args[0] == "环境名称" and call.kwargs.get("value") == "UAT" for call in fake_ui.input.call_args_list))
            self.assertIn("搜索环境", [call.args[0] for call in fake_ui.input.call_args_list if call.args])
            self.assertEqual(page.selected_environment_id, "env-1")
            controller.call.assert_awaited_once_with("environment.list")

        asyncio.run(scenario())

    def test_save_parses_values_and_refreshes_only_after_success(self):
        async def scenario():
            controller = AsyncMock()
            repaint = AsyncMock()
            selected = AsyncMock()
            page = EnvironmentPage(controller, AsyncMock(), repaint, selected)

            await page.save_environment("UAT", [("count", "3", "数字"), ("flag", "true", "开关")])

            controller.call.assert_awaited_once_with(
                "environment.save", name="UAT", public_config={"count": 3, "flag": True},
                secret_refs={}, descriptions={"count": "数字", "flag": "开关"}, environment_id=None,
            )
            repaint.assert_awaited_once()

        asyncio.run(scenario())

    def test_invalid_key_leaves_saved_environment_and_selection_unchanged(self):
        async def scenario():
            controller = AsyncMock()
            repaint = AsyncMock()
            selected = AsyncMock()
            page = EnvironmentPage(controller, AsyncMock(), repaint, selected)

            with self.assertRaises(TaskError):
                await page.save_environment("UAT", [("same", "1", ""), ("same", "2", "")])

            controller.call.assert_not_awaited()
            repaint.assert_not_awaited()
            selected.assert_not_awaited()

        asyncio.run(scenario())
