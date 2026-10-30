"""The shared execution selector routes task combinations to their launch UI."""
import asyncio
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from taskweave.desktop.pages.executions import RunPage
from taskweave.presentation.state import ExecutionPageState


class ExecutionEntryTests(unittest.TestCase):
    def exercise(self, *, tasks_available):
        self.assertIn('open_sequence', inspect.signature(RunPage).parameters,
                      'the execution selector needs a combination launch callback')
        client = Client(page('/execution-entry-' + str(tasks_available)))
        calls, opened = [], []
        async def call(operation, **params):
            calls.append((operation, params))
            if operation == 'task.list':
                return [{'task_id': 'task', 'name': 'A task'}] if tasks_available else []
            if operation == 'step.list':
                return [{'step_id': 'step', 'name': 'First', 'validation_state': 'VALIDATED',
                         'input_schema': {'properties': {}}, 'bindings': {}}]
            if operation == 'sequence.list':
                return [{'sequence_id': 'combo', 'name': 'A combination', 'nodes': []}]
            if operation == 'task.flow.get':
                return {'version': 2, 'root': {'id': 'root', 'kind': 'sequence',
                    'children': [{'id': 'action', 'kind': 'action', 'step_id': 'step'}]}}
            if operation == 'task.get': return {'input_schema_json': '{"properties":{}}'}
            if operation == 'environment.list': return []
            raise AssertionError(operation)
        async def open_sequence(sequence_id):
            dialogs = [item for item in client.elements.values() if isinstance(item, ui.dialog)]
            self.assertTrue(dialogs)
            self.assertTrue(all(not item.value for item in dialogs), 'close task dialog before opening combination')
            await asyncio.sleep(0)
            opened.append(sequence_id)
        async def environment_select():
            return ui.select({}, value=None, label='环境')
        async def scenario():
            with client:
                editor = RunPage(SimpleNamespace(call=call), ExecutionPageState(),
                    lambda label, callback, **kwargs: ui.button(label, on_click=callback), AsyncMock(),
                    environment_select, AsyncMock(), MagicMock(), lambda: 'executions', lambda: 1,
                    open_sequence=open_sequence)
                await editor.open_create()
                dialog = next(item for item in client.elements.values() if isinstance(item, ui.dialog) and item.value)
                selector = next(item for item in dialog.descendants() if getattr(item, 'label', None) == '选择任务')
                self.assertEqual(selector.options['sequence:combo'], '任务组合 · A combination')
                if tasks_available:
                    self.assertEqual(selector.options['task'], 'A task')
                else:
                    self.assertFalse(any(isinstance(item, ui.button) and item.text == '创建并执行'
                                         for item in dialog.descendants()))
                await selector._change_handlers[-1](SimpleNamespace(value='sequence:combo'))
                self.assertEqual(opened, ['combo'])
                self.assertFalse(dialog.value)
                self.assertFalse(any(operation in {'run.create', 'run.start'} for operation, _ in calls))
                if not tasks_available:
                    self.assertEqual([operation for operation, _ in calls], ['task.list', 'sequence.list'])
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_selector_routes_combination_alongside_eligible_tasks(self):
        self.exercise(tasks_available=True)

    def test_combination_can_be_selected_without_eligible_tasks(self):
        self.exercise(tasks_available=False)
