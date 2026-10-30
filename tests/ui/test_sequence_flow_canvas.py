"""Actual combination editor callbacks persist structured control definitions."""

import asyncio

from nicegui.client import Client
from nicegui.page import page

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
from taskweave.presentation.flow_editor import find_node
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from nicegui import ui
from taskweave.desktop.pages.sequences import SequencesPage


class SequenceCanvasTests(CoreFixture):
    def test_add_after_control_selects_task_and_preserves_control_form(self):
        task = self.task()
        client = Client(page('/sequence-add-selection'))
        async def scenario():
            with client, patch.object(ui.button, 'on_click', lambda item, callback: item.on('click', callback)):
                editor = SequencesPage(DesktopController(self.app),
                    lambda label, callback, **kwargs: ui.button(label, on_click=callback),
                    AsyncMock(), identity=lambda: 'sequences')
                await editor._load()
                await editor.flow_editor.add('foreach')
                control = editor.flow_editor.selected
                editor.flow_editor.form = SimpleNamespace(value=lambda: {'items': {'literal': [1, 2]}, 'max_items': 4})
                await editor.add_dialog()
                chooser = next(e for e in client.elements.values() if e.props.get('label') == '选择任务')
                chooser.set_value(task)
                button = next(e for e in client.elements.values() if isinstance(e, ui.button) and e.text == '添加到末尾')
                await next(e.handler for e in button._event_listeners.values() if e.type == 'click')()
                await asyncio.sleep(.01)
                self.assertIsNone(editor.flow_editor.selected)
                self.assertEqual(editor.selected_node_id, editor.draft.nodes[-1]['node_id'])
                self.assertEqual(find_node(editor.draft.flow, control)[0]['items'], {'literal': [1, 2]})
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_drop_selects_moved_reference_and_keeps_literal_text(self):
        task = self.task()
        client = Client(page('/sequence-drop-selection'))
        async def scenario():
            with client:
                editor = SequencesPage(DesktopController(self.app),
                    lambda label, callback, **kwargs: ui.button(label, on_click=callback),
                    AsyncMock(), identity=lambda: 'sequences')
                await editor._load()
                first = editor.draft.add(task)
                editor.draft.add(task)
                await editor.flow_editor.add('foreach')
                control = editor.flow_editor.selected
                editor.literal_text[(first, None, 'value')] = '{unfinished'
                editor.invalid_literals.add((first, None, 'value'))
                await editor.flow_editor.drop(first, control + '-body', 0)
                self.assertIsNone(editor.flow_editor.selected)
                self.assertEqual(editor.selected_node_id, first)
                self.assertEqual(editor.literal_text[(first, None, 'value')], '{unfinished')
                self.assertIn((first, None, 'value'), editor.invalid_literals)
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_dependency_failure_is_visible_and_preserves_draft_and_selection(self):
        from copy import deepcopy
        task = self.task()
        client = Client(page('/sequence-rejected-operations'))
        async def scenario():
            with client:
                editor = SequencesPage(DesktopController(self.app),
                    lambda label, callback, **kwargs: ui.button(label, on_click=callback),
                    AsyncMock(), identity=lambda: 'sequences')
                await editor._load()
                producer = editor.draft.add(task)
                consumer = editor.draft.add(task)
                editor.draft.nodes[1]['inputs']['value'] = {'kind': 'output', 'node_id': producer,
                    'step_id': 'child-step', 'output': 'data', 'pointer': ''}
                editor.selected_node_id = consumer
                editor.flow_editor.render()
                before = deepcopy(editor.draft.payload())
                await editor.flow_editor.drop(consumer, 'root', 0)
                self.assertIn('无法移动：', editor.flow_editor.error.text)
                self.assertEqual(editor.draft.payload(), before)
                self.assertEqual(editor.selected_node_id, consumer)
                await editor.remove_node(0)
                self.assertIn('无法移除：', editor.flow_editor.error.text)
                self.assertEqual(editor.draft.payload(), before)
                self.assertEqual(editor.selected_node_id, consumer)
                editor.repaint.assert_not_awaited()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_optional_projection_scope_renders_combination_loop_mapping(self):
        source_task = self.task()
        source_step = self.step(source_task)
        receiver_task = self.task()
        self.step(receiver_task, input_schema={'type': 'object', 'properties': {'values': {}}})
        client = Client(page('/sequence-projection-default'))
        async def scenario():
            with client:
                editor = SequencesPage(DesktopController(self.app), lambda label, callback, **kwargs: ui.button(label, on_click=callback),
                                       AsyncMock(), identity=lambda: 'sequences')
                await editor._load()
                editor.draft.add(source_task)
                editor.draft.add(receiver_task)
                first, receiver = editor.draft.nodes
                loop_id = editor.draft.add_control('foreach')
                loop, _ = find_node(editor.draft.flow, loop_id)
                editor.draft.move_to(first['node_id'], loop['body']['id'])
                editor.draft.move_to(receiver['node_id'], 'root')
                receive_step = editor.steps[receiver_task][0]['step_id']
                receiver['step_inputs'][receive_step] = {'values': {'kind': 'output', 'node_id': first['node_id'],
                    'step_id': source_step['step_id'], 'output': 'data', 'pointer': '', 'item_pointer': '/value', 'loop_node_id': loop_id}}
                await editor._node_mappings(1, receiver)
                choice = next(element for element in client.elements.values() if element.props.get('label') == '逐轮投影所属循环')
                self.assertEqual(choice.value, 'combination:' + loop_id)
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_control_failure_keeps_history_actions_renderable(self):
        task = self.task()
        step = self.step(task)
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        node = {'node_id': 'unreached', 'task_id': task, 'environment_id': None, 'inputs': {}, 'step_inputs': {}}
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
            {'id': 'each', 'kind': 'foreach', 'items': {'literal': 42}, 'body': {'id': 'body', 'kind': 'sequence', 'children': [
                {'id': 'unreached', 'kind': 'action', 'step_id': 'unreached'}]}}]}}
        saved = self.app.sequences.save('Invalid runtime list', [node], {'type': 'object'}, flow=flow)
        run = self.app.sequences.prepare_start(saved['sequence_id'], 'invalid-list', {})
        self.app.sequence_driver.advance(run['sequence_run_id'])
        run = self.app.sequences.run_get(run['sequence_run_id'])
        self.assertEqual(run['status'], 'BLOCKED')
        client = Client(page('/sequence-control-error'))
        async def scenario():
            with client:
                editor = SequencesPage(SimpleNamespace(), lambda label, callback, **kwargs: ui.button(label, on_click=callback),
                                       AsyncMock(), identity=lambda: 'sequences')
                await editor._run_controls(run)
                texts = [getattr(element, 'text', '') for element in client.elements.values()]
                self.assertIn('删除运行记录', texts)
                self.assertNotIn('重试步骤', texts)
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_parallel_control_and_task_path_save_through_real_page(self):
        task = self.task()
        step = self.step(task)
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        client = Client(page('/sequence-flow-canvas'))
        async def scenario():
            with client:
                workbench = Workbench(DesktopController(self.app))
                await workbench.navigate('sequences')
                editor = workbench.sequences_page
                await editor.add_node(task)
                task_node = editor.draft.nodes[0]['node_id']
                await editor.flow_editor.add('if')
                control = editor.flow_editor.selected
                editor.flow_editor.form.parallel.set_value(True)
                editor.flow_editor.flush()
                node, _ = find_node(editor.draft.flow, control)
                editor.draft.move_to(task_node, node['cases'][0]['body']['id'])
                editor.flow_editor.form = None
                await editor.repaint()
                editor.draft.name = 'Parallel canvas'
                await editor.save()
                saved = self.app.sequences.get(editor.draft.sequence_id)
                node, _ = find_node(saved['flow'], control)
                self.assertTrue(node['parallel'])
                self.assertEqual(node['cases'][0]['body']['children'][0]['step_id'], task_node)
                editor.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_invalid_control_draft_blocks_selection_without_losing_form(self):
        task = self.task()
        step = self.step(task)
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        client = Client(page('/sequence-control-draft'))
        async def scenario():
            with client:
                workbench = Workbench(DesktopController(self.app))
                await workbench.navigate('sequences')
                editor = workbench.sequences_page
                await editor.add_node(task)
                await editor.flow_editor.add('if')
                original_form = editor.flow_editor.form
                original_control = editor.flow_editor.selected
                original_form.cases[0]['condition'].op.set_value('all')
                with self.assertRaises(TaskError):
                    await editor.select_node(editor.draft.nodes[0]['node_id'])
                self.assertIs(editor.flow_editor.form, original_form)
                self.assertEqual(editor.flow_editor.selected, original_control)
                self.assertEqual(original_form.cases[0]['condition'].op.value, 'all')
                editor.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
