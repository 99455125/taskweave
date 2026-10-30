"""Workspace maintenance stages all databases and rolls back partial writes."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from taskweave.infrastructure.locking import InstanceLock
from taskweave.core.validation import TaskError
from taskweave.infrastructure.sqlite_storage import initialize


class WorkspaceMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'workspace'
        self.home.mkdir()
        self.control = self.home / 'taskweave.db'
        initialize(self.control, 'control')
        with closing(sqlite3.connect(self.control)) as db, db:
            db.execute("INSERT INTO tasks(task_id,name,graph_json,created_at,updated_at) VALUES('task','preserve',?,'now','now')", (json.dumps({'entry_node_id': None, 'nodes': []}),))
            db.execute("INSERT INTO run_events VALUES('event','run',NULL,'debug','{}','now')")
            db.execute("INSERT INTO task_runs(run_id,task_id,mode,status,definition_hash) VALUES('run','task','TRIAL','FAILED','history')")
        self.data = self.home / 'tasks' / 'task' / 'data.db'
        self.data.parent.mkdir(parents=True)
        initialize(self.data, 'task-data')
        with closing(sqlite3.connect(self.data)) as db, db:
            db.execute('ALTER TABLE plugin_table_schemas ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
            db.execute('CREATE TABLE p_demo_records(value TEXT)')
            db.execute("INSERT INTO p_demo_records VALUES('preserve secret')")
            db.execute("INSERT INTO plugin_table_schemas VALUES('p_demo_records',1)")
        self.asset = self.data.parent / 'image.bin'
        self.asset.write_bytes(b'asset bytes')
        self.backups = Path(self.temp.name) / 'maintenance'

    def read(self, path, sql):
        with closing(sqlite3.connect(path)) as db:
            return db.execute(sql).fetchall()

    def test_dry_run_stages_wal_rows_without_changing_sources(self):
        from scripts.maintain_workspace import maintain_workspace
        with closing(sqlite3.connect(self.data)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute("INSERT INTO p_demo_records VALUES('committed in WAL')")
            writer.commit()
            before = self.read(self.control, 'SELECT graph_json FROM tasks')
            report = maintain_workspace(self.home, backup_dir=self.backups)
            self.assertEqual(report['status'], 'dry_run')
            self.assertEqual(self.read(self.control, 'SELECT graph_json FROM tasks'), before)
            self.assertEqual(len(self.read(self.backups / 'original' / 'tasks/task/data.db', 'SELECT * FROM p_demo_records')), 2)
        self.assertEqual(self.asset.read_bytes(), b'asset bytes')
        self.assertNotIn('preserve secret', (self.backups / 'report.json').read_text())

    def test_apply_converts_every_database_and_preserves_history(self):
        from scripts.maintain_workspace import maintain_workspace
        report = maintain_workspace(self.home, backup_dir=self.backups, apply=True)
        self.assertEqual(report['status'], 'applied')
        self.assertEqual(json.loads(self.read(self.control, 'SELECT graph_json FROM tasks')[0][0])['version'], 2)
        self.assertEqual(self.read(self.control, 'SELECT status,definition_hash FROM task_runs'), [('FAILED', 'history')])
        self.assertEqual(self.read(self.control, 'SELECT event_id FROM run_events'), [('event',)])
        self.assertEqual([row[1] for row in self.read(self.data, 'PRAGMA table_info(plugin_table_schemas)')], ['table_name'])
        self.assertEqual(self.asset.read_bytes(), b'asset bytes')
        owner = InstanceLock(self.home / 'coordinator.lock')
        owner.close()

    def test_failed_second_write_restores_all_touched_databases(self):
        import scripts.maintain_workspace as maintenance
        before_control = self.read(self.control, 'SELECT * FROM tasks')
        before_columns = self.read(self.data, 'PRAGMA table_info(plugin_table_schemas)')
        original = maintenance.apply_database
        count = 0
        def fail_second(source, target):
            nonlocal count
            count += 1
            with self.assertRaises(TaskError) as locked:
                InstanceLock(self.home / 'coordinator.lock')
            self.assertEqual(locked.exception.code, 'INSTANCE_RUNNING')
            original(source, target)
            if count == 2:
                raise RuntimeError('injected write failure')
        with patch.object(maintenance, 'apply_database', fail_second):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                maintenance.maintain_workspace(self.home, backup_dir=self.backups, apply=True)
        self.assertEqual(self.read(self.control, 'SELECT * FROM tasks'), before_control)
        self.assertEqual(self.read(self.data, 'PRAGMA table_info(plugin_table_schemas)'), before_columns)
        self.assertEqual(self.read(self.data, 'SELECT * FROM p_demo_records'), [('preserve secret',)])
        self.assertEqual(json.loads((self.backups / 'report.json').read_text())['status'], 'rolled_back')

    def test_rollback_failure_is_reported_and_other_databases_are_restored(self):
        import scripts.maintain_workspace as maintenance
        real_backup = maintenance.backup_database
        real_apply = maintenance.apply_database
        before = self.read(self.control, 'SELECT * FROM tasks')
        def fail_apply(source, target):
            real_apply(source, target)
            if target == self.data.resolve():
                raise RuntimeError('injected apply failure')
        def fail_restore(source, target, *, existing=False):
            if existing and 'original' in source.parts and target == self.data.resolve():
                raise OSError('injected restore failure')
            return real_backup(source, target, existing=existing)
        with patch.object(maintenance, 'apply_database', fail_apply), patch.object(maintenance, 'backup_database', fail_restore):
            with self.assertRaisesRegex(RuntimeError, 'Rollback incomplete'):
                maintenance.maintain_workspace(self.home, backup_dir=self.backups, apply=True)
        report = json.loads((self.backups / 'report.json').read_text())
        self.assertEqual(report['status'], 'rollback_failed')
        self.assertEqual(len(report['rollback_failures']), 1)
        self.assertEqual(self.read(self.control, 'SELECT * FROM tasks'), before)
        self.assertTrue((self.backups / 'original/tasks/task/data.db').is_file())

    def test_invalid_last_database_never_changes_first(self):
        from scripts.maintain_workspace import maintain_workspace
        with closing(sqlite3.connect(self.data)) as db, db:
            db.execute('ALTER TABLE plugin_table_schemas ADD COLUMN unreviewed TEXT')
        before = self.read(self.control, 'SELECT * FROM tasks')
        with self.assertRaises(ValueError):
            maintain_workspace(self.home, backup_dir=self.backups, apply=True)
        self.assertEqual(self.read(self.control, 'SELECT * FROM tasks'), before)
        self.assertEqual(json.loads((self.backups / 'report.json').read_text())['status'], 'preparation_failed')

    def test_active_owner_and_unsafe_backup_locations_are_rejected(self):
        from scripts.maintain_workspace import maintain_workspace
        owner = InstanceLock(self.home / 'coordinator.lock')
        try:
            with self.assertRaises(TaskError):
                maintain_workspace(self.home, backup_dir=self.backups, apply=True)
            self.assertFalse(self.backups.exists())
        finally:
            owner.close()
        for folder in [self.data.parent / 'backup', self.home]:
            with self.subTest(folder=folder), self.assertRaises((ValueError, FileExistsError)):
                maintain_workspace(self.home, backup_dir=folder)
        with self.assertRaises(ValueError):
            maintain_workspace(Path('relative-workspace'))

    def test_definition_evidence_repairs_guard_without_replacing_user_edits(self):
        from scripts.maintain_workspace import maintain_workspace, backup_database
        from taskweave.core.validation import fingerprint
        evidence = Path(self.temp.name) / 'evidence.db'
        with closing(sqlite3.connect(self.control)) as db, db:
            schema, graph = db.execute('SELECT input_schema_json,graph_json FROM tasks').fetchone()
            old_hash = fingerprint({'input_schema': schema, 'graph': graph, 'steps': []})
            definition = {'task': {'task_id': 'task', 'input_schema_json': schema, 'graph_json': graph}, 'steps': []}
            db.execute('UPDATE task_runs SET definition_hash=?,definition_json=?', (old_hash, json.dumps(definition)))
        backup_database(self.control.resolve(), evidence.resolve())
        maintain_workspace(self.home, backup_dir=self.backups, apply=True)
        with closing(sqlite3.connect(self.control)) as db, db:
            db.execute('UPDATE task_runs SET definition_hash=?', (old_hash,))
            db.execute("UPDATE tasks SET name='user edit after maintenance'")
        repair = Path(self.temp.name) / 'repair'
        report = maintain_workspace(self.home, backup_dir=repair, apply=True, definition_evidence=evidence)
        with closing(sqlite3.connect(self.control)) as db:
            schema, graph, name = db.execute('SELECT input_schema_json,graph_json,name FROM tasks').fetchone()
            expected = fingerprint({'input_schema': schema, 'graph': graph, 'steps': []})
            self.assertEqual(db.execute('SELECT definition_hash FROM task_runs').fetchone()[0], expected)
            self.assertEqual(name, 'user edit after maintenance')
        self.assertEqual(report['databases'][0]['definition_hash_updates'][0]['old_hash'], old_hash)
        self.assertTrue(Path(report['definition_evidence_backup']).is_file())
