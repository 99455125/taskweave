"""Context collection binds a retained path, not an arbitrary same-run worker."""

import unittest

from taskweave.presentation.collection_form import CollectionForm


class BranchContextSelectionTests(unittest.TestCase):
    def test_same_run_paths_stay_distinct_and_options_target_selected_worker(self):
        fields = {'provider': 'demo.page', 'forms': {}, 'include_view': False}
        form = CollectionForm(fields, {'demo.page': {'type': 'object'}})
        form.configure('demo.page', {'type': 'object'})
        runs = [{'run_id': 'run', 'status': 'PAUSED', 'session_id': session,
                 'execution_paths': [{'step_id': 'step', 'execution_path': path}]}
                for session, path in [('session-a', '/root/loop/0/a'), ('session-b', '/root/loop/1/a')]]
        choices, _, _ = form.run_choices(runs, step_id='step')
        self.assertEqual(len({row['selection_id'] for row in choices}), 2)
        fields['run'] = choices[1]['selection_id']
        options, _ = form.start_options(step=True)
        self.assertEqual(options['run_id'], 'run')
        self.assertEqual(options['execution_path'], '/root/loop/1/a')
        self.assertEqual(options['expected_session_id'], 'session-b')

    def test_other_branch_without_selected_step_is_not_a_capture_source(self):
        form = CollectionForm({'provider': 'demo.page'}, {'demo.page': {}})
        choices, _, _ = form.run_choices([
            {'run_id': 'run', 'status': 'PAUSED', 'session_id': 'other',
             'execution_paths': [{'step_id': 'unrelated', 'execution_path': '/root/b'}]}], step_id='step')
        self.assertEqual(choices, [])
