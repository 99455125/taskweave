"""RunPage owns execution creation and its page-specific refresh loop."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.executions import RunPage
from taskweave.desktop.state import ExecutionPageState


class RunPageTests(unittest.TestCase):
    def test_run_page_renders_list_and_owns_initial_refresh(self):
        async def scenario():
            controller = SimpleNamespace(call=AsyncMock(return_value=[]))
            details = SimpleNamespace(refresh=AsyncMock(), own_timer=MagicMock())
            page = RunPage(controller, ExecutionPageState(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), details, lambda: "run", lambda: 1)
            ui = MagicMock()
            with patch("taskweave.desktop.pages.executions.ui", ui):
                await page.render()
            ui.label.assert_any_call("执行列表")
            details.refresh.assert_awaited_once_with()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
