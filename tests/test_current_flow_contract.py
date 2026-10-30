"""The current flow and portable package have one accepted representation."""
import unittest
from taskweave.core.task_flow import normalize_flow
from taskweave.core.task_package import FORMAT, TASK_PACKAGE_SCHEMA
from taskweave.core.validation import TaskError, validate


def sequence(identity="root"):
    return {"id": identity, "kind": "sequence", "children": []}


class CurrentFlowContractTests(unittest.TestCase):
    def test_action_chain_requires_explicit_data_maintenance(self):
        with self.assertRaises(TaskError):
            normalize_flow({"entry_node_id": None, "nodes": []}, [])

    def test_then_else_requires_explicit_data_maintenance(self):
        branch = {"id": "branch", "kind": "if", "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}}, "then": sequence("yes"), "else": sequence("no")}
        with self.assertRaises(TaskError):
            normalize_flow({"version": 2, "root": {**sequence(), "children": [branch]}}, [])

    def test_current_package_requires_flow_even_for_empty_task(self):
        package = {"format": FORMAT, "origin": "task_export", "task": {"name": "empty", "description": "", "input_schema": {}}, "steps": []}
        with self.assertRaises(TaskError):
            validate(package, TASK_PACKAGE_SCHEMA)
        package.update(flow={"version": 2, "root": sequence()}, flow_validation_state="DRAFT")
        validate(package, TASK_PACKAGE_SCHEMA)
        self.assertEqual(FORMAT, "taskweave-task-3")

    def test_current_cases_are_preserved_without_mutation(self):
        branch = {"id": "branch", "kind": "if", "cases": [{"id": "case", "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}}, "body": sequence("yes")}], "default": {"id": "default", "body": sequence("no")}}
        flow = {"version": 2, "root": {**sequence(), "children": [branch]}}
        actual = normalize_flow(flow, [])
        self.assertEqual(actual, flow)
        self.assertIsNot(actual, flow)
