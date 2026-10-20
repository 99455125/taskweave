"""Controlled task execution through the real worker and repositories."""

from datetime import datetime
import json

from taskweave.infrastructure.storage import uid
from tests._core_fixture import CoreFixture


def sequence(*children, node_id="root"):
    return {"id": node_id, "kind": "sequence", "children": list(children)}


def action(step):
    return {"id": step["step_id"], "kind": "action", "step_id": step["step_id"]}


class FlowExecutionTests(CoreFixture):
    def confirmed_step(self, task, **kwargs):
        step = self.step(task, **kwargs)
        self.app.confirm_step_manual(step["step_id"], step["content_hash"])
        return step

    def save_flow(self, task, root):
        self.app.repo.tasks.save_flow(task, {"version": 2, "root": root}, self.app.repo.tasks.definition_hash(task))
        self.app.repo.tasks.confirm_flow(task, self.app.repo.tasks.definition_hash(task))

    def test_result_branch_runs_selected_action_and_joins(self):
        task = self.task()
        first = self.confirmed_step(task, bindings={"value": {"literal": True}})
        yes = self.confirmed_step(task, bindings={"value": {"literal": "yes"}})
        no = self.confirmed_step(task, bindings={"value": {"literal": "no"}})
        join = self.confirmed_step(task, bindings={"value": {"ref": {"source": "branch",
                                                                      "node_id": "decision", "output": "chosen",
                                                                      "pointer": "/value"}}})
        self.save_flow(task, sequence(action(first), {
            "id": "decision", "kind": "if",
            "condition": {"op": "eq", "left": {"ref": {"source": "step", "step_id": first["step_id"], "pointer": "/value"}},
                          "right": {"literal": True}},
            "then": sequence(action(yes), node_id="then"),
            "else": sequence(action(no), node_id="else"),
            "outputs": {"chosen": {
                "then": {"ref": {"source": "step", "step_id": yes["step_id"], "pointer": ""}},
                "else": {"ref": {"source": "step", "step_id": no["step_id"], "pointer": ""}},
            }},
        }, action(join)))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual([a["step_id"] for a in run["attempts"]],
                         [first["step_id"], yes["step_id"], join["step_id"]])
        self.assertEqual(self.app.runs.output(run["run_id"], join["step_id"]), {"value": "yes"})

    def test_foreach_yields_distinct_action_instances_and_aggregate(self):
        task = self.task()
        source = self.confirmed_step(task, bindings={"items": {"literal": [1, 1, 3]}})
        visit = self.confirmed_step(task, bindings={"item": {"ref": {"source": "loop", "node_id": "each",
                                                                    "field": "item", "pointer": ""}}})
        consume = self.confirmed_step(task, bindings={"value": {"ref": {"source": "step",
                                                                         "step_id": visit["step_id"],
                                                                         "pointer": "/item"}}})
        after = self.confirmed_step(task, bindings={"all": {"ref": {"source": "step",
                                                                      "step_id": consume["step_id"],
                                                                      "pointer": ""}}})
        self.save_flow(task, sequence(action(source), {
            "id": "each", "kind": "foreach",
            "items": {"ref": {"source": "step", "step_id": source["step_id"], "pointer": "/items"}},
            "body": sequence(action(visit), action(consume), node_id="body"),
        }, action(after)))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        visits = [a for a in run["attempts"] if a["step_id"] == visit["step_id"]]
        self.assertEqual(len(visits), 3)
        self.assertEqual(len({a["execution_path"] for a in visits}), 3)
        self.assertEqual(self.app.runs.output(run["run_id"], visit["step_id"]),
                         [{"item": 1}, {"item": 1}, {"item": 3}])
        self.assertEqual(self.app.runs.output(run["run_id"], visit["step_id"],
                                              loop_node_id="each", item_pointer="/item"), [1, 1, 3])
        self.assertEqual(self.app.runs.output(run["run_id"], visit["step_id"],
                                              execution_path=visits[1]["execution_path"]), {"item": 1})
        self.assertEqual(self.app.runs.output(run["run_id"], consume["step_id"]),
                         [{"value": 1}, {"value": 1}, {"value": 3}])
        self.assertEqual(self.app.runs.output(run["run_id"], after["step_id"]),
                         {"all": [{"value": 1}, {"value": 1}, {"value": 3}]})

    def test_completed_foreach_output_is_visible_to_immediate_condition(self):
        task = self.task()
        value = self.confirmed_step(task, bindings={"value": {"ref": {
            "source": "loop", "node_id": "each", "field": "item", "pointer": ""}}})
        after = self.confirmed_step(task, bindings={"done": {"literal": True}})
        self.save_flow(task, sequence({"id": "each", "kind": "foreach", "items": {"literal": [1]},
                                      "body": sequence(action(value), node_id="body")},
            {"id": "decide", "kind": "if", "condition": {
                "op": "eq", "left": {"ref": {"source": "step", "step_id": value["step_id"], "pointer": ""}},
                "right": {"literal": [{"value": 1}]}},
             "then": sequence(action(after), node_id="then"), "else": sequence(node_id="else")}))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual([item["step_id"] for item in run["attempts"]], [value["step_id"], after["step_id"]])

    def test_control_only_batches_complete_before_final_action(self):
        task = self.task()
        last = self.confirmed_step(task)
        self.save_flow(task, sequence({"id": "outer", "kind": "foreach",
            "items": {"literal": list(range(15))}, "body": sequence({"id": "inner", "kind": "foreach",
                "items": {"literal": list(range(15))}, "body": sequence(node_id="empty")}, node_id="outer_body")},
            action(last)))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(len(run["attempts"]), 1)
        self.assertEqual(len([item for item in run["flow_instances"] if item["kind"] == "iteration"]), 240)

    def test_completed_empty_branch_output_is_visible_to_next_condition(self):
        task = self.task()
        last = self.confirmed_step(task)
        first_branch = {"id": "first", "kind": "if", "condition": {
            "op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(node_id="first_then"), "else": sequence(node_id="first_else"),
            "outputs": {"choice": {"then": {"literal": 0}, "else": {"literal": 1}}}}
        second_branch = {"id": "second", "kind": "if", "condition": {
            "op": "eq", "left": {"ref": {"source": "branch", "node_id": "first",
                                           "output": "choice", "pointer": ""}}, "right": {"literal": 0}},
            "then": sequence(action(last), node_id="second_then"),
            "else": sequence(node_id="second_else")}
        self.save_flow(task, sequence(first_branch, second_branch))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(len(run["attempts"]), 1)

    def test_delay_is_applied_between_foreach_occurrences(self):
        task = self.task()
        step = self.confirmed_step(task, delay_after_previous_seconds=1)
        self.save_flow(task, sequence({"id": "each", "kind": "foreach", "items": {"literal": [1, 2]},
                                      "body": sequence(action(step), node_id="body")}))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        attempts = [item for item in run["attempts"] if item["step_id"] == step["step_id"]]
        self.assertEqual(len(attempts), 2)
        elapsed = datetime.fromisoformat(attempts[1]["started_at"]) - datetime.fromisoformat(attempts[0]["finished_at"])
        self.assertGreaterEqual(elapsed.total_seconds(), 0.9)

    def test_each_occurrence_requests_its_own_missing_input(self):
        task = self.task()
        step = self.confirmed_step(task, input_schema={"type": "object", "properties": {"answer": {"type": "integer"}},
                                                       "required": ["answer"]})
        self.save_flow(task, sequence({"id": "each", "kind": "foreach", "items": {"literal": [1, 2]},
                                      "body": sequence(action(step), node_id="body")}))
        run = self.app.create_run(task)
        for answer in (7, 9):
            self.app.coordinator.start(run["run_id"], uid())
            paused = self.app.coordinator.wait(run["run_id"])
            self.assertEqual(paused["status"], "PAUSED")
            waiting = json.loads(paused["request_json"])["waiting_input"]
            self.assertEqual(waiting["scope"], "step")
            self.assertIn("execution_path", waiting)
            self.app.coordinator.provide_inputs(run["run_id"], uid(), {"answer": answer},
                                                expected_input_id=waiting["id"])
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(self.app.runs.output(run["run_id"], step["step_id"]),
                         [{"answer": 7}, {"answer": 9}])

    def test_task_input_required_by_first_condition_pauses_before_decision(self):
        task = self.app.repo.create_task("Input", input_schema={
            "type": "object", "properties": {"flag": {"type": "boolean"}}, "required": ["flag"]})["task_id"]
        step = self.confirmed_step(task)
        self.save_flow(task, sequence({"id": "decision", "kind": "if", "condition": {
            "op": "eq", "left": {"ref": {"source": "task", "pointer": "/flag"}},
            "right": {"literal": True}},
            "then": sequence(action(step), node_id="then"), "else": sequence(node_id="else")}))
        run = self.app.create_run(task, defer_inputs=True)
        self.app.coordinator.start(run["run_id"], uid())
        paused = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(paused["status"], "PAUSED")
        waiting = json.loads(paused["request_json"])["waiting_input"]
        self.assertEqual(waiting["scope"], "task")
        self.app.coordinator.provide_inputs(run["run_id"], uid(), {"flag": True}, expected_input_id=waiting["id"])
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len(done["attempts"]), 1)

    def test_while_state_uses_current_round_output(self):
        task = self.task()
        tick = self.confirmed_step(task,
            source='async def run(ctx, inputs):\n    return ctx.result(data={"count": inputs["count"] + 1})\n',
            bindings={"count": {"ref": {"source": "loop", "node_id": "repeat",
                                         "field": "state", "pointer": "/count"}}})
        self.save_flow(task, sequence({
            "id": "repeat", "kind": "loop", "mode": "while", "max_iterations": 5,
            "state_initial": {"count": {"literal": 0}},
            "state_update": {"count": {"ref": {"source": "step", "step_id": tick["step_id"],
                                               "pointer": "/count"}}},
            "condition": {"op": "lt", "left": {"ref": {"source": "loop", "node_id": "repeat",
                                                      "field": "state", "pointer": "/count"}},
                          "right": {"literal": 3}},
            "body": sequence(action(tick), node_id="body"),
        }))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(self.app.runs.output(run["run_id"], tick["step_id"]),
                         [{"count": 1}, {"count": 2}, {"count": 3}])

    def test_loop_limit_fails_control_and_retains_completed_round(self):
        task = self.task()
        tick = self.confirmed_step(task, bindings={"value": {"literal": 1}})
        self.save_flow(task, sequence({
            "id": "repeat", "kind": "loop", "mode": "while", "max_iterations": 1,
            "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "state_initial": {}, "state_update": {},
            "body": sequence(action(tick), node_id="body"),
        }))
        run = self.run_task(task)
        self.assertEqual(run["status"], "FAILED", run)
        self.assertEqual(self.app.runs.output(run["run_id"], tick["step_id"]), [{"value": 1}])
        failures = [item for item in run["flow_instances"] if item["kind"] == "control"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error_code"], "LOOP_LIMIT_EXCEEDED")

    def test_retry_one_failed_iteration_preserves_previous_success(self):
        task = self.task()
        source = self.confirmed_step(task, bindings={"items": {"literal": [1, 2]}})
        fail = self.confirmed_step(task,
            source='async def run(ctx, inputs):\n    if inputs["item"] == 2:\n        raise ValueError("second item")\n    return ctx.result(data=inputs)\n',
            bindings={"item": {"ref": {"source": "loop", "node_id": "each",
                                        "field": "item", "pointer": ""}}})
        self.save_flow(task, sequence(action(source), {
            "id": "each", "kind": "foreach", "items": {"ref": {"source": "step",
                                                               "step_id": source["step_id"], "pointer": "/items"}},
            "body": sequence(action(fail), node_id="body"),
        }))
        run = self.run_task(task)
        self.assertEqual(run["status"], "FAILED")
        attempts = [a for a in run["attempts"] if a["step_id"] == fail["step_id"]]
        self.assertEqual([a["status"] for a in attempts], ["SUCCEEDED", "FAILED"])
        second_path = attempts[1]["execution_path"]
        self.app.coordinator.start(run["run_id"], uid(), retry_execution_path=second_path)
        retried = self.app.coordinator.wait(run["run_id"])
        attempts = [a for a in retried["attempts"] if a["step_id"] == fail["step_id"]]
        self.assertEqual([a["status"] for a in attempts], ["SUCCEEDED", "FAILED", "FAILED"])
        self.assertEqual(attempts[0]["valid"], 1)
        self.assertEqual(attempts[1]["valid"], 0)

    def test_branch_public_output_aggregates_across_iterations(self):
        task = self.task()
        source = self.confirmed_step(task, bindings={"items": {"literal": [1, 2]}})
        yes = self.confirmed_step(task, bindings={"choice": {"literal": "yes"}})
        no = self.confirmed_step(task, bindings={"choice": {"literal": "no"}})
        after = self.confirmed_step(task, bindings={"choices": {"ref": {
            "source": "branch", "node_id": "decision", "output": "chosen", "pointer": ""}}})
        self.save_flow(task, sequence(action(source), {
            "id": "each", "kind": "foreach", "items": {"ref": {"source": "step",
                "step_id": source["step_id"], "pointer": "/items"}},
            "body": sequence({"id": "decision", "kind": "if",
                "condition": {"op": "eq", "left": {"ref": {"source": "loop", "node_id": "each",
                                                            "field": "item", "pointer": ""}},
                              "right": {"literal": 1}},
                "then": sequence(action(yes), node_id="then"),
                "else": sequence(action(no), node_id="else"),
                "outputs": {"chosen": {
                    "then": {"ref": {"source": "step", "step_id": yes["step_id"], "pointer": "/choice"}},
                    "else": {"ref": {"source": "step", "step_id": no["step_id"], "pointer": "/choice"}},
                }}}, node_id="body"),
        }, action(after)))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(self.app.runs.output(run["run_id"], after["step_id"]),
                         {"choices": ["yes", "no"]})

    def test_branch_public_output_reads_each_historical_item(self):
        task = self.task()
        after = self.confirmed_step(task, bindings={"values": {"ref": {
            "source": "branch", "node_id": "pick", "output": "value", "pointer": ""}}})
        choice = {"id": "pick", "kind": "if", "condition": {
            "op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(node_id="then"), "else": sequence(node_id="else"),
            "outputs": {"value": {"then": {"ref": {"source": "loop", "node_id": "each",
                "field": "item", "pointer": ""}}, "else": {"literal": None}}}}
        self.save_flow(task, sequence({"id": "each", "kind": "foreach", "items": {"literal": [10, 20]},
                                      "body": sequence(choice, node_id="body")}, action(after)))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(self.app.runs.output(run["run_id"], after["step_id"]), {"values": [10, 20]})

    def test_branch_public_output_reads_each_historical_loop_state(self):
        task = self.task()
        tick = self.confirmed_step(task,
            source='async def run(ctx, inputs):\n    return ctx.result(data={"count": inputs["count"] + 1})\n',
            bindings={"count": {"ref": {"source": "loop", "node_id": "repeat",
                                         "field": "state", "pointer": "/count"}}})
        after = self.confirmed_step(task, bindings={"values": {"ref": {
            "source": "branch", "node_id": "pick", "output": "value", "pointer": ""}}})
        choice = {"id": "pick", "kind": "if", "condition": {
            "op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(node_id="then"), "else": sequence(node_id="else"),
            "outputs": {"value": {"then": {"ref": {"source": "loop", "node_id": "repeat",
                "field": "state", "pointer": "/count"}}, "else": {"literal": None}}}}
        self.save_flow(task, sequence({"id": "repeat", "kind": "loop", "mode": "while",
            "max_iterations": 3, "state_initial": {"count": {"literal": 0}},
            "state_update": {"count": {"ref": {"source": "step", "step_id": tick["step_id"],
                                               "pointer": "/count"}}},
            "condition": {"op": "lt", "left": {"ref": {"source": "loop", "node_id": "repeat",
                                                      "field": "state", "pointer": "/count"}},
                          "right": {"literal": 2}},
            "body": sequence(choice, action(tick), node_id="body")}, action(after)))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(self.app.runs.output(run["run_id"], after["step_id"]), {"values": [0, 1]})

    def test_until_condition_uses_branch_value_from_current_round(self):
        task = self.task()
        tick = self.confirmed_step(task,
            source='async def run(ctx, inputs):\n    return ctx.result(data={"count": inputs["count"] + 1})\n',
            bindings={"count": {"ref": {"source": "loop", "node_id": "repeat",
                                         "field": "state", "pointer": "/count"}}})
        branch = {"id": "choice", "kind": "if", "condition": {
            "op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(node_id="then"), "else": sequence(node_id="else"),
            "outputs": {"value": {"then": {"ref": {"source": "loop", "node_id": "repeat",
                "field": "state", "pointer": "/count"}}, "else": {"literal": None}}}}
        self.save_flow(task, sequence({"id": "repeat", "kind": "loop", "mode": "until",
            "max_iterations": 3, "state_initial": {"count": {"literal": 0}},
            "state_update": {"count": {"ref": {"source": "step", "step_id": tick["step_id"],
                                               "pointer": "/count"}}},
            "condition": {"op": "eq", "left": {"ref": {"source": "branch", "node_id": "choice",
                                                      "output": "value", "pointer": ""}},
                          "right": {"literal": 1}},
            "body": sequence(branch, action(tick), node_id="body")}))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(len([item for item in run["attempts"] if item["step_id"] == tick["step_id"]]), 2)

    def test_controlled_binding_checks_tree_order_instead_of_display_position(self):
        task = self.task()
        consumer = self.confirmed_step(task)
        producer = self.confirmed_step(task, bindings={"value": {"literal": 7}})
        self.save_flow(task, sequence({
            "id": "decision", "kind": "if",
            "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(action(producer), node_id="then"),
            "else": sequence(node_id="else"),
            "outputs": {"value": {"then": {"ref": {"source": "step",
                "step_id": producer["step_id"], "pointer": "/value"}},
                "else": {"literal": 0}}},
        }, action(consumer)))
        changed = {"name": consumer["name"], "step_content": consumer["step_content"],
                   "bindings": {"value": {"ref": {"source": "branch", "node_id": "decision",
                                                   "output": "value", "pointer": ""}}}}
        saved = self.app.repo.save_step(task, changed, consumer["step_id"], consumer["content_hash"])
        self.assertEqual(saved["bindings"]["value"]["ref"]["node_id"], "decision")

    def test_next_on_final_iteration_finishes_and_until_reports_skipped_target(self):
        task = self.task()
        step = self.confirmed_step(task)
        self.save_flow(task, sequence({"id": "each", "kind": "foreach", "items": {"literal": [1]},
                                      "body": sequence(action(step), node_id="body")}))
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED")

        task = self.task()
        yes = self.confirmed_step(task)
        no = self.confirmed_step(task)
        self.save_flow(task, sequence({"id": "decision", "kind": "if",
            "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(action(yes), node_id="then"),
            "else": sequence(action(no), node_id="else")}))
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="UNTIL", target_step_id=no["step_id"])
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED")
        events = self.app.runs.events(run["run_id"])
        self.assertTrue(any(event["kind"] == "TargetNotReached" for event in events))

    def test_single_step_trial_stays_single_step_in_controlled_task(self):
        task = self.task()
        first = self.confirmed_step(task, bindings={"value": {"literal": "first"}})
        second = self.confirmed_step(task, bindings={"value": {"literal": "second"}})
        self.save_flow(task, sequence({"id": "choose", "kind": "if",
            "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(action(first), node_id="then"),
            "else": sequence(node_id="else")}, action(second)))
        trial = self.app.trial_step(second["step_id"], {"value": "trial"}, uid())
        done = self.app.coordinator.wait(trial["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual([a["step_id"] for a in done["attempts"]], [second["step_id"]])

    def test_flow_trial_stops_at_target_action_in_tree(self):
        task = self.task()
        first = self.confirmed_step(task)
        target = self.confirmed_step(task)
        later = self.confirmed_step(task)
        self.save_flow(task, sequence(action(first), {"id": "choose", "kind": "if",
            "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": sequence(action(target), node_id="then"),
            "else": sequence(node_id="else")}, action(later)))
        trial = self.app.trial_flow(target["step_id"], {}, uid())
        done = self.app.coordinator.wait(trial["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual([a["step_id"] for a in done["attempts"]], [first["step_id"], target["step_id"]])


if __name__ == "__main__":
    import unittest
    unittest.main()
