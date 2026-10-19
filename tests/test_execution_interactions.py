"""Run selection, polling and log state run without UI objects."""
import unittest


class PollingTests(unittest.TestCase):
    def test_hidden_or_replaced_inflight_response_is_rejected(self):
        from taskweave.presentation.polling import PollingState
        state = PollingState()
        token = state.begin('run-a', now=0)
        state.observe('run-b', visible=True)
        self.assertFalse(state.accepts(token))
        state.finish(token)
        state.observe('run-b', visible=False)
        self.assertIsNone(state.begin('run-b', now=10))
        state.observe('run-b', visible=True)
        self.assertIsNotNone(state.begin('run-b', now=10))

    def test_logs_stop_at_terminal_page_and_keep_opt_in_visibility(self):
        from taskweave.presentation.polling import LogStreamState
        state = LogStreamState()
        state.toggle()
        state.apply_page({'reset': False, 'cursor': 3, 'has_more': False, 'status': 'SUCCEEDED'}, 'one')
        self.assertEqual(state.text, 'one')
        self.assertTrue(state.enabled)
        self.assertFalse(state.following)
        state.toggle()
        state.toggle()
        self.assertTrue(state.following)
        state.apply_page({'reset': True, 'cursor': 1, 'has_more': True, 'status': 'RUNNING'}, 'new')
        self.assertEqual(state.text, 'new')
        self.assertEqual(state.cursor, 1)


class ExecutionSelectionTests(unittest.TestCase):
    def test_step_selection_is_view_only_and_cache_changes_on_event_revision(self):
        from taskweave.presentation.execution import ExecutionInteraction
        from taskweave.presentation.state import ExecutionPageState
        state = ExecutionPageState()
        interaction = ExecutionInteraction(state)
        run = {'run_id': 'r', 'status': 'PAUSED', 'event_revision': 1,
               'attempts': [{'step_id': 'b', 'valid': True}]}
        steps = [{'step_id': 'a'}, {'step_id': 'b'}]
        self.assertEqual(interaction.selected_step(run, steps), 'b')
        interaction.select_step('r', 'a')
        self.assertEqual(interaction.selected_step(run, steps), 'a')
        interaction.remember(run, run)
        self.assertIs(interaction.cached_detail(run, force=False), run)
        self.assertIsNone(interaction.cached_detail({**run, 'event_revision': 2}, force=False))
        interaction.select_run('other')
        self.assertIsNone(state.selected_step_id)


class DebugInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_keeps_accepted_background_work_but_discards_late_view_result(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from taskweave.presentation.debug import DebugInteraction
        from taskweave.presentation.state import DebugState
        application = SimpleNamespace(trial=AsyncMock(return_value={'run_id': 'r'}))
        trials = {}
        interaction = DebugInteraction(DebugState(), trials, application)
        result = await interaction.launch({'step_id': 's'}, {'count': 0}, None)
        self.assertFalse(interaction.accept_run(('t', 's', 1), ('t', 'other', 2), 's', result))
        self.assertEqual(trials, {})
        application.trial.assert_awaited_once()
        self.assertTrue(interaction.accept_run(('t', 's', 1), ('t', 's', 1), 's', result))
        self.assertEqual(trials, {'s': 'r'})

    async def test_resume_decisions_preserve_environment_input_and_unknown_guards(self):
        from taskweave.presentation.debug import DebugInteraction
        run = {'can_end': True, 'environment_id': 'e', 'status': 'PAUSED', 'attempts': []}
        self.assertEqual(DebugInteraction.continuation(run, {}, 'other', 's').action, 'abandon')
        waiting = {'waiting_input': {'scope': 'step', 'step_id': 'other'}}
        self.assertEqual(DebugInteraction.continuation(run, waiting, 'e', 's').action, 'other_step')
        waiting['waiting_input']['step_id'] = 's'
        self.assertEqual(DebugInteraction.continuation(run, waiting, 'e', 's').action, 'resume')
        run['attempts'] = [{'valid': True, 'status': 'UNKNOWN'}]
        self.assertTrue(DebugInteraction.continuation(run, {}, 'e', 's').needs_confirmation)
