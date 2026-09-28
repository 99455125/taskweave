"""Context repository return shapes follow their real read models."""

import tempfile
import unittest
from pathlib import Path

from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.storage import Store


STEP = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class StepContextReturnContractTests(unittest.TestCase):
    def test_capture_label_update_returns_group_sequence_with_updated_label(self):
        with tempfile.TemporaryDirectory() as directory:
            repos = build_sqlite_repositories(Store(Path(directory)))
            task = repos.tasks.create_task("task")
            step = repos.steps.save_step(task["task_id"], {"step_content": STEP})
            group = repos.step_contexts.create_step_context_group(step["step_id"], "demo.page", "group")
            capture = repos.step_contexts.append_step_context_capture(group["context_id"], {"items": [{"content": "value"}]})
            current = repos.step_contexts.list_step_contexts(step["step_id"])[0]

            result = repos.step_contexts.update_step_context_capture_label(
                group["context_id"], capture["capture_id"], " renamed ", current["revision"], step["step_id"],
            )

            self.assertIsInstance(result, list)
            self.assertEqual(result[0]["revision"], current["revision"] + 1)
            self.assertEqual(result[0]["captures"][0]["label"], "renamed")

    def test_capture_reorder_returns_group_sequence_and_only_moves_in_range(self):
        with tempfile.TemporaryDirectory() as directory:
            repos = build_sqlite_repositories(Store(Path(directory)))
            task = repos.tasks.create_task("task")
            step = repos.steps.save_step(task["task_id"], {"step_content": STEP})
            group = repos.step_contexts.create_step_context_group(step["step_id"], "demo.page", "group")
            first = repos.step_contexts.append_step_context_capture(group["context_id"], {"items": [{"content": "one"}]})
            second = repos.step_contexts.append_step_context_capture(group["context_id"], {"items": [{"content": "two"}]})
            current = repos.step_contexts.list_step_contexts(step["step_id"])[0]

            boundary = repos.step_contexts.reorder_step_context_capture(
                group["context_id"], first["capture_id"], "up", current["revision"], step["step_id"],
            )
            self.assertIsInstance(boundary, list)
            self.assertEqual(boundary[0]["revision"], current["revision"])
            self.assertEqual([entry["capture_id"] for entry in boundary[0]["captures"]], [first["capture_id"], second["capture_id"]])

            moved = repos.step_contexts.reorder_step_context_capture(
                group["context_id"], second["capture_id"], "up", current["revision"], step["step_id"],
            )
            self.assertIsInstance(moved, list)
            self.assertEqual(moved[0]["revision"], current["revision"] + 1)
            self.assertEqual([entry["capture_id"] for entry in moved[0]["captures"]], [second["capture_id"], first["capture_id"]])


if __name__ == "__main__":
    unittest.main()
