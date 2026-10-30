"""Single current schema and explicit, source-preserving data maintenance."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.maintain_current_schema import rebuild
from taskweave.core.validation import TaskError
from taskweave.infrastructure.sqlite_storage import initialize, validate_schema, connect


class CurrentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_new_databases_have_complete_current_schema(self):
        for kind in ('control', 'task-data'):
            path = self.root / (kind + '.db')
            initialize(path, kind)
            with connect(path) as db:
                validate_schema(db, kind)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            initialize(path, kind)
        with connect(self.root / 'control.db') as db:
            self.assertIn('flow_json', [r[1] for r in db.execute('PRAGMA table_info(task_sequences)')])
            self.assertIn('revision', [r[1] for r in db.execute('PRAGMA table_info(step_contexts)')])
            self.assertIn('content_hash', [r[1] for r in db.execute('PRAGMA table_info(steps)')])
            self.assertEqual(db.execute('SELECT * FROM sequence_commands').fetchall(), [])

    def test_existing_incomplete_schema_is_not_migrated(self):
        path = self.root / 'old.db'
        with closing(sqlite3.connect(path)) as db:
            db.executescript("CREATE TABLE tasks(task_id TEXT); INSERT INTO tasks VALUES('kept'); PRAGMA user_version=2;")
        before = path.read_bytes()
        with self.assertRaises(TaskError) as error:
            initialize(path, 'control')
        self.assertEqual(error.exception.code, "SCHEMA_MAINTENANCE_REQUIRED")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.bak')), [])

    def test_missing_index_or_extra_column_is_rejected(self):
        for mutation in ('DROP INDEX steps_task_order', 'ALTER TABLE tasks ADD COLUMN obsolete TEXT'):
            path = self.root / ('test' + str(len(list(self.root.iterdir()))) + '.db')
            initialize(path, 'control')
            with connect(path) as db:
                db.execute(mutation)
            with self.assertRaises(TaskError) as error:
                initialize(path, 'control')

            self.assertEqual(error.exception.code, "SCHEMA_MAINTENANCE_REQUIRED")
    def test_current_data_reopens_without_changes(self):
        path = self.root / 'control.db'
        initialize(path, 'control')
        with connect(path) as db:
            db.execute("INSERT INTO environments(environment_id,name) VALUES('env','kept')")
        before = path.read_bytes()
        initialize(path, 'control')
        self.assertEqual(path.read_bytes(), before)

    def test_explicit_rebuild_preserves_data_and_source(self):
        source, target = self.root / 'source.db', self.root / 'target.db'
        initialize(source, 'control')
        with connect(source) as db:
            db.execute("INSERT INTO environments(environment_id,name) VALUES('env','kept')")
            db.execute('PRAGMA user_version=24')
        before = source.read_bytes()
        rebuild(source, target, 'control')
        self.assertEqual(source.read_bytes(), before)
        initialize(target, 'control')
        with connect(target) as db:
            self.assertEqual(db.execute('SELECT name FROM environments').fetchone()[0], 'kept')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        with self.assertRaises(FileExistsError):
            rebuild(source, target, 'control')

    def test_explicit_task_copy_preserves_plugin_data_and_removes_version_metadata(self):
        source, target = self.root / 'source.db', self.root / 'target.db'
        initialize(source, 'task-data')
        with connect(source) as db:
            db.execute('ALTER TABLE plugin_table_schemas ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
            db.execute('CREATE TABLE p_demo_items(value TEXT)')
            db.execute('CREATE INDEX p_demo_items_value ON p_demo_items(value)')
            db.execute("INSERT INTO p_demo_items VALUES('kept')")
            db.execute("INSERT INTO plugin_table_schemas VALUES('p_demo_items',2)")
        before = source.read_bytes()
        with self.assertRaises(TaskError) as error:
            initialize(source, 'task-data')
        self.assertEqual(error.exception.code, "SCHEMA_MAINTENANCE_REQUIRED")
        rebuild(source, target, 'task-data')
        self.assertEqual(source.read_bytes(), before)
        initialize(target, 'task-data')
        with connect(target) as db:
            self.assertEqual(db.execute('SELECT value FROM p_demo_items').fetchone()[0], 'kept')
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(plugin_table_schemas)')], ['table_name'])

    def test_rebuild_does_not_guess_missing_business_columns(self):
        source, target = self.root / 'source.db', self.root / 'target.db'
        initialize(source, 'control')
        with connect(source) as db:
            db.execute('ALTER TABLE environments DROP COLUMN descriptions_json')
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'business columns differ'):
            rebuild(source, target, 'control')
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(target.exists())

    def test_rebuild_rejects_invalid_relationships(self):
        source, target = self.root / 'source.db', self.root / 'target.db'
        initialize(source, 'control')
        with closing(sqlite3.connect(source)) as db, db:
            db.execute("INSERT INTO run_events VALUES('event','absent',NULL,'test','{}','now')")
        with self.assertRaisesRegex(ValueError, 'Foreign key violations'):
            rebuild(source, target, 'control')
        self.assertFalse(target.exists())
