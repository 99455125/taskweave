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
            group = repo.create_step_context_group(step['step_id'], 'fake.page', '合约', '说明')
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

    def test_legacy_context_rows_migrate_to_single_capture(self):
        import sqlite3
        from pathlib import Path
        from taskweave.infrastructure.storage import CONTROL_V14, migrate
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/'old.db'
            db=sqlite3.connect(path); db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON')
            db.executescript("""
            CREATE TABLE steps(step_id TEXT PRIMARY KEY);
            CREATE TABLE plans(plan_id TEXT PRIMARY KEY);
            CREATE TABLE step_contexts(context_id TEXT PRIMARY KEY,step_id TEXT REFERENCES steps(step_id),provider_id TEXT,name TEXT,source_page TEXT,item_json TEXT,created_at TEXT,updated_at TEXT,context_notes TEXT,order_index INTEGER,request_json TEXT,views_json TEXT,include_view INTEGER,captured_at TEXT);
            CREATE TABLE plan_contexts(context_id TEXT PRIMARY KEY,plan_id TEXT REFERENCES plans(plan_id),provider_id TEXT,name TEXT,context_notes TEXT,order_index INTEGER,captured_at TEXT,source_session_id TEXT,item_json TEXT,created_at TEXT,updated_at TEXT,request_json TEXT,views_json TEXT,include_view INTEGER);
            INSERT INTO steps VALUES('s'); INSERT INTO plans VALUES('p');
            INSERT INTO step_contexts VALUES('c','s','fake.page','old group','draft','[{"content":"legacy"}]','created','updated','keep',0,'{"q":1}','[{"title":"legacy preview"}]',1,'captured');
            INSERT INTO plan_contexts VALUES('pc','p','fake.page','plan group','notes',0,'captured','session','[]','created','updated','{}','[]',1);
            PRAGMA user_version=13;
            """)
            migrate(db,path,14,{14:CONTROL_V14})
            capture=db.execute('SELECT * FROM step_context_captures WHERE context_id="c"').fetchone()
            self.assertEqual(json.loads(capture['items_json']),[{'content':'legacy'}])
            self.assertEqual(json.loads(capture['views_json']),[{'title':'legacy preview'}])
            self.assertEqual(capture['captured_at'],'captured')
            self.assertNotIn('item_json',{row['name'] for row in db.execute('PRAGMA table_info(step_contexts)')})
            self.assertEqual(db.execute('SELECT count(*) FROM plan_context_captures WHERE context_id="pc"').fetchone()[0],1)
            db.close()
