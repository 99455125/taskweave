"""Sequence-owned child runs cannot be changed from independent run paths."""

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError
from unittest.mock import patch


class SequenceLifecycleTests(CoreFixture):
    def test_child_and_referenced_task_are_protected_from_independent_deletion(self):
        task = self.task()
        self.confirm(self.step(task))
        node = {"node_id": "first", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        definition = self.app.sequences.save("Protected", [node], {"type": "object"})
        started = self.app.sequences.start(definition["sequence_id"], "protected-request", {})
        import time
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.app.sequences.run_get(started["sequence_run_id"])
            if result["status"] == "SUCCEEDED":
                break
            time.sleep(0.03)
        self.assertEqual(result["status"], "SUCCEEDED")
        child_id = result["nodes"][0]["run_id"]
        with self.assertRaises(TaskError):
            self.app.runs.delete(child_id)
        with self.assertRaises(TaskError):
            self.app.tasks.clear_runs(task)
        with self.assertRaises(TaskError):
            self.app.tasks.delete(task)
        self.assertEqual(self.app.runs.get(child_id)["status"], "SUCCEEDED")

    def test_history_cleanup_deletes_owned_child_then_allows_task_deletion(self):
        task = self.task()
        self.confirm(self.step(task))
        node = {"node_id": "first", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        definition = self.app.sequences.save("Cleanup", [node], {"type": "object"})
        started = self.app.sequences.start(definition["sequence_id"], "cleanup-request", {})
        import time
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.app.sequences.run_get(started["sequence_run_id"])
            if result["status"] == "SUCCEEDED":
                break
            time.sleep(0.03)
        self.assertEqual(result["status"], "SUCCEEDED")
        child_id = result["nodes"][0]["run_id"]
        self.app.sequences.run_delete(started["sequence_run_id"])
        self.assertFalse(self.app.sequences.run_list())
        self.assertFalse(any(row["run_id"] == child_id for row in self.app.runs.list()))
        self.app.sequences.delete(definition["sequence_id"], definition["revision"])
        self.app.tasks.delete(task)

    def test_failed_cleanup_keeps_child_owned_until_retry(self):
        task = self.task()
        self.confirm(self.step(task))
        node = {"node_id": "first", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        definition = self.app.sequences.save("Failed cleanup", [node], {"type": "object"})
        started = self.app.sequences.start(definition["sequence_id"], "failed-cleanup", {})
        import time
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = self.app.sequences.run_get(started["sequence_run_id"])
            if run["status"] == "SUCCEEDED":
                break
            time.sleep(0.03)
        self.assertEqual(run["status"], "SUCCEEDED")
        child_id = run["nodes"][0]["run_id"]
        with patch.object(self.app.coordinator, "delete_run", side_effect=TaskError("INJECTED")):
            with self.assertRaises(TaskError):
                self.app.sequences.run_delete(started["sequence_run_id"])
        self.assertEqual(self.app.sequences.run_get(started["sequence_run_id"])["status"], "DELETING")
        child = next(row for row in self.app.runs.list() if row['run_id'] == child_id)
        self.assertEqual(child['sequence_run_id'], started['sequence_run_id'])
        with self.assertRaises(TaskError) as error:
            self.app.runs.delete(child_id)
        self.assertEqual(error.exception.code, "SEQUENCE_CHILD_MANAGED")
        self.app.sequences.run_delete(started["sequence_run_id"])
        self.assertFalse(self.app.sequences.run_list())


if __name__ == "__main__":
    import unittest
    unittest.main()
