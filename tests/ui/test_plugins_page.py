"""Plugin page interactions use controller and navigation callbacks."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.plugins import PluginsPage, filter_plugins


class PluginsPageTests(unittest.TestCase):
    def test_plugin_search_and_status_filters(self):
        plugins = [
            {"id": "playwright", "enabled": True},
            {"id": "ocr", "enabled": False},
        ]
        self.assertEqual(filter_plugins(plugins, "play", "all"), [plugins[0]])
        self.assertEqual(filter_plugins(plugins, "", "enabled"), [plugins[0]])
        self.assertEqual(filter_plugins(plugins, "", "disabled"), [plugins[1]])

    def test_toggle_calls_controller_then_refreshes_page(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                {"versions": {"sample_plugin": "1.0"}, "load_errors": {}, "actions": [], "tools": [], "manifests": {}},
                [{"id": "sample_plugin", "enabled": False}],
            ]
            buttons = MagicMock()
            controller.plugin_contributions = MagicMock(return_value=[])
            repaint = AsyncMock()
            page = PluginsPage(controller, buttons, repaint)
            with patch("taskweave.desktop.pages.plugins.ui"):
                await page.render()
            title, callback = buttons.call_args.args
            self.assertEqual(title, "启用")
            controller.call.side_effect = None
            await callback()
            controller.call.assert_any_await("plugin.configure", plugin_id="sample_plugin", enabled=True)
            repaint.assert_awaited_once_with()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
