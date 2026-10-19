"""Collection forms and opaque target identities work without UI controls."""
import asyncio
import unittest
from taskweave.core.validation import TaskError


class CollectionFormTests(unittest.TestCase):
    def test_request_precedence_hidden_required_and_raw_recovery(self):
        from taskweave.presentation.collection_form import CollectionForm, TargetSelection
        schema = {'properties': {'url': {'type': 'string'}, 'count': {'type': 'integer', 'default': 1}},
                  'required': ['url'], 'x-taskweave-context-view': {'default': True},
                  'x-taskweave-context-targets': {'hide_parameters_when_selected': True, 'keep_parameters_when_selected': ['count']}}
        fields = {'provider': 'page', 'advanced': '{"count": 3}', 'include_view': True, 'run': 'r'}
        form = CollectionForm(fields, {'page': schema})
        form.configure('page', schema)
        form.change_input('page', 'count', 2)
        target = TargetSelection()
        revision, previous = target.begin()
        target.apply(revision, previous, {'session_id': 'session', 'targets': [{'target_id': 'tab', 'label': 'Tab', 'request': {'url': 'selected'}}]})
        target.select('tab')
        form.target = target
        options, view = form.start_options(environment_id='env', step=True)
        self.assertEqual(options, {'provider_id': 'page', 'request': {'count': 3, 'url': 'selected'}, 'expected_session_id': 'session', 'run_id': 'r'})
        self.assertTrue(view)
        form.change_input('page', 'count', 2.5)
        with self.assertRaises(TaskError): form.start_options(step=True)
        self.assertEqual(fields['forms']['page']['count'], 2.5)

    def test_removed_provider_retains_recording_choice_but_cannot_start(self):
        from taskweave.presentation.collection_form import CollectionForm
        form = CollectionForm({'provider': 'removed'}, {}, available={'active'})
        self.assertEqual(form.provider_choices('removed'), ['active', 'removed'])
        self.assertTrue(form.provider_removed('removed'))
        with self.assertRaises(TaskError): form.start_options(step=True)


class TargetSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_result_rejected_and_auto_selection_resets_when_many(self):
        from taskweave.presentation.collection_form import TargetSelection
        target = TargetSelection({'auto_select_single': True})
        old, previous = target.begin()
        current, previous = target.begin()
        one = {'session_id': 's', 'targets': [{'target_id': 'a', 'label': 'A', 'request': {'target_id': 'a'}}]}
        self.assertTrue(target.apply(current, previous, one))
        self.assertFalse(target.apply(old, '', {'session_id': 'old', 'targets': []}))
        self.assertEqual(target.selection(), ({'target_id': 'a'}, 's'))
        current, previous = target.begin()
        with self.assertRaises(TaskError): target.selection()
        target.apply(current, previous, {'session_id': 's2', 'targets': one['targets'] + [{'target_id': 'b', 'label': 'B', 'request': {}}]})
        self.assertEqual(target.selection(), ({}, None))
        target.select('a')
        current, previous = target.begin()
        target.fail(current, RuntimeError('offline'))
        with self.assertRaises(TaskError): target.selection()
        self.assertIn('offline', target.note)

class RunSessionChoiceTests(unittest.TestCase):
    def test_missing_run_falls_back_but_retained_recording_preserves_authority(self):
        from taskweave.presentation.collection_form import CollectionForm
        form = CollectionForm({'run': 'gone'}, {})
        runs = [{'run_id': 'paused', 'status': 'PAUSED'}, {'run_id': 'running', 'status': 'RUNNING'}]
        eligible, selected, retained = form.run_choices(runs, None)
        self.assertEqual([r['run_id'] for r in eligible], ['paused'])
        self.assertEqual((selected, retained), ('', False))
        self.assertEqual(form.run_choices(runs, 'gone')[1:], ('gone', True))
