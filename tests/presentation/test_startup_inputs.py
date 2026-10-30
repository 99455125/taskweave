"""Startup drafts collect only manual values and defer blank required inputs."""
import importlib.util
import unittest

from taskweave.core.validation import TaskError


TASK_SCHEMA = {'type': 'object', 'properties': {'shared': {'type': 'string'}}, 'required': ['shared']}
STEPS = [
    {'step_id': 'first', 'name': 'First', 'bindings': {'bound': {'literal': 10}},
     'input_schema': {'type': 'object', 'properties': {
         'bound': {'type': 'number'}, 'shared': {'type': 'string'}, 'env': {'type': 'string'},
         'amount': {'type': 'number'}, 'flag': {'type': 'boolean'}}, 'required': ['amount', 'flag']}},
    {'step_id': 'second', 'name': 'Second', 'bindings': {},
     'input_schema': {'type': 'object', 'properties': {
         'shared': {'type': 'string', 'default': 'local'}, 'answer': {'type': 'integer'}},
         'required': ['answer']}}]


class StartupDraftTests(unittest.TestCase):
    def draft(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.startup_inputs'),
                             'startup needs a draft for all steps')
        from taskweave.presentation.startup_inputs import StartupInputDraft
        draft = StartupInputDraft()
        draft.configure(TASK_SCHEMA, STEPS, {'env': 'automatic'}, environment_id='env-a')
        return draft

    def test_blank_required_fields_are_deferred_and_false_is_only_explicit(self):
        draft = self.draft()
        self.assertEqual(draft.task_values(), {})
        self.assertEqual(draft.step_values(), {})
        draft.steps['first'].change('flag', False)
        self.assertEqual(draft.step_values(), {'first': {'flag': False}})
        self.assertEqual(draft.environment_id, 'env-a')

    def test_bound_and_inherited_names_are_excluded_but_explicit_local_default_survives(self):
        draft = self.draft()
        self.assertEqual(set(draft.steps['first'].data['schema']['properties']), {'amount', 'flag'})
        self.assertEqual(set(draft.steps['second'].data['schema']['properties']), {'shared', 'answer'})
        self.assertEqual(draft.task.data['schema'], TASK_SCHEMA)
        draft.steps['second'].change('shared', 'override')
        self.assertEqual(draft.step_values(), {'second': {'shared': 'override'}})

    def test_environment_reconfigure_preserves_invalid_manual_raw_edits(self):
        draft = self.draft()
        draft.steps['first'].change('amount', 'unfinished')
        draft.task.change('shared', 'written')
        draft.configure(TASK_SCHEMA, STEPS, {'env': 'other', 'amount': 20}, environment_id='env-b')
        self.assertEqual(draft.steps['first'].raw['amount'], 'unfinished')
        self.assertEqual(draft.task_values(), {'shared': 'written'})
        with self.assertRaises(TaskError): draft.step_values()
        draft.steps['first'].change('amount', 12)
        draft.steps['second'].change('answer', 7)
        self.assertEqual(draft.step_values(['second']), {'second': {'answer': 7}})

    def test_new_environment_supplies_untouched_required_field_without_a_manual_blank(self):
        draft = self.draft()
        draft.configure(TASK_SCHEMA, STEPS, {'amount': 20}, environment_id='env-b')
        self.assertNotIn('amount', draft.steps['first'].data['schema']['properties'])
        self.assertEqual(draft.step_values(), {})

    def test_task_environment_values_are_automatic_and_original_schema_stays_intact(self):
        draft = self.draft()
        draft.configure(TASK_SCHEMA, STEPS, {'shared': 'private-env'}, environment_id='env-b')
        self.assertNotIn('shared', draft.task.data['schema']['properties'])
        self.assertNotIn('private-env', str(draft.task.raw))
        self.assertEqual(draft.task_schema, TASK_SCHEMA)
        self.assertEqual(draft.task_values(), {})
