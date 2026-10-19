"""Step list workflows can execute without a GUI or rendering callback."""
import unittest
from taskweave.core.validation import TaskError
from taskweave.presentation.step_actions import StepActions


class StepActionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.identity = ['task', 'a', 1, 1]
        self.steps = [dict(step_id=x, name=x, capabilities=['web.click'], validation_state='DRAFT', content_hash=x) for x in 'abc']
        self.calls = []
        self.invalid = set()
        self.fail_confirm = None
        self.late = None

    async def call(self, operation, **params):
        self.calls.append((operation, params))
        if self.late == operation:
            self.identity[-1] += 1
        if operation == 'step.list': return [dict(x) for x in self.steps]
        if operation == 'step.save': return dict(step_id='new', **params['document'])
        if operation == 'step.validate': return {'valid': params['step_id'] not in self.invalid}
        if operation == 'step.confirm.manual':
            if params['step_id'] == self.fail_confirm: raise TaskError('CONFLICT', 'changed')
            next(x for x in self.steps if x['step_id'] == params['step_id'])['validation_state'] = 'VALIDATED'
        return {}

    def actions(self):
        return StepActions(self.call, 'task', 'a', lambda: tuple(self.identity))

    async def test_add_inherits_all_capabilities_of_selected_plugins(self):
        result = await self.actions().add(dict(actions=[{'id': 'web.type'}, {'id': 'other.run'}], tools=[], result_handlers=['web.result'], resource_providers=[]))
        self.assertEqual(result.selected_step_id, 'new')
        self.assertEqual(self.calls[-1][1]['document']['capabilities'], ['web.click', 'web.result', 'web.type'])

    async def test_reorder_and_delete_return_selection_without_render(self):
        actions = self.actions()
        result = await actions.reorder(1)
        self.assertEqual((result.index, result.target), (0, 1))
        self.assertEqual(self.calls[-1][1]['step_ids'], ['b', 'a', 'c'])
        self.assertIsNone(await actions.delete(self.steps, confirmed=False))
        result = await actions.delete(self.steps, confirmed=True)
        self.assertEqual(result.selected_step_id, 'b')

    async def test_invalid_batch_never_confirms_and_selects_first_invalid(self):
        self.invalid = {'b', 'c'}
        result = await self.actions().confirm_all()
        self.assertEqual(result.status, 'invalid')
        self.assertEqual(result.selected_step_id, 'b')
        self.assertEqual(len(result.failures), 2)
        self.assertFalse(any(op == 'step.confirm.manual' for op, _ in self.calls))

    async def test_partial_failure_uses_persisted_count(self):
        self.fail_confirm = 'b'
        result = await self.actions().confirm_all()
        self.assertEqual((result.status, result.confirmed_count, result.total, result.selected_step_id), ('partial', 1, 3, 'b'))
        self.assertEqual(self.calls[-1][0], 'step.list')

    async def test_late_list_does_not_start_mutation(self):
        self.late = 'step.list'
        self.assertIsNone(await self.actions().add({}))
        self.assertEqual(len(self.calls), 1)

    async def test_repaint_identity_accepts_only_same_target_next_generation(self):
        actions = self.actions()
        expected = tuple(self.identity)
        self.identity[-1] += 1
        self.assertTrue(actions.accepts_repaint(expected))
        self.identity[1] = 'b'
        self.assertFalse(actions.accepts_repaint(expected))

    async def test_delete_middle_selects_previous_and_boundary_reorder_does_nothing(self):
        self.assertIsNone(await self.actions().reorder(-1))
        actions = StepActions(self.call, 'task', 'b', lambda: tuple(self.identity))
        result = await actions.delete(self.steps, confirmed=True)
        self.assertEqual(result.selected_step_id, 'a')
        self.assertFalse(any(op == 'step.reorder' for op, _ in self.calls))

    async def test_late_confirm_stops_remaining_steps(self):
        self.late = 'step.confirm.manual'
        self.assertIsNone(await self.actions().confirm_all())
        self.assertEqual([x['validation_state'] for x in self.steps], ['VALIDATED', 'DRAFT', 'DRAFT'])

    async def test_unexpected_validation_failure_propagates(self):
        async def call(operation, **params):
            if operation == 'step.validate': raise RuntimeError('validator failed')
            return await self.call(operation, **params)
        actions = StepActions(call, 'task', 'a', lambda: tuple(self.identity))
        with self.assertRaisesRegex(RuntimeError, 'validator failed'):
            await actions.confirm_all()

    async def test_raised_validation_error_collects_failure_and_skips_confirm(self):
        async def call(operation, **params):
            if operation == 'step.validate': raise TaskError('INVALID', 'invalid Python')
            return await self.call(operation, **params)
        result = await StepActions(call, 'task', 'a', lambda: tuple(self.identity)).confirm_all()
        self.assertEqual(len(result.failures), 3)
        self.assertEqual(result.failures[0]['reason'], 'invalid Python')
        self.assertFalse(any(op == 'step.confirm.manual' for op, _ in self.calls))

    def test_workflows_run_with_gui_imports_forbidden(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-c', """
import importlib.abc
import sys
import unittest
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(('taskweave.desktop', 'taskweave.infrastructure', 'nicegui', 'webview')):
            raise AssertionError('Forbidden dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from tests.presentation.test_step_actions import StepActionsTests
names = [name for name in unittest.defaultTestLoader.getTestCaseNames(StepActionsTests)
         if name != 'test_workflows_run_with_gui_imports_forbidden']
result = unittest.TextTestRunner().run(unittest.TestSuite(StepActionsTests(name) for name in names))
sys.exit(not result.wasSuccessful())
"""], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
