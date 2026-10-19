"""AI choices reject late/duplicate submissions without a UI runtime."""
import importlib
import unittest


class AIInteractionTests(unittest.TestCase):
    def state(self):
        module = importlib.import_module('taskweave.presentation.authoring')
        self.assertTrue(hasattr(module, 'AIInteraction'), 'AI flow ownership must be available without a desktop')
        return module.AIInteraction()

    def test_modal_exclusion_and_shared_request_recovery(self):
        state = self.state()
        self.assertEqual(state.begin(retained_pending=True), 'request_pending')
        self.assertIsNone(state.begin(retained_pending=True, recovering=True))
        self.assertEqual(state.begin(), 'flow_active')
        state.finish()
        self.assertIsNone(state.begin())

    def test_choice_preserves_draft_and_rejects_duplicate_or_late_reply(self):
        state = self.state()
        identity = ('task', 'step', 0, 0)
        draft = state.choice(identity, supplement='initial')
        draft.supplement = 'typed text'
        draft.history_rounds = 3
        draft.deduplicate = False
        self.assertIsNone(draft.submit('api', ('task', 'other', 0, 0)))
        self.assertEqual(draft.submit('chat', identity), ('chat', 3, False, 'typed text'))
        self.assertIsNone(draft.submit('api', identity))

    def test_reply_parser_consumes_plain_draft(self):
        state = self.state()
        draft = state.choice(('task', 'step', 0, 0))
        draft.reply = '```python\nasync def run(ctx, inputs):\n    return None\n```'
        self.assertEqual(draft.parse_content(), ('async def run(ctx, inputs):\n    return None\n', ''))
        draft.reply = '{"step_description":" Goal ","step_notes":" Note "}'
        self.assertEqual(draft.parse_goal(), ('Goal', 'Note'))

    def test_new_repair_round_clears_only_current_step_evidence(self):
        from taskweave.presentation.state import DebugState
        state = self.state()
        debug = DebugState()
        debug.supplements = {'step': 'old', 'other': 'keep'}
        debug.feedback = {'run_id': 'run'}
        debug.feedback_run_id = 'run'
        debug.removed_feedback = {'logs'}
        self.assertTrue(hasattr(state, 'clear_repair'), 'repair reset belongs to the interaction')
        state.clear_repair(debug, 'step')
        self.assertEqual(debug.supplements, {'other': 'keep'})
        self.assertIsNone(debug.feedback)
        self.assertIsNone(debug.feedback_run_id)
        self.assertEqual(debug.removed_feedback, set())
