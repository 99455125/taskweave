"""Execution filters are owned by their page state."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.pages.executions import ExecutionsPage, RunPage
from taskweave.desktop.state import ExecutionPageState


class ExecutionsPageTests(unittest.TestCase):
    def test_create_controlled_flow_starts_whole_flow_without_linear_step_override(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        from taskweave.presentation.debug import TrialInputDraft
        client = Client(page_route('/create-controlled-flow'))
        calls, callbacks = [], {}
        async def call(operation, **params):
            calls.append((operation, params))
            if operation == 'task.list': return [{'task_id': 'task', 'name': 'Loop task'}]
            if operation == 'step.list': return [{'step_id': 'step', 'name': 'First', 'validation_state': 'VALIDATED'}]
            if operation == 'task.flow.get': return {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
                {'id': 'each', 'kind': 'foreach', 'items': {'literal': [1, 2]},
                 'body': {'id': 'body', 'kind': 'sequence', 'children': [{'id': 'step', 'kind': 'action', 'step_id': 'step'}]}}]}}
            if operation == 'task.get': return {'input_schema_json': '{"type":"object"}'}
            if operation == 'environment.list': return []
            if operation == 'run.create': return {'run_id': 'controlled-run'}
            if operation == 'run.start': return {'accepted': True}
            raise AssertionError(operation)
        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)
        async def inputs(step, environment, **kwargs):
            draft = TrialInputDraft()
            draft.task.configure({'type': 'object'}, {})
            draft.step.configure({'type': 'object'}, {})
            return SimpleNamespace(input_draft=draft)
        async def scenario():
            with client:
                editor = RunPage(SimpleNamespace(call=call), ExecutionPageState(), button, AsyncMock(),
                    AsyncMock(return_value=SimpleNamespace(value=None, on_value_change=lambda _: None)), inputs, MagicMock(), lambda: 'executions', lambda: 1)
                await editor.open_create('task')
                dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                start = next(el for el in dialog.descendants() if isinstance(el, ui.select)
                             and el._props.get('label') in {'开始步骤', '启动范围'})
                self.assertFalse(start.enabled, 'Controlled flows must not offer a linear start step')
                await callbacks['创建并执行']()
                self.assertEqual(calls[-1][0], 'run.start')
                self.assertIsNone(calls[-1][1]['start_step_id'])
                self.assertEqual(calls[-2][1]['step_inputs'], {})
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_task_switch_renders_one_input_panel_when_start_change_event_overlaps(self):
        import json
        from nicegui import background_tasks, core, ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        from taskweave.desktop.components.trial_inputs import TrialInputPanel

        client = Client(page_route('/run-create-task-switch'))

        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            calls, callbacks = [], {}
            tasks = [{'task_id': key, 'name': key} for key in ('first', 'second')]
            steps = {key: [{'step_id': key + '-step', 'name': key,
                           'validation_state': 'VALIDATED', 'bindings': {},
                           'input_schema': {'type': 'object', 'properties': {}}}] for key in ('first', 'second')}

            async def call(operation, **params):
                calls.append((operation, params))
                if operation == 'task.list': return tasks
                if operation == 'step.list': return steps[params['task_id']]
                if operation == 'task.flow.get': return {'version': 2, 'root': {'id': 'root', 'kind': 'sequence',
                    'children': [{'id': step['step_id'], 'kind': 'action', 'step_id': step['step_id']}
                                 for step in steps[params['task_id']]]}}
                if operation == 'task.get':
                    if params['task_id'] == 'second':
                        entered.set()
                        await release.wait()
                    return {'input_schema_json': json.dumps({'type': 'object',
                        'properties': {'org': {'type': 'string'}}, 'required': ['org']})}
                if operation == 'environment.list': return []
                if operation == 'run.create': return {'run_id': 'new-run'}
                if operation == 'run.start': return {'accepted': True}
                raise AssertionError(operation)

            def button(label, callback, **kwargs):
                callbacks[label] = callback
                return ui.button(label, on_click=callback)

            async def environment_select():
                return ui.select({}, label='运行 / 调试环境', value=None)

            previous_tasks = set(background_tasks.running_tasks)
            with client, patch.object(core, 'loop', asyncio.get_running_loop()):
                controller = SimpleNamespace(call=call)
                panel = TrialInputPanel(controller, lambda: None, str)
                page = RunPage(controller, ExecutionPageState(), button, AsyncMock(),
                               environment_select, panel.render, MagicMock(), lambda: 'executions', lambda: 1)
                await page.open_create('first')
                dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                task_select = next(el for el in dialog.descendants() if el._props.get('label') == '选择任务')
                task_select.value = 'second'
                await asyncio.wait_for(entered.wait(), timeout=1)
                task_select.value = 'first'
                await asyncio.sleep(0)
                release.set()
                while pending := set(background_tasks.running_tasks) - previous_tasks:
                    await asyncio.gather(*pending)

                expansions = [el.text for el in dialog.descendants() if isinstance(el, ui.expansion)]
                self.assertEqual(expansions, ['任务输入 · 各步骤共用', '1. first'])
                org_inputs = [el for el in dialog.descendants() if el._props.get('label') == 'org · 必录']
                self.assertEqual(len(org_inputs), 1)
                org_inputs[0].value = 'selected-org'
                await callbacks['创建并执行']()
                self.assertEqual(calls[-2], ('run.create', {'task_id': 'first',
                    'inputs': {'org': 'selected-org'}, 'step_inputs': {},
                    'environment_id': None, 'defer_inputs': True}))
                self.assertEqual(calls[-1][1]['start_step_id'], 'first-step')

        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_create_dialog_cancel_preserves_state_and_submit_starts_selected_step(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        from taskweave.presentation.debug import TrialInputDraft
        client = Client(page_route('/run-create-confirmation'))
        calls, callbacks = [], {}
        steps = [
            {'step_id': 'step-1', 'name': 'First', 'validation_state': 'VALIDATED'},
            {'step_id': 'step-2', 'name': 'Second', 'validation_state': 'VALIDATED'},
        ]

        async def call(operation, **params):
            calls.append((operation, params))
            if operation == 'task.list':
                return [{'task_id': 'task-1', 'name': 'Task'}]
            if operation == 'step.list':
                return steps
            if operation == 'task.flow.get':
                return {'version': 2, 'root': {'id': 'root', 'kind': 'sequence',
                    'children': [{'id': step['step_id'], 'kind': 'action', 'step_id': step['step_id']} for step in steps]}}
            if operation == 'task.get':
                return {'input_schema_json': '{"type":"object"}'}
            if operation == 'environment.list':
                return []
            if operation == 'run.create':
                return {'run_id': 'created-run'}
            if operation == 'run.start':
                return {'accepted': True}
            raise AssertionError(operation)

        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)

        async def inputs(step, environment, **kwargs):
            draft = TrialInputDraft()
            draft.task.configure({'type': 'object'}, {})
            draft.step.configure({'type': 'object'}, {})
            return SimpleNamespace(input_draft=draft)

        async def scenario():
            with client:
                state, repaint = ExecutionPageState(), AsyncMock()
                page = RunPage(SimpleNamespace(call=call), state, button, repaint,
                               AsyncMock(return_value=SimpleNamespace(value=None, on_value_change=lambda _: None)), inputs, MagicMock(), lambda: 'executions', lambda: 1)
                await page.open_create('task-1')
                dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                cancel = next(el for el in dialog.descendants() if isinstance(el, ui.button) and el.text == '取消')
                next(event.handler for event in cancel._event_listeners.values() if event.type == 'click')(None)
                self.assertFalse(dialog.value)
                self.assertEqual([operation for operation, _ in calls], ['task.list', 'step.list', 'task.flow.get', 'task.get', 'environment.list'])
                self.assertIsNone(state.run_id)
                repaint.assert_not_awaited()
                await page.open_create('task-1')
                dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                start = next(el for el in dialog.descendants() if el._props.get('label') == '开始步骤')
                await start._change_handlers[-1](SimpleNamespace(value='step-2'))
                await callbacks['创建并执行']()
                self.assertEqual(calls[-2], ('run.create', {'task_id': 'task-1', 'inputs': {},
                    'step_inputs': {}, 'environment_id': None, 'defer_inputs': True}))
                self.assertEqual(calls[-1][0], 'run.start')
                self.assertEqual(calls[-1][1]['start_step_id'], 'step-2')
                self.assertEqual(state.run_id, 'created-run')
                self.assertFalse(dialog.value)
                repaint.assert_awaited_once()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_filters_update_page_state_and_refresh_runs(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [[{"task_id": "t1", "name": "Task"}], []]
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
