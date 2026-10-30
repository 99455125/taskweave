"""Task sequence desktop route and draft state use the real application."""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page

from tests._core_fixture import CoreFixture
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.pages.sequences import SequencesPage
from taskweave.desktop.components.sequence_execution import SequenceExecution
from taskweave.desktop.workbench import Workbench
from taskweave.infrastructure.storage import uid
from taskweave.presentation.sequences import SequenceDraft


class SequenceDraftTests(unittest.TestCase):
    def test_move_uses_flow_neighbors_at_global_list_boundary(self):
        draft = SequenceDraft()
        draft.add('same-task')
        first = draft.nodes[0]['node_id']
        control = draft.add_control('foreach')
        draft.move(0, 1)
        self.assertEqual([n['id'] for n in draft.flow['root']['children']], [control, first])
        draft.move(0, -1)
        self.assertEqual([n['id'] for n in draft.flow['root']['children']], [first, control])

    def test_insert_and_move_keep_reference_data_and_tree_order(self):
        draft = SequenceDraft()
        first = draft.add('same-task')
        control = draft.add_control('if', index=0)
        second = draft.add('same-task', control + '-then', 0)
        original = next(n for n in draft.nodes if n['node_id'] == first)
        original.update(environment_id='environment', inputs={'v': {'kind': 'literal', 'value': 7}})
        draft.move_to(first, control + '-then', 0)
        self.assertEqual([n['node_id'] for n in draft.nodes], [first, second])
        self.assertIs(draft.nodes[0], original)
        self.assertEqual(draft.nodes[0]['environment_id'], 'environment')
        self.assertEqual(draft.nodes[0]['inputs']['v']['value'], 7)

    def test_invalid_dependency_moves_and_removal_are_atomic(self):
        from copy import deepcopy
        from taskweave.core.validation import TaskError
        draft = SequenceDraft()
        draft.add('producer')
        draft.add('receiver')
        first, second = draft.nodes
        second['inputs']['value'] = {'kind': 'output', 'node_id': first['node_id'],
            'step_id': 'source-step', 'output': 'data', 'pointer': ''}
        before = deepcopy(draft.payload())
        with self.assertRaises(TaskError):
            draft.move(1, -1)
        self.assertEqual(draft.payload(), before)
        with self.assertRaises(TaskError):
            draft.remove(0)
        self.assertEqual(draft.payload(), before)

    def test_load_uses_tree_order_for_reference_numbers(self):
        draft = SequenceDraft()
        first = draft.add('same-task')
        second = draft.add('same-task')
        definition = draft.payload()
        definition.update(sequence_id='saved', revision=1, name='saved')
        definition['nodes'].reverse()
        draft.load(definition)
        self.assertEqual([node['node_id'] for node in draft.nodes], [first, second])
        self.assertFalse(draft.needs_save())
        self.assertEqual(definition['nodes'][0]['node_id'], second)

    def test_sibling_moves_cross_controls_with_nested_references(self):
        draft = SequenceDraft()
        first = draft.add('same-task')
        control = draft.add_control('if')
        nested = draft.add('same-task', control + '-then')
        last = draft.add('same-task')
        draft.move(2, -1)
        self.assertEqual([node['node_id'] for node in draft.nodes], [first, last, nested])
        self.assertFalse(draft.can_move(2, -1))
        self.assertFalse(draft.can_move(2, 1))
        draft.move(0, 1)
        self.assertEqual([node['node_id'] for node in draft.nodes], [last, first, nested])

    def test_order_and_repeated_task_identity(self):
        draft = SequenceDraft()
        draft.add("same-task")
        draft.add("same-task")
        first, second = [item["node_id"] for item in draft.nodes]
        self.assertNotEqual(first, second)
        draft.move(1, -1)
        self.assertEqual([item["node_id"] for item in draft.nodes], [second, first])
        draft.remove(0)
        self.assertEqual(draft.nodes[0]["node_id"], first)


class SequencesPageTests(CoreFixture):
    def test_debug_history_excludes_formal_and_other_definition_records(self):
        client = Client(page('/sequence-debug-history'))
        async def scenario():
            runs = [{'sequence_run_id': key, 'sequence_id': owner,
                     'snapshot': {'name': name, 'mode': mode}, 'status': 'SUCCEEDED',
                     'created_at': '2026-10-24T00:00:00', 'error_code': None, 'nodes': []}
                    for key, owner, name, mode in [('debug-run', 'current', '当前组合', 'TRIAL'),
                        ('formal-run', 'current', '当前组合', 'EXECUTION'),
                        ('other-run', 'other', '其他组合', 'TRIAL')]]
            with client:
                editor = SequencesPage(SimpleNamespace(call=AsyncMock(return_value=runs)),
                    lambda title, cb, **kw: ui.button(title, on_click=cb), AsyncMock(), identity=lambda: 'sequences')
                editor.draft.sequence_id = 'current'
                editor.draft.selected_run_id = 'formal-run'
                editor.progress_area = ui.column()
                await editor.refresh_progress()
                selected = next(e for e in editor.progress_area.descendants() if e.props.get('label') == '调试记录')
                self.assertEqual(list(selected.options), ['debug-run'])
                self.assertEqual(editor.draft.selected_run_id, 'debug-run')
                editor.draft.sequence_id = 'no-runs'
                await editor.refresh_progress()
                self.assertIn('当前组合暂无调试记录', [getattr(e, 'text', '') for e in editor.progress_area.descendants()])
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_launch_dialog_cancel_keeps_input_and_start_uses_existing_action(self):
        client = Client(page('/sequence-launch-dialog'))
        async def scenario():
            callbacks = {}
            def button(label, callback, **kwargs):
                callbacks[label] = callback
                return ui.button(label, on_click=callback)
            with client:
                editor = SequencesPage(SimpleNamespace(), button, AsyncMock(), identity=lambda: 'sequences')
                editor.start = AsyncMock()
                await editor.launch_dialog()
                dialog = next(e for e in client.elements.values() if isinstance(e, ui.dialog) and e.value)
                entry = next(e for e in dialog.descendants() if e.props.get('label') == '启动输入（JSON 对象）')
                entry.set_value('{"value": 17}')
                cancel = next(e for e in dialog.descendants() if isinstance(e, ui.button) and e.text == '取消')
                next(v.handler for v in cancel._event_listeners.values() if v.type == 'click')(None)
                self.assertFalse(dialog.value)
                editor.start.assert_not_awaited()
                await editor.launch_dialog()
                dialog = next(e for e in client.elements.values() if isinstance(e, ui.dialog) and e.value)
                self.assertEqual(next(e for e in dialog.descendants()
                    if e.props.get('label') == '启动输入（JSON 对象）').value, '{"value": 17}')
                await callbacks['开始调试']()
                self.assertFalse(dialog.value)
                editor.start.assert_awaited_once_with()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_sequence_workspace_separates_composition_settings_history_and_node_tabs(self):
        task, _ = self._task('分层配置验收')
        client = Client(page('/sequence-hierarchy'))
        async def scenario():
            with client:
                wb = Workbench(DesktopController(self.app))
                await wb.navigate('sequences')
                editor = wb.sequences_page
                await editor.add_node(task)
                outer = next((e for e in client.elements.values() if 'tw-sequence-tabs' in e.classes), None)
                self.assertIsNotNone(outer, 'Composition, settings, and history belong at combination level')
                self.assertEqual([e.label for e in outer.descendants() if isinstance(e, ui.tab)],
                                 ['任务编排', '基础配置', '调试'])
                inner = next(e for e in client.elements.values() if 'tw-sequence-node-tabs' in e.classes)
                self.assertEqual([e.label for e in inner.descendants() if isinstance(e, ui.tab)],
                                 ['任务配置', '输入映射'])
                self.assertEqual(editor.active_section, 'flow')
                draft = editor.draft
                draft.nodes[0]['inputs']['value'] = {'kind': 'literal', 'value': 11}
                inner.set_value('mapping')
                outer.set_value('basic')
                await asyncio.sleep(0)
                await wb.paint()
                outer = next(e for e in client.elements.values() if 'tw-sequence-tabs' in e.classes)
                inner = next(e for e in client.elements.values() if 'tw-sequence-node-tabs' in e.classes)
                self.assertEqual(outer.value, 'basic')
                self.assertEqual(inner.value, 'mapping')
                self.assertEqual(draft.nodes[0]['inputs']['value']['value'], 11)
                outer.set_value('debug')
                await asyncio.sleep(0)
                self.assertIn(editor.progress_area, next(e for e in client.elements.values()
                    if 'tw-sequence-history' in e.classes).descendants())
                editor.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_add_task_previews_real_task_summary_and_confirmation(self):
        task, _ = self._task('已验证任务')
        other = self.app.repo.create_task('尚无步骤', description='本地未完成任务')['task_id']
        client = Client(page('/sequence-task-summary'))
        async def scenario():
            with client:
                editor = SequencesPage(DesktopController(self.app),
                    lambda title, cb, **kw: ui.button(title, on_click=cb), AsyncMock(), identity=lambda: 'sequences')
                await editor._load()
                await editor.add_dialog()
                chooser = next(e for e in client.elements.values() if e.props.get('label') == '选择任务')
                chooser.set_value(task)
                summary = next((e for e in client.elements.values() if 'tw-sequence-task-summary' in e.classes), None)
                self.assertIsNotNone(summary, 'Task selection needs an actual summary')
                labels = lambda: ' '.join(getattr(e, 'text', '') for e in summary.descendants())
                self.assertIn('1 个步骤', labels())
                self.assertIn('任务已确认', labels())
                chooser.set_value(other)
                self.assertIn('本地未完成任务', labels())
                self.assertIn('0 个步骤', labels())
                self.assertIn('任务待确认', labels())
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_delete_run_waits_for_confirmation_and_keeps_captured_run_identity(self):
        client = Client(page('/sequence-delete-confirmation'))
        async def scenario():
            writes, callbacks = [], {}
            async def call(operation, **kwargs): writes.append((operation, kwargs))
            def button(title, callback, **kwargs):
                callbacks[title] = callback
                return ui.button(title, on_click=callback)
            with client:
                editor = SequenceExecution(SimpleNamespace(call=call, open_review=AsyncMock()), button,
                    AsyncMock(), identity=lambda: 'sequences')
                editor.refresh_progress = AsyncMock()
                selection = SimpleNamespace(selected_run_id='run-to-delete')
                async def deleted(run_id):
                    if selection.selected_run_id == run_id:
                        selection.selected_run_id = None
                editor.on_deleted = deleted
                await editor._run_controls({'sequence_run_id': 'run-to-delete', 'status': 'CANCELLED'})

                async def decide(label):
                    async def invoke():
                        with client:
                            await callbacks['删除执行']()
                    pending = asyncio.create_task(invoke())
                    await asyncio.sleep(0)
                    self.assertEqual(writes, [], 'Deletion must wait for explicit confirmation')
                    dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                    selection.selected_run_id = 'other-run'
                    control = next(el for el in dialog.descendants() if isinstance(el, ui.button) and el.text == label)
                    next(event.handler for event in control._event_listeners.values() if event.type == 'click')(None)
                    await pending

                await decide('取消')
                self.assertEqual(writes, [])
                await decide('确认删除执行')
                self.assertEqual(writes, [('sequence.run.delete', {'sequence_run_id': 'run-to-delete'})])
                self.assertEqual(selection.selected_run_id, 'other-run')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_paused_waiting_and_blocked_combinations_can_be_cancelled(self):
        client = Client(page('/sequence-cancel-states'))
        async def scenario():
            calls, callbacks = [], {}
            async def call(operation, **kwargs): calls.append((operation, kwargs))
            def button(title, cb, **kwargs):
                callbacks[title] = cb
                return ui.button(title, on_click=cb)
            with client:
                editor = SequenceExecution(SimpleNamespace(call=call, open_review=AsyncMock()), button,
                    AsyncMock(), identity=lambda: 'sequences')
                editor.refresh_progress = AsyncMock()
                for status in ('READY', 'RUNNING', 'PAUSED', 'WAITING_INPUT', 'BLOCKED'):
                    callbacks.clear()
                    with ui.column():
                        await editor._run_controls({'sequence_run_id': 'sequence-'+status, 'status': status,
                            'current_node_id': None, 'nodes': [], 'error_code': None})
                    self.assertIn('取消', callbacks, status)
                    await callbacks['取消']()
                    self.assertEqual(calls[-1][0], 'sequence.cancel')
                    self.assertEqual(calls[-1][1]['sequence_run_id'], 'sequence-'+status)
                for status in ('SUCCEEDED', 'CANCELLED', 'DELETING'):
                    callbacks.clear()
                    with ui.column():
                        await editor._run_controls({'sequence_run_id': 'terminal', 'status': status})
                    self.assertNotIn('取消', callbacks)
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_run_dialogs_cancel_without_writing_and_retry_defaults_to_failed_step(self):
        client = Client(page('/sequence-run-dialogs'))
        async def scenario():
            child = {'definition_json': json.dumps({'steps': [
                {'step_id': key, 'name': name} for key, name in [('one', '准备'), ('two', '失败步骤'), ('three', '后续步骤')]],
                'flow': {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': []}}}),
                'attempts': [
                    {'attempt_id': 'old', 'step_id': 'one', 'valid': False, 'status': 'UNKNOWN'},
                    {'attempt_id': 'current', 'step_id': 'two', 'valid': True, 'status': 'FAILED', 'effect_state': 'UNKNOWN', 'attempt_no': 2}]}
            writes = []
            async def call(operation, **kwargs):
                if operation == 'run.get': return child
                if operation == 'step.list': return [{'step_id': key, 'name': key} for key in ('one', 'two', 'three')]
                writes.append((operation, kwargs))
            controller = SimpleNamespace(call=call, run_request=AsyncMock(return_value={
                'waiting_input': {'id': 'input-exact', 'missing': ['org'], 'values': {}}}))
            with client, patch.object(ui.button, 'on_click', lambda button, callback: button.on('click', callback)):
                editor = SequenceExecution(controller, lambda title, cb, **kw: ui.button(title, on_click=cb),
                    AsyncMock(), identity=lambda: 'sequences')
                run = {'sequence_run_id': 'sequence-exact', 'current_node_id': 'node',
                       'nodes': [{'node_id': 'node', 'task_id': 'task', 'run_id': 'child'}]}
                for method in (lambda: editor._inputs_dialog(run),
                               lambda: editor._retry_dialog(run, run['nodes'][0]),
                               lambda: editor._reconcile_dialog(run, run['nodes'][0])):
                    await method()
                    dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                    controls = list(dialog.descendants())
                    choices = [el for el in controls if isinstance(el, ui.select)]
                    if choices and choices[0]._props['label'] == '重试步骤':
                        self.assertEqual(choices[0].value, 'two')
                    if choices and choices[0]._props['label'] == '步骤尝试':
                        self.assertNotIn('old', choices[0].options)
                        self.assertEqual(choices[0].value, 'current')
                    cancel = next(el for el in controls if isinstance(el, ui.button) and el.text == '取消')
                    next(event.handler for event in cancel._event_listeners.values() if event.type == 'click')()
                    self.assertFalse(dialog.value)
                self.assertEqual(writes, [])
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def _task(self, name):
        task = self.app.repo.create_task(name, {
            "type": "object", "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        })["task_id"]
        step = self.step(task,
            source="async def run(ctx, inputs):\n    return ctx.result(data={'value': inputs['value']})\n",
            bindings={"value": {"ref": {"source": "task", "pointer": "/value"}}},
            input_schema={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
        )
        self.confirm(step, {"value": 1})
        return task, step["step_id"]

    def test_child_execution_uses_frozen_names_and_opens_saved_result(self):
        task, step_id = self._task("执行时的任务名")
        run = self.run_task(task, inputs={"value": 6})
        self.assertEqual(run["status"], "SUCCEEDED")
        client = Client(page("/sequence-child-summary"))
        try:
            async def scenario():
                with client, patch.object(ui.button, "on_click",
                        lambda button, callback: button.on("click", callback)):
                    controller = DesktopController(self.app)
                    editor = SequenceExecution(controller,
                        lambda title, callback, **options: ui.button(title, on_click=callback),
                        lambda: None, identity=lambda: "sequences")
                    editor.tasks = [{"task_id": task, "name": "后来改过的任务名"}]
                    await editor.show_child(run["run_id"])
                    labels = [element.text for element in client.elements.values()
                              if isinstance(element, ui.label)]
                    self.assertIn("执行时的任务名", labels)
                    self.assertIn("成功", labels)
                    self.assertNotIn("后来改过的任务名", labels)
                    attempts = [element for element in client.elements.values()
                                if isinstance(element, ui.expansion)
                                and "Step" in element.text]
                    self.assertEqual(len(attempts), 1)
                    self.assertIn("当前有效", attempts[0].text)
                    raw = next(element for element in client.elements.values()
                               if isinstance(element, ui.expansion) and element.text == "原始数据")
                    self.assertFalse(raw.value)
                    raw_code = next(element for element in raw.descendants() if isinstance(element, ui.code))
                    self.assertEqual(json.loads(raw_code.content), await controller.call("run.get", run_id=run["run_id"]))
                    result_button = next(element for element in client.elements.values()
                                         if isinstance(element, ui.button) and element.text == "查看结果")
                    handler = next(event.handler for event in result_button._event_listeners.values()
                                   if event.type == "click")
                    before = set(client.elements)
                    await handler()
                    rendered = [element for key, element in client.elements.items()
                                if key not in before and isinstance(element, ui.code)]
                    self.assertTrue(any(json.loads(element.content) == {"value": 6} for element in rendered))
                    self.assertEqual(self.app.runs.output(run["run_id"], step_id), {"value": 6})
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_child_execution_retains_failed_and_invalid_attempt_details(self):
        task = self.app.repo.create_task("失败任务", {
            "type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]})["task_id"]
        step = self.step(task, source="async def run(ctx, inputs):\n    if inputs['value'] == 0:\n        raise RuntimeError('记录未匹配')\n    return ctx.result(data=inputs)\n",
            bindings={"value": {"ref": {"source": "task", "pointer": "/value"}}},
            input_schema={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]})
        self.confirm(step, {"value": 1})
        run = self.run_task(task, inputs={"value": 0})
        self.app.coordinator.start(run["run_id"], uid(), retry_step_id=step["step_id"])
        run = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual([attempt["valid"] for attempt in run["attempts"]], [0, 1])
        client = Client(page("/sequence-child-failure"))
        try:
            async def scenario():
                with client:
                    editor = SequenceExecution(DesktopController(self.app),
                        lambda title, callback, **options: ui.button(title, on_click=callback),
                        lambda: None, identity=lambda: "sequences")
                    await editor.show_child(run["run_id"])
                    attempts = [element for element in client.elements.values()
                                if isinstance(element, ui.expansion) and "Step" in element.text]
                    self.assertEqual(len(attempts), 2)
                    self.assertIn("已失效", attempts[0].text)
                    self.assertIn("当前有效", attempts[1].text)
                    for attempt in attempts:
                        texts = [element.text for element in attempt.descendants() if isinstance(element, ui.label)]
                        self.assertTrue(any("记录未匹配" in text for text in texts))
                        self.assertTrue(any(json.loads(element.content) == {"value": 0}
                                            for element in attempt.descendants() if isinstance(element, ui.code)))
                    self.assertFalse(any(isinstance(element, ui.button) and element.text == "查看结果"
                                         for element in client.elements.values()))
                    self.assertEqual(len(self.app.runs.get(run["run_id"])["attempts"]), 2)
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_child_execution_does_not_open_after_navigation(self):
        task, _ = self._task("离页响应")
        run = self.run_task(task, inputs={"value": 2})
        client = Client(page("/sequence-child-stale"))
        try:
            async def scenario():
                with client:
                    controller = DesktopController(self.app)
                    original = controller.call
                    entered, release = asyncio.Event(), asyncio.Event()
                    identity = ["sequences"]
                    async def delayed(operation, **params):
                        value = await original(operation, **params)
                        entered.set()
                        await release.wait()
                        return value
                    editor = SequenceExecution(controller,
                        lambda title, callback, **options: ui.button(title, on_click=callback),
                        lambda: None, identity=lambda: identity[0])
                    async def show():
                        with client:
                            await editor.show_child(run["run_id"])
                    with patch.object(controller, "call", delayed):
                        pending = asyncio.create_task(show())
                        await entered.wait()
                        identity[0] = "home"
                        release.set()
                        await pending
                    self.assertFalse(any(isinstance(element, ui.dialog) and element.value
                                         for element in client.elements.values()))
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_canvas_selection_preserves_repeated_node_configuration(self):
        task, _ = self._task("Repeated")
        client = Client(page("/sequence-selection"))
        try:
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(self.app))
                    await workbench.navigate("sequences")
                    editor = workbench.sequences_page
                    await editor.add_dialog()
                    await editor.repaint()
                    await editor.add_node(task)
                    first = editor.draft.nodes[0]["node_id"]
                    await editor.add_node(task)
                    second = editor.draft.nodes[1]["node_id"]
                    self.assertEqual(editor.selected_node_id, second)
                    editor.draft.nodes[0]["inputs"]["value"] = {"kind": "literal", "value": 4}
                    editor.draft.nodes[1]["inputs"]["value"] = {"kind": "literal", "value": 8}
                    await editor.select_node(first)
                    self.assertEqual(editor.selected_node_id, first)
                    self.assertTrue(any("tw-sequence-canvas" in e.classes for e in client.elements.values()))
                    self.assertEqual(len([e for e in client.elements.values()
                                          if "tw-sequence-node" in e.classes]), 2)
                    await editor.move_node(0, 1)
                    self.assertEqual(editor.selected_node_id, first)
                    self.assertEqual([n["node_id"] for n in editor.draft.nodes], [second, first])
                    self.assertEqual(editor.draft.nodes[1]["inputs"]["value"]["value"], 4)
                    await editor.remove_node(1)
                    self.assertEqual(editor.selected_node_id, second)
                    self.assertEqual(editor.draft.nodes[0]["inputs"]["value"]["value"], 8)
                    editor.dispose()
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_invalid_mapping_text_survives_node_switch_and_blocks_save(self):
        from taskweave.core.validation import TaskError
        task, _ = self._task("Mapping")
        client = Client(page("/sequence-invalid-mapping"))
        try:
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(self.app))
                    await workbench.navigate("sequences")
                    editor = workbench.sequences_page
                    await editor.add_node(task)
                    first = editor.draft.nodes[0]
                    first["inputs"]["value"] = {"kind": "literal", "value": 3}
                    await editor.add_node(task)
                    second_id = editor.selected_node_id
                    await editor.select_node(first["node_id"])
                    field = next(e for e in client.elements.values() if e._props.get("label") == "JSON 值")
                    field.set_value('{"unfinished":')
                    await editor.select_node(second_id)
                    await editor.select_node(first["node_id"])
                    field = next(e for e in client.elements.values() if e._props.get("label") == "JSON 值")
                    self.assertEqual(field.value, '{"unfinished":')
                    with self.assertRaises(TaskError):
                        await editor.save()
                    field.set_value('9')
                    self.assertFalse(editor.invalid_literals)
                    self.assertEqual(first["inputs"]["value"]["value"], 9)
                    field.set_value('{')
                    await editor.remove_node(0)
                    self.assertFalse(editor.invalid_literals)
                    editor.dispose()
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_edit_save_start_leave_and_return(self):
        first, first_step = self._task("First")
        second, second_step = self._task("Second")
        third, _ = self._task("Third")
        client = Client(page("/sequence-page-test"))
        try:
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(self.app))
                    await workbench.navigate("sequences")
                    self.assertIn("sequences", workbench.nav_buttons)
                    draft = workbench.sequences_page.draft
                    draft.name = "Three tasks"
                    for task_id in (first, second, third):
                        draft.add(task_id)
                    draft.nodes[0]["inputs"]["value"] = {"kind": "literal", "value": 4}
                    for node in draft.nodes[1:]:
                        node["inputs"]["value"] = {"kind": "output", "node_id": draft.nodes[0]["node_id"],
                            "step_id": first_step, "output": "data", "pointer": "/value"}
                    await workbench.sequences_page.save()
                    self.assertEqual(len(self.app.sequences.list()), 1)
                    draft.nodes[0]["inputs"]["value"]["value"] = 6
                    await workbench.sequences_page.start()
                    run_id = draft.selected_run_id
                    self.assertEqual(workbench.sequences_page.active_section, 'debug')
                    self.assertEqual(self.app.sequences.run_get(run_id)['snapshot']['mode'], 'TRIAL')
                    await workbench.navigate("home")
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        run = self.app.sequences.run_get(run_id)
                        if run["status"] == "SUCCEEDED":
                            break
                        await asyncio.sleep(0.05)
                    self.assertEqual(run["status"], "SUCCEEDED", run)
                    self.assertEqual(self.app.runs.output(run["nodes"][1]["run_id"], second_step)["value"], 6)
                    await workbench.navigate("sequences")
                    self.assertEqual(workbench.sequences_page.draft.selected_run_id, run_id)
                    self.assertEqual([member["status"] for member in run["nodes"]], ["SUCCEEDED"] * 3)
                    area = workbench.sequences_page.progress_area
                    controls = list(area.descendants())
                    await workbench.sequences_page.refresh_progress()
                    self.assertEqual(list(area.descendants()), controls)
                    await workbench.sequences_page.delete_definition()
                    self.assertEqual(workbench.sequences_page.draft.selected_run_id, run_id)
                    workbench.sequences_page.dispose()
            asyncio.run(scenario())
        finally:
            client.delete()
