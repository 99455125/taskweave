"""Raw debug drafts survive invalid input, refresh and restore without widgets."""
import importlib.util
import unittest

from taskweave.core.validation import TaskError
from taskweave.presentation.state import DebugState


class DebugInputDraftTests(unittest.TestCase):
    def draft(self):
        import taskweave.presentation.debug as debug
        self.assertTrue(hasattr(debug, 'TrialInputDraft'))
        return debug.TrialInputDraft()

    def test_blank_and_incomplete_json_survive_environment_defaults_and_restore(self):
        draft = self.draft()
        schema = {'type': 'object', 'properties': {'org': {'type': 'string'}, 'settings': {'type': 'object'}}, 'required': ['org']}
        draft.task.configure(schema, {'org': 'old', 'settings': '{}'})
        draft.step.configure({'type': 'object', 'properties': {}}, {})
        draft.task.change('org', '')
        draft.task.change('settings', '{"incomplete":')
        draft.task.configure(schema, {'org': 'new', 'settings': '{"new":true}'})
        self.assertEqual(draft.task.raw['org'], '')
        self.assertEqual(draft.task.raw['settings'], '{"incomplete":')
        with self.assertRaises(TaskError): draft.task.values()
        restored = self.draft()
        restored.task.configure(schema, {'org': 'another', 'settings': '{}'})
        restored.step.configure({'type': 'object', 'properties': {}}, {})
        restored.restore(draft.snapshot('task', 'step'))
        self.assertEqual(restored.task.raw, draft.task.raw)
        restored.task.change('org', 'fixed')
        restored.task.change('settings', '{"ok":true}')
        self.assertEqual(restored.values(), {'org': 'fixed', 'settings': {'ok': True}})

    def test_debug_state_and_submission_share_one_raw_owner(self):
        draft = self.draft()
        draft.task.configure({'type': 'object', 'properties': {'count': {'type': 'integer'}}}, {'count': 1})
        draft.step.configure({'type': 'object', 'properties': {'count': {'type': 'integer'}}}, {'count': 2})
        state = DebugState()
        draft.bind(state, ('task', 'step'))
        draft.task.change('count', 3.0)
        self.assertIs(state.task_inputs, draft.task.data)
        self.assertEqual(state.task_inputs['raw']['count'], 3.0)
        self.assertEqual(draft.task.values(), {'count': 3})
        self.assertEqual(draft.values(), {'count': 2})
        draft.set_environment('env')
        self.assertEqual(state.environment_id, 'env')
        self.assertEqual(draft.snapshot('task', 'step')['task'], {'count': 3.0})

    def test_partial_submission_keeps_optional_validation(self):
        draft = self.draft()
        draft.task.configure({'type': 'object', 'properties': {'required': {'type': 'string'}, 'count': {'type': 'integer'}}, 'required': ['required']}, {'required': '', 'count': 1.5})
        with self.assertRaises(TaskError): draft.task.values(partial=True)
        draft.task.change('count', 2)
        self.assertEqual(draft.task.values(partial=True), {'count': 2})
