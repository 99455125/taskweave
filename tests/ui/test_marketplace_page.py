"""The local marketplace view reports only capabilities that exist locally."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.marketplace import MarketplacePage


class MarketplacePageTests(unittest.TestCase):
    def test_render_shows_under_construction_resources_and_secondary_local_links(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                [{"id": "sample", "enabled": True}, {"id": "disabled", "enabled": False}],
                [{"task_id": "t1"}],
            ]
            button = MagicMock()
            navigate = AsyncMock()
            page = MarketplacePage(controller, button, navigate)
            with patch("taskweave.desktop.pages.marketplace.ui") as fake_ui:
                await page.render()
            labels = [call.args[0] for call in fake_ui.label.call_args_list]
            self.assertIn("把好的工作方式，分享给更多人。", labels)
            self.assertIn("市集暂未开放，当前版本不提供浏览、下载或安装服务。", labels)
            self.assertEqual([call.args[0] for call in button.call_args_list], ["打开任务 · 1", "查看插件 · 2"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
