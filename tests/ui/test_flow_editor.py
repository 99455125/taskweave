"""Flow tree editing keeps action identity and rejects destructive moves."""

import unittest

from taskweave.core.task_flow import validate_flow
from taskweave.core.validation import TaskError
from taskweave.presentation.flow_editor import insert_control, move_node, remove_control, update_control


class FlowEditorTests(unittest.TestCase):
    def test_move_dialog_excludes_control_descendants_and_cancel_preserves_flow(self):
        import asyncio
        import tempfile
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.workbench import Workbench
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('move targets')
            step = app.repo.save_step(task['task_id'], {'name': 'step'})
            original = app.dispatch('task.flow.describe', {'task_id': task['task_id']})
            flow, loop_id = insert_control(original['flow'], 'loop')
            flow, inner_id = insert_control(flow, 'foreach', parent_id=loop_id+'-body')
            flow, sibling_id = insert_control(flow, 'foreach')
            app.dispatch('task.flow.save', {'task_id': task['task_id'], 'flow': flow,
                                          'expected_hash': original['definition_hash']})
            client = Client(page('/move-control-targets'))
            async def scenario():
                with client, patch.object(ui.menu_item, 'on_click', lambda item, callback: item.on('click', callback)):
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    menu_items = [element for element in client.elements.values()
                                  if isinstance(element, ui.menu_item) and any(
                                      getattr(child, 'text', '') == '移动到其他分组'
                                      for child in element.default_slot.children)]
                    # Action, outer loop, inner foreach, sibling foreach in render order.
                    handler = next(event.handler for event in menu_items[1]._event_listeners.values()
                                   if event.type == 'click')
                    async def open_dialog():
                        with client:
                            await handler()
                    pending = asyncio.create_task(open_dialog())
                    await asyncio.sleep(0)
                    dialog = next(element for element in client.elements.values()
                                  if isinstance(element, ui.dialog) and element.value)
                    target = next(element for element in dialog.descendants() if isinstance(element, ui.select))
                    try:
                        self.assertNotIn(loop_id+'-body', target.options)
                        self.assertNotIn(inner_id+'-body', target.options)
                        self.assertIn(sibling_id+'-body', target.options)
                        self.assertIn('root', target.options)
                    finally:
                        cancel = next(element for element in dialog.descendants()
                                      if isinstance(element, ui.button) and element.text == '取消')
                        next(event.handler for event in cancel._event_listeners.values()
                             if event.type == 'click')(None)
                        await pending
                        workbench._dispose_page(workbench.page)
                    self.assertEqual(app.dispatch('task.flow.describe', {'task_id': task['task_id']})['flow'], flow)
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_canvas_preserves_node_callbacks_and_exposes_both_branch_paths(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.desktop.components.flow_tree import FlowTree
        client = Client(page('/flow-canvas'))
        selected = []
        configured = []
        flow, control_id = insert_control(self.flow, 'if')
        flow = move_node(flow, 'step-b', control_id + '-then')
        try:
            import asyncio
            async def render():
                with client:
                    FlowTree([{'step_id': 'step-a', 'name': '查询'},
                              {'step_id': 'step-b', 'name': '更新'}], 'step-a',
                             selected.append, configured.append, lambda _: None,
                             lambda _: None).render(flow)
            from unittest.mock import patch
            with patch('nicegui.ui.run_javascript'):
                asyncio.run(render())
            elements = list(client.elements.values())
            self.assertTrue(any('tw-flow-canvas' in e.classes for e in elements))
            branch = next(e for e in elements if e._props.get('aria-label') == '配置条件分支')
            action = next(e for e in elements if e._props.get('aria-label') == '选择步骤：查询')
            next(iter(branch._event_listeners.values())).handler(None)
            next(iter(action._event_listeners.values())).handler(None)
            self.assertEqual(configured, [control_id])
            self.assertEqual(selected, ['step-a'])
            self.assertTrue(any(getattr(e, 'text', '') == '分支 1' for e in elements))
            self.assertTrue(any(getattr(e, 'text', '') == '否则' for e in elements))
        finally:
            client.delete()

    def test_control_forms_round_trip_existing_flow_fields(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.desktop.components.flow_controls import ControlForm
        from taskweave.presentation.flow_editor import find_node
        client = Client(page('/control-forms'))
        try:
            with client:
                for kind in ('if', 'foreach', 'loop'):
                    flow, node_id = insert_control(self.flow, kind)
                    node, _ = find_node(flow, node_id)
                    form = ControlForm(node, {'step-a': '查询'}, {})
                    updated = update_control(flow, node_id, form.value())
                    changed, _ = find_node(updated, node_id)
                    for key, value in node.items():
                        self.assertEqual(changed[key], value)
                    validate_flow(updated, [{'step_id': 'step-a'}, {'step_id': 'step-b'}])
        finally:
            client.delete()

    def test_canvas_gap_insert_and_drop_have_exact_targets(self):
        import asyncio
        from types import SimpleNamespace
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.desktop.components.flow_tree import FlowTree
        client = Client(page('/canvas-edit-targets'))
        inserted, dropped = [], []
        async def drop(node, parent, index):
            dropped.append((node, parent, index))
        try:
            with client:
                tree = FlowTree([{'step_id': 'step-a', 'name': 'A'}, {'step_id': 'step-b', 'name': 'B'}],
                    None, lambda _: None, lambda _: None, lambda _: None, lambda _: None,
                    on_insert=lambda parent, index: inserted.append((parent, index)), on_drop=drop)
                tree.render(self.flow)
                gaps = [e for e in client.elements.values() if 'tw-flow-insert' in e.classes]
                middle = next(e for e in gaps if e._props.get('data-index') == 1)
                self.assertFalse(any(e.type == 'click' for e in middle._event_listeners.values()))
                self.assertNotIn('icon', middle._props)
                asyncio.run(next(e.handler for e in middle._event_listeners.values() if e.type == 'drop')(
                    SimpleNamespace(args={'node_id': 'step-b'})))
            self.assertEqual(inserted, [])
            self.assertEqual(dropped, [('step-b', 'root', 1)])
        finally:
            client.delete()

    def test_zero_step_canvas_can_create_control_then_select_inserted_step(self):
        import asyncio
        import tempfile
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.workbench import Workbench
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('empty canvas')
            client = Client(page('/empty-flow'))
            async def scenario():
                with client, patch.object(ui.menu_item, 'on_click', lambda item, callback: item.on('click', callback)):
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'])
                    await wb.tasks_page.select_workspace_tab('steps', wb.tasks_page._workspace_tabs)
                    tree = wb.step_editor.view.get('flow_tree')
                    self.assertIsNotNone(tree, 'Zero steps must retain an editable flow canvas')
                    self.assertEqual(app.steps.list(task['task_id']), [])
                    menu = next(e for e in client.elements.values() if isinstance(e, ui.menu_item)
                        and any(getattr(c, 'text', '') == '列表遍历' for c in e.default_slot.children))
                    await next(e.handler for e in menu._event_listeners.values() if e.type == 'click')()
                    flow = app.tasks.describe_flow(task['task_id'])['flow']
                    control = flow['root']['children'][0]
                    self.assertEqual(control['kind'], 'foreach')
                    self.assertEqual(app.steps.list(task['task_id']), [])
                    self.assertIn('is-selected', wb.step_editor.view['flow_tree'].nodes[control['id']].classes)
                    self.assertTrue(any(getattr(e, 'text', '') == '保存配置' for e in client.elements.values()))
                    # The empty body uses the same positional insertion callback as populated canvases.
                    tree = wb.step_editor.view['flow_tree']
                    async def insert():
                        with client:
                            await tree.on_insert(control['body']['id'], 0)
                    pending = asyncio.create_task(insert())
                    await asyncio.sleep(0)
                    dialog = next(e for e in client.elements.values() if isinstance(e, ui.dialog) and e.value)
                    dialog.submit('action')
                    await pending
                    stored = app.steps.list(task['task_id'])
                    self.assertEqual(len(stored), 1)
                    self.assertEqual(wb.step_id, stored[0]['step_id'])
                    self.assertIn('is-selected', wb.step_editor.view['flow_tree'].nodes[stored[0]['step_id']].classes)
                    self.assertEqual(app.tasks.describe_flow(task['task_id'])['flow']['root']['children'][0]['body']['children'][0]['step_id'], stored[0]['step_id'])
                    before = app.tasks.describe_flow(task['task_id'])
                    with patch('nicegui.ui.notify') as notify:
                        await wb.step_editor.view['flow_tree'].on_delete_control(control['id'])
                        self.assertIn('删除失败：', notify.call_args.args[0])
                    self.assertEqual(app.tasks.describe_flow(task['task_id']), before)
                    wb._dispose_page(wb.page)
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def setUp(self):
        self.flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": "step-a", "kind": "action", "step_id": "step-a"},
            {"id": "step-b", "kind": "action", "step_id": "step-b"},
        ]}}

    def test_insert_move_update_and_remove_control(self):
        flow, control_id = insert_control(self.flow, "foreach", index=1)
        flow = move_node(flow, "step-b", control_id + "-body")
        flow = update_control(flow, control_id, {"items": {"literal": [1, 2]}, "max_items": 2})
        validate_flow(flow, [{"step_id": "step-a"}, {"step_id": "step-b"}])
        self.assertEqual(flow["root"]["children"][1]["body"]["children"][0]["step_id"], "step-b")
        with self.assertRaises(TaskError):
            remove_control(flow, control_id)
        flow = move_node(flow, "step-b", "root")
        flow = remove_control(flow, control_id)
        self.assertEqual([node["step_id"] for node in flow["root"]["children"]], ["step-a", "step-b"])

    def test_reject_move_into_own_body(self):
        flow, control_id = insert_control(self.flow, "loop")
        with self.assertRaises(TaskError):
            move_node(flow, control_id, control_id + "-body")

    def test_run_history_recognizes_iteration_paths(self):
        from taskweave.desktop.components.execution_details import controlled_run, round_label
        import json
        self.assertEqual(round_label('/root/each/0/body/inner/2/body/action'), '第 1 轮 / 第 3 轮')
        flow, _ = insert_control(self.flow, 'foreach')
        self.assertTrue(controlled_run({'definition_json': json.dumps({'flow': flow})}))
        self.assertFalse(controlled_run({'definition_json': json.dumps({'flow': self.flow})}))


if __name__ == "__main__":
    unittest.main()
