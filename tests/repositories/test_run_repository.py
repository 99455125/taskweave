"""Run queries use existing schema fields and support their real consumer."""

import tempfile
import unittest
from pathlib import Path

from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.runtime import Coordinator


STEP = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class RunRepositoryTests(unittest.TestCase):
    def _task_with_runs(self, repo, name, count):
        task = repo.create_task(name)
        step = repo.save_step(task["task_id"], {"step_content": STEP})
        repo.confirm_manual(step["step_id"], step["content_hash"])
        runs = [repo.create_run(task["task_id"], {}, {}) for _ in range(count)]
        return task["task_id"], runs

    def test_runs_for_task_is_empty_and_scoped_and_clear_consumer_uses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory))
            target_id, target_runs = self._task_with_runs(repo, "target", 2)
            other_id, other_runs = self._task_with_runs(repo, "other", 1)

            self.assertEqual(repo.repositories.runs.runs_for_task("missing-task"), [])
            target_rows = repo.repositories.runs.runs_for_task(target_id)
            self.assertEqual({(row["run_id"], row["status"]) for row in target_rows}, {(run["run_id"], "READY") for run in target_runs})
            self.assertEqual({row["run_id"] for row in repo.repositories.runs.runs_for_task(other_id)}, {other_runs[0]["run_id"]})

            stores = repo.repositories
            coordinator = Coordinator(
                stores.runs, stores.tasks, stores.steps, stores.environments,
                stores.results, None, None, repo.home, recover=False,
            )
            result = coordinator.clear_task_runs(target_id)
            self.assertEqual(result["deleted_runs"], 2)
            self.assertEqual(repo.repositories.runs.runs_for_task(target_id), [])
            self.assertEqual({row["run_id"] for row in repo.repositories.runs.runs_for_task(other_id)}, {other_runs[0]["run_id"]})


if __name__ == "__main__":
    unittest.main()
