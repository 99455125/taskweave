"""Structured task-flow definition and condition semantics."""

import importlib
import unittest

from taskweave.core.validation import TaskError
from tests._core_fixture import CoreFixture


def flow_api():
    try:
        return importlib.import_module("taskweave.core.task_flow")
    except ModuleNotFoundError as exc:
        raise AssertionError("task_flow module is missing") from exc


class TaskFlowTests(unittest.TestCase):
    def test_action_chain_is_rejected(self):
        with self.assertRaises(TaskError) as error:
            flow_api().normalize_flow({"entry_node_id": None, "nodes": []}, [])
        self.assertEqual(error.exception.code, "FLOW_INVALID")

    def test_nested_flow_rejects_reused_action_and_depth_over_eight(self):
        api = flow_api()
        action = {"id": "step", "kind": "action", "step_id": "step"}
        duplicate = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [action, action]}}
        with self.assertRaises(TaskError) as error:
            api.validate_flow(duplicate, [{"step_id": "step"}])
        self.assertEqual(error.exception.code, "FLOW_ACTION_DUPLICATE")
        nested = action
        for depth in range(9):
            nested = {"id": f"repeat-{depth}", "kind": "foreach", "items": {"literal": [1]},
                      "body": {"id": f"sequence-{depth}", "kind": "sequence", "children": [nested]}}
        with self.assertRaises(TaskError) as error:
            api.validate_flow({"version": 2, "root": {"id": "root", "kind": "sequence", "children": [nested]}},
                              [{"step_id": "step"}])
        self.assertEqual(error.exception.code, "FLOW_DEPTH_EXCEEDED")

    def test_eight_control_levels_are_allowed(self):
        nested = {"id": "step", "kind": "action", "step_id": "step"}
        for depth in range(8):
            nested = {"id": f"repeat-{depth}", "kind": "foreach", "items": {"literal": [1]},
                      "body": {"id": f"sequence-{depth}", "kind": "sequence", "children": [nested]}}
        flow_api().validate_flow({"version": 2, "root": {"id": "root", "kind": "sequence", "children": [nested]}},
                                 [{"step_id": "step"}])

    def test_exists_false_for_missing_but_other_operations_raise(self):
        api = flow_api()
        missing = {"ref": {"source": "task", "pointer": "/absent"}}
        def read(binding):
            if binding == missing:
                raise TaskError("INPUT_MISSING")
            return binding["literal"]
        self.assertFalse(api.evaluate_condition({"op": "exists", "value": missing}, read))
        with self.assertRaises(TaskError) as error:
            api.evaluate_condition({"op": "eq", "left": missing, "right": {"literal": None}}, read)
        self.assertEqual(error.exception.code, "INPUT_MISSING")

    def test_comparison_does_not_treat_bool_as_number(self):
        api = flow_api()
        read = lambda binding: binding["literal"]
        with self.assertRaises(TaskError) as error:
            api.evaluate_condition({"op": "gt", "left": {"literal": True}, "right": {"literal": 0}}, read)
        self.assertEqual(error.exception.code, "FLOW_TYPE_INVALID")
        self.assertTrue(api.evaluate_condition({"op": "all", "conditions": [
            {"op": "empty", "value": {"literal": []}},
            {"op": "eq", "left": {"literal": 2}, "right": {"literal": 2.0}},
        ]}, read))

    def test_loop_limits_are_checked_at_definition_time(self):
        api = flow_api()
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [{
            "id": "repeat", "kind": "loop", "mode": "until", "max_iterations": 0,
            "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}},
            "state_initial": {}, "state_update": {},
            "body": {"id": "body", "kind": "sequence", "children": [{"id": "step", "kind": "action", "step_id": "step"}]},
        }]}}
        with self.assertRaises(TaskError) as error:
            api.validate_flow(flow, [{"step_id": "step"}])
        self.assertEqual(error.exception.code, "LOOP_LIMIT_INVALID")

    def test_condition_cannot_read_future_action(self):
        api = flow_api()
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": "branch", "kind": "if", "cases": [{"id": "match", "condition": {"op": "exists", "value": {
                "ref": {"source": "step", "step_id": "future", "pointer": ""}}},
             "body": {"id": "yes", "kind": "sequence", "children": []}}],
             "default": {"id": "fallback", "body": {"id": "no", "kind": "sequence", "children": []}}},
            {"id": "future", "kind": "action", "step_id": "future"},
        ]}}
        with self.assertRaises(TaskError) as error:
            api.validate_flow(flow, [{"step_id": "future"}])
        self.assertEqual(error.exception.code, "FLOW_REFERENCE_INVALID")


class FlowConfirmationTests(CoreFixture):
    def test_flow_operations_expose_versioned_definition(self):
        task = self.task()
        step = self.step(task)
        current = self.app.dispatch("task.flow.get", {"task_id": task})
        self.assertEqual(current["root"]["children"][0]["step_id"], step["step_id"])
        saved = self.app.dispatch("task.flow.save", {
            "task_id": task, "flow": current,
            "expected_hash": self.app.repo.repositories.tasks.definition_hash(task),
        })
        self.assertEqual(saved["flow_validation_state"], "VALIDATED")

    def test_controlled_run_requires_confirmed_flow(self):
        task = self.task()
        step = self.step(task)
        self.app.confirm_step_manual(step["step_id"], step["content_hash"])
        repo = self.app.repo.repositories.tasks
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": "branch", "kind": "if", "cases": [{"id": "match", "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}},
             "body": {"id": "yes", "kind": "sequence", "children": [
                 {"id": step["step_id"], "kind": "action", "step_id": step["step_id"]}]}}],
             "default": {"id": "fallback", "body": {"id": "no", "kind": "sequence", "children": []}}},
        ]}}
        repo.save_flow(task, flow, repo.definition_hash(task))
        with self.assertRaises(TaskError) as error:
            self.app.create_run(task)
        self.assertEqual(error.exception.code, "FLOW_NOT_CONFIRMED")
        repo.confirm_flow(task, repo.definition_hash(task))
        self.assertEqual(self.app.create_run(task)["status"], "READY")


if __name__ == "__main__":
    unittest.main()
