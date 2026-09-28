import tempfile
import unittest
from pathlib import Path
import sqlite3

from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.storage import Store


class PlanGenerationRepositoryTests(unittest.TestCase):
    def test_generation_state_transitions_return_frozen_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            repos = build_sqlite_repositories(Store(Path(directory)))
            plan = repos.plans.create("plan")
            generation = repos.plan_generations.create_generation(plan["plan_id"], plan["revision"], "api", "request.json")
            ready = repos.plan_generations.finish_generation(generation["generation_id"], "READY", candidate={"steps": []})
            imported = repos.plan_generations.mark_imported(generation["generation_id"], "task-1")
            self.assertEqual({"steps": []}, ready["candidate"])
            self.assertEqual("task-1", imported["imported_task_id"])

    def test_mark_imported_rolls_back_receipt_when_status_update_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            repos = build_sqlite_repositories(store)
            plan = repos.plans.create("plan")
            generation = repos.plan_generations.create_generation(plan["plan_id"], plan["revision"], "api", "request.json")
            repos.plan_generations.finish_generation(generation["generation_id"], "READY", candidate={"steps": []})
            store.execute("CREATE TRIGGER reject_imported_status BEFORE UPDATE ON plan_generations WHEN NEW.status='IMPORTED' BEGIN SELECT RAISE(ABORT,'injected update failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                repos.plan_generations.mark_imported(generation["generation_id"], "task-1")
            self.assertEqual(repos.plan_generations.imports(generation["generation_id"]), [])
            row = repos.plan_generations.generation(generation["generation_id"])
            self.assertEqual(row["status"], "READY")
            self.assertIsNone(row["imported_task_id"])
