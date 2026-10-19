"""Execution filters are owned by their page state."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.executions import ExecutionsPage
from taskweave.desktop.state import ExecutionPageState


class ExecutionsPageTests(unittest.TestCase):
    def test_filters_update_page_state_and_refresh_runs(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [[{"task_id": "t1", "name": "Task"}]]
            state = ExecutionPageState(task_ids=["deleted"], statuses=["FAILED"])
            refresh = AsyncMock()
            task_filter, status_filter = MagicMock(), MagicMock()
            task_filter.props.return_value = task_filter
            task_filter.classes.return_value = task_filter
            status_filter.props.return_value = status_filter
            status_filter.classes.return_value = status_filter
            task_filter.value = ["stale-control-value"]
            status_filter.value = ["stale-control-value"]
            fake_ui = MagicMock()
            fake_ui.select.side_effect = [task_filter, status_filter]
            page = ExecutionsPage(controller, state, MagicMock(), refresh)

            with patch("taskweave.desktop.pages.executions.ui", fake_ui):
                await page.render()
                await task_filter.on_value_change.call_args.args[0](SimpleNamespace(value=["t1"]))
                self.assertEqual(state.statuses, ["FAILED"])
                await status_filter.on_value_change.call_args.args[0](SimpleNamespace(value=["RUNNING"]))

            self.assertEqual(state.task_ids, ["t1"])
            self.assertEqual(state.statuses, ["RUNNING"])
            self.assertEqual(refresh.await_count, 3)
            self.assertIsNone(state.signature)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
