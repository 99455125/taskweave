"""Composition launch asks manual inputs for every distinct task call."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page

from taskweave.desktop.pages.sequences import SequencesPage
from tests._core_fixture import CoreFixture
from taskweave.desktop.controller import DesktopController


class SequenceStartupInputsUITests(unittest.TestCase):
    def test_launch_has_two_levels_and_keeps_repeated_call_values_distinct(self):
        client = Client(page('/composition-startup-fields'))
        callbacks, calls = {}, []
        async def call(operation, **kwargs):
            calls.append((operation, kwargs))
            if operation == 'environment.list': return []
            if operation == 'sequence.trial': return {'sequence_run_id': 'new-run'}
            raise AssertionError(operation)
        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)
        async def scenario():
            with client:
                editor = SequencesPage(SimpleNamespace(call=call), button, AsyncMock(), identity=lambda: 'sequences')
                editor.tasks = [{'task_id': 'task', 'name': '重复任务', 'input_schema_json': json.dumps({
                    'type': 'object', 'properties': {'task_value': {'type': 'string'}}})}]
                editor.steps = {'task': [{'step_id': 'step', 'name': '手工步骤', 'bindings': {
                    'automatic': {'literal': 'derived'}}, 'input_schema': {'type': 'object', 'properties': {
                        'value': {'type': 'integer'}, 'optional': {'type': 'string'},
                        'automatic': {'type': 'string'}}, 'required': ['value']}}]}
                editor.draft.load({'sequence_id': 'combo', 'revision': 1, 'name': '组合', 'description': '',
                    'input_schema': {'type': 'object'}, 'nodes': [
                        {'node_id': nid, 'task_id': 'task', 'environment_id': None, 'inputs': {}, 'step_inputs': {}}
                        for nid in ['first', 'second']]})
                await editor.launch_dialog()
                dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                groups = [el for el in dialog.descendants() if isinstance(el, ui.expansion)
                          and '重复任务' in el.props.get('label', '')]
                self.assertEqual(len(groups), 2)
                for group, value in zip(groups, [11, 22]):
                    step = next(el for el in group.descendants() if isinstance(el, ui.expansion)
                                and '手工步骤' in el.props.get('label', ''))
                    number = next(el for el in step.descendants() if isinstance(el, ui.number))
                    number.set_value(value)
                    labels = [el.props.get('label', '') for el in step.descendants()]
                    self.assertFalse(any('automatic' in label for label in labels))
                await callbacks['开始调试']()
                launch = next(kwargs for operation, kwargs in calls if operation == 'sequence.trial')
                self.assertEqual(launch['node_step_inputs'], {
                    'first': {'step': {'value': 11}}, 'second': {'step': {'value': 22}}})
                self.assertEqual(editor.draft.selected_run_id, 'new-run')
                self.assertEqual(set(operation for operation, _ in calls), {'sequence.trial'})
        try:
            asyncio.run(scenario())
        finally:
            client.delete()


class SequenceStartupDefaultTests(CoreFixture):
    def test_task_mapping_preserves_editable_step_default_but_hides_direct_bindings(self):
        task_schema = {'type': 'object', 'properties': {'x': {'type': 'integer'}}}
        task = self.app.repo.create_task('自动任务输入', task_schema)['task_id']
        step_schema = {'type': 'object', 'properties': {'x': {'type': 'integer', 'default': 7}}}
        local = self.step(task, name='本地默认值', input_schema=step_schema)
        bound = self.step(task, name='直接绑定', input_schema=step_schema, bindings={'x': {'literal': 4}})
        mapped = self.step(task, name='组合步骤映射', input_schema=step_schema)
        literal = self.step(task, name='组合固定值', input_schema={
            'type': 'object', 'properties': {'x': {'type': 'integer'}}})
        for step in [local, bound, mapped, literal]:
            self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        saved = self.app.sequences.save('本地默认值优先', [{
            'node_id': 'call', 'task_id': task, 'environment_id': None,
            'inputs': {'x': {'kind': 'sequence', 'pointer': '/x'}},
            'step_inputs': {mapped['step_id']: {'x': {'kind': 'sequence', 'pointer': '/x'}},
                            literal['step_id']: {'x': {'kind': 'literal', 'value': 8}}}}], task_schema)
        client = Client(page('/composition-local-default'))
        callbacks = {}
        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)
        async def scenario():
            with client:
                editor = SequencesPage(DesktopController(self.app), button, AsyncMock(), identity=lambda: 'sequences')
                editor.tasks = await editor.controller.call('task.list')
                editor.steps = {task: await editor.controller.call('step.list', task_id=task)}
                editor.draft.load(saved)
                editor.draft.launch_inputs_text = '{"x": 3}'
                await editor.launch_dialog()
                view = editor.startup_views['call']
                self.assertIn('x', view.step_forms[local['step_id']].controls)
                self.assertIn('x', view.step_forms[literal['step_id']].controls)
                literal_control = view.step_forms[literal['step_id']].controls['x'][1]
                self.assertEqual(literal_control.value, 8)
                literal_control.set_value(10)
                self.assertNotIn('x', view.step_forms[bound['step_id']].controls)
                self.assertNotIn('x', view.step_forms[mapped['step_id']].controls)
                control = view.step_forms[local['step_id']].controls['x'][1]
                self.assertEqual(control.value, 7)
                control.set_value(9)
                await callbacks['开始调试']()
                for _ in range(600):
                    run = self.app.sequences.run_get(editor.draft.selected_run_id)
                    if run['status'] not in {'READY', 'RUNNING'}:
                        break
                    await asyncio.sleep(.03)
                self.assertEqual(run['status'], 'SUCCEEDED', run)
                self.assertEqual(run['snapshot']['node_step_inputs'], {
                    'call': {local['step_id']: {'x': 9}, literal['step_id']: {'x': 10}}})
                child = run['nodes'][0]['run_id']
                self.assertEqual(self.app.runs.output(child, local['step_id']), {'x': 9})
                self.assertEqual(self.app.runs.output(child, bound['step_id']), {'x': 4})
                self.assertEqual(self.app.runs.output(child, mapped['step_id']), {'x': 3})
                self.assertEqual(self.app.runs.output(child, literal['step_id']), {'x': 10})
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
