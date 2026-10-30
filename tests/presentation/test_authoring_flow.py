"""Authoring policy runs on plain identities, versions and application ports."""
import asyncio
import importlib.util
import subprocess
import sys
import unittest

from taskweave.core.validation import TaskError


class AuthoringFlowTests(unittest.TestCase):
    def flow_type(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.authoring'))
        from taskweave.presentation.authoring import AuthoringFlow
        return AuthoringFlow

    def test_generation_does_not_submit_after_context_reply_changes_identity(self):
        Flow = self.flow_type()
        async def scenario():
            identity = ['task', 'step', 1, 1]
            calls = []
            async def call(operation, **params):
                calls.append(operation)
                identity[1] = 'other'
                return []
            async def request(*args, **kwargs):
                self.fail('A stale editor must not submit a new request')
            flow = Flow(call=call, request=request, identity=lambda: tuple(identity), trials={})
            saved = {'step_id': 'step', 'content_hash': 'h', 'step_content': 'original', 'step_description': ''}
            result = await flow.generate(saved, tuple(identity), environment_id=None)
            self.assertIsNone(result.candidate)
            self.assertEqual(calls, ['context.ai'])
        asyncio.run(scenario())

    def test_candidate_conflict_keeps_editable_content_unchanged(self):
        Flow = self.flow_type()
        flow = Flow(call=None, request=None, identity=lambda: ('task', 'step', 1, 1), trials={})
        saved = {'step_content': 'original'}
        proposal = {'stale': False, 'proposed_content': 'candidate'}
        with self.assertRaises(TaskError) as caught:
            flow.content_candidate(saved, proposal, ('task', 'step', 1, 1), 'user edit')
        self.assertEqual(caught.exception.code, 'EDIT_CONFLICT')
        self.assertEqual(flow.content_candidate(saved, proposal, ('task', 'step', 1, 1), 'original'), 'candidate')

    def test_confirmation_requests_manual_choice_and_rejects_late_approval(self):
        Flow = self.flow_type()
        async def scenario():
            identity = ['task', 'step', 1, 1]
            calls = []
            async def confirm(saved, run_id):
                raise TaskError('VALIDATION_EVIDENCE_INVALID')
            async def call(operation, **params):
                calls.append((operation, params))
                return {'confirmed': True}
            flow = Flow(call=call, request=None, identity=lambda: tuple(identity), trials={'step': 'trial'}, confirm=confirm)
            decision = await flow.confirm_saved({'step_id': 'step', 'content_hash': 'h'}, tuple(identity))
            self.assertEqual(decision.status, 'manual')
            self.assertEqual(calls, [])
            identity[1] = 'other'
            late = await flow.confirm_manual(decision, approved=True, environment_id='env')
            self.assertEqual(late.status, 'stale')
            self.assertEqual(calls, [])
        asyncio.run(scenario())

    def test_import_and_flow_do_not_load_gui(self):
        self.flow_type()
        result = subprocess.run([sys.executable, '-c', '''
import importlib.abc
import sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('taskweave.desktop', 'nicegui', 'webview')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Boundary())
from taskweave.presentation.authoring import AuthoringFlow
flow = AuthoringFlow(call=None, request=None, identity=lambda: ('task','step',1,1), trials={})
assert flow.content_candidate({'step_content':'old'}, {'stale':False,'proposed_content':'new'}, ('task','step',1,1), 'old') == 'new'
'''], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_submitted_generation_completes_but_late_candidate_is_not_adopted(self):
        Flow = self.flow_type()
        async def scenario():
            identity = ['task', 'step', 1, 1]
            saved = {'step_id': 'step', 'content_hash': 'h', 'step_content': 'original', 'step_description': 'goal'}
            submissions = []
            async def call(operation, **params):
                return []
            async def request(operation, snapshot, **params):
                submissions.append((operation, snapshot, params))
                identity[1] = 'other'
                return {'proposed_content': 'late'}
            flow = Flow(call=call, request=request, identity=lambda: tuple(identity), trials={})
            events = [event async for event in flow.generate_events(saved, tuple(identity), environment_id='')]
            self.assertEqual([event.code for event in events], ['generating'])
            self.assertEqual(submissions[0][0], 'step.generate')
            self.assertIsNone(submissions[0][2]['environment_id'])
            self.assertEqual(submissions[0][2]['expected_hash'], 'h')
            self.assertEqual(submissions[0][2]['history_rounds'], 0)
            self.assertEqual(saved['step_content'], 'original')
        asyncio.run(scenario())

    def test_changed_repair_attempt_does_not_submit_bound_old_evidence(self):
        Flow = self.flow_type()
        async def scenario():
            identity = ('task', 'step', 1, 1)
            saved = {'step_id': 'step', 'content_hash': 'h', 'step_content': 'original', 'step_description': 'goal'}
            async def call(operation, **params):
                self.assertEqual(operation, 'run.get')
                return {'run_id': 'run', 'attempts': [{'step_id': 'step', 'attempt_id': 'new', 'valid': True, 'status': 'FAILED'}]}
            async def feedback(run_id, step_id):
                return {'run_id': run_id, 'attempt_id': 'new'}
            async def request(*args, **kwargs):
                self.fail('Old failure evidence must not produce a new request')
            flow = Flow(call=call, request=request, identity=lambda: identity,
                        trials={'step': 'run'}, trial_feedback=feedback)
            outcome = await flow.generate(
                saved, identity, fix_logs=True, run_id='run', feedback_run_id='run',
                feedback_override={'run_id': 'run', 'attempt_id': 'old'})
            self.assertIsNone(outcome.candidate)
            self.assertEqual([notice.code for notice in outcome.notices], ['repair_changed'])
        asyncio.run(scenario())

    def test_successful_trial_can_be_revised_without_failure_feedback(self):
        Flow = self.flow_type()
        async def scenario(attempts, web_chat):
            identity = ('task', 'step', 0, 0)
            saved = {'step_id': 'step', 'content_hash': 'h', 'step_content': 'original', 'step_description': 'goal'}
            submissions = []
            async def call(operation, **params):
                if operation == 'run.get':
                    return {'run_id': 'run', 'attempts': attempts}
                self.assertEqual(operation, 'context.ai')
                return []
            async def request(operation, snapshot, **params):
                submissions.append(params)
                return {'prompt': 'revision'}
            async def unexpected(*args):
                self.fail('A successful trial has no failure feedback to collect or refresh')
            flow = Flow(call=call, request=request, identity=lambda: identity, trials={'step': 'run'},
                        trial_feedback=unexpected, repair_contexts=unexpected)
            result = await flow.generate(saved, identity, fix_logs=True, run_id='run',
                feedback_override={}, history_rounds=2, supplement='结果不符合预期', web_chat=web_chat)
            self.assertIsNotNone(result.candidate)
            self.assertFalse(submissions[0]['feedback'])
            self.assertTrue(submissions[0]['use_history'])
            self.assertEqual(submissions[0]['history_rounds'], 2)
            self.assertEqual(submissions[0]['export_only'], web_chat)
        for attempts in ([], [{'step_id': 'step', 'valid': True, 'status': 'SUCCEEDED'}],
                         [{'step_id': 'other', 'valid': True, 'status': 'FAILED'}]):
            for web_chat in (False, True):
                with self.subTest(attempts=attempts, web_chat=web_chat):
                    asyncio.run(scenario(attempts, web_chat))

    def test_bound_failure_disappearing_does_not_submit_as_unbound_revision(self):
        Flow = self.flow_type()
        async def scenario():
            identity = ('task', 'step', 0, 0)
            async def call(operation, **params):
                return {'run_id': 'run', 'attempts': []}
            async def request(*args, **kwargs):
                self.fail('An obsolete failure must require a fresh request')
            flow = Flow(call=call, request=request, identity=lambda: identity, trials={'step': 'run'})
            result = await flow.generate({'step_id': 'step'}, identity, fix_logs=True, run_id='run',
                feedback_override={'run_id': 'run', 'attempt_id': 'old'}, feedback_run_id='run')
            self.assertIsNone(result.candidate)
            self.assertEqual([notice.code for notice in result.notices], ['repair_changed'])
        asyncio.run(scenario())
