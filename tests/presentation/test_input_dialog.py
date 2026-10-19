"""Paused input drafts and command guards without rendering controls."""
import unittest
from types import SimpleNamespace
from taskweave.presentation.debug import TrialInputDraft
from taskweave.presentation.inputs import RunInputs


class InputDialogTests(unittest.TestCase):
    def test_raw_draft_validation_and_failed_submit_guard_recovery(self):
        flow = RunInputs(SimpleNamespace(), {}, lambda _: 'identity')
        draft = TrialInputDraft()
        schema = {'properties': {'org': {'type': 'string'}, 'settings': {'type': 'object'}}, 'required': ['org']}
        draft.task.configure(schema, {})
        draft.step.configure({'properties': {'count': {'type': 'integer'}}, 'required': ['count']}, {})
        waiting = {'id': 'input', 'scope': 'task', 'step_id': 'step', 'schema': schema}
        form = flow.bind('run', waiting, draft, draft.step.data['schema'])
        self.assertEqual(form.issues(), ['org', 'count'])
        draft.task.change('org', 'Org')
        draft.task.change('settings', '{unfinished')
        draft.step.change('count', 2)
        form.remember()
        self.assertTrue(form.issues())
        self.assertEqual(flow.drafts[form.key]['task']['settings'], '{unfinished')
        self.assertTrue(flow.begin_submit(form.key))
        self.assertFalse(flow.begin_submit(form.key))
        flow.end_submit(form.key)
        draft.task.change('settings', '{}')
        self.assertEqual(form.issues(), [])
        self.assertEqual(form.submission(), ({'org': 'Org', 'settings': {}}, {'step': {'count': 2}}))
        self.assertTrue(flow.begin_submit(form.key))

    def test_open_guard_is_released_and_step_scope_keeps_task_draft(self):
        flow = RunInputs(SimpleNamespace(), {}, lambda _: 'identity')
        self.assertTrue(flow.begin_open())
        self.assertFalse(flow.begin_open())
        flow.end_open()
        self.assertTrue(flow.begin_open())
        draft = TrialInputDraft()
        draft.task.configure({'properties': {'org': {'type': 'string'}}}, {'org': 'preserved'})
        draft.step.configure({'properties': {'flag': {'type': 'boolean'}}}, {'flag': False})
        waiting = {'scope': 'step', 'step_id': 'step', 'schema': draft.step.data['schema']}
        form = flow.bind('run', waiting, draft)
        form.remember()
        self.assertEqual(form.submission(), ({'flag': False}, None))
        self.assertEqual(flow.drafts[form.key]['task'], {'org': 'preserved'})
