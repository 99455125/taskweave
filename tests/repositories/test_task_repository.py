"""Task repository lifecycle rollback checks using the real control database."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from taskweave.infrastructure.repository import Repository
from taskweave.core.validation import TaskError


STEP = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class TaskRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name))
        self.task_id = self.repo.create_task("source")["task_id"]
        self.repo.save_step(self.task_id, {"step_content": STEP})
        self.repo.save_step(self.task_id, {"step_content": STEP})

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_failure_rolls_back_partial_task_and_keeps_source(self):
        original = self.repo.step_repository.save_step
        source_task = deepcopy(self.repo.repositories.tasks.task(self.task_id))
        source_steps = deepcopy(self.repo.repositories.steps.steps(self.task_id))
        calls = 0
        target_id = None

        def fail_second_save(*args, **kwargs):
            nonlocal calls, target_id
            calls += 1
            if calls == 2:
                target_id = args[0]
                self.assertNotEqual(target_id, self.task_id)
                self.assertEqual(
                    {row["task_id"] for row in self.repo.list_tasks()},
                    {self.task_id, target_id},
                )
                self.assertEqual(len(self.repo.repositories.steps.steps(target_id)), 1)
                self.assertEqual(self.repo.repositories.tasks.task(self.task_id), source_task)
                self.assertEqual(self.repo.repositories.steps.steps(self.task_id), source_steps)
                raise RuntimeError("injected step copy failure")
            return original(*args, **kwargs)

        with patch.object(self.repo.step_repository, "save_step", side_effect=fail_second_save):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.repo.copy_task(self.task_id)

        self.assertEqual(calls, 2)
        self.assertIsNotNone(target_id)
        self.assertEqual([self.task_id], [row["task_id"] for row in self.repo.list_tasks()])
        self.assertEqual([], self.repo.repositories.steps.steps(target_id))
        self.assertEqual(self.repo.repositories.tasks.task(self.task_id), source_task)
        self.assertEqual(self.repo.repositories.steps.steps(self.task_id), source_steps)

    def test_repository_set_exposes_all_domains_on_shared_store(self):
        repositories = self.repo.repositories
        self.assertEqual(
            {
                "tasks", "steps", "environments", "runs", "results",
                "step_contexts", "plans", "plan_contexts", "plan_generations", "organization", "sequences", "flow_runs",
            },
            set(vars(repositories)),
        )
        for repository in vars(repositories).values():
            self.assertIs(repository.store, self.repo)

    def test_facade_and_repository_set_return_equivalent_task_definition(self):
        other_home = Path(self.temp.name) / "other"
        other = Repository(other_home)
        legacy_task = self.repo.create_task("equivalent", {"type": "object"}, "description")
        direct_task = other.repositories.tasks.create_task("equivalent", {"type": "object"}, "description")
        legacy_step = self.repo.save_step(legacy_task["task_id"], {"step_content": STEP})
        direct_step = other.repositories.steps.save_step(direct_task["task_id"], {"step_content": STEP})

        for key in ("name", "description", "input_schema_json", "graph_json"):
            self.assertEqual(legacy_task[key], direct_task[key])
        for key in ("name", "step_content", "content_hash", "validation_state", "position", "bindings"):
            self.assertEqual(legacy_step[key], direct_step[key])

    def test_control_flow_save_is_versioned_and_step_edit_preserves_structure(self):
        steps = self.repo.repositories.steps.steps(self.task_id)
        first, second = [step["step_id"] for step in steps]
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": first, "kind": "action", "step_id": first},
            {"id": "branch", "kind": "if", "condition": {
                "op": "eq", "left": {"literal": True}, "right": {"literal": True}},
             "then": {"id": "yes", "kind": "sequence", "children": [
                 {"id": second, "kind": "action", "step_id": second}]},
             "else": {"id": "no", "kind": "sequence", "children": []}},
        ]}}
        expected = self.repo.repositories.tasks.definition_hash(self.task_id)
        saved = self.repo.repositories.tasks.save_flow(self.task_id, flow, expected)
        self.assertEqual(saved["flow_validation_state"], "DRAFT")
        with self.assertRaises(TaskError) as error:
            self.repo.repositories.tasks.save_flow(self.task_id, flow, expected)
        self.assertEqual(error.exception.code, "EDIT_CONFLICT")
        confirmed = self.repo.repositories.tasks.confirm_flow(
            self.task_id, self.repo.repositories.tasks.definition_hash(self.task_id))
        self.assertEqual(confirmed["flow_validation_state"], "VALIDATED")
        old = self.repo.repositories.steps.step(first)
        self.repo.save_step(self.task_id, {**old, "name": "edited"}, first, old["content_hash"])
        current = self.repo.repositories.tasks.task(self.task_id)
        self.assertEqual(current["graph_json"], confirmed["graph_json"])
        self.assertEqual(current["flow_validation_state"], "VALIDATED")

    def test_copy_preserves_control_flow_with_new_action_ids(self):
        tasks = self.repo.repositories.tasks
        first, second = [step["step_id"] for step in self.repo.repositories.steps.steps(self.task_id)]
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [{
            "id": "choose", "kind": "if", "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}},
            "then": {"id": "yes", "kind": "sequence", "children": [{"id": first, "kind": "action", "step_id": first}]},
            "else": {"id": "no", "kind": "sequence", "children": [{"id": second, "kind": "action", "step_id": second}]},
        }]}}
        tasks.save_flow(self.task_id, flow, tasks.definition_hash(self.task_id))
        tasks.confirm_flow(self.task_id, tasks.definition_hash(self.task_id))
        copied = self.repo.copy_task(self.task_id)
        copied_flow = tasks.flow(copied["task_id"])
        copied_ids = {step["step_id"] for step in self.repo.repositories.steps.steps(copied["task_id"])}
        branch = copied_flow["root"]["children"][0]
        self.assertEqual({branch["then"]["children"][0]["step_id"], branch["else"]["children"][0]["step_id"]}, copied_ids)
        self.assertTrue(tasks.flow_is_confirmed(copied["task_id"]))


if __name__ == "__main__":
    unittest.main()
