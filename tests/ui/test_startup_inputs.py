"""Startup controls show every step and keep ordinary raw drafts on refresh."""
import asyncio
import importlib.util
import json
from types import SimpleNamespace
import unittest

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from tests.presentation.test_startup_inputs import TASK_SCHEMA, STEPS


class StartupInputsTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(page('/startup-inputs'))

    def tearDown(self):
        self.client.delete()

    def view(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.desktop.components.startup_inputs'),
                             'startup needs inputs for all steps')
        from taskweave.desktop.components.startup_inputs import StartupInputs
        return StartupInputs(SimpleNamespace(call=self.call))

    async def call(self, operation, **params):
        if operation == 'task.get':
            return {'input_schema_json': json.dumps(TASK_SCHEMA)}
        if operation == 'environment.list':
            return [{'environment_id': 'env-a', 'public_config_json': '{"env":"automatic"}'},
                    {'environment_id': 'env-b', 'public_config_json': '{"env":"other"}'}]
        raise AssertionError(f'Startup must not evaluate bindings: {operation}')

    def test_all_steps_collapsed_manual_fields_tagged_and_blank_required_submits(self):
        async def scenario():
            view = self.view()
            environment = ui.select(['env-a', 'env-b'], value='env-a')
            await view.render(STEPS, environment, task_id='task')
            self.assertEqual(set(view.step_forms), {'first', 'second'})
            self.assertTrue(all(not expansion.value for expansion in view.step_expansions.values()))
            first = view.step_forms['first']
            self.assertEqual(set(first.controls), {'amount', 'flag'})
            self.assertIn('必录', first.controls['amount'][1].label)
            self.assertIn('可选', view.step_forms['second'].controls['shared'][1].label)
            self.assertEqual(view.step_values(), {})
            first.controls['flag'][1].set_value(False)
            view.step_forms['second'].controls['answer'][1].set_value(8)
            self.assertEqual(view.step_values(), {'first': {'flag': False}, 'second': {'answer': 8}})
        self.run_scenario(scenario)

    def test_environment_and_collapse_keep_invalid_json_and_task_draft(self):
        async def scenario():
            steps = [{'step_id': 'step', 'name': 'Rows', 'bindings': {}, 'input_schema': {
                'properties': {'settings': {'type': 'object'}}}}]
            view = self.view()
            environment = ui.select(['env-a', 'env-b'], value='env-a')
            await view.render(steps, environment, task_id='task')
            view.step_expansions['step'].set_value(True)
            view.step_forms['step'].controls['settings'][1].set_value('{unfinished')
            view.task_form.controls['shared'][1].set_value('typed')
            view.step_expansions['step'].set_value(False)
            environment.value = 'env-b'
            self.assertEqual(view.step_forms['step'].controls['settings'][1].value, '{unfinished')
            self.assertEqual(view.task_form.controls['shared'][1].value, 'typed')
            self.assertFalse(view.step_expansions['step'].value)
        self.run_scenario(scenario)

    def run_scenario(self, scenario):
        async def mounted():
            with self.client: await scenario()
        asyncio.run(mounted())


class StartupExecutionPageTests(unittest.TestCase):
    def test_create_dialog_submits_both_steps_and_restores_task_raw_drafts(self):
        from unittest.mock import AsyncMock, MagicMock
        from taskweave.desktop.pages.executions import RunPage
        from taskweave.presentation.state import ExecutionPageState

        client = Client(page('/startup-all-steps-create'))
        calls, actions = [], {}
        tasks = [{'task_id': task_id, 'name': task_id} for task_id in ('task-a', 'task-b')]
        steps = [{'step_id': step_id, 'name': step_id, 'validation_state': 'VALIDATED', 'bindings': {},
                  'input_schema': {'type': 'object', 'properties': {'count': {'type': 'integer'},
                      'settings': {'type': 'object'}}, 'required': ['count']}}
                 for step_id in ('first', 'second')]
        async def call(operation, **params):
            calls.append((operation, params))
            if operation == 'task.list': return tasks
            if operation == 'step.list': return steps
            if operation == 'task.get': return {'input_schema_json': json.dumps(TASK_SCHEMA)}
            if operation == 'environment.list': return []
            if operation == 'task.flow.get':
                return {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
                    {'id': item['step_id'], 'kind': 'action', 'step_id': item['step_id']} for item in steps]}}
            if operation == 'run.create': return {'run_id': 'created'}
            if operation == 'run.start': return {'accepted': True}
            raise AssertionError(operation)
        def button(label, callback, **kwargs):
            actions[label] = callback
            return ui.button(label)
        async def environment_select():
            return ui.select({}, value=None, label='环境')
        async def forbidden_trial_variables(*args, **kwargs):
            self.fail('Startup must not resolve trial bindings')
        async def scenario():
            with client:
                run_page = RunPage(SimpleNamespace(call=call), ExecutionPageState(), button, AsyncMock(),
                    environment_select, forbidden_trial_variables, MagicMock(), lambda: 'executions', lambda: 1)
                await run_page.open_create('task-a')
                dialog = next(item for item in client.elements.values() if isinstance(item, ui.dialog) and item.value)
                counts = [item for item in dialog.descendants() if getattr(item, 'label', None) == 'count · 必录']
                settings = [item for item in dialog.descendants() if getattr(item, 'label', None) == 'settings · 可选']
                self.assertEqual(len(counts), 2)
                self.assertEqual(len(settings), 2)
                counts[0].set_value(11)
                counts[1].set_value(22)
                settings[1].set_value('{unfinished')
                task_selector = next(item for item in dialog.descendants() if getattr(item, 'label', None) == '选择任务')
                await task_selector._change_handlers[-1](SimpleNamespace(value='task-b'))
                await task_selector._change_handlers[-1](SimpleNamespace(value='task-a'))
                settings = [item for item in dialog.descendants() if getattr(item, 'label', None) == 'settings · 可选']
                self.assertEqual(settings[1].value, '{unfinished')
                settings[1].set_value('{"ok":true}')
                await actions['创建并执行']()
                self.assertEqual(calls[-2], ('run.create', {'task_id': 'task-a', 'inputs': {},
                    'step_inputs': {'first': {'count': 11}, 'second': {'count': 22, 'settings': {'ok': True}}},
                    'environment_id': None, 'defer_inputs': True}))
                self.assertEqual(calls[-1][1]['start_step_id'], 'first')
                # A fresh creation accepts every required field left blank.
                await run_page.open_create('task-a')
                await actions['创建并执行']()
                self.assertEqual(calls[-2][1]['inputs'], {})
                self.assertEqual(calls[-2][1]['step_inputs'], {})
                self.assertTrue(calls[-2][1]['defer_inputs'])
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
