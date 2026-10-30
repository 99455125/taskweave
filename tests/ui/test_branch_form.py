"""Multi-exit condition editing preserves paths and incomplete drafts."""

from copy import deepcopy
import unittest

from nicegui.client import Client
from nicegui.page import page

from taskweave.core.validation import TaskError
from taskweave.desktop.components.flow_branches import split_branches


class BranchFormTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(page('/branch-form'))
        self.node = {'id': 'branch', 'kind': 'if',
                     'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
                     'then': {'id': 'yes', 'kind': 'sequence', 'children': []},
                     'else': {'id': 'fallback', 'kind': 'sequence', 'children': []},
                     'outputs': {'status': {'then': {'literal': 'matched'}, 'else': {'literal': 'default'}}}}

    def tearDown(self):
        self.client.delete()

    def form(self):
        from taskweave.desktop.components.branch_form import BranchForm
        self.changes = []
        with self.client:
            return BranchForm(self.node, {}, {}, on_change=lambda: self.changes.append(True))

    def test_noop_and_new_branch_requires_explicit_output_value(self):
        form = self.form()
        self.assertEqual(form.value(), self.node)
        self.assertEqual(self.changes, [])
        with self.client:
            form.add_case()
        self.assertTrue(self.changes)
        with self.assertRaises(TaskError):
            form.value()
        output = form.mappings[0]['values'][form.cases[1]['key']]
        output.source.set_value('literal')
        output.literal.set_value('"second"')
        cases, fallback = split_branches(form.value())
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[1]['values']['status'], {'literal': 'second'})
        self.assertEqual(fallback, self.node['else'])
        self.assertEqual(form.value(), form.value(), 'Reading a draft must not change structural IDs')

    def test_legacy_node_named_fallback_keeps_distinct_output_values(self):
        self.node['id'] = 'fallback'
        self.node['else']['id'] = 'default-path'
        form = self.form()
        self.assertEqual(form.value(), self.node)

    def test_reordering_keeps_invalid_condition_draft_and_output_with_its_path(self):
        form = self.form()
        with self.client:
            form.add_case()
        second = form.cases[1]
        second['condition'].op.set_value('all')
        field = form.mappings[0]['values'][second['key']]
        field.source.set_value('literal')
        field.literal.set_value('"second"')
        with self.client:
            form.move_case(second, -1)
        self.assertIs(form.cases[0], second)
        self.assertEqual(second['condition'].op.value, 'all')
        with self.assertRaises(TaskError):
            form.value()
        with self.client:
            second['condition']._add(None)
        cases, _ = split_branches(form.value())
        self.assertEqual(cases[0]['then'], second['node']['then'])
        self.assertEqual(cases[0]['values']['status'], {'literal': 'second'})
        self.assertEqual(cases[1]['values']['status'], {'literal': 'matched'})

    def test_remove_branch_protects_nonempty_path_and_last_condition(self):
        self.node['then']['children'] = [{'id': 'a', 'kind': 'action', 'step_id': 'a'}]
        form = self.form()
        with self.client:
            form.add_case()
        with self.assertRaises(TaskError):
            form.remove_case(form.cases[0])
        with self.client:
            form.remove_case(form.cases[1])
        self.assertEqual(form.value(), self.node)
        with self.assertRaises(TaskError):
            form.remove_case(form.cases[0])

    def test_mapping_name_and_values_follow_add_remove_without_mutating_original(self):
        original = deepcopy(self.node)
        form = self.form()
        with self.client:
            form.add_mapping()
        with self.assertRaises(TaskError):
            form.value()
        row = form.mappings[-1]
        row['name'].set_value('contract_id')
        for field in row['values'].values():
            field.source.set_value('literal')
            field.literal.set_value('"DEMO-002"')
        self.assertEqual(form.value()['outputs']['contract_id']['else'], {'literal': 'DEMO-002'})
        with self.client:
            form.remove_mapping(row)
        self.assertEqual(form.value(), original)
        self.assertEqual(self.node, original)

    def test_move_destinations_exclude_else_if_wrapper_sequences(self):
        from taskweave.desktop.components.branch_form import branch_sequence_targets
        form = self.form()
        with self.client:
            form.add_case()
        value = form.mappings[0]['values'][form.cases[1]['key']]
        value.source.set_value('literal')
        value.literal.set_value('"second"')
        node = form.value()
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [node]}}
        targets = dict(branch_sequence_targets(flow))
        self.assertNotIn(node['else']['id'], targets)
        self.assertIn(node['else']['children'][0]['then']['id'], targets)
        self.assertTrue(targets[self.node['else']['id']].endswith('否则'))
