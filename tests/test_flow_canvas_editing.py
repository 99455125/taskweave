"""Canvas changes preserve dependencies and commit placement atomically."""
import tempfile
import unittest
from copy import deepcopy

from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.presentation.flow_editor import insert_control, move_node


class CanvasEditingTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.app = Application(self.home.name)
        self.addCleanup(self.home.cleanup)
        self.addCleanup(self.app.close)
        self.task = self.app.repo.create_task('canvas')['task_id']
        self.a = self.app.steps.save(self.task, {'name': 'producer'})
        self.b = self.app.steps.save(self.task, {'name': 'consumer'})

    def describe(self):
        return self.app.tasks.describe_flow(self.task)

    def save(self, flow):
        return self.app.tasks.save_flow(self.task, flow, self.describe()['definition_hash'])

    def test_move_order_survives_subsequent_step_save(self):
        self.save(move_node(self.describe()['flow'], self.b['step_id'], 'root', 0))
        self.app.steps.save(self.task, {'name': 'renamed'}, self.a['step_id'], self.a['content_hash'])
        self.assertEqual([n['step_id'] for n in self.describe()['flow']['root']['children']],
                         [self.b['step_id'], self.a['step_id']])
        self.assertEqual([s['step_id'] for s in self.app.steps.list(self.task)], [self.b['step_id'], self.a['step_id']])

    def test_insert_at_middle_and_invalid_target_rolls_back(self):
        saved = self.app.dispatch('step.insert', dict(task_id=self.task, document={'name': 'middle'},
            parent_id='root', index=1, expected_hash=self.describe()['definition_hash']))
        self.assertEqual([n['step_id'] for n in self.describe()['flow']['root']['children']],
                         [self.a['step_id'], saved['step_id'], self.b['step_id']])
        before = deepcopy(self.describe())
        with self.assertRaises(TaskError):
            self.app.dispatch('step.insert', dict(task_id=self.task, document={'name': 'invalid'},
                parent_id='missing', index=0, expected_hash=before['definition_hash']))
        self.assertEqual(self.describe(), before)
        self.assertEqual(len(self.app.steps.list(self.task)), 3)

    def test_move_cannot_precede_dependency_or_cross_sibling_paths(self):
        self.b = self.app.steps.save(self.task, {'name': 'consumer', 'bindings': {'value': {
            'ref': {'source': 'step', 'step_id': self.a['step_id'], 'pointer': ''}}}},
            self.b['step_id'], self.b['content_hash'])
        before = self.describe()
        with self.assertRaises(TaskError):
            self.save(move_node(before['flow'], self.b['step_id'], 'root', 0))
        self.assertEqual(self.describe(), before)
        flow, branch = insert_control(before['flow'], 'if', index=0)
        flow = move_node(flow, self.a['step_id'], branch + '-then')
        flow = move_node(flow, self.b['step_id'], branch + '-else')
        with self.assertRaises(TaskError):
            self.save(flow)
        self.assertEqual(self.describe(), before)

    def test_delete_rejects_control_condition_reference_without_mutation(self):
        flow, branch = insert_control(self.describe()['flow'], 'if')
        control = flow['root']['children'][-1]
        control['cases'][0]['condition']['left'] = {'ref': {
            'source': 'step', 'step_id': self.a['step_id'], 'pointer': ''}}
        self.save(flow)
        before = self.describe()
        with self.assertRaises(TaskError):
            self.app.steps.delete(self.a['step_id'])
        self.assertEqual(self.describe(), before)
        self.assertEqual(len(self.app.steps.list(self.task)), 2)
