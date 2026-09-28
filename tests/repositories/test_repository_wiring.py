"""Business repositories must use explicit ports and complete compositions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.repositories.tasks import TaskRepository
from taskweave.infrastructure.repositories.plans import PlanMetadataRepository
from taskweave.infrastructure.storage import Store


STEP = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class RepositoryWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_repositories_reject_missing_required_ports(self):
        with self.assertRaises(TypeError):
            TaskRepository(self.store)
        with self.assertRaises(TypeError):
            PlanMetadataRepository(self.store)

    def test_task_definition_hash_reads_steps_from_injected_port(self):
        repos = build_sqlite_repositories(self.store)
        task = repos.tasks.create_task("source")
        read_steps = Mock(wraps=repos.steps)
        repos.tasks.steps = read_steps

        repos.tasks.definition_hash(task["task_id"])

        read_steps.steps.assert_called_once_with(task["task_id"])

    def test_direct_composition_copies_tasks_and_plans(self):
        repos = build_sqlite_repositories(self.store)
        task = repos.tasks.create_task("task")
        step = repos.steps.save_step(task["task_id"], {"step_content": STEP})
        repos.step_contexts.save_step_context_batch(
            step["step_id"], None, None, "demo.page", "page", "notes",
            [{"label": "one", "capture": {"items": [{"kind": "text", "content": "x"}], "views": []}}],
        )
        task_copy = repos.tasks.copy_task(task["task_id"])
        self.assertEqual(1, len(repos.steps.steps(task_copy["task_id"])))

        plan = repos.plans.create("plan")
        saved = repos.plan_contexts.save_context_batch(
            plan["plan_id"], plan["revision"], None, "demo.page", "page", "notes",
            [{"label": "one", "capture": {"items": [{"kind": "text", "content": "x"}], "views": []}, "request": {}}],
        )
        plan_copy = repos.plans.copy(plan["plan_id"], saved["plan"]["revision"])
        self.assertEqual(1, len(repos.plan_contexts.contexts(plan_copy["plan_id"])))

    def test_composed_repositories_share_outer_transaction_rollback(self):
        repos = build_sqlite_repositories(self.store)
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.store.transaction():
                task = repos.tasks.create_task("rolled back")
                repos.steps.save_step(task["task_id"], {"step_content": STEP})
                raise RuntimeError("rollback")
        self.assertEqual([], repos.tasks.list_tasks())
        self.assertEqual([], self.store.query("SELECT * FROM steps"))


if __name__ == "__main__":
    unittest.main()
