"""The same branch editor saves real parallel configuration and stable IDs."""

import unittest
from nicegui.client import Client
from nicegui.page import page

from taskweave.desktop.components.branch_form import BranchForm
from taskweave.presentation.flow_editor import insert_control, move_node, find_node
from taskweave.presentation.sequences import SequenceDraft


class ParallelBranchFormTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(page('/parallel-branch-form'))

    def tearDown(self):
        self.client.delete()

    def test_parallel_toggle_roundtrips_with_all_branch_paths(self):
        flow, identity = insert_control({"version": 2, "root": {"id": "root", "kind": "sequence", "children": []}}, "if")
        node, _ = find_node(flow, identity)
        with self.client:
            form = BranchForm(node, {}, {})
        form.parallel.set_value(True)
        with self.client:
            form.add_case()
        new = form.value()
        self.assertTrue(new["parallel"])
        self.assertEqual(len(new["cases"]), 2)
        with self.client:
            reopened = BranchForm(new, {}, {})
        self.assertTrue(reopened.parallel.value)
        self.assertEqual(reopened.value(), new)

    def test_branch_identity_moves_with_condition_and_path(self):
        flow, identity = insert_control({"version": 2, "root": {"id": "root", "kind": "sequence", "children": []}}, "if")
        node, _ = find_node(flow, identity)
        with self.client:
            form = BranchForm(node, {}, {})
            form.add_case()
        before = form.value()
        with self.client:
            form.move_case(form.cases[1], -1)
        after = form.value()
        self.assertEqual(after["cases"][0], before["cases"][1])
        self.assertEqual(after["cases"][1], before["cases"][0])

    def test_move_action_into_explicit_branch_preserves_id(self):
        flow, group_id = insert_control({"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": "a", "kind": "action", "step_id": "s"}]}}, "if")
        group, _ = find_node(flow, group_id)
        target = group["cases"][0]["body"]["id"]
        moved = move_node(flow, "a", target)
        action, parent = find_node(moved, "a")
        self.assertEqual(action["step_id"], "s")
        self.assertEqual(parent["id"], target)

    def test_sequence_draft_roundtrip_keeps_flow_and_scope(self):
        draft = SequenceDraft()
        draft.add('first')
        first = draft.nodes[-1]['node_id']
        group_id = draft.add_control('if')
        group, _ = find_node(draft.flow, group_id)
        draft.add('inside', group['cases'][0]['body']['id'])
        inside = draft.nodes[-1]['node_id']
        draft.add('after')
        after = draft.nodes[-1]['node_id']
        group['parallel'] = True
        scope = draft.scope(inside)
        self.assertEqual(scope['nodes'], {first})
        self.assertNotIn(inside, draft.scope(after)['nodes'])
        saved = {**draft.payload(), 'sequence_id': 'saved', 'revision': 1}
        loaded = SequenceDraft()
        loaded.load(saved)
        self.assertEqual(loaded.flow, draft.flow)
        self.assertFalse(loaded.needs_save())
