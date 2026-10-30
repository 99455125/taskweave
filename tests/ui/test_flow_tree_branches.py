"""First-match branch paths share one canvas control without losing step identity."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from nicegui.client import Client
from nicegui.page import page

from taskweave.core.task_flow import validate_flow
from taskweave.desktop.components.flow_tree import FlowTree


class FlowTreeBranchesTests(unittest.TestCase):
    def setUp(self):
        # Route layout requires a browser; this test exercises component identities.
        self.javascript = patch('nicegui.ui.run_javascript')
        self.javascript.start()
        self.addCleanup(self.javascript.stop)
        self.client = Client(page('/flow-tree-branches'))
        self.selected, self.configured, self.moved, self.deleted = [], [], [], []
        self.steps = [{'step_id': 'step-a', 'name': '更新记录'},
                      {'step_id': 'step-b', 'name': '新建记录'},
                      {'step_id': 'step-c', 'name': '记录未匹配'}]
        condition = lambda n: {"op": "eq", "left": {"literal": n}, "right": {"literal": n}}
        body = lambda identity, action_id, step: {"id": identity, "kind": "sequence", "children": [
            {"id": action_id, "kind": "action", "step_id": step}]}
        self.flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{
            'id': 'gate', 'kind': 'if', 'cases': [
                {'id': 'case-a', 'condition': condition(1), 'body': body('path-a', 'action-a', 'step-a')},
                {'id': 'case-b', 'condition': condition(2), 'body': body('path-b', 'action-b', 'step-b')}],
            'default': {'id': 'default', 'body': body('fallback', 'action-c', 'step-c')},
        }]}}

    def tearDown(self):
        self.client.delete()

    def render(self):
        validate_flow(self.flow, self.steps)
        with self.client:
            tree = FlowTree(self.steps, 'step-b', self.selected.append, self.configured.append,
                            self.moved.append, self.deleted.append)
            tree.render(self.flow)
        return tree, list(self.client.elements.values())

    @staticmethod
    def click(element):
        next(iter(element._event_listeners.values())).handler(None)

    @staticmethod
    def branch_ancestor(element):
        parent = element.parent_slot.parent
        while 'tw-flow-branch' not in parent.classes:
            parent = parent.parent_slot.parent
        return parent

    def test_first_match_paths_are_siblings_with_one_root_control(self):
        original = deepcopy(self.flow)
        tree, elements = self.render()
        controls = [e for e in elements if e._props.get('aria-label') == '配置条件分支']
        self.assertEqual(len(controls), 1)
        self.click(controls[0])
        self.assertEqual(self.configured, ['gate'])

        rows = [e for e in elements if 'tw-flow-branch' in e.classes]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.parent_slot.parent is rows[0].parent_slot.parent for row in rows))
        self.assertEqual([getattr(e, 'text', '') for e in elements if 'tw-flow-path-label' in e.classes],
                         ['分支 1', '分支 2', '否则'])

        for index, name in enumerate(('更新记录', '新建记录', '记录未匹配')):
            button = next(e for e in elements if e._props.get('aria-label') == '选择步骤：' + name)
            self.assertIs(self.branch_ancestor(button), rows[index])
            self.click(button)
        self.assertEqual(self.selected, ['step-a', 'step-b', 'step-c'])
        self.assertEqual(self.flow, original)
        self.assertNotIn('gate-next', tree.nodes)
        tree.select('gate')
        self.assertIn('is-selected', tree.nodes['gate'].classes)

    def test_group_menu_uses_outer_identity(self):
        _, elements = self.render()
        moves = [e for e in elements if getattr(e, 'text', '') == '移动到其他分组']
        deletes = [e for e in elements if getattr(e, 'text', '') == '删除空控制块']
        self.assertEqual(len(moves), 4)
        self.assertEqual(len(deletes), 1)
        for move in moves:
            self.click(move.parent_slot.parent)
        self.click(deletes[0].parent_slot.parent)
        self.assertEqual(self.moved, ['gate', 'action-a', 'action-b', 'action-c'])
        self.assertEqual(self.deleted, ['gate'])

    def test_step_breadcrumb_uses_visible_branch_and_loop_path(self):
        original_root = self.flow['root']
        self.flow['root'] = {'id': 'outer', 'kind': 'sequence', 'children': [{
            'id': 'contracts', 'kind': 'foreach', 'items': {'literal': []},
            'body': original_root,
        }]}
        # Rendering identity metadata must not change execution definitions.
        original = deepcopy(self.flow)
        validate_flow(self.flow, self.steps)
        with self.client:
            tree = FlowTree(self.steps, 'step-b', self.selected.append, self.configured.append,
                            self.moved.append, self.deleted.append)
            tree.render(self.flow)
        self.assertTrue(hasattr(tree, 'step_paths'), 'Editor title needs the actual visible flow path')
        self.assertEqual(tree.step_paths, {
            'step-a': '主流程 › 列表遍历 › 分支 1',
            'step-b': '主流程 › 列表遍历 › 分支 2',
            'step-c': '主流程 › 列表遍历 › 否则',
        })
        self.assertEqual(self.flow, original)

    def test_nested_default_keeps_its_own_branch_control(self):
        outer = self.flow['root']['children'][0]
        second = outer['cases'].pop()
        fallback = outer['default']
        inner = {'id': 'gate-next', 'kind': 'if', 'cases': [second], 'default': fallback}
        outer['default'] = {'id': 'nested', 'body': {'id': 'continuation', 'kind': 'sequence', 'children': [inner]}}
        original = deepcopy(self.flow)
        _, elements = self.render()
        controls = [e for e in elements if e._props.get('aria-label') == '配置条件分支']
        self.assertEqual(len(controls), 2)
        for control in controls:
            self.click(control)
        self.assertEqual(self.configured, ['gate', 'gate-next'])
        rows = [e for e in elements if 'tw-flow-branch' in e.classes]
        self.assertEqual(len(rows), 4)
        self.assertIsNot(rows[0].parent_slot.parent, rows[2].parent_slot.parent)
        self.assertEqual(self.flow, original)


if __name__ == '__main__':
    unittest.main()
