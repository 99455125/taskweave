"""Pure structured flow traversal and loop boundaries."""

import unittest

from taskweave.core.validation import TaskError


def sequence(*children, node_id="root"):
    return {"id": node_id, "kind": "sequence", "children": list(children)}


def action(step_id):
    return {"id": step_id, "kind": "action", "step_id": step_id}


def literal(value):
    return {"literal": value}


class FlowMachineTests(unittest.TestCase):
    def test_empty_nested_loops_yield_bounded_control_batches(self):
        from taskweave.core.flow_machine import CONTROL_BATCH_SIZE, next_action
        flow = {"version": 2, "root": sequence({"id": "outer", "kind": "foreach",
            "items": literal(list(range(30))), "body": sequence({"id": "inner", "kind": "foreach",
                "items": literal(list(range(30))), "body": sequence(node_id="empty")}, node_id="outer_body")})}
        cursor = None
        batches = 0
        while True:
            result = next_action(flow, cursor, lambda binding, _: binding["literal"])
            self.assertLessEqual(len(result["instances"]), CONTROL_BATCH_SIZE + 4)
            self.assertIsNone(result["action"])
            batches += 1
            cursor = result["cursor"]
            if result["done"]:
                break
        self.assertGreater(batches, 1)
        self.assertEqual(cursor["control_visits"], sum(1 for _ in range(30) for _ in range(30)) + 92)

    def test_control_visit_budget_stops_actionless_flow(self):
        from taskweave.core.flow_machine import FlowDecisionError, MAX_CONTROL_VISITS, next_action
        flow = {"version": 2, "root": sequence({"id": "each", "kind": "foreach",
            "items": literal([1]), "body": sequence(node_id="empty")})}
        cursor = {"frames": [{"node_id": "root", "kind": "sequence", "path": "/root", "index": 0}],
                  "pending": None, "actions": 0, "control_visits": MAX_CONTROL_VISITS}
        with self.assertRaises(FlowDecisionError) as error:
            next_action(flow, cursor, lambda binding, _: binding["literal"])
        self.assertEqual(error.exception.code, "FLOW_CONTROL_LIMIT_EXCEEDED")

    def drive(self, flow, read=None, limit=20):
        from taskweave.core.flow_machine import next_action, advance_after_action
        cursor = None
        actions = []
        decisions = []
        read = read or (lambda binding, cursor: binding["literal"])
        for _ in range(limit):
            transition = next_action(flow, cursor, read)
            decisions.extend(transition["instances"])
            cursor = transition["cursor"]
            if transition["done"]:
                return actions, decisions
            pending = transition["action"]
            actions.append((pending["step_id"], pending["execution_path"]))
            advanced = advance_after_action(flow, cursor, attempt_id=f"attempt-{len(actions)}")
            decisions.extend(advanced["instances"])
            cursor = advanced["cursor"]
        self.fail("flow did not finish")

    def test_if_runs_selected_branch_then_joins(self):
        flow = {"version": 2, "root": sequence(
            {"id": "choose", "kind": "if", "condition": {"op": "eq", "left": literal(1), "right": literal(1)},
             "then": sequence(action("yes"), node_id="then"),
             "else": sequence(action("no"), node_id="else")},
            action("join"),
        )}
        actions, decisions = self.drive(flow)
        self.assertEqual([step for step, _ in actions], ["yes", "join"])
        self.assertEqual(next(item["payload"]["selected"] for item in decisions if item["node_id"] == "choose"), "then")

    def test_foreach_repeats_same_action_with_distinct_paths_and_empty_skips(self):
        def flow(items):
            return {"version": 2, "root": sequence(
                {"id": "each", "kind": "foreach", "items": literal(items), "max_items": 4,
                 "body": sequence(action("visit"), node_id="body")},
                action("after"),
            )}
        actions, decisions = self.drive(flow(["a", "a", "b"]))
        self.assertEqual([step for step, _ in actions], ["visit", "visit", "visit", "after"])
        self.assertEqual(len({path for step, path in actions if step == "visit"}), 3)
        self.assertEqual([visit["payload"]["item"] for visit in decisions if visit["kind"] == "iteration"],
                         ["a", "a", "b"])
        empty, _ = self.drive(flow([]))
        self.assertEqual([step for step, _ in empty], ["after"])

    def test_while_can_run_zero_times_and_until_runs_at_least_once(self):
        base = {"id": "repeat", "kind": "loop", "condition": {"op": "eq", "left": literal(False), "right": literal(True)},
                "state_initial": {}, "state_update": {}, "max_iterations": 2,
                "body": sequence(action("tick"), node_id="body")}
        zero, _ = self.drive({"version": 2, "root": sequence({**base, "mode": "while"}, action("after"))})
        self.assertEqual([step for step, _ in zero], ["after"])
        with self.assertRaises(TaskError) as error:
            self.drive({"version": 2, "root": sequence({**base, "mode": "until"})})
        self.assertEqual(error.exception.code, "LOOP_LIMIT_EXCEEDED")

    def test_foreach_rejects_oversized_list_before_first_action(self):
        flow = {"version": 2, "root": sequence({
            "id": "each", "kind": "foreach", "items": literal([1, 2, 3]), "max_items": 2,
            "body": sequence(action("visit"), node_id="body"),
        })}
        with self.assertRaises(TaskError) as error:
            self.drive(flow)
        self.assertEqual(error.exception.code, "LOOP_LIMIT_EXCEEDED")

    def test_loop_state_updates_and_nested_paths(self):
        state = {"ref": {"source": "loop", "node_id": "repeat", "field": "state", "pointer": "/count"}}
        flow = {"version": 2, "root": sequence({
            "id": "repeat", "kind": "loop", "mode": "while", "max_iterations": 4,
            "state_initial": {"count": literal(0)},
            "state_update": {"count": {"ref": {"source": "step", "step_id": "tick", "output": "value"}}},
            "condition": {"op": "lt", "left": state, "right": literal(2)},
            "body": sequence(action("tick"), node_id="body"),
        }, action("after"))}
        completed = {"count": 0}

        def read(binding, cursor):
            ref = binding["ref"]
            if ref["source"] == "loop":
                return next(frame["state"]["count"] for frame in reversed(cursor["frames"]) if frame["node_id"] == "repeat")
            completed["count"] += 1
            return completed["count"]

        actions, _ = self.drive(flow, read)
        self.assertEqual([step for step, _ in actions], ["tick", "tick", "after"])
        self.assertNotEqual(actions[0][1], actions[1][1])

    def test_nested_foreach_keeps_both_iteration_coordinates(self):
        inner = {"id": "inner", "kind": "foreach", "items": literal(["x", "y"]),
                 "body": sequence(action("visit"), node_id="inner_body")}
        outer = {"id": "outer", "kind": "foreach", "items": literal([1, 2]),
                 "body": sequence(inner, node_id="outer_body")}
        actions, _ = self.drive({"version": 2, "root": sequence(outer)})
        self.assertEqual(len(actions), 4)
        self.assertEqual(len({path for _, path in actions}), 4)
        self.assertIn("/outer/0/", actions[0][1])
        self.assertIn("/inner/1/", actions[1][1])

    def test_aggregate_nested_outputs_and_skipped_branch_placeholders(self):
        from taskweave.core.flow_values import aggregate_output
        inner = {"id": "inner", "kind": "foreach", "items": literal([0, 1]),
                 "body": sequence({"id": "choice", "kind": "if",
                                   "condition": {"op": "eq", "left": {"ref": {"source": "loop", "node_id": "inner", "field": "index"}},
                                                 "right": literal(0)},
                                   "then": sequence(action("visit"), node_id="yes"),
                                   "else": sequence(node_id="no")}, node_id="inner_body")}
        outer = {"id": "outer", "kind": "foreach", "items": literal([0, 1]),
                 "body": sequence(inner, node_id="outer_body")}
        flow = {"version": 2, "root": sequence(outer)}

        def read(binding, cursor):
            ref = binding["ref"]
            return next(frame["index"] for frame in reversed(cursor["frames"]) if frame["node_id"] == ref["node_id"])

        actions, visits = self.drive(flow, read)
        self.assertEqual([step for step, _ in actions], ["visit", "visit"])
        values = {"attempt-1": {"value": 0}, "attempt-2": {"value": 2}}
        result = aggregate_output(flow, visits, "visit", "data", lambda attempt, output: values[attempt])
        self.assertEqual(result, [[{"value": 0}, None], [{"value": 2}, None]])
        projected = aggregate_output(flow, visits, "visit", "data", lambda attempt, output: values[attempt],
                                     loop_node_id="inner", item_pointer="/value")
        self.assertEqual(projected, [[0, None], [2, None]])

    def test_aggregate_empty_loop_is_empty_list(self):
        from taskweave.core.flow_values import aggregate_output
        flow = {"version": 2, "root": sequence({"id": "each", "kind": "foreach", "items": literal([]),
                                                  "body": sequence(action("visit"), node_id="body")})}
        _, visits = self.drive(flow)
        self.assertEqual(aggregate_output(flow, visits, "visit", "data", lambda *_: self.fail("unexpected read")), [])

    def test_aggregate_executed_action_requires_a_committed_result(self):
        from taskweave.core.flow_values import aggregate_output
        flow = {"version": 2, "root": sequence(action("visit"))}
        with self.assertRaises(TaskError) as error:
            aggregate_output(flow, [], "visit", "data", lambda *_: None)
        self.assertEqual(error.exception.code, "RESULT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
