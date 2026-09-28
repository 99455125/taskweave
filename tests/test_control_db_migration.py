"""Durable interval scheduling, task operations and desktop API evidence."""
from contextlib import closing
from pathlib import Path
import sqlite3
from taskweave.application.service import Application
from tests._runtime_fixture import RuntimeFixture

class ControlDbMigrationTests(RuntimeFixture):
    def test_v2_migration_backup_and_default_interval(self):
        self.app.close()
        path = Path(self.temp.name) / "taskweave.db"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("ALTER TABLE steps DROP COLUMN delay_after_previous_seconds")
            db.execute("ALTER TABLE steps DROP COLUMN validation_source")
            db.execute("ALTER TABLE steps RENAME COLUMN step_description TO goal")
            db.execute("ALTER TABLE steps DROP COLUMN step_notes")
            db.execute("ALTER TABLE environments DROP COLUMN descriptions_json")
            db.execute("ALTER TABLE tasks DROP COLUMN sort_order")
            db.execute("ALTER TABLE tasks DROP COLUMN category_id")
            db.execute("ALTER TABLE tasks DROP COLUMN is_favorite")
            db.execute("ALTER TABLE task_runs DROP COLUMN definition_json")
            db.execute("ALTER TABLE task_runs DROP COLUMN waiting_step_id")
            db.execute("ALTER TABLE task_runs DROP COLUMN wait_until")
            db.execute("DROP TABLE step_context_captures")
            db.execute("DROP TABLE plan_context_captures")
            db.execute("DROP TABLE step_contexts")
            db.execute("DROP TABLE plan_generations")
            db.execute("DROP TABLE plan_generation_imports")
            db.execute("DROP TABLE organization_categories")
            db.execute("DROP TABLE plan_contexts")
            db.execute("DROP TABLE plans")
            db.execute("PRAGMA user_version=2")
        self.app = Application(self.temp.name)
        self.assertTrue(Path(str(path) + ".v2.bak").exists())
        self.assertEqual(self.app.repo.task(self.task)["name"], "Interval")
        self.assertEqual(
            self.app.repo.query("PRAGMA user_version")[0]["user_version"], 17
        )

    def test_v14_generation_import_is_backfilled_and_task_deletion_keeps_history(self):
        plan = self.app.dispatch("plan.create", {"name": "Migration"})
        self.app.close()
        from taskweave.infrastructure.storage import Store
        store = Store(self.temp.name)
        generation_id = "legacy-generation"
        store.execute("INSERT INTO plan_generations(generation_id,plan_id,plan_revision,channel,request_snapshot_path,status,imported_task_id,created_at,updated_at) VALUES(?,?,1,'api','request','IMPORTED',?,'now','now')", (generation_id, plan["plan_id"], self.task))
        store.execute("DROP TABLE plan_generation_imports")
        with sqlite3.connect(store.path) as db:
            db.execute("ALTER TABLE tasks DROP COLUMN category_id")
            db.execute("ALTER TABLE tasks DROP COLUMN is_favorite")
            db.execute("ALTER TABLE plans DROP COLUMN category_id")
            db.execute("ALTER TABLE plans DROP COLUMN is_favorite")
            db.execute("DROP TABLE organization_categories")
            for table in ("step_context_captures", "plan_context_captures"):
                db.execute(f"ALTER TABLE {table} DROP COLUMN operation_notes")
                db.execute(f"ALTER TABLE {table} DROP COLUMN send_preview")
            db.execute("PRAGMA user_version=14")
        self.app = Application(self.temp.name)
        imports = self.app.planning.generation_imports(generation_id)
        self.assertEqual([row["task_id"] for row in imports], [self.task])
        self.app.repo.delete_task(self.task)
        self.assertEqual([row["task_id"] for row in self.app.planning.generation_imports(generation_id)], [self.task])
        self.assertTrue(Path(str(store.path) + ".v14.bak").exists())
        self.assertEqual(self.app.repo.query("PRAGMA user_version")[0]["user_version"], 17)
