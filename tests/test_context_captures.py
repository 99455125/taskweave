import json
import tempfile
import unittest

from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.storage import Store
from taskweave.infrastructure.plan_repository import PlanRepository
from taskweave.core.validation import TaskError


class ContextCaptureTests(unittest.TestCase):
    def test_step_context_batch_save_commits_one_revision_and_invalidates_once(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home)
            task = repo.create_task('T')
            step = repo.save_step(task['task_id'], {'action_id': 'demo.noop', 'step_content': 'pass'})
            repo.confirm_manual(step['step_id'], step['content_hash'])
            result = repo.save_step_context_batch(
                step['step_id'], None, None, 'fake.page', 'Group', 'notes',
                [{'capture': {'items': [{'content': 'one'}], 'views': [{'title': 'p1'}]}, 'request': {'n': 1}, 'label': 'A'},
                {'capture': {'items': [{'content': 'two'}], 'views': [{'title': 'p2'}]}, 'request': {'n': 2}, 'label': 'B'},
                ]
            )
            group = result['group']
            self.assertEqual([c['label'] for c in group['captures']], ['A', 'B'])
            self.assertEqual(repo.step(step['step_id'])['validation_state'], 'DRAFT')
            before = repo.list_step_contexts(step['step_id'])
            with self.assertRaises(TaskError):
                repo.save_step_context_batch(
                    step['step_id'], group['context_id'], group['revision'], 'fake.page', 'Changed', '',
                    [{'capture': {'items': [], 'views': []}, 'request': {}, 'label': 'bad'}],
                )
            self.assertEqual(repo.list_step_contexts(step['step_id']), before)

    def test_plan_context_batch_save_updates_all_items_once_and_allows_empty_group(self):
        with tempfile.TemporaryDirectory() as home:
            plans = PlanRepository(Repository(home))
            plan = plans.create('P')
            first = plans.save_context_batch(plan['plan_id'], plan['revision'], None, 'fake.page', 'G', '', [
                {'capture': {'items': [{'content': 'one'}], 'views': []}, 'request': {}, 'label': 'one'},
                {'capture': {'items': [{'content': 'two'}], 'views': [{'title': 'two'}]}, 'request': {}, 'label': 'two'},
            ])
            self.assertEqual(first['plan']['revision'], plan['revision'] + 1)
            group = first['group']
            kept = group['captures'][1]['capture_id']
            with self.assertRaises(TaskError) as stale:
                plans.save_context_batch(plan['plan_id'], plan['revision'], group['context_id'], 'fake.page', 'Stale', '', [])
            self.assertEqual(stale.exception.code, 'EDIT_CONFLICT')
            self.assertEqual(plans.contexts(plan['plan_id'])[0]['name'], 'G')
            saved = plans.save_context_batch(plan['plan_id'], first['plan']['revision'], group['context_id'], 'fake.page', 'Renamed', 'notes', [
                {'capture_id': kept, 'label': 'kept'},
            ])
            self.assertEqual(saved['plan']['revision'], first['plan']['revision'] + 1)
            self.assertEqual(saved['group']['name'], 'Renamed')
            self.assertEqual([x['capture_id'] for x in saved['group']['captures']], [kept])
            self.assertEqual(plans.get_capture(group['context_id'], kept)['views'], [{'title': 'two'}])
            empty = plans.save_context_batch(plan['plan_id'], saved['plan']['revision'], group['context_id'], 'fake.page', 'Renamed', 'notes', [])
            self.assertEqual(empty['group']['captures'], [])

    def test_step_groups_store_ordered_independent_capture_items(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home)
            task = repo.create_task('T')
            step = repo.save_step(task['task_id'], {'action_id': 'demo.noop', 'step_content': 'pass'})
            group = repo.create_step_context_group(step['step_id'], 'fake.page', '记录', '说明')
            first = repo.append_step_context_capture(group['context_id'], {'items': [{'content': 'one'}], 'views': [{'title': '1'}]}, request={'n': 1})
            second = repo.append_step_context_capture(group['context_id'], {'items': [{'content': 'two'}], 'views': [{'title': '2'}]}, request={'n': 2})
            third = repo.append_step_context_capture(group['context_id'], {'items': [{'content': 'three'}], 'views': [{'title': '3'}]}, request={'n': 3})
            summaries = repo.list_step_contexts(step['step_id'])
            self.assertNotIn('items', summaries[0])
            self.assertEqual([item['label'] for item in summaries[0]['captures']], ['采集 1', '采集 2', '采集 3'])
            self.assertEqual(repo.get_step_context_capture(group['context_id'], second['capture_id'])['items'], [{'content': 'two'}])
            repo.reorder_step_context_capture(group['context_id'], second['capture_id'], 'up')
            summary = repo.list_step_contexts(step['step_id'])[0]
            self.assertEqual([item['capture_id'] for item in summary['captures']], [second['capture_id'], first['capture_id'], third['capture_id']])
            with self.assertRaises(TaskError) as stale:
                repo.append_step_context_capture(group['context_id'], {'items':[{'content':'stale'}]}, expected_revision=summary['revision']-1)
            self.assertEqual(stale.exception.code,'EDIT_CONFLICT')
            repo.delete_step_context_capture(group['context_id'], first['capture_id'])
            self.assertEqual([item['capture_id'] for item in repo.list_step_contexts(step['step_id'])[0]['captures']], [second['capture_id'],third['capture_id']])
            self.assertEqual(repo.get_step_context_capture(group['context_id'], second['capture_id'])['views'], [{'title': '2'}])
            self.assertEqual(len(repo.list_step_contexts(step['step_id'])), 1)
