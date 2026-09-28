"""Workbench's generic button helper delegates page-specific error handling."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.workbench import Workbench


class ButtonDispatchTests(unittest.TestCase):
    def test_overlapping_clicks_submit_once(self):
        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.busy = False
            workbench._buttons = []
            control = MagicMock()
            control.enabled = True
            control.is_deleted = False
            control.props.return_value = control
            control.style.return_value = control
            calls, entered, release = [], asyncio.Event(), asyncio.Event()
            async def callback():
                calls.append("submit")
                entered.set()
                await release.wait()
            ui = MagicMock()
            ui.button.return_value = control
            with patch("taskweave.desktop.workbench.ui", ui):
                workbench.button("save", callback)
                click = ui.button.call_args.kwargs["on_click"]
                first = asyncio.create_task(click())
                await entered.wait()
                await click()
                release.set()
                await first
            self.assertEqual(calls, ["submit"])
            self.assertFalse(workbench.busy)

        asyncio.run(scenario())

    def test_failure_and_settled_callbacks_are_explicit_and_busy_state_recovers(self):
        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.busy = False
            workbench._buttons = []
            control = MagicMock()
            control.enabled = True
            control.is_deleted = False
            control.props.return_value = control
            control.style.return_value = control
            ui = MagicMock()
            ui.button.return_value = control
            failure = AsyncMock()
            settled = AsyncMock()

            async def callback():
                raise TaskError("STEP_NOT_FOUND")

            with patch("taskweave.desktop.workbench.ui", ui):
                workbench.button("test", callback, on_failure=failure, on_settled=settled)
                await ui.button.call_args.kwargs["on_click"]()

            failure.assert_awaited_once()
            settled.assert_awaited_once_with()
            self.assertFalse(workbench.busy)
            control.set_enabled.assert_called_with(True)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
