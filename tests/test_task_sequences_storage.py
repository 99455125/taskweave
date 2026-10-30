"""Persistent sequence definitions and child-run ownership."""

import tempfile
import unittest

from taskweave.core.validation import TaskError
from taskweave.infrastructure.sqlite_storage import SQLiteStorage
from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.repositories.sequences import SequenceRepository


class SequenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.store = SQLiteStorage(self.home.name)
        self.repositories = build_sqlite_repositories(self.store)
        self.repo = SequenceRepository(self.store)
        self.first_task = self.repositories.tasks.create_task("First")["task_id"]
        self.second_task = self.repositories.tasks.create_task("Second")["task_id"]
        self.first_step = self.repositories.steps.save_step(self.first_task, {
            "name": "Produce", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data={})\n",
        })["step_id"]
        self.nodes = [
            {"node_id": "a", "task_id": self.first_task, "environment_id": None,
             "inputs": {}, "step_inputs": {}},
            {"node_id": "b", "task_id": self.second_task, "environment_id": None,
             "inputs": {}, "step_inputs": {}},
        ]

    def tearDown(self):
        self.home.cleanup()

    def test_definition_survives_reopen_with_node_order_and_revision(self):
        saved = self.repo.save("Morning", self.nodes, {"type": "object"})
        reopened = SequenceRepository(SQLiteStorage(self.home.name)).get(saved["sequence_id"])
        self.assertEqual(reopened["name"], "Morning")
        self.assertEqual([n["node_id"] for n in reopened["nodes"]], ["a", "b"])
        self.assertEqual(reopened["revision"], 1)
        self.assertEqual(len(self.repo.list()), 1)

    def test_duplicate_node_ids_and_forward_output_references_are_rejected(self):
        with self.assertRaises(TaskError):
            self.repo.save("Duplicate", [self.nodes[0], self.nodes[0]], {"type": "object"})
        forward = [self.nodes[0], {**self.nodes[1], "inputs": {
            "x": {"kind": "output", "node_id": "b", "step_id": "s", "output": "data", "pointer": ""}}}]
        with self.assertRaises(TaskError):
            self.repo.save("Forward", forward, {"type": "object"})
        self.assertEqual(self.repo.list(), [])

    def test_run_freezes_definition_and_rejects_second_child_association(self):
        saved = self.repo.save("Morning", self.nodes, {"type": "object"})
        started = self.repo.create_run(saved["sequence_id"], "request-1", {},
                                       {"a": "hash-a", "b": "hash-b"}, {})
        self.assertEqual(self.repo.get_run(started["sequence_run_id"])["snapshot"]["nodes"], self.nodes)
        self.repo.save("Changed", list(reversed(self.nodes)), {"type": "object"},
                       sequence_id=saved["sequence_id"], expected_revision=1)
        self.assertEqual([n["node_id"] for n in self.repo.get_run(started["sequence_run_id"])["snapshot"]["nodes"]], ["a", "b"])
        child = self.repositories.runs.create_run(self.first_task, {}, {}, trial_step_id=self.first_step, defer_inputs=True)
        self.repo.attach_child(started["sequence_run_id"], "a", child["run_id"], {}, {})
        self.assertEqual(self.repo.owner_of_child(child["run_id"]), (started["sequence_run_id"], "/root/a"))
        another = self.repositories.runs.create_run(self.first_task, {}, {}, trial_step_id=self.first_step, defer_inputs=True)
        with self.assertRaises(TaskError):
            self.repo.attach_child(started["sequence_run_id"], "a", another["run_id"], {}, {})
        self.assertEqual(self.repo.get_run(started["sequence_run_id"])["nodes"][0]["run_id"], child["run_id"])


if __name__ == "__main__":
    unittest.main()
