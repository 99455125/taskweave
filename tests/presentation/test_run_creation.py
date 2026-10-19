"""Execution creation decisions and accepted-operation failure semantics, without GUI."""
import unittest

from taskweave.presentation.state import ExecutionPageState


class Application:
    def __init__(self):
        self.calls = []
        self.fail = None

    async def call(self, operation, **params):
        self.calls.append((operation, params))
        if operation == self.fail:
            raise RuntimeError(operation)
        if operation == 'task.list':
            return [{'task_id': key, 'name': key} for key in ('empty', 'draft', 'a', 'b')]
        if operation == 'step.list':
            key = params['task_id']
            return [] if key == 'empty' else [{'step_id': key + str(i), 'name': str(i),
                'validation_state': 'DRAFT' if key == 'draft' else 'VALIDATED'} for i in (1, 2)]
        return {'run_id': 'created'}


class RunCreationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from taskweave.presentation.run_creation import RunCreation
        self.application = Application()
        self.state = ExecutionPageState()
        self.creation = RunCreation(self.application, self.state)
        await self.creation.load()

    async def test_eligibility_pending_and_task_start_defaults(self):
        flow = self.creation
        self.assertEqual([t['task_id'] for t in flow.eligible], ['a', 'b'])
        self.assertIsNotNone(flow.open('draft'))
        self.assertIsNone(flow.open())
        self.assertEqual((flow.task_id, flow.start_step_id), ('a', 'a1'))
        flow.select_start('a2')
        flow.select_task('b')
        self.assertEqual(flow.start_step_id, 'b1')
        flow.pending_task_id, flow.pending_open_create = 'a', True
        self.assertEqual(flow.consume_pending(), (True, 'a'))
        self.assertEqual(flow.consume_pending(), (True, None))
        self.assertEqual(flow.consume_pending(), (False, None))

    async def test_create_start_consumes_plain_input_draft_and_updates_selection(self):
        from taskweave.presentation.debug import TrialInputDraft
        flow = self.creation
        flow.open('b')
        flow.select_start('b2')
        draft = TrialInputDraft()
        draft.task.configure({'type': 'object', 'properties': {'x': {'type': 'integer'}}, 'required': ['x']}, {})
        draft.step.configure({'type': 'object', 'properties': {'flag': {'type': 'boolean'}}}, {})
        draft.step.change('flag', False)
        draft.set_environment('env')
        flow.input_draft = draft
        self.state.task_ids = ['a']
        await flow.submit()
        self.assertEqual(self.state.run_id, 'created')
        self.assertEqual(self.state.task_ids, ['a', 'b'])
        create, start = self.application.calls[-2:]
        self.assertEqual(create, ('run.create', {'task_id': 'b', 'inputs': {}, 'step_inputs': {'b2': {'flag': False}}, 'environment_id': 'env', 'defer_inputs': True}))
        self.assertEqual(start[1]['start_step_id'], 'b2')
        self.assertEqual(start[1]['mode'], 'ALL')
        self.assertTrue(start[1]['command_id'])

    async def test_create_failure_keeps_selection_and_start_failure_keeps_created_run(self):
        flow = self.creation
        flow.open('a')
        self.application.fail = 'run.create'
        with self.assertRaisesRegex(RuntimeError, 'run.create'):
            await flow.submit()
        self.assertIsNone(self.state.run_id)
        self.assertEqual(flow.task_id, 'a')
        self.application.fail = 'run.start'
        with self.assertRaisesRegex(RuntimeError, 'run.start'):
            await flow.submit()
        self.assertEqual(self.state.run_id, 'created')
        self.assertEqual(self.state.task_ids, [])
