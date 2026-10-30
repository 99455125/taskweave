"""End-to-end sequence advancement through the existing task executor."""

import time
import threading
from unittest.mock import patch

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError
from taskweave.core.validation import fingerprint
from taskweave.application.service import Application


class TaskSequenceTests(CoreFixture):
    def test_trial_parallel_calls_to_same_task_have_independent_workers(self):
        self.app.close()
        self.app = Application(self.home, registry_factory="tests._parallel_plugin:build_registry")
        task = self.task()
        self.step(task, source='async def run(ctx, inputs):\n    result = await ctx.call("demo.timed", {"seconds": 0.2})\n    return ctx.result(data=result)\n', capabilities=['demo.timed'])
        nodes = [{'node_id': key, 'task_id': task, 'environment_id': None,
                  'inputs': {}, 'step_inputs': {}} for key in ('a', 'b')]
        choose = {'id': 'choose', 'kind': 'if', 'parallel': True,
                  'cases': [{'id': key + '-case', 'condition': {'op': 'eq', 'left': {'literal': True},
                             'right': {'literal': True}}, 'body': {'id': key + '-body', 'kind': 'sequence',
                             'children': [{'id': key, 'kind': 'action', 'step_id': key}]}} for key in ('a', 'b')],
                  'default': {'id': 'fallback', 'body': {'id': 'fallback-body', 'kind': 'sequence', 'children': []}}}
        saved = self.app.sequences.save('Parallel debug', nodes, {},
            flow={'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [choose]}})
        done = self._wait(self.app.sequences.trial(saved['sequence_id'], 'parallel-trial', {})['sequence_run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        children = [self.app.runs.get(node['run_id']) for node in done['nodes']]
        self.assertEqual(len(children), 2)
        self.assertTrue(all(child['mode'] == 'TRIAL' for child in children))
        step_id = self.app.repo.steps(task)[0]['step_id']
        outputs = [self.app.runs.output(child['run_id'], step_id) for child in children]
        self.assertNotEqual(outputs[0]['pid'], outputs[1]['pid'])
        self.assertLess(max(item['started'] for item in outputs), min(item['finished'] for item in outputs))

    def test_combination_trial_runs_unconfirmed_full_flow_without_formal_records(self):
        task = self.task()
        step = self.step(task, source="async def run(ctx, inputs):\n    return ctx.result(data={'value': 7})\n")
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": "each", "kind": "foreach", "items": {"literal": [1, 2]},
             "body": {"id": "body", "kind": "sequence", "children": [
                 {"id": step['step_id'], "kind": "action", "step_id": step['step_id']}]}}]}}
        self.app.repo.tasks.save_flow(task, flow, self.app.repo.tasks.definition_hash(task))
        nodes = [{"node_id": "a", "task_id": task, "environment_id": None, "inputs": {}, "step_inputs": {}}]
        saved = self.app.sequences.save("Debug draft", nodes, {"type": "object"})
        done = self._wait(self.app.dispatch('sequence.trial', {'sequence_id': saved['sequence_id'],
                                           'request_id': 'trial-combination', 'inputs': {}})['sequence_run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual(done['snapshot']['mode'], 'TRIAL')
        child = self.app.runs.get(done['nodes'][0]['run_id'])
        self.assertEqual(child['mode'], 'TRIAL')
        self.assertEqual(len(child['attempts']), 2, 'Debug must finish every loop iteration')
        self.assertFalse(any(row['mode'] == 'EXECUTION' for row in self.app.runs.list()))
        row = next(row for row in self.app.runs.list() if row['run_id'] == child['run_id'])
        self.assertEqual(row['sequence_run_id'], done['sequence_run_id'])
        with self.assertRaises(TaskError) as conflict:
            self.app.sequences.start(saved['sequence_id'], 'trial-combination', {})
        self.assertEqual(conflict.exception.code, 'COMMAND_CONFLICT')
        with self.assertRaises(TaskError) as unconfirmed:
            self.app.sequences.start(saved['sequence_id'], 'formal-combination', {})
        self.assertEqual(unconfirmed.exception.code, 'STEP_NOT_VALIDATED')

    def _task(self, name):
        task = self.app.repo.create_task(name, {
            "type": "object", "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        })["task_id"]
        step = self.step(task,
            source="async def run(ctx, inputs):\n    return ctx.result(data={'value': inputs['value']})\n",
            bindings={"value": {"ref": {"source": "task", "pointer": "/value"}}},
            input_schema={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
        )
        self.confirm(step, {"value": 7})
        return task, step["step_id"]

    def _wait(self, sequence_run_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = self.app.sequences.run_get(sequence_run_id)
            if result["status"] not in {"READY", "RUNNING"}:
                return result
            time.sleep(0.03)
        self.fail("sequence did not finish")

    def test_three_nodes_run_in_order_with_nonadjacent_output_mapping(self):
        first, first_step = self._task("First")
        second, second_step = self._task("Second")
        nodes = [
            {"node_id": "a", "task_id": first, "environment_id": None,
             "inputs": {"value": {"kind": "literal", "value": 7}}, "step_inputs": {}},
            {"node_id": "b", "task_id": second, "environment_id": None,
             "inputs": {"value": {"kind": "output", "node_id": "a", "step_id": first_step,
                                  "output": "data", "pointer": "/value"}}, "step_inputs": {}},
            {"node_id": "c", "task_id": first, "environment_id": None,
             "inputs": {"value": {"kind": "output", "node_id": "a", "step_id": first_step,
                                  "output": "data", "pointer": "/value"}}, "step_inputs": {}},
        ]
        saved = self.app.sequences.save("Chain", nodes, {"type": "object"})
        started = self.app.sequences.start(saved["sequence_id"], "request-chain", {})
        done = self._wait(started["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual([n["status"] for n in done["nodes"]], ["SUCCEEDED"] * 3)
        self.assertEqual(len({n["run_id"] for n in done["nodes"]}), 3)
        self.assertEqual(self.app.runs.output(done["nodes"][1]["run_id"], second_step)["value"], 7)
        self.assertFalse(any(key[0] == "execution" and key[1] in {n["run_id"] for n in done["nodes"]}
                             for key in self.app.coordinator.instances))
        self.assertEqual(self.app.sequences.start(saved["sequence_id"], "request-chain", {})["sequence_run_id"], started["sequence_run_id"])
        self.assertEqual(len(self.app.sequences.run_list()), 1)

    def test_controlled_child_projects_each_iteration_into_next_task(self):
        first = self.task()
        source = self.step(first, bindings={"items": {"literal": [1, 2]}})
        visit = self.step(first, bindings={"value": {"ref": {"source": "loop", "node_id": "each",
                                                              "field": "item", "pointer": ""}}})
        for step in (source, visit):
            self.app.confirm_step_manual(step["step_id"], step["content_hash"])
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": source["step_id"], "kind": "action", "step_id": source["step_id"]},
            {"id": "each", "kind": "foreach", "items": {"ref": {"source": "step",
                "step_id": source["step_id"], "pointer": "/items"}},
             "body": {"id": "body", "kind": "sequence", "children": [
                 {"id": visit["step_id"], "kind": "action", "step_id": visit["step_id"]}]}}
        ]}}
        self.app.repo.tasks.save_flow(first, flow, self.app.repo.tasks.definition_hash(first))
        self.app.repo.tasks.confirm_flow(first, self.app.repo.tasks.definition_hash(first))
        second = self.app.repo.create_task("Receiver", {"type": "object", "properties": {
            "items": {"type": "array", "items": {"type": "integer"}}}, "required": ["items"]})["task_id"]
        receive = self.step(second, bindings={"items": {"ref": {"source": "task", "pointer": "/items"}}})
        self.app.confirm_step_manual(receive["step_id"], receive["content_hash"])
        nodes = [
            {"node_id": "a", "task_id": first, "environment_id": None, "inputs": {}, "step_inputs": {}},
            {"node_id": "b", "task_id": second, "environment_id": None,
             "inputs": {"items": {"kind": "output", "node_id": "a", "step_id": visit["step_id"],
                                  "output": "data", "pointer": "", "loop_node_id": "each",
                                  "item_pointer": "/value"}}, "step_inputs": {}},
        ]
        saved = self.app.sequences.save("Controlled source", nodes, {"type": "object"})
        done = self._wait(self.app.sequences.start(saved["sequence_id"], "controlled-child", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(self.app.runs.output(done["nodes"][1]["run_id"], receive["step_id"]),
                         {"items": [1, 2]})

    def test_missing_output_blocks_without_creating_next_child(self):
        first, first_step = self._task("First")
        second, _ = self._task("Second")
        nodes = [
            {"node_id": "a", "task_id": first, "environment_id": None,
             "inputs": {"value": {"kind": "literal", "value": 1}}, "step_inputs": {}},
            {"node_id": "b", "task_id": second, "environment_id": None,
             "inputs": {"value": {"kind": "output", "node_id": "a", "step_id": first_step,
                                  "output": "data", "pointer": "/absent"}}, "step_inputs": {}},
        ]
        saved = self.app.sequences.save("Bad mapping", nodes, {"type": "object"})
        done = self._wait(self.app.sequences.start(saved["sequence_id"], "request-bad", {})["sequence_run_id"])
        self.assertEqual(done["status"], "BLOCKED")
        self.assertIsNone(done["nodes"][1]["run_id"])
        self.assertEqual(done["nodes"][0]["status"], "SUCCEEDED")

    def test_failed_child_association_rolls_back_child_run(self):
        task, _ = self._task("Atomic")
        nodes = [{"node_id": "a", "task_id": task, "environment_id": None,
                  "inputs": {"value": {"kind": "literal", "value": 2}}, "step_inputs": {}}]
        saved = self.app.sequences.save("Atomic", nodes, {"type": "object"})
        sequence_run = self.app.sequences.repository.create_run(saved["sequence_id"], "atomic-request", {},
                                                                 {"a": self.app.repo.definition_hash(task)},
                                                                 {"a": fingerprint(self.app.repo.environment(None))},
                                                                 self.app.registry.versions)
        before = len(self.app.repo.list_runs())
        with patch.object(self.app.sequences.repository, "attach_child", side_effect=TaskError("INJECTED")) as attach:
            with self.assertRaises(TaskError):
                self.app.sequence_driver._create_child(sequence_run, nodes[0], {"value": 2}, {})
            attach.assert_called_once()
        self.assertEqual(len(self.app.repo.list_runs()), before)
        self.assertIsNone(self.app.sequences.run_get(sequence_run["sequence_run_id"])["nodes"][0]["run_id"])

    def test_reopen_starts_associated_ready_child_without_creating_another(self):
        task, _ = self._task("Resume")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {"value": {"kind": "literal", "value": 4}}, "step_inputs": {}}
        saved = self.app.sequences.save("Resume", [node], {"type": "object"})
        run = self.app.sequences.repository.create_run(saved["sequence_id"], "resume-request", {},
            {"a": self.app.repo.definition_hash(task)},
            {"a": fingerprint(self.app.repo.environment(None))}, self.app.registry.versions)
        self.app.sequence_driver._create_child(run, node, {"value": 4}, {})
        run_id = self.app.sequences.run_get(run["sequence_run_id"])["nodes"][0]["run_id"]
        self.app.close()
        self.app = Application(self.home, registry_factory="taskweave.plugins.demo:build_registry")
        done = self._wait(run["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(done["nodes"][0]["run_id"], run_id)

    def test_plugin_version_drift_blocks_child_before_creation(self):
        task, _ = self._task("Plugin drift")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {"value": {"kind": "literal", "value": 9}}, "step_inputs": {}}
        saved = self.app.sequences.save("Plugin drift", [node], {"type": "object"})
        run = self.app.sequences.repository.create_run(saved["sequence_id"], "plugin-request", {},
            {"a": self.app.repo.definition_hash(task)},
            {"a": fingerprint(self.app.repo.environment(None))},
            self.app.registry.versions)
        self.app.registry.versions["changed"] = "99.0"
        with self.assertRaises(TaskError) as error:
            self.app.sequence_driver._create_child(run, node, {"value": 9}, {})
        self.assertEqual(error.exception.code, "PLUGIN_VERSION_MISMATCH")
        self.assertIsNone(self.app.sequences.run_get(run["sequence_run_id"])["nodes"][0]["run_id"])

    def test_missing_task_input_waits_and_can_resume_same_child(self):
        task, _ = self._task("Input wait")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        saved = self.app.sequences.save("Input wait", [node], {"type": "object"})
        run = self.app.sequences.start(saved["sequence_id"], "input-request", {})
        done = self._wait(run["sequence_run_id"])
        self.assertEqual(done["status"], "WAITING_INPUT", done)
        child_id = done["nodes"][0]["run_id"]
        waiting = self.app.runs.request(child_id)["waiting_input"]
        self.app.sequences.run_inputs(run["sequence_run_id"], "input-command", {"value": 3},
                                      expected_input_id=waiting["id"])
        resumed = self._wait(run["sequence_run_id"])
        self.assertEqual(resumed["status"], "SUCCEEDED", resumed)
        self.assertEqual(resumed["nodes"][0]["run_id"], child_id)

    def test_start_replay_survives_definition_deletion(self):
        task, _ = self._task("Replay")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {"value": {"kind": "literal", "value": 2}}, "step_inputs": {}}
        saved = self.app.sequences.save("Replay", [node], {"type": "object"})
        started = self.app.sequences.start(saved["sequence_id"], "replay-after-delete", {})
        self._wait(started["sequence_run_id"])
        self.app.sequences.delete(saved["sequence_id"], saved["revision"])
        replay = self.app.sequences.start(saved["sequence_id"], "replay-after-delete", {})
        self.assertEqual(replay["sequence_run_id"], started["sequence_run_id"])

    def test_invalid_later_literal_rejected_before_first_child(self):
        task, _ = self._task("Preflight")
        first = {"node_id": "a", "task_id": task, "environment_id": None,
                 "inputs": {"value": {"kind": "literal", "value": 2}}, "step_inputs": {}}
        second = {"node_id": "b", "task_id": task, "environment_id": None,
                  "inputs": {"value": {"kind": "literal", "value": "invalid"}}, "step_inputs": {}}
        before = len(self.app.repo.list_runs())
        with self.assertRaises(TaskError) as error:
            self.app.sequences.save("Invalid later", [first, second], {"type": "object"})
        self.assertEqual(error.exception.code, "SCHEMA_MISMATCH")
        self.assertEqual(len(self.app.repo.list_runs()), before)

    def test_durable_input_command_resumes_after_reopen(self):
        task, _ = self._task("Durable input")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        saved = self.app.sequences.save("Durable input", [node], {"type": "object"})
        started = self.app.sequences.start(saved["sequence_id"], "durable-input", {})
        waiting = self._wait(started["sequence_run_id"])
        child_id = waiting["nodes"][0]["run_id"]
        input_id = self.app.runs.request(child_id)["waiting_input"]["id"]
        self.app.sequences.repository.command(started["sequence_run_id"], "durable-command", "inputs",
            {"inputs": {"value": 6}, "step_inputs": None, "expected_input_id": input_id})
        self.app.close()
        self.app = Application(self.home, registry_factory="taskweave.plugins.demo:build_registry")
        done = self._wait(started["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(done["nodes"][0]["run_id"], child_id)

    def test_pause_during_lint_prevents_child_creation(self):
        task, _ = self._task("Pause race")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {"value": {"kind": "literal", "value": 2}}, "step_inputs": {}}
        saved = self.app.sequences.save("Pause race", [node], {"type": "object"})
        run = self.app.sequences.repository.create_run(saved["sequence_id"], "pause-race", {},
            {"a": self.app.repo.definition_hash(task)},
            {"a": fingerprint(self.app.repo.environment(None))}, self.app.registry.versions)
        entered, release = threading.Event(), threading.Event()
        def slow_lint(_node):
            entered.set()
            release.wait(5)
        with patch.object(self.app.sequence_driver, "_lint_child", side_effect=slow_lint):
            self.app.sequence_driver.wake(run["sequence_run_id"])
            self.assertTrue(entered.wait(3))
            self.app.dispatch("sequence.pause", {"sequence_run_id": run["sequence_run_id"],
                                                 "command_id": "pause-race-command"})
            release.set()
            self.app.sequence_driver.threads[run["sequence_run_id"]].join(3)
        state = self.app.sequences.run_get(run["sequence_run_id"])
        self.assertEqual(state["status"], "PAUSED")
        self.assertIsNone(state["nodes"][0]["run_id"])

    def test_rejected_input_command_can_be_corrected(self):
        task, _ = self._task("Correct input")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        saved = self.app.sequences.save("Correct input", [node], {"type": "object"})
        started = self.app.sequences.start(saved["sequence_id"], "correct-input", {})
        waiting = self._wait(started["sequence_run_id"])
        input_id = self.app.runs.request(waiting["nodes"][0]["run_id"])["waiting_input"]["id"]
        self.app.dispatch("sequence.run.inputs", {"sequence_run_id": started["sequence_run_id"],
            "command_id": "wrong-input", "inputs": {"value": "wrong"}, "expected_input_id": input_id})
        rejected = self._wait(started["sequence_run_id"])
        self.assertEqual(rejected["status"], "WAITING_INPUT", rejected)
        self.assertEqual(rejected["control_command"]["phase"], "failed")
        with self.assertRaises(TaskError):
            self.app.dispatch("sequence.run.inputs", {"sequence_run_id": started["sequence_run_id"],
                "command_id": "wrong-input", "inputs": {"value": "wrong"}, "expected_input_id": input_id})
        self.app.dispatch("sequence.run.inputs", {"sequence_run_id": started["sequence_run_id"],
            "command_id": "fixed-input", "inputs": {"value": 5}, "expected_input_id": input_id})
        self.assertEqual(self._wait(started["sequence_run_id"])["status"], "SUCCEEDED")

    def test_pause_before_first_child_can_continue(self):
        task, _ = self._task("Early pause")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {"value": {"kind": "literal", "value": 8}}, "step_inputs": {}}
        saved = self.app.sequences.save("Early pause", [node], {"type": "object"})
        run = self.app.sequences.repository.create_run(saved["sequence_id"], "early-pause", {},
            {"a": self.app.repo.definition_hash(task)},
            {"a": fingerprint(self.app.repo.environment(None))}, self.app.registry.versions)
        self.app.dispatch("sequence.pause", {"sequence_run_id": run["sequence_run_id"],
                                             "command_id": "early-pause-command"})
        self.app.dispatch("sequence.continue", {"sequence_run_id": run["sequence_run_id"],
                                                "command_id": "early-continue-command"})
        self.assertEqual(self._wait(run["sequence_run_id"])["status"], "SUCCEEDED")

    def test_pause_with_pending_inputs_resumes_same_command(self):
        task, _ = self._task("Pending pause")
        node = {"node_id": "a", "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {}}
        saved = self.app.sequences.save("Pending pause", [node], {"type": "object"})
        started = self.app.sequences.start(saved["sequence_id"], "pending-pause", {})
        waiting = self._wait(started["sequence_run_id"])
        child_id = waiting["nodes"][0]["run_id"]
        input_id = self.app.runs.request(child_id)["waiting_input"]["id"]
        self.app.sequences.repository.command(started["sequence_run_id"], "pending-input-command", "inputs",
            {"inputs": {"value": 9}, "step_inputs": None, "expected_input_id": input_id})
        self.app.dispatch("sequence.pause", {"sequence_run_id": started["sequence_run_id"],
                                             "command_id": "pause-pending-command"})
        self.app.dispatch("sequence.continue", {"sequence_run_id": started["sequence_run_id"],
                                                "command_id": "continue-pending-command"})
        done = self._wait(started["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(done["nodes"][0]["run_id"], child_id)


if __name__ == "__main__":
    import unittest
    unittest.main()
