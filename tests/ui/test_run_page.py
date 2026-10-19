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

    def test_real_dialog_submits_plain_selection_and_input_state(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as nicegui_page
        from taskweave.presentation.debug import TrialInputDraft
        from tests.presentation.test_run_creation import Application

        async def scenario():
            app = Application()
            actions = {}
            def button(label, action, **kwargs):
                actions[label] = action
                return ui.button(label)
            environment = ui.select({'env': 'Environment'}, value='env')
            forms = []
            async def inputs(step, environment, *, task_id):
                draft = TrialInputDraft()
                draft.set_environment(environment.value)
                draft.task.configure({'properties': {'count': {'type': 'integer'}}}, {})
                control = ui.number('count')
                control.on_value_change(lambda event: draft.task.change('count', event.value))
                forms.append(control)
                return SimpleNamespace(input_draft=draft)
            details = SimpleNamespace(refresh=AsyncMock(), own_timer=lambda timer: timer.cancel())
            run_page = RunPage(app, ExecutionPageState(), button, AsyncMock(),
                AsyncMock(return_value=environment), inputs, details, lambda: 'run', lambda: 1)
            await run_page.render()
            await actions['新建执行']()
            forms[-1].value = 7
            # Delete render handles: submitting must still consume ordinary state.
            forms[-1].delete()
            await actions['创建并执行']()
            create = app.calls[-2]
            self.assertEqual(create[1]['task_id'], 'a')
            self.assertEqual(create[1]['inputs'], {'count': 7})
            self.assertEqual(create[1]['environment_id'], 'env')
            self.assertEqual(run_page.state.run_id, 'created')
            run_page.paint.assert_awaited_once()

        client = Client(nicegui_page('/run-creation-state-owner'))
        try:
            async def mounted():
                with client:
                    await scenario()
            asyncio.run(mounted())
        finally:
            client.delete()


if __name__ == "__main__":
    unittest.main()
