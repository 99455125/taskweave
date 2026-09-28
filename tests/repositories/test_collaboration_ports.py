"""Infrastructure-only repository collaboration remains substitutable."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints

from taskweave.core.validation import TaskError
from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.repositories.collaboration import PlanContextCopier, TaskLockGuard
from taskweave.infrastructure.repositories.plans import PlanMetadataRepository
from taskweave.infrastructure.repositories.results import ResultRepository
from taskweave.infrastructure.storage import Store, connect, initialize, now, uid


class PortOnlyPlanContextCopier:
    def __init__(self, delegate, fail_after_copy=False):
        self._delegate = delegate
        self._fail_after_copy = fail_after_copy

    def copy_contexts(self, db, plan_id, target_id, stamp):
        self._delegate.copy_contexts(db, plan_id, target_id, stamp)
        if self._fail_after_copy:
            raise RuntimeError("copy contexts failed after write")


class PortOnlyTaskLockGuard:
    def __init__(self, delegate):
        self._delegate = delegate

    def assert_unlocked(self, db, task_id, allow_idle_trial=False):
        return self._delegate.assert_unlocked(db, task_id, allow_idle_trial)


class RepositoryCollaborationTests(unittest.TestCase):
    def test_collaborating_repositories_declare_narrow_infrastructure_ports(self):
        self.assertIs(get_type_hints(PlanMetadataRepository.__init__)["plan_contexts"], PlanContextCopier)
        self.assertIs(get_type_hints(ResultRepository.__init__)["tasks"], TaskLockGuard)

    def test_plan_copy_uses_only_context_copier_contract_and_rolls_back_mid_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            repositories = build_sqlite_repositories(store)
            source = repositories.plans.create("source")
            saved = repositories.plan_contexts.save_context_batch(
                source["plan_id"], source["revision"], None, "demo.page", "group", "notes",
                [{"label": "one", "capture": {"items": [{"content": "kept"}], "views": [{"title": "preview"}]}, "request": {"scope": "page"}}],
            )
            port_only = PortOnlyPlanContextCopier(repositories.plan_contexts)
            plans = PlanMetadataRepository(store, port_only)

            copied = plans.copy(source["plan_id"], saved["plan"]["revision"])
            copied_group = repositories.plan_contexts.contexts(copied["plan_id"])[0]
            copied_capture = repositories.plan_contexts.get_capture(copied_group["context_id"], copied_group["captures"][0]["capture_id"])
            self.assertEqual(copied_group["name"], "group")
            self.assertEqual(copied_capture["items"], [{"content": "kept"}])
            self.assertEqual(copied_capture["views"], [{"title": "preview"}])

            failing = PlanMetadataRepository(store, PortOnlyPlanContextCopier(repositories.plan_contexts, fail_after_copy=True))
            with self.assertRaisesRegex(RuntimeError, "after write"):
                failing.copy(source["plan_id"], saved["plan"]["revision"])
            self.assertEqual({row["plan_id"] for row in failing.list()}, {source["plan_id"], copied["plan_id"]})
            self.assertEqual(len(repositories.plan_contexts.contexts(source["plan_id"])), 1)
            self.assertEqual(len(repositories.plan_contexts.contexts(copied["plan_id"])), 1)

    def test_result_delete_uses_only_lock_guard_and_preserves_lock_and_delete_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            repositories = build_sqlite_repositories(store)
            task = repositories.tasks.create_task("task")
            step = repositories.steps.save_step(task["task_id"], {"step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"})
            run = repositories.runs.create_run(task["task_id"], {}, {}, trial_step_id=step["step_id"])
            attempt_id, result_id = uid(), uid()
            stamp = now()
            with store.transaction() as db:
                db.execute(
                    "INSERT INTO step_attempts(attempt_id,task_id,run_id,step_id,execution_path,attempt_no,content_hash,status,effect_state,started_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, task["task_id"], run["run_id"], step["step_id"], step["step_id"], 1, step["content_hash"], "SUCCEEDED", "SUCCEEDED", stamp),
                )
                db.execute(
                    "INSERT INTO result_refs(result_id,task_id,run_id,step_id,attempt_id,handler_id,kind,locator,media_type) VALUES(?,?,?,?,?,?,?,?,?)",
                    (result_id, task["task_id"], run["run_id"], step["step_id"], attempt_id, "core.json", "file", "result.txt", "text/plain"),
                )
            task_db = store.task_path(task["task_id"])
            initialize(task_db, "task-data")
            result_file = task_db.parent / "result.txt"
            result_file.write_text("result", encoding="utf-8")
            receipt = [{"result_id": result_id, "locator": "result.txt", "name": "result"}]
            with connect(task_db) as db:
                db.execute("INSERT INTO result_receipts VALUES(?,?,?,?,?,?)", (attempt_id, run["run_id"], step["step_id"], "COMMITTED", json.dumps(receipt), stamp))
            store.execute("INSERT INTO runtime_lease(slot,run_id,owner_id,heartbeat_at) VALUES(1,?,?,?)", (run["run_id"], "owner", stamp))

            results = ResultRepository(store, PortOnlyTaskLockGuard(repositories.tasks))
            with self.assertRaises(TaskError) as locked:
                results.delete_result(result_id)
            self.assertEqual(locked.exception.code, "TASK_LOCKED")
            self.assertEqual(store.query("SELECT state FROM result_refs WHERE result_id=?", (result_id,), True)["state"], "AVAILABLE")
            self.assertTrue(result_file.exists())

            store.execute("DELETE FROM runtime_lease WHERE run_id=?", (run["run_id"],))
            self.assertEqual(results.delete_result(result_id), {"deleted": result_id})
            self.assertEqual(store.query("SELECT state FROM result_refs WHERE result_id=?", (result_id,), True)["state"], "UNAVAILABLE")
            self.assertFalse(result_file.exists())


if __name__ == "__main__":
    unittest.main()
