"""Headless interaction contracts used by the NiceGUI adapter."""
import asyncio
import importlib.util
import unittest
from copy import deepcopy
from taskweave.core.validation import TaskError


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    def require(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation'),
                             'Framework-independent interactions must be available without desktop')

    async def test_save_conflict_retains_draft_and_uses_latest_baseline(self):
        self.require()
        from taskweave.presentation.editor import EditorSession
        from taskweave.presentation.state import StepEditorState
        state = StepEditorState(task_id='t', step_id='s', old_step={'step_id': 's', 'content_hash': 'one'})
        calls = []
        async def save(task, document, old):
            calls.append(old['content_hash'])
            if document['name'] == 'conflict':
                raise TaskError('EDIT_CONFLICT')
            return {'step_id': 's', 'content_hash': str(len(calls))}
        session = EditorSession(state, save, lambda: 1)
        with self.assertRaises(TaskError):
            await session.save({'name': 'conflict'})
        self.assertEqual(state.old_step['content_hash'], 'one')
        await asyncio.gather(session.save({'name': 'a'}), session.save({'name': 'b'}))
        self.assertEqual(calls, ['one', 'one', '2'])

    async def test_late_save_does_not_replace_new_selection(self):
        self.require()
        from taskweave.presentation.editor import EditorSession
        from taskweave.presentation.state import StepEditorState
        state = StepEditorState(task_id='t', step_id='s', old_step={'step_id': 's'})
        async def save(*args):
            state.step_id = 'other'
            state.generation += 1
            return {'step_id': 's'}
        await EditorSession(state, save, lambda: 1).save({'name': 'old'})
        self.assertEqual(state.step_id, 'other')

    async def test_retained_request_survives_waiter_cancel_and_rejects_duplicate(self):
        self.require()
        from taskweave.presentation.requests import AuthoringRequests
        pending = asyncio.Event()
        async def call(operation, **params):
            await pending.wait()
            return {'candidate': True}
        requests = AuthoringRequests(call)
        waiter = asyncio.create_task(requests.submit('step.generate', {'step_id': 's'}))
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        with self.assertRaises(TaskError):
            await requests.submit('step.generate', {'step_id': 's'})
        pending.set()
        self.assertEqual(await requests.get('s')['task'], {'candidate': True})

    async def test_resume_continues_after_view_leaves_without_updating_view(self):
        self.require()
        from taskweave.presentation.inputs import RunInputs
        calls = []
        current = [1]
        class Port:
            async def run_request(self, run_id):
                return {'waiting_input': {'id': 'q', 'scope': 'task', 'schema': {'type': 'object'}},
                        'last_command': {'mode': 'ONE', 'target': 's'}}
            async def call(self, operation, **params):
                calls.append((operation, params))
                if operation == 'run.inputs': current[0] = 2
        result = await RunInputs(Port(), {}, lambda _: current[0]).resume('r', {'x': 1})
        self.assertFalse(result.current)
        self.assertEqual([x[0] for x in calls], ['run.inputs', 'run.start'])
        self.assertEqual(calls[-1][1]['mode'], 'ONE')

    async def test_invalid_schema_draft_is_retained_without_controls(self):
        self.require()
        from taskweave.presentation.forms import schema_from_rows
        rows = [['', 'integer', '1', '', False, {}]]
        saved = deepcopy(rows)
        with self.assertRaises(TaskError): schema_from_rows({}, rows)
        self.assertEqual(rows, saved)


class DraftTests(unittest.TestCase):
    def test_raw_binding_and_schema_are_compiled_without_widgets(self):
        from taskweave.presentation import editor
        self.assertTrue(hasattr(editor, 'document_from_draft'))
        raw = {'fields': {'name': 'demo', 'step_description': '', 'step_notes': '',
                          'code': 'async def run(ctx, inputs): pass', 'caps': [], 'delay': 0, 'timeout': 60},
               'schema': [], 'bindings': [['count', 'literal', '0', None, 'data', '']],
               'plugin_actions': {}, 'field_types': {}, 'schema_original': {'type': 'object', 'properties': {}}}
        doc = editor.document_from_draft({}, raw)
        self.assertEqual(doc['bindings']['count'], {'literal': 0})
        self.assertEqual(doc['input_schema']['properties']['count'], {'type': 'integer'})

    def test_snapshot_is_independent_of_mutated_input(self):
        from taskweave.presentation.state import StepEditorState
        state = StepEditorState()
        self.assertTrue(hasattr(state, 'capture_draft'))
        raw = {'fields': {'name': 'original'}}
        state.capture_draft(raw)
        raw['fields']['name'] = 'changed'
        self.assertEqual(state.draft['fields']['name'], 'original')

class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_leave_decision_waits_for_save_and_rejects_changed_identity(self):
        from taskweave.presentation import editor
        self.assertTrue(hasattr(editor, 'LeaveDecision'))
        from taskweave.presentation.state import StepEditorState
        state = StepEditorState()
        identity = [1]
        decision = editor.LeaveDecision(state, lambda: identity[0])
        await state.save_lock.acquire()
        pending = asyncio.create_task(decision.begin(lambda: True))
        await asyncio.sleep(0)
        identity[0] = 2
        state.save_lock.release()
        self.assertEqual(await pending, 'stay')
        self.assertEqual(await decision.begin(lambda: True), 'ask')
        self.assertEqual(decision.resolve('discard'), 'discard')
        identity[0] = 3
        self.assertEqual(decision.resolve('save'), 'stay')

    async def test_recovery_snapshots_do_not_share_tab_data(self):
        import taskweave.presentation as package
        self.assertIsNotNone(importlib.util.find_spec(package.__name__ + '.workspace'))
        from taskweave.presentation.workspace import RecoveryState
        from taskweave.presentation.state import StepEditorState, DebugState
        a, b = StepEditorState(), StepEditorState()
        source = {'step': {'fields': {'name': 'draft'}}, 'input_drafts': {('r', 'q'): {'x': 0}}}
        drafts_a, drafts_b = {}, {}
        RecoveryState.restore(source, a, DebugState(), {}, drafts_a)
        RecoveryState.restore(source, b, DebugState(), {}, drafts_b)
        a.reload_draft['fields']['name'] = 'changed'
        drafts_a[('r', 'q')]['x'] = 4
        self.assertEqual(b.reload_draft['fields']['name'], 'draft')
        self.assertEqual(drafts_b[('r', 'q')]['x'], 0)

class CandidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_code_rejects_retained_candidate(self):
        from taskweave.presentation import requests
        self.assertTrue(hasattr(requests, 'validate_candidate'))
        async def call(operation, **params):
            return {'content_hash': 'h'}
        request = {'saved': {'step_id': 's', 'content_hash': 'h', 'step_content': 'original'}, 'params': {}}
        with self.assertRaises(TaskError) as raised:
            await requests.validate_candidate(call, request, lambda: True, lambda: 'changed', {})
        self.assertEqual(raised.exception.code, 'EDIT_CONFLICT')

    async def test_old_failure_cannot_authorize_repair_candidate(self):
        from taskweave.presentation import requests
        self.assertTrue(hasattr(requests, 'validate_candidate'))
        async def call(operation, **params):
            if operation == 'step.get': return {'content_hash': 'h'}
            return {'attempts': [{'valid': True, 'status': 'FAILED', 'step_id': 's', 'attempt_id': 'new'}]}
        request = {'saved': {'step_id': 's', 'content_hash': 'h', 'step_content': 'original'},
                   'params': {'feedback': {'run_id': 'r', 'attempt_id': 'old'}}}
        with self.assertRaises(TaskError) as raised:
            await requests.validate_candidate(call, request, lambda: True, lambda: 'original', {'s': 'r'})
        self.assertEqual(raised.exception.code, 'VALIDATION_EVIDENCE_INVALID')

class TabTests(unittest.TestCase):
    def test_newer_tab_selection_invalidates_pending_transition(self):
        from taskweave.presentation import workspace
        self.assertTrue(hasattr(workspace, 'TaskWorkspace'))
        state = workspace.TaskWorkspace()
        first = state.begin('steps')
        second = state.begin('overview')
        self.assertFalse(state.commit(first, 'steps'))
        self.assertTrue(state.commit(second, 'overview'))
        self.assertEqual(state.tab, 'overview')

class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_batch_retains_capture_and_late_success_does_not_replace_state(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.step_contexts'))
        from taskweave.presentation.step_contexts import StepContexts
        from taskweave.presentation.state import ContextPageState
        state = ContextPageState()
        identity = [1]
        captures = [{'label': 'original', 'items': []}]
        async def failed(*args, **kwargs): raise TaskError('EDIT_CONFLICT')
        session = StepContexts(failed, state, lambda: identity[0])
        with self.assertRaises(TaskError):
            await session.save_batch('s', None, 'provider', 'name', '', captures)
        self.assertEqual(captures[0]['label'], 'original')
        self.assertEqual(state.entries, [])
        async def late(*args, **kwargs):
            identity[0] = 2
            return {'group': {'context_id': 'c', 'captures': []}}
        session.call = late
        group, current = await session.save_batch('s', None, 'provider', 'name', '', captures)
        self.assertFalse(current)
        self.assertEqual(group['context_id'], 'c')
        self.assertEqual(state.entries, [])

class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_save_rejects_blank_name_and_preserves_existing_id(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.tasks'))
        from taskweave.presentation.tasks import TaskCommands
        calls = []
        async def call(operation, **params):
            calls.append((operation, params))
            return params
        commands = TaskCommands(call)
        with self.assertRaises(TaskError): await commands.save(None, ' ', {}, '')
        self.assertEqual(calls, [])
        await commands.save({'task_id': 't'}, ' renamed ', {}, 'note')
        self.assertEqual(calls, [('task.update', {'task_id': 't', 'name': 'renamed', 'input_schema': {}, 'description': 'note'})])
