"""Conditional groups freeze selection and advance independent execution paths."""
from copy import deepcopy
import unittest
import json

from taskweave.core.task_flow import validate_flow
from taskweave.core.flow_machine import next_action, advance_after_action
from taskweave.core.validation import TaskError
from tests.test_flow_machine import sequence, action, literal


def group(parallel=False, matches=(True, True)):
    return {"id": "choose", "kind": "if", "parallel": parallel,
            "cases": [{"id": name, "condition": {"op": "eq", "left": literal(match), "right": literal(True)},
                       "body": sequence(action(name), node_id=name + "_body")}
                      for name, match in zip(("a", "b"), matches)],
            "default": {"id": "fallback", "body": sequence(action("fallback"), node_id="fallback_body")}}


def definition(node):
    return {"version": 2, "root": sequence(node, action("join"))}


class ParallelFlowTests(unittest.TestCase):
    def test_explicit_cases_validate_and_parallel_requires_real_boolean(self):
        flow = definition(group())
        steps = [{"step_id": name} for name in ("a", "b", "fallback", "join")]
        validate_flow(flow, steps)
        for invalid in (1, "true", None, []):
            flow["root"]["children"][0]["parallel"] = invalid
            with self.assertRaises(TaskError):
                validate_flow(flow, steps)

    def test_first_match_and_default(self):
        for matches, expected in (((True, True), "a"), ((False, True), "b"), ((False, False), "fallback")):
            with self.subTest(matches=matches):
                result = next_action(definition(group(matches=matches)), None, lambda *_: None)
                self.assertEqual([a["step_id"] for a in result["actions"]], [expected])

    def test_all_matches_frozen_and_join_waits_for_every_path(self):
        flow = definition(group(True))
        first = next_action(flow, None, lambda *_: None)
        self.assertEqual([a["step_id"] for a in first["actions"]], ["a", "b"])
        frozen = deepcopy(first["cursor"])
        flow["root"]["children"][0]["cases"][1]["condition"]["left"] = literal(False)
        self.assertEqual(next_action(flow, frozen, lambda *_: self.fail("re-evaluated"))["actions"], first["actions"])
        second = advance_after_action(flow, frozen, "b-attempt", execution_path=first["actions"][1]["execution_path"])
        result = next_action(flow, second["cursor"], lambda *_: None)
        self.assertEqual([a["step_id"] for a in result["actions"]], ["a"])
        third = advance_after_action(flow, result["cursor"], "a-attempt", execution_path=first["actions"][0]["execution_path"])
        result = next_action(flow, third["cursor"], lambda *_: None)
        self.assertEqual([a["step_id"] for a in result["actions"]], ["join"])

    def test_parallel_public_output_preserves_branch_identity(self):
        from taskweave.core.flow_values import aggregate_branch_output
        node = group(True)
        node["outputs"] = {"value": {"a": literal(0), "b": literal(False), "fallback": literal(None)}}
        flow = definition(node)
        cursor = None
        visits = []
        for _ in range(5):
            result = next_action(flow, cursor, lambda *_: None)
            visits.extend(result["instances"])
            cursor = result["cursor"]
            if result["action"]["step_id"] == "join":
                break
            for pending in result["actions"]:
                result = advance_after_action(flow, cursor, pending["step_id"], execution_path=pending["execution_path"])
                cursor = result["cursor"]
                visits.extend(result["instances"])
        value = aggregate_branch_output(flow, visits, "choose", "value", lambda binding, *_: binding["literal"])
        self.assertEqual(value, {"a": 0, "b": False})
        self.assertEqual(list(value), ["a", "b"])

    def test_each_condition_reads_the_same_frozen_operand_value(self):
        node = group(True)
        operand = {"ref": {"source": "task", "pointer": "/flag"}}
        for case in node["cases"]:
            case["condition"]["left"] = operand
        reads = []
        def read(binding, cursor):
            reads.append(binding)
            return len(reads) == 1
        result = next_action(definition(node), None, read)
        self.assertEqual([a["step_id"] for a in result["actions"]], ["a", "b"])
        self.assertEqual(len(reads), 1)

    def test_invalid_branch_id_and_sibling_output_reference_are_rejected(self):
        flow = definition(group(True))
        steps = [{"step_id": name} for name in ("a", "b", "fallback", "join")]
        flow["root"]["children"][0]["default"]["id"] = "a"
        with self.assertRaises(TaskError):
            validate_flow(flow, steps)
        flow = definition(group(True))
        steps[1]["bindings"] = {"sibling": {"ref": {"source": "step", "step_id": "a", "pointer": ""}}}
        with self.assertRaises(TaskError) as error:
            validate_flow(flow, steps)
        self.assertEqual(error.exception.code, "FLOW_REFERENCE_INVALID")

    def test_many_actionless_parallel_paths_yield_bounded_batches(self):
        from taskweave.core.flow_machine import CONTROL_BATCH_SIZE
        cases = [{"id": str(i), "condition": {"op": "eq", "left": literal(True), "right": literal(True)},
                  "body": sequence({"id": "loop" + str(i), "kind": "foreach", "items": literal(list(range(100))),
                                    "body": sequence(node_id="empty" + str(i))}, node_id="body" + str(i))} for i in range(4)]
        node = {"id": "choose", "kind": "if", "parallel": True, "cases": cases,
                "default": {"id": "fallback", "body": sequence(node_id="fallback")}}
        result = next_action(definition(node), None, lambda *_: None)
        self.assertLessEqual(len(result["instances"]), CONTROL_BATCH_SIZE + 8)


from tests import test_flow_execution as execution_helpers
from tests._core_fixture import CoreFixture
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid


class ParallelFixture(CoreFixture):
    confirmed_step = execution_helpers.FlowExecutionTests.confirmed_step
    save_flow = execution_helpers.FlowExecutionTests.save_flow

    def setUp(self):
        super().setUp()
        self.app.close()
        self.app = Application(self.home, registry_factory="tests._parallel_plugin:build_registry")
    def install_group(self, task, branches, join=None, parallel=True):
        node = {"id": "choose", "kind": "if", "parallel": parallel,
                "cases": [{"id": name, "condition": {"op": "eq", "left": literal(True), "right": literal(True)},
                           "body": sequence(*[action(s["step_id"]) for s in steps], node_id=name + "_body")}
                          for name, steps in branches],
                "default": {"id": "fallback", "body": sequence(node_id="fallback_body")}}
        self.save_flow(task, sequence(node, *([action(join["step_id"])] if join else [])))



class ParallelWorkerTests(ParallelFixture):
    def test_real_workers_overlap_in_one_run_and_join_after_both(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    value = await ctx.call("demo.timed", inputs)\n    return ctx.result(data=value)\n'
        a = self.confirmed_step(task, source=source, capabilities=["demo.timed"], bindings={"seconds": literal(0.7)})
        b = self.confirmed_step(task, source=source, capabilities=["demo.timed"], bindings={"seconds": literal(0.7)})
        join = self.confirmed_step(task, source=source, capabilities=["demo.timed"])
        self.install_group(task, [("a", [a]), ("b", [b])], join)
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        av = self.app.runs.output(run["run_id"], a["step_id"])
        bv = self.app.runs.output(run["run_id"], b["step_id"])
        jv = self.app.runs.output(run["run_id"], join["step_id"])
        self.assertNotEqual(av["pid"], bv["pid"])
        self.assertLess(max(av["started"], bv["started"]), min(av["finished"], bv["finished"]))
        self.assertGreaterEqual(jv["started"], max(av["finished"], bv["finished"]))
        self.assertEqual({a["run_id"] for a in run["attempts"]}, {run["run_id"]})

    def test_failed_path_does_not_stop_independent_sibling_or_run_join(self):
        task = self.task()
        a = self.confirmed_step(task, source='async def run(ctx, inputs):\n    raise ValueError("failed branch")\n')
        b = self.confirmed_step(task, source='async def run(ctx, inputs):\n    value = await ctx.call("demo.timed", {"seconds": 0.4})\n    return ctx.result(data=value)\n', capabilities=["demo.timed"])
        b2 = self.confirmed_step(task)
        join = self.confirmed_step(task)
        self.install_group(task, [("a", [a]), ("b", [b, b2])], join)
        run = self.run_task(task)
        self.assertEqual(run["status"], "FAILED", run)
        self.assertEqual({a["step_id"]: a["status"] for a in run["attempts"]},
                         {a["step_id"]: "FAILED", b["step_id"]: "SUCCEEDED", b2["step_id"]: "SUCCEEDED"})
        successful_ids = {item["attempt_id"] for item in run["attempts"] if item["status"] == "SUCCEEDED"}
        failed = next(item for item in run["attempts"] if item["status"] == "FAILED")
        self.app.coordinator.start(run["run_id"], uid(), retry_execution_path=failed["execution_path"])
        retried = self.app.coordinator.wait(run["run_id"])
        self.assertEqual({item["attempt_id"] for item in retried["attempts"] if item["status"] == "SUCCEEDED"}, successful_ids)


class ParallelRecoveryTests(ParallelFixture):
    def test_two_missing_paths_receive_distinct_requests_without_replaying_success(self):
        task = self.task()
        schema = {"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"]}
        a, b = [self.confirmed_step(task, input_schema=schema) for _ in range(2)]
        self.install_group(task, [("a", [a]), ("b", [b])])
        run = self.run_task(task)
        first = json.loads(run["request_json"])["waiting_input"]
        self.app.coordinator.provide_inputs(run["run_id"], uid(), {"answer": 1}, expected_input_id=first["id"])
        self.app.coordinator.start(run["run_id"], uid())
        middle = self.app.coordinator.wait(run["run_id"])
        second = json.loads(middle["request_json"])["waiting_input"]
        self.assertNotEqual(first["execution_path"], second["execution_path"])
        self.assertEqual(len(middle["attempts"]), 1)
        with self.assertRaises(TaskError) as error:
            self.app.coordinator.provide_inputs(run["run_id"], uid(), {"answer": 2}, expected_input_id=first["id"])
        self.assertEqual(error.exception.code, "INPUT_REQUEST_STALE")
        self.app.coordinator.provide_inputs(run["run_id"], uid(), {"answer": 2}, expected_input_id=second["id"])
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len(done["attempts"]), 2)

    def test_nested_control_failure_preserves_parent_and_runs_sibling(self):
        task = self.task()
        good = self.confirmed_step(task)
        after = self.confirmed_step(task)
        bad_loop = {"id": "bad", "kind": "foreach", "items": literal("not-list"), "body": sequence(node_id="bad_body")}
        node = {"id": "outer", "kind": "if", "parallel": True,
                "cases": [{"id": "bad_path", "condition": {"op": "eq", "left": literal(True), "right": literal(True)},
                           "body": sequence(bad_loop, node_id="bad_sequence")},
                          {"id": "good_path", "condition": {"op": "eq", "left": literal(True), "right": literal(True)},
                           "body": sequence(action(good["step_id"]), node_id="good_sequence")}],
                "default": {"id": "fallback", "body": sequence(node_id="default_sequence")}}
        self.save_flow(task, sequence(node, action(after["step_id"])))
        run = self.run_task(task)
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual([a["step_id"] for a in run["attempts"]], [good["step_id"]])
        cursor = json.loads(run["flow_cursor_json"])
        self.assertEqual(cursor["frames"][0]["node_id"], "root")

    def test_missing_input_blocks_only_its_path_and_resume_preserves_sibling(self):
        task = self.task()
        a = self.confirmed_step(task, input_schema={"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"]})
        b = self.confirmed_step(task)
        b2 = self.confirmed_step(task)
        join = self.confirmed_step(task)
        self.install_group(task, [("a", [a]), ("b", [b, b2])], join)
        run = self.run_task(task)
        self.assertEqual(run["status"], "PAUSED", run)
        self.assertEqual([a["step_id"] for a in run["attempts"]], [b["step_id"], b2["step_id"]])
        waiting = json.loads(run["request_json"])["waiting_input"]
        self.assertIn("/choose/a/", waiting["execution_path"])
        self.app.coordinator.provide_inputs(run["run_id"], uid(), {"answer": 3}, expected_input_id=waiting["id"])
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len(done["attempts"]), 4)

    def test_nested_parallel_in_loop_with_capacity_one_finishes_and_keeps_context(self):
        task = self.task()
        steps = [self.confirmed_step(task, bindings={"item": {"ref": {"source": "loop", "node_id": "each", "field": "item", "pointer": ""}}}) for _ in range(3)]
        inner = group(True)
        inner["id"] = "inner"
        for case, step in zip(inner["cases"], steps):
            case["body"]["children"] = [action(step["step_id"])]
        inner["default"]["body"]["children"] = []
        outer = {"id": "outer", "kind": "if", "parallel": True,
                 "cases": [{"id": "nested", "condition": {"op": "eq", "left": literal(True), "right": literal(True)}, "body": sequence(inner, node_id="nested_body")},
                            {"id": "other", "condition": {"op": "eq", "left": literal(True), "right": literal(True)}, "body": sequence(action(steps[2]["step_id"]), node_id="other_body")}],
                 "default": {"id": "fallback", "body": sequence(node_id="outer_default")}}
        self.save_flow(task, sequence({"id": "each", "kind": "foreach", "items": literal([2, 5]), "body": sequence(outer, node_id="loop_body")}))
        self.app.coordinator.set_max_concurrency(1)
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(len(run["attempts"]), 6)
        for step in steps:
            self.assertEqual(self.app.runs.output(run["run_id"], step["step_id"]), [{"item": 2}, {"item": 5}])

    def test_successful_receipts_are_consumed_after_restart_without_reexecution(self):
        from unittest.mock import patch
        from taskweave.infrastructure.parallel_flow_runner import ParallelFlowRunner
        task = self.task()
        a = self.confirmed_step(task)
        b = self.confirmed_step(task)
        join = self.confirmed_step(task)
        self.install_group(task, [("a", [a]), ("b", [b])], join)
        with patch.object(ParallelFlowRunner, "_consume", side_effect=RuntimeError("crash before cursor commit")):
            run = self.run_task(task)
        self.assertEqual(run["status"], "INTERRUPTED")
        original = {item["attempt_id"] for item in run["attempts"]}
        self.app.close()
        self.app = Application(self.home, registry_factory="tests._parallel_plugin:build_registry")
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len(done["attempts"]), 3)
        self.assertTrue(original <= {item["attempt_id"] for item in done["attempts"]})


class ParallelOutputTests(ParallelFixture):
    def test_configured_branch_order_survives_worker_inputs_and_result_storage(self):
        task = self.task()
        join = self.confirmed_step(task,
            source='async def run(ctx, inputs):\n    return ctx.result(data={"keys": list(inputs["all"]), "all": inputs["all"]})\n',
            bindings={"all": {"ref": {"source": "branch", "node_id": "choose", "output": "value", "pointer": ""}}})
        node = group(True)
        node["cases"][0]["id"] = "z"
        node["cases"][1]["id"] = "a"
        for case in [*node["cases"], node["default"]]:
            case["body"]["children"] = []
        node["outputs"] = {"value": {"z": literal(0), "a": literal(False), "fallback": literal(None)}}
        self.save_flow(task, sequence(node, action(join["step_id"])))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        output = self.app.runs.output(run["run_id"], join["step_id"])
        self.assertEqual(output["keys"], ["z", "a"])
        self.assertEqual(list(output["all"]), ["z", "a"])

    def test_simultaneous_first_results_initialize_one_shared_task_store(self):
        for _ in range(12):
            task = self.task()
            a = self.confirmed_step(task)
            b = self.confirmed_step(task)
            self.install_group(task, [("a", [a]), ("b", [b])])
            run = self.run_task(task)
            failures = [(a["status"], a["error_summary"]) for a in run["attempts"]]
            self.assertEqual(run["status"], "SUCCEEDED", failures)

    def test_public_output_is_validated_before_join_even_if_unused(self):
        task = self.task()
        a = self.confirmed_step(task)
        b = self.confirmed_step(task)
        join = self.confirmed_step(task)
        node = group(True)
        node["cases"][0]["body"]["children"] = [action(a["step_id"])]
        node["cases"][1]["body"]["children"] = [action(b["step_id"])]
        node["default"]["body"]["children"] = []
        node["outputs"] = {"value": {"a": {"ref": {"source": "step", "step_id": a["step_id"], "pointer": "/missing"}}, "b": literal(2), "fallback": literal(None)}}
        self.save_flow(task, sequence(node, action(join["step_id"])))
        run = self.run_task(task)
        self.assertEqual(run["status"], "FAILED", run)
        self.assertEqual([item["status"] for item in run["attempts"]], ["SUCCEEDED", "SUCCEEDED"], run)
        self.assertEqual(len(run["attempts"]), 2)

    def test_parallel_output_mapping_is_consumed_by_json_pointer(self):
        task = self.task()
        a = self.confirmed_step(task, bindings={"value": literal(0)})
        b = self.confirmed_step(task, bindings={"value": literal(False)})
        join = self.confirmed_step(task, bindings={"all": {"ref": {"source": "branch", "node_id": "choose", "output": "value", "pointer": ""}}, "one": {"ref": {"source": "branch", "node_id": "choose", "output": "value", "pointer": "/a"}}})
        node = group(True)
        for case, step in zip(node["cases"], (a, b)):
            case["body"]["children"] = [action(step["step_id"])]
        node["default"]["body"]["children"] = []
        node["outputs"] = {"value": {"a": {"ref": {"source": "step", "step_id": a["step_id"], "pointer": "/value"}}, "b": {"ref": {"source": "step", "step_id": b["step_id"], "pointer": "/value"}}, "fallback": literal(None)}}
        self.save_flow(task, sequence(node, action(join["step_id"])))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        self.assertEqual(self.app.runs.output(run["run_id"], join["step_id"]), {"all": {"a": 0, "b": False}, "one": 0})


class ParallelControlFixture(ParallelFixture):
    def timed_step(self, task, seconds=0.4):
        return self.confirmed_step(task,
            source='async def run(ctx, inputs):\n    value = await ctx.call("demo.timed", inputs)\n    return ctx.result(data=value)\n',
            capabilities=["demo.timed"], bindings={"seconds": literal(seconds)})

    def wait_started(self, run_id, count=2):
        import time
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events = self.app.runs.events(run_id)
            if sum(event["kind"] == "ActionStarted" for event in events) >= count:
                return
            time.sleep(0.01)
        self.fail("workers did not start")



class ParallelControlTests(ParallelControlFixture):
    def test_pause_drains_current_actions_and_retains_independent_sessions(self):
        task = self.task()
        a, a2, b, b2 = [self.timed_step(task) for _ in range(4)]
        self.install_group(task, [("a", [a, a2]), ("b", [b, b2])])
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        self.wait_started(run["run_id"])
        self.assertIn(run["run_id"], {item["run_id"] for item in self.app.coordinator.active_instances()})
        self.app.coordinator.control(run["run_id"], uid(), "pause")
        paused = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(paused["status"], "PAUSED", paused)
        self.assertEqual(len(paused["attempts"]), 2)
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        values = [self.app.runs.output(run["run_id"], step["step_id"]) for step in (a, a2, b, b2)]
        self.assertEqual(values[0]["pid"], values[1]["pid"])
        self.assertEqual(values[2]["pid"], values[3]["pid"])
        self.assertNotEqual(values[0]["pid"], values[2]["pid"])

    def test_cancel_stops_all_paths_and_never_starts_join(self):
        task = self.task()
        a, b = [self.timed_step(task) for _ in range(2)]
        join = self.confirmed_step(task)
        self.install_group(task, [("a", [a]), ("b", [b])], join)
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        self.wait_started(run["run_id"])
        self.app.coordinator.control(run["run_id"], uid(), "cancel")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "CANCELLED", done)
        self.assertEqual(len(done["attempts"]), 2)
        self.assertFalse(self.app.coordinator._for_run(run["run_id"]).branch_workers)

    def test_unknown_worker_requires_reconciliation_and_preserves_other_branch(self):
        task = self.task()
        a, b = [self.timed_step(task, 0.7) for _ in range(2)]
        join = self.confirmed_step(task)
        self.install_group(task, [("a", [a]), ("b", [b])], join)
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        self.wait_started(run["run_id"])
        worker = self.app.coordinator._for_run(run["run_id"]).branch_workers["/root/choose/a"]
        worker.process.terminate()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED", done)
        unknown = next(a for a in done["attempts"] if a["status"] == "UNKNOWN")
        succeeded = next(a for a in done["attempts"] if a["status"] == "SUCCEEDED")
        with self.assertRaises(TaskError) as error:
            self.app.coordinator.start(run["run_id"], uid())
        self.assertEqual(error.exception.code, "RECONCILIATION_REQUIRED")
        self.app.coordinator.reconcile(unknown["attempt_id"], "not_completed", {"verified": True}, uid())
        self.app.coordinator.start(run["run_id"], uid(), retry_execution_path=unknown["execution_path"])
        recovered = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(recovered["status"], "SUCCEEDED", recovered)
        self.assertEqual(len([a for a in recovered["attempts"] if a["step_id"] == b["step_id"]]), 1)
        self.assertIn(succeeded["attempt_id"], {a["attempt_id"] for a in recovered["attempts"]})

    def test_delay_applies_inside_each_path(self):
        from datetime import datetime
        task = self.task()
        a = self.confirmed_step(task)
        a2 = self.confirmed_step(task, delay_after_previous_seconds=1)
        b = self.timed_step(task, 0.1)
        self.install_group(task, [("a", [a, a2]), ("b", [b])])
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        attempts = {item["step_id"]: item for item in run["attempts"]}
        elapsed = datetime.fromisoformat(attempts[a2["step_id"]]["started_at"]) - datetime.fromisoformat(attempts[a["step_id"]]["finished_at"])
        self.assertGreaterEqual(elapsed.total_seconds(), 0.95)


class ParallelCapacityTests(ParallelControlFixture):
    def test_two_runs_share_leaf_capacity_without_blocking_nested_dispatch(self):
        self.app.coordinator.set_max_concurrency(2)
        tasks = []
        runs = []
        for _ in range(2):
            task = self.task()
            steps = [self.timed_step(task, 0.6) for _ in range(2)]
            self.install_group(task, [("a", [steps[0]]), ("b", [steps[1]])])
            tasks.append(steps)
            runs.append(self.app.create_run(task))
        for run in runs:
            self.app.coordinator.start(run["run_id"], uid())
        values = []
        for run, steps in zip(runs, tasks):
            done = self.app.coordinator.wait(run["run_id"])
            self.assertEqual(done["status"], "SUCCEEDED", done)
            values.extend(self.app.runs.output(run["run_id"], step["step_id"]) for step in steps)
        events = sorted([(v["started"], 1) for v in values] + [(v["finished"], -1) for v in values])
        active = peak = 0
        for _, delta in events:
            active += delta
            peak = max(peak, active)
        self.assertEqual(peak, 2)

    def test_next_at_complete_parallel_frontier_reports_success(self):
        task = self.task()
        a, b = [self.timed_step(task, 0.1) for _ in range(2)]
        self.install_group(task, [("a", [a]), ("b", [b])])
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)


class ParallelAuthoringTests(ParallelFixture):
    def test_edit_append_and_delete_preserve_explicit_branch_placement(self):
        task = self.task()
        a, b = [self.confirmed_step(task) for _ in range(2)]
        self.install_group(task, [("a", [a]), ("b", [b])])
        updated = self.app.repo.save_step(task, {"name": "Edited", "step_content": a["step_content"]},
                                         a["step_id"], a["content_hash"])
        self.assertEqual(updated["name"], "Edited")
        added = self.step(task)
        self.app.repo.repositories.steps.delete_step(b["step_id"])
        flow = self.app.repo.tasks.flow(task)
        self.assertEqual(flow["root"]["children"][0]["cases"][0]["body"]["children"][0]["step_id"], a["step_id"])
        self.assertEqual(flow["root"]["children"][0]["cases"][1]["body"]["children"], [])
        self.assertEqual(flow["root"]["children"][1]["step_id"], added["step_id"])


class ParallelReviewRegressionTests(ParallelControlFixture):
    def test_nested_group_preserves_suspended_outer_session(self):
        task = self.task()
        before, inside, after = [self.timed_step(task, 0) for _ in range(3)]
        true = {"op": "eq", "left": literal(True), "right": literal(True)}
        def conditional(name, body):
            return {"id": name, "kind": "if", "parallel": True,
                    "cases": [{"id": "path", "condition": true, "body": body}],
                    "default": {"id": "default", "body": sequence(node_id=name + "_default")}}
        inner = conditional("inner", sequence(action(inside["step_id"]), node_id="inner_body"))
        outer = conditional("outer", sequence(action(before["step_id"]), inner,
                                              action(after["step_id"]), node_id="outer_body"))
        self.save_flow(task, sequence(outer))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        pids = [self.app.runs.output(run["run_id"], step["step_id"])["pid"] for step in (before, inside, after)]
        self.assertEqual(pids[0], pids[2])
        self.assertNotEqual(pids[0], pids[1])

    def test_debug_stop_does_not_mask_failed_sibling(self):
        for mode in ("NEXT", "UNTIL"):
            with self.subTest(mode=mode):
                task = self.task()
                bad = self.confirmed_step(task, source='async def run(ctx, inputs):\n    raise ValueError("branch failure")\n')
                good = self.timed_step(task, 0.2)
                self.install_group(task, [("bad", [bad]), ("good", [good])])
                run = self.app.create_run(task)
                self.app.coordinator.start(run["run_id"], uid(), mode=mode,
                                           target_step_id=good["step_id"] if mode == "UNTIL" else None)
                done = self.app.coordinator.wait(run["run_id"])
                self.assertEqual(done["status"], "FAILED", [(a["status"], a["error_code"]) for a in done["attempts"]])
                with self.assertRaises(TaskError) as error:
                    self.app.coordinator.start(run["run_id"], uid())
                self.assertEqual(error.exception.code, "EXPLICIT_RETRY_REQUIRED")

    def test_debug_stop_does_not_mask_unknown_sibling(self):
        task = self.task()
        bad, good = [self.timed_step(task, 0.5) for _ in range(2)]
        self.install_group(task, [("bad", [bad]), ("good", [good])])
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.wait_started(run["run_id"])
        worker = self.app.coordinator._for_run(run["run_id"]).branch_workers["/root/choose/bad"]
        worker.process.terminate()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED", done)


class SerialConditionalResourceTests(ParallelControlFixture):
    def _serial(self, identifier, inside, *, omitted=False):
        node = {"id": identifier, "kind": "if",
                "cases": [{"id": "selected", "condition": {"op": "eq", "left": literal(True), "right": literal(True)},
                           "body": sequence(action(inside["step_id"]), node_id=identifier + "_body")}],
                "default": {"id": "default", "body": sequence(node_id=identifier + "_default")}}
        if not omitted:
            node["parallel"] = False
        return node

    def test_serial_condition_preserves_before_inside_after_session(self):
        for omitted in (False, True):
            with self.subTest(omitted=omitted):
                task = self.task()
                before, inside, after = [self.timed_step(task, 0) for _ in range(3)]
                self.save_flow(task, sequence(action(before["step_id"]), self._serial("serial", inside, omitted=omitted),
                                              action(after["step_id"])))
                run = self.run_task(task)
                self.assertEqual(run["status"], "SUCCEEDED", run)
                pids = [self.app.runs.output(run["run_id"], step["step_id"])["pid"] for step in (before, inside, after)]
                self.assertEqual(len(set(pids)), 1, pids)

    def test_serial_inside_parallel_inherits_only_its_enclosing_branch_session(self):
        task = self.task()
        before, inside, after, peer = [self.timed_step(task, 0.1) for _ in range(4)]
        outer = group(True)
        outer["cases"][0]["body"]["children"] = [action(before["step_id"]), self._serial("serial", inside), action(after["step_id"])]
        outer["cases"][1]["body"]["children"] = [action(peer["step_id"])]
        outer["default"]["body"]["children"] = []
        self.save_flow(task, sequence(outer))
        run = self.run_task(task)
        self.assertEqual(run["status"], "SUCCEEDED", run)
        pids = [self.app.runs.output(run["run_id"], step["step_id"])["pid"] for step in (before, inside, after, peer)]
        self.assertEqual(len(set(pids[:3])), 1, pids)
        self.assertNotEqual(pids[0], pids[3])
