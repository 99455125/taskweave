import tempfile
import unittest
from taskweave.infrastructure.repository import Repository
from taskweave.core.validation import TaskError


class ContextTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repository(self.tmp.name)
        self.contexts = self.repo.repositories.step_contexts
        self.task = self.repo.create_task('T')
        self.source = self.repo.save_step(self.task['task_id'], {'action_id': 'demo.noop', 'step_content': 'pass'})
        self.target = self.repo.save_step(self.task['task_id'], {'action_id': 'demo.noop', 'step_content': 'pass'})
        self.group = self.contexts.save_step_context_batch(self.source['step_id'], None, None, 'demo.page', 'Source', 'group notes', [
            {'capture': {'items': [{'content': str(n)}], 'views': [{'title': str(n)}]}, 'request': {'n': n}, 'include_view': False, 'label': f'item {n}', 'operation_notes': 'notes', 'send_preview': True, 'source_page': 'trial_feedback', 'source_session_id': 'session', 'captured_at': '2026-01-01'} for n in range(3)])['group']

    def transfer(self, **kwargs):
        args = dict(mode='copy', expected_revision=self.group['revision'], target_name='Destination')
        args.update(kwargs)
        return self.contexts.transfer_step_context_captures(self.source['step_id'], self.group['context_id'], [c['capture_id'] for c in self.group['captures'][:2]], self.target['step_id'], **args)

    def test_copy_preserves_metadata_and_uses_new_ids(self):
        result = self.transfer()
        self.assertEqual(len(self.contexts.list_step_contexts(self.source['step_id'])[0]['captures']), 3)
        for old, new in zip(self.group['captures'], result['target_group']['captures']):
            a = self.contexts.get_step_context_capture(self.group['context_id'], old['capture_id'])
            b = self.contexts.get_step_context_capture(result['target_group']['context_id'], new['capture_id'])
            self.assertNotEqual(a['capture_id'], b['capture_id'])
            for key in ('items', 'views', 'request', 'include_view', 'captured_at', 'source_page', 'source_session_id', 'label', 'operation_notes', 'send_preview'):
                self.assertEqual(a[key], b[key], key)

    def test_move_keeps_ids_and_normalizes_source_order(self):
        result = self.transfer(mode='move')
        self.assertEqual(result['capture_ids'], [c['capture_id'] for c in self.group['captures'][:2]])
        source = self.contexts.list_step_contexts(self.source['step_id'])[0]
        self.assertEqual(source['revision'], 1)
        self.assertEqual([c['order_index'] for c in source['captures']], [0])

    def test_stale_target_and_invalid_selection_are_atomic(self):
        target = self.contexts.create_step_context_group(self.target['step_id'], 'demo.page', 'D')
        before = self.contexts.list_step_contexts(self.source['step_id'])
        with self.assertRaises(TaskError) as error:
            self.transfer(target_context_id=target['context_id'], target_expected_revision=9)
        self.assertEqual(error.exception.code, 'EDIT_CONFLICT')
        self.assertEqual(before, self.contexts.list_step_contexts(self.source['step_id']))
        self.assertEqual(self.contexts.list_step_contexts(self.target['step_id'])[0]['captures'], [])

    def test_same_step_group_transfer(self):
        self.target = self.source
        result = self.transfer(mode='move')
        self.assertEqual(len(result['target_group']['captures']), 2)

    def test_cross_task_rejected(self):
        other = self.repo.create_task('Other')
        self.target = self.repo.save_step(other['task_id'], {'action_id': 'demo.noop', 'step_content': 'pass'})
        with self.assertRaises(TaskError):
            self.transfer()
        self.assertEqual(self.contexts.list_step_contexts(self.target['step_id']), [])

    def test_application_checks_target_provider_before_writing(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from taskweave.application.contexts import ContextUseCases
        use = ContextUseCases(self.contexts, self.repo.repositories.steps,
                              SimpleNamespace(contributions=lambda _: []), None, None, None)
        with self.assertRaises(TaskError) as error:
            use.transfer(self.source['step_id'], self.group['context_id'], None, self.target['step_id'],
                         mode='copy', expected_revision=0)
        self.assertEqual(error.exception.code, 'CONTEXT_PROVIDER_UNAVAILABLE')
        self.assertEqual(self.contexts.list_step_contexts(self.target['step_id']), [])

    def test_stale_source_and_unknown_capture_do_not_create_destination(self):
        with self.assertRaises(TaskError) as error:
            self.transfer(expected_revision=8)
        self.assertEqual(error.exception.code, 'EDIT_CONFLICT')
        with self.assertRaises(TaskError):
            self.contexts.transfer_step_context_captures(self.source['step_id'], self.group['context_id'], ['missing'],
                self.target['step_id'], mode='move', expected_revision=0)
        self.assertEqual(self.contexts.list_step_contexts(self.target['step_id']), [])

    def test_failure_after_partial_insert_rolls_back_new_group_and_all_captures(self):
        from unittest.mock import patch
        original = self.contexts.list_step_contexts(self.source['step_id'])
        with patch('taskweave.infrastructure.repositories.step_contexts.uid', side_effect=['new-group', 'first-copy', RuntimeError('injected failure')]):
            with self.assertRaises(RuntimeError):
                self.transfer()
        self.assertEqual(self.contexts.list_step_contexts(self.target['step_id']), [])
        self.assertEqual(self.contexts.list_step_contexts(self.source['step_id']), original)

    def test_append_existing_group_and_reject_provider_mismatch(self):
        target = self.contexts.save_step_context_batch(self.target['step_id'], None, None, 'demo.page', 'Existing', '',
            [{'capture': {'items': [{'content': 'existing'}]}, 'label': 'existing'}])['group']
        result = self.transfer(target_context_id=target['context_id'], target_expected_revision=0)
        self.assertEqual([c['label'] for c in result['target_group']['captures']], ['existing', 'item 0', 'item 1'])
        self.assertEqual(result['target_group']['revision'], 1)
        wrong = self.contexts.create_step_context_group(self.target['step_id'], 'different.page', 'Wrong')
        with self.assertRaises(TaskError) as error:
            self.transfer(target_context_id=wrong['context_id'], target_expected_revision=wrong['revision'])
        self.assertEqual(error.exception.code, 'CONTEXT_PROVIDER_MISMATCH')
