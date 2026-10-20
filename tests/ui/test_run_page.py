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
        self._exercise_dialog(standalone=False)

    def test_standalone_dialog_selects_task_then_calls_completion(self):
        self._exercise_dialog(standalone=True)

    def _exercise_dialog(self, *, standalone):
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
            completed = AsyncMock()
            if standalone:
                await run_page.open_create(on_created=completed)
                details.refresh.assert_not_awaited()
                selects = [element for element in client.elements.values()
                           if isinstance(element, ui.select) and element.label == '选择任务']
                task_select = selects[-1]
                # Exercise the real task-change event and dependent start selector.
                task_select._props['model-value'] = 'b'
                await task_select._change_handlers[-1](SimpleNamespace(value='b'))
            else:
                await run_page.render()
                await actions['新建执行']()
            forms[-1].value = 7
            # Delete render handles: submitting must still consume ordinary state.
            forms[-1].delete()
            await actions['创建并执行']()
            create = app.calls[-2]
            self.assertEqual(create[1]['task_id'], 'b' if standalone else 'a')
            self.assertEqual(create[1]['inputs'], {'count': 7})
            self.assertEqual(create[1]['environment_id'], 'env')
            self.assertEqual(run_page.state.run_id, 'created')
            if standalone:
                completed.assert_awaited_once()
                run_page.paint.assert_not_awaited()
            else:
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
