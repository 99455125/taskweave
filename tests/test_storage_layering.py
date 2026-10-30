"""SQLite infrastructure runs without loading domain or legacy adapters."""

import subprocess
import sys
import textwrap
import unittest


class StorageLayeringTests(unittest.TestCase):
    def run_isolated(self, blocked, body):
        script = f"""
import importlib.abc
import sys
import tempfile
class BlockImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in {blocked!r}):
            raise AssertionError('forbidden dependency: ' + fullname)
sys.meta_path.insert(0, BlockImports())
""" + textwrap.dedent(body)
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_low_level_storage_initializes_without_domain_repositories(self):
        self.run_isolated(
            ['taskweave.infrastructure.repositories', 'taskweave.infrastructure.repository',
             'taskweave.infrastructure.storage', 'taskweave.infrastructure.plan_repository'],
            '''
            from taskweave.infrastructure.sqlite_storage import SQLiteStorage, connect, initialize
            with tempfile.TemporaryDirectory() as home:
                store = SQLiteStorage(home)
                assert store.query('PRAGMA user_version', one=True)['user_version'] == 0
                path = store.task_path('00000000-0000-0000-0000-000000000001')
                initialize(path, 'task-data')
                with connect(path) as db:
                    assert db.execute('PRAGMA user_version').fetchone()[0] == 0
                try:
                    with store.transaction():
                        store.execute("INSERT INTO environments(environment_id,name) VALUES('test', 'rollback')")
                        raise RuntimeError('rollback')
                except RuntimeError:
                    pass
                assert store.query("SELECT * FROM environments WHERE environment_id='test'") == []
            ''',
        )

    def test_domain_composition_operates_without_legacy_facades(self):
        self.run_isolated(
            ['taskweave.infrastructure.storage', 'taskweave.infrastructure.repository',
             'taskweave.infrastructure.plan_repository'],
            '''
            from taskweave.infrastructure.repositories import build_sqlite_repositories
            from taskweave.infrastructure.sqlite_storage import SQLiteStorage
            with tempfile.TemporaryDirectory() as home:
                store = SQLiteStorage(home)
                repositories = build_sqlite_repositories(store)
                task = repositories.tasks.create_task('original')
                copy = repositories.tasks.copy_task(task['task_id'])
                assert copy['task_id'] != task['task_id']
                assert len(repositories.tasks.list_tasks()) == 2
                try:
                    with store.transaction():
                        repositories.plans.create('rollback')
                        raise RuntimeError('rollback')
                except RuntimeError:
                    pass
                assert repositories.plans.list() == []
            ''',
        )
