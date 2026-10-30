"""Structured combinations execute actual task instances, including repeats."""

import time
from unittest.mock import patch

from tests._core_fixture import CoreFixture
from taskweave.application.service import Application
from taskweave.core.validation import TaskError


def sequence(identifier, *children):
    return {"id": identifier, "kind": "sequence", "children": list(children)}


def action(identifier):
    return {"id": identifier, "kind": "action", "step_id": identifier}


class SequenceControlFlowTests(CoreFixture):
    def task_node(self, identifier, inputs=None):
        task = self.app.repo.create_task(identifier)["task_id"]
        step = self.step(task, input_schema={"type": "object", "properties": {key: {} for key in (inputs or {})}},
                         source="async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n")
        self.app.confirm_step_manual(step["step_id"], step["content_hash"])
        return {"node_id": identifier, "task_id": task, "environment_id": None,
                "inputs": {}, "step_inputs": {step["step_id"]: inputs or {}}}, step["step_id"]

    def wait_sequence(self, run_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            run = self.app.sequences.run_get(run_id)
            if run["status"] not in {"READY", "RUNNING"}:
                return run
            time.sleep(.02)
        self.fail("combination timed out")

    def test_foreach_creates_distinct_children_and_resolves_current_item(self):
        node, step_id = self.task_node("visit", {"value": {
            "kind": "loop", "node_id": "each", "field": "item", "pointer": ""}})
        flow = {"version": 2, "root": sequence("root", {
            "id": "each", "kind": "foreach", "items": {"literal": [4, 8]},
            "body": sequence("body", action("visit")), "max_items": 5})}
        saved = self.app.sequences.save("Each", [node], {"type": "object"}, flow=flow)
        self.assertEqual(self.app.sequences.get(saved["sequence_id"])["flow"], flow)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "each", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len(done["nodes"]), 2)
        self.assertEqual([n['task_id'] for n in done['nodes']], [node['task_id']] * 2)
        self.assertEqual(len({n["run_id"] for n in done["nodes"]}), 2)
        self.assertEqual([self.app.runs.output(n["run_id"], step_id)["value"] for n in done["nodes"]], [4, 8])

    def test_while_zero_iterations_does_not_create_child(self):
        node, _ = self.task_node("never")
        flow = {"version": 2, "root": sequence("root", {
            "id": "repeat", "kind": "loop", "mode": "while",
            "condition": {"op": "eq", "left": {"literal": False}, "right": {"literal": True}},
            "body": sequence("body", action("never")), "max_iterations": 3})}
        saved = self.app.sequences.save("Zero", [node], {"type": "object"}, flow=flow)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "zero", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(done["nodes"], [])

    def test_until_uses_current_round_output_and_aggregates_for_following_task(self):
        visit, step_id = self.task_node("visit", {"value": {
            "kind": "loop", "node_id": "repeat", "field": "index", "pointer": ""}})
        collect, collect_step = self.task_node("collect", {"values": {
            "kind": "output", "node_id": "visit", "step_id": step_id,
            "output": "data", "pointer": "", "item_pointer": "/value", "loop_node_id": "repeat"}})
        flow = {"version": 2, "root": sequence("root", {
            "id": "repeat", "kind": "loop", "mode": "until", "max_iterations": 3,
            "condition": {"op": "gte", "left": {"ref": {
                "source": "node", "node_id": "visit", "step_id": step_id,
                "output": "data", "pointer": "/value"}}, "right": {"literal": 1}},
            "body": sequence("body", action("visit"))}, action("collect"))}
        saved = self.app.sequences.save("Repeat", [visit, collect], {"type": "object"}, flow=flow)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "repeat", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len(done["nodes"]), 3)
        self.assertEqual(self.app.runs.output(done["nodes"][-1]["run_id"], collect_step), {"values": [0, 1]})

    def test_reopen_after_child_success_consumes_once_and_continues_next_round(self):
        node, step_id = self.task_node('visit', {'value': {
            'kind': 'loop', 'node_id': 'each', 'field': 'item', 'pointer': ''}})
        flow = {'version': 2, 'root': sequence('root', {'id': 'each', 'kind': 'foreach',
            'items': {'literal': [4, 8]}, 'body': sequence('body', action('visit'))})}
        saved = self.app.sequences.save('Recover', [node], {'type': 'object'}, flow=flow)
        run = self.app.sequences.prepare_start(saved['sequence_id'], 'recover-loop', {})
        transition, _ = self.app.sequence_driver._decide(run)
        pending = transition['actions'][0]
        self.app.sequences.repository.ensure_action(run['sequence_run_id'], pending, node['task_id'])
        run = self.app.sequences.run_get(run['sequence_run_id'])
        inputs, step_inputs = self.app.sequence_driver._resolve(run, node, transition['cursor'])
        child_id = self.app.sequence_driver._create_child(run, {**node, 'execution_path': pending['execution_path']}, inputs, step_inputs)
        self.app.runs._managed_start(child_id, 'first-round')
        self.assertEqual(self.app.coordinator.wait(child_id)['status'], 'SUCCEEDED')
        self.app.close()
        self.app = Application(self.home, registry_factory='taskweave.plugins.demo:build_registry')
        done = self.wait_sequence(run['sequence_run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual(len(done['nodes']), 2)
        self.assertEqual(done['nodes'][0]['run_id'], child_id)
        self.assertEqual([self.app.runs.output(n['run_id'], step_id)['value'] for n in done['nodes']], [4, 8])

    def test_retry_second_round_keeps_first_round_and_reuses_second_child(self):
        task = self.task()
        step = self.step(task, input_schema={'type': 'object', 'properties': {'value': {'type': 'integer'}}},
            source="async def run(ctx, inputs):\n    if inputs['value'] == 1:\n        raise ValueError('second round')\n    return ctx.result(data=inputs)\n")
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        node = {'node_id': 'visit', 'task_id': task, 'environment_id': None, 'inputs': {},
                'step_inputs': {step['step_id']: {'value': {'kind': 'loop', 'node_id': 'each', 'field': 'item', 'pointer': ''}}}}
        flow = {'version': 2, 'root': sequence('root', {'id': 'each', 'kind': 'foreach',
                'items': {'literal': [0, 1]}, 'body': sequence('body', action('visit'))})}
        saved = self.app.sequences.save('Retry round', [node], {'type': 'object'}, flow=flow)
        run = self.wait_sequence(self.app.sequences.start(saved['sequence_id'], 'retry-round', {})['sequence_run_id'])
        self.assertEqual(run['status'], 'BLOCKED')
        first, second = run['nodes']
        prior = self.app.runs.get(first['run_id'])['attempts'][0]['attempt_id']
        self.app.sequences.run_retry(run['sequence_run_id'], 'retry-second', retry_step_id=step['step_id'],
                                    execution_path=second['execution_path'])
        retried = self.wait_sequence(run['sequence_run_id'])
        self.assertEqual(retried['status'], 'BLOCKED', 'The same business error remains after an explicit retry')
        self.assertEqual([member['run_id'] for member in retried['nodes']], [first['run_id'], second['run_id']])
        self.assertEqual([a['attempt_id'] for a in self.app.runs.get(first['run_id'])['attempts']], [prior])
        self.assertEqual(len(self.app.runs.get(second['run_id'])['attempts']), 2)

    def test_stopped_combination_rejects_new_exact_path_input_command(self):
        for operation in ('cancel', 'pause'):
            with self.subTest(operation=operation):
                task = self.app.repo.create_task('Wait', {'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value']})['task_id']
                step = self.step(task)
                self.app.confirm_step_manual(step['step_id'], step['content_hash'])
                node = {'node_id': 'wait', 'task_id': task, 'environment_id': None, 'inputs': {}, 'step_inputs': {}}
                saved = self.app.sequences.save('Stopped', [node], {'type': 'object'})
                run = self.wait_sequence(self.app.sequences.start(saved['sequence_id'], 'stopped-' + operation, {})['sequence_run_id'])
                member = run['nodes'][0]
                waiting = self.app.runs.request(member['run_id'])['waiting_input']
                if operation == 'cancel':
                    self.app.sequences.cancel(run['sequence_run_id'], 'cancel-input')
                else:
                    self.app.sequences.repository.set_run_status(run['sequence_run_id'], 'PAUSED', 'wait', stop_intent='pause', execution_path=member['execution_path'])
                with self.assertRaises(TaskError):
                    self.app.sequences.run_inputs(run['sequence_run_id'], 'stale-' + operation, {'value': 1},
                        expected_input_id=waiting['id'], execution_path=member['execution_path'])
                current = self.app.sequences.run_get(run['sequence_run_id'])
                self.assertEqual(current['stop_intent'], operation)
                self.assertEqual(current['commands'], [])

    def test_cancelled_failed_child_rejects_new_retry(self):
        task = self.task()
        step = self.step(task, source="async def run(ctx, inputs):\n    raise ValueError('failed')\n")
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        node = {'node_id': 'failed', 'task_id': task, 'environment_id': None, 'inputs': {}, 'step_inputs': {}}
        saved = self.app.sequences.save('Failed', [node], {'type': 'object'})
        run = self.wait_sequence(self.app.sequences.start(saved['sequence_id'], 'failed', {})['sequence_run_id'])
        self.assertEqual(run['status'], 'BLOCKED')
        self.app.sequences.cancel(run['sequence_run_id'], 'cancel-failed')
        with self.assertRaises(TaskError):
            self.app.sequences.run_retry(run['sequence_run_id'], 'stale-retry', retry_step_id=step['step_id'],
                                        execution_path=run['nodes'][0]['execution_path'])
        self.assertEqual(self.app.sequences.run_get(run['sequence_run_id'])['status'], 'CANCELLED')

    def test_frozen_unreached_task_remains_protected_after_definition_deleted(self):
        node, _ = self.task_node('unreached')
        flow = {'version': 2, 'root': sequence('root', {'id': 'each', 'kind': 'foreach',
                'items': {'literal': 42}, 'body': sequence('body', action('unreached'))})}
        saved = self.app.sequences.save('Control error', [node], {'type': 'object'}, flow=flow)
        run = self.wait_sequence(self.app.sequences.start(saved['sequence_id'], 'control-error', {})['sequence_run_id'])
        self.assertEqual(run['status'], 'BLOCKED')
        self.assertEqual(run['nodes'], [])
        self.app.sequences.delete(saved['sequence_id'], saved['revision'])
        self.assertTrue(self.app.sequences.repository.task_is_referenced(node['task_id']))
        with self.assertRaises(TaskError):
            self.app.tasks.delete(node['task_id'])

    def _assert_child_loop_projection(self, outer_id="outer", projection_scope=None):
        task = self.app.repo.create_task('Producer', {'type': 'object', 'properties': {'base': {'type': 'integer'}}})['task_id']
        step = self.step(task, source="async def run(ctx, inputs):\n    return ctx.result(data={'value': inputs['base'] + inputs['item']})\n",
            input_schema={'type': 'object', 'properties': {'base': {'type': 'integer'}, 'item': {'type': 'integer'}}},
            bindings={'base': {'ref': {'source': 'task', 'pointer': '/base'}},
                      'item': {'ref': {'source': 'loop', 'node_id': 'inner', 'field': 'item', 'pointer': ''}}})
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        child_flow = {'version': 2, 'root': sequence('root', {'id': 'inner', 'kind': 'foreach',
                     'items': {'literal': [2, 3]}, 'body': sequence('inner-body', action(step['step_id']))})}
        self.app.repo.tasks.save_flow(task, child_flow, self.app.repo.tasks.definition_hash(task))
        self.app.repo.tasks.confirm_flow(task, self.app.repo.tasks.definition_hash(task))
        producer = {'node_id': 'producer', 'task_id': task, 'environment_id': None,
                    'inputs': {'base': {'kind': 'loop', 'node_id': outer_id, 'field': 'item', 'pointer': ''}}, 'step_inputs': {}}
        consumer, consumer_step = self.task_node('consumer', {'values': {'kind': 'output', 'node_id': 'producer',
                'step_id': step['step_id'], 'output': 'data', 'pointer': '', 'item_pointer': '/value', 'loop_node_id': 'inner', **({'projection_scope': projection_scope} if projection_scope else {})}})
        flow = {'version': 2, 'root': sequence('root', {'id': outer_id, 'kind': 'foreach', 'items': {'literal': [10, 20]},
                    'body': sequence('outer-body', action('producer'), action('consumer'))})}
        saved = self.app.sequences.save('Nested projection', [producer, consumer], {'type': 'object'}, flow=flow)
        run = self.wait_sequence(self.app.sequences.start(saved['sequence_id'], 'nested-projection', {})['sequence_run_id'])
        self.assertEqual(run['status'], 'SUCCEEDED', run)
        results = [self.app.runs.output(node['run_id'], consumer_step) for node in run['nodes'] if node['node_id'] == 'consumer']
        self.assertEqual(results, [{'values': [12, 13]}, {'values': [22, 23]}])

    def test_child_loop_projection_selects_current_outer_round_first(self):
        self._assert_child_loop_projection()

    def test_child_loop_projection_scope_distinguishes_same_control_id(self):
        self._assert_child_loop_projection(outer_id='inner', projection_scope='task')


class SequenceParallelTests(CoreFixture):
    wait_sequence = SequenceControlFlowTests.wait_sequence

    def setUp(self):
        super().setUp()
        self.app.close()
        self.app = Application(self.home, registry_factory="tests._parallel_plugin:build_registry")

    def timed_node(self, name, seconds=.5):
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    value = await ctx.call("demo.timed", inputs)\n    return ctx.result(data=value)\n',
                         input_schema={"type": "object", "properties": {"seconds": {"type": "number"}}},
                         capabilities=["demo.timed"])
        self.app.confirm_step_manual(step["step_id"], step["content_hash"])
        node = {"node_id": name, "task_id": task, "environment_id": None, "inputs": {},
                "step_inputs": {step["step_id"]: {"seconds": {"kind": "literal", "value": seconds}}}}
        return node, step["step_id"]

    def install(self, parallel):
        nodes, steps = zip(*(self.timed_node(name, .7 if name != "join" else 0) for name in ("a", "b", "join")))
        choose = {"id": "choose", "kind": "if", "parallel": parallel,
                  "cases": [{"id": name + "-case", "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
                             "body": sequence(name + "-body", action(name))} for name in ("a", "b")],
                  "default": {"id": "fallback", "body": sequence("fallback-body")}}
        saved = self.app.sequences.save("Conditional", list(nodes), {"type": "object"},
                                        flow={"version": 2, "root": sequence("root", choose, action("join"))})
        return saved, dict(zip(("a", "b", "join"), steps))

    def test_parallel_task_calls_overlap_and_join_after_all(self):
        saved, steps = self.install(True)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "parallel-tasks", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        outputs = {node["node_id"]: self.app.runs.output(node["run_id"], steps[node["node_id"]]) for node in done["nodes"]}
        a, b, join = (outputs[name] for name in ("a", "b", "join"))
        self.assertNotEqual(a["pid"], b["pid"])
        self.assertLess(max(a["started"], b["started"]), min(a["finished"], b["finished"]))
        self.assertGreaterEqual(join["started"], max(a["finished"], b["finished"]))

    def test_serial_condition_only_creates_first_matching_task(self):
        saved, _ = self.install(False)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "serial-condition", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual([node["node_id"] for node in done["nodes"]], ["a", "join"])

    def test_capacity_one_queues_parallel_calls_without_deadlock(self):
        self.app.coordinator.set_max_concurrency(1)
        saved, steps = self.install(True)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "queued-condition", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual({node["node_id"] for node in done["nodes"]}, {"a", "b", "join"})

    def test_stop_during_child_completion_keeps_stop_and_drains_other_paths(self):
        for operation, status in [('cancel', 'CANCELLED'), ('pause', 'PAUSED')]:
            with self.subTest(operation=operation):
                saved, _ = self.install(True)
                # Keep the second branch live when the first reaches its natural boundary.
                definition = self.app.sequences.get(saved['sequence_id'])
                for member in definition['nodes']:
                    if member['node_id'] == 'b':
                        next(iter(member['step_inputs'].values()))['seconds']['value'] = 1.5
                saved = self.app.sequences.save(definition['name'], definition['nodes'], definition['input_schema'],
                    sequence_id=saved['sequence_id'], expected_revision=saved['revision'], flow=definition['flow'])
                run_id = self.app.sequences.start(saved['sequence_id'], 'stop-race-' + operation, {})['sequence_run_id']
                deadline = time.monotonic() + 5
                first = None
                while time.monotonic() < deadline:
                    run = self.app.sequences.run_get(run_id)
                    running = [node for node in run['nodes'] if node['run_id'] and self.app.runs.stored(node['run_id'])['status'] == 'RUNNING']
                    if len(running) == 2:
                        first = running[0]['run_id']
                        break
                    time.sleep(.01)
                self.assertIsNotNone(first)
                control = self.app.runs._managed_control
                controlled_live_peers = []
                def finish_before_control(child_id, command, action):
                    if child_id == first:
                        end = time.monotonic() + 5
                        while self.app.runs.stored(child_id)['status'] == 'RUNNING' and time.monotonic() < end:
                            time.sleep(.01)
                    else:
                        controlled_live_peers.append(child_id)
                        self.assertEqual(self.app.runs.stored(child_id)['status'], 'RUNNING')
                    return control(child_id, command, action)
                with patch.object(self.app.runs, '_managed_control', side_effect=finish_before_control):
                    result = getattr(self.app.sequences, operation)(run_id, operation + '-race')
                self.assertEqual(result['status'], status)
                self.assertEqual(result['stop_intent'], operation)
                self.assertEqual(len(controlled_live_peers), 1)
                for child_id in controlled_live_peers:
                    self.app.coordinator.wait(child_id)
                final = self.app.sequences.run_get(run_id)
                self.assertEqual(final['stop_intent'], operation)
                self.assertFalse(any(member['node_id'] == 'join' for member in final['nodes']))

    def test_multiple_waiting_branches_require_exact_input_target(self):
        nodes = []
        for name in ("a", "b"):
            task = self.app.repo.create_task(name, {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]})["task_id"]
            step = self.step(task)
            self.app.confirm_step_manual(step["step_id"], step["content_hash"])
            nodes.append({"node_id": name, "task_id": task, "environment_id": None, "inputs": {}, "step_inputs": {}})
        choose = {"id": "choose", "kind": "if", "parallel": True,
                  "cases": [{"id": name, "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
                             "body": sequence(name + "-body", action(name))} for name in ("a", "b")],
                  "default": {"id": "fallback", "body": sequence("fallback-body")}}
        saved = self.app.sequences.save("Wait", nodes, {"type": "object"}, flow={"version": 2, "root": sequence("root", choose)})
        waiting = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "multiple-wait", {})["sequence_run_id"])
        self.assertEqual(waiting["status"], "WAITING_INPUT", waiting)
        with self.assertRaises(TaskError) as error:
            self.app.sequences.run_inputs(waiting["sequence_run_id"], "ambiguous", {"value": 1})
        self.assertEqual(error.exception.code, "SEQUENCE_INSTANCE_REQUIRED")
        first = waiting["nodes"][0]
        input_id = self.app.runs.request(first["run_id"])["waiting_input"]["id"]
        self.app.sequences.run_inputs(waiting["sequence_run_id"], "first-input", {"value": 1},
                                      expected_input_id=input_id, execution_path=first["execution_path"])
        remaining = self.wait_sequence(waiting["sequence_run_id"])
        self.assertEqual(remaining["status"], "WAITING_INPUT", remaining)
        self.assertEqual(remaining["nodes"][0]["status"], "SUCCEEDED")
        self.assertEqual(remaining["nodes"][1]["status"], "WAITING_INPUT")


class SequenceLiteralPayloadTests(CoreFixture):
    task_node = SequenceControlFlowTests.task_node
    wait_sequence = SequenceControlFlowTests.wait_sequence

    def payloads(self):
        return [{"ref": {"source": "customer", "id": 42}},
                {"ref": {"source": "node", "node_id": "customer", "step_id": "value", "output": "data"}},
                {"literal": {"ref": {"source": "untrusted-data"}}, "items": [{"ref": []}]}]

    def make_flow(self, values):
        return {"version": 2, "root": sequence("root", {"id": "each", "kind": "foreach",
            "items": {"literal": values}, "body": sequence("body", action("visit"))})}

    def test_literal_payloads_validate_and_translate_without_interpreting_ref_keys(self):
        from copy import deepcopy
        from taskweave.core.sequence_flow import machine_flow, validate_sequence_flow
        values = self.payloads()
        original = deepcopy(values)
        node = {"node_id": "visit", "task_id": "task", "environment_id": None, "inputs": {}, "step_inputs": {}}
        flow = self.make_flow(values)
        validate_sequence_flow(flow, [node])
        self.assertEqual(machine_flow(flow), flow)
        for value in values:
            self.assertEqual(machine_flow({"literal": value}), {"literal": value})
        self.assertEqual(values, original)

    def test_foreach_save_start_and_children_preserve_ref_shaped_business_values(self):
        values = self.payloads()
        node, step_id = self.task_node("visit", {"value": {"kind": "loop", "node_id": "each", "field": "item", "pointer": ""}})
        flow = self.make_flow(values)
        saved = self.app.sequences.save("Literal JSON", [node], {"type": "object"}, flow=flow)
        self.assertEqual(self.app.sequences.get(saved["sequence_id"])["flow"], flow)
        done = self.wait_sequence(self.app.sequences.start(saved["sequence_id"], "literal-payloads", {})["sequence_run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual([self.app.runs.output(item["run_id"], step_id)["value"] for item in done["nodes"]], values)
        self.assertEqual(done["snapshot"]["flow"], flow)

    def test_actual_malformed_refs_still_reject_at_operand_positions(self):
        from taskweave.core.sequence_flow import validate_sequence_flow
        node = {"node_id": "visit", "task_id": "task", "environment_id": None, "inputs": {}, "step_inputs": {}}
        for ref in ({"source": "customer"}, {"source": "node", "node_id": "visit"}):
            with self.subTest(ref=ref):
                flow = self.make_flow([])
                flow["root"]["children"][0]["items"] = {"ref": ref}
                with self.assertRaises(TaskError) as error:
                    validate_sequence_flow(flow, [node])
                self.assertEqual(error.exception.code, "SEQUENCE_SOURCE_INVALID")

    def test_named_literal_output_still_translates_and_preflights_genuine_refs(self):
        from copy import deepcopy
        from taskweave.core.sequence_flow import machine_flow
        source, source_step = self.task_node("source")
        visit, _ = self.task_node("visit")
        group = {"id": "choice", "kind": "if", "parallel": False,
                 "cases": [{"id": "literal", "condition": {"op": "eq", "left": {"literal": self.payloads()[0]},
                            "right": {"literal": self.payloads()[0]}}, "body": sequence("yes", action("visit"))}],
                 "default": {"id": "ref", "body": sequence("no")},
                 "outputs": {"literal": {"literal": {"ref": {"source": "node", "node_id": "source", "step_id": source_step,
                            "output": "data", "pointer": ""}}, "ref": {"literal": self.payloads()[1]}}}}
        flow = {"version": 2, "root": sequence("root", action("source"), group)}
        translated = machine_flow(flow)["root"]["children"][1]
        self.assertEqual(translated["outputs"]["literal"]["literal"]["ref"]["step_id"], "source")
        self.assertEqual(translated["outputs"]["literal"]["ref"], {"literal": self.payloads()[1]})
        self.app.sequences.save("Literal names", [source, visit], {"type": "object"}, flow=flow)
        invalid = deepcopy(flow)
        invalid["root"]["children"][1]["outputs"]["literal"]["literal"]["ref"]["step_id"] = "missing-child-step"
        with self.assertRaises(TaskError) as error:
            self.app.sequences.save("Invalid genuine output", [source, visit], {"type": "object"}, flow=invalid)
        self.assertEqual(error.exception.code, "SEQUENCE_SOURCE_INVALID")


class SequenceStopErrorTests(CoreFixture):
    def setUp(self):
        super().setUp()
        self.app.close()
        self.app = Application(self.home, registry_factory="tests._parallel_plugin:build_registry")
    timed_node = SequenceParallelTests.timed_node
    install = SequenceParallelTests.install

    def test_stop_propagates_unrelated_errors_and_unverified_state_races(self):
        for code in ("RUN_STATE_INVALID", "CONTROL_FAILURE"):
            with self.subTest(code=code):
                saved, _ = self.install(True)
                run_id = self.app.sequences.start(saved["sequence_id"], "stop-error-" + code, {})["sequence_run_id"]
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    children = [node["run_id"] for node in self.app.sequences.run_get(run_id)["nodes"]
                                if node["run_id"] and self.app.runs.stored(node["run_id"])["status"] == "RUNNING"]
                    if len(children) == 2:
                        break
                    time.sleep(.01)
                self.assertEqual(len(children), 2)
                with patch.object(self.app.runs, "_managed_control", side_effect=TaskError(code)):
                    with self.assertRaises(TaskError) as error:
                        self.app.sequences.cancel(run_id, "stop-error-" + code)
                self.assertEqual(error.exception.code, code)
                self.assertEqual(self.app.sequences.run_get(run_id)["stop_intent"], "cancel")
                for child_id in children:
                    self.app.coordinator.wait(child_id)

    def _unknown_child_with_live_peer(self):
        saved, _ = self.install(True)
        definition = self.app.sequences.get(saved['sequence_id'])
        for node in definition['nodes']:
            if node['node_id'] in {'a', 'b'}:
                next(iter(node['step_inputs'].values()))['seconds']['value'] = 2
        saved = self.app.sequences.save(definition['name'], definition['nodes'], definition['input_schema'],
            sequence_id=saved['sequence_id'], expected_revision=saved['revision'], flow=definition['flow'])
        run_id = self.app.sequences.start(saved['sequence_id'], 'unknown-child-' + saved['sequence_id'], {})['sequence_run_id']
        deadline = time.monotonic() + 5
        started = []
        while time.monotonic() < deadline:
            run = self.app.sequences.run_get(run_id)
            started = [node for node in run['nodes'] if node['run_id']
                       and any(event['kind'] == 'ActionStarted' for event in self.app.runs.events(node['run_id']))]
            if len(started) == 2:
                break
            time.sleep(.01)
        self.assertEqual(len(started), 2)
        victim, peer = started
        self.app.coordinator._for_run(victim['run_id']).process.terminate()
        interrupted = self.app.coordinator.wait(victim['run_id'])
        self.assertEqual(interrupted['status'], 'INTERRUPTED')
        unknown = next(attempt for attempt in interrupted['attempts'] if attempt['status'] == 'UNKNOWN')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = self.app.sequences.run_get(run_id)
            member = next(node for node in run['nodes'] if node['run_id'] == victim['run_id'])
            if member['status'] == 'BLOCKED':
                break
            time.sleep(.01)
        self.assertEqual(member['status'], 'BLOCKED')
        return run_id, member, unknown, peer

    def test_stale_reconcile_cannot_change_cancelled_or_explicitly_paused_combination(self):
        for operation, expected_status in [('cancel', 'CANCELLED'), ('pause', 'PAUSED')]:
            with self.subTest(operation=operation):
                run_id, member, unknown, peer = self._unknown_child_with_live_peer()
                if operation == 'cancel':
                    self.app.coordinator.wait(peer['run_id'])
                    deadline = time.monotonic() + 5
                    while self.app.sequences.run_get(run_id)['status'] != 'BLOCKED' and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertEqual(self.app.sequences.run_get(run_id)['status'], 'BLOCKED')
                getattr(self.app.sequences, operation)(run_id, 'stop-before-reconcile-' + operation)
                with self.assertRaises(TaskError) as stopped:
                    self.app.sequences.run_reconcile(run_id, unknown['attempt_id'], 'not_completed', {'checked': True},
                        'stale-reconcile-' + operation, execution_path=member['execution_path'])
                self.assertEqual(stopped.exception.code, 'SEQUENCE_STATE_INVALID')
                current = self.app.sequences.run_get(run_id)
                self.assertEqual(current['status'], expected_status)
                self.assertEqual(current['stop_intent'], operation)
                self.assertEqual(next(node for node in current['nodes'] if node['run_id'] == member['run_id'])['status'], 'BLOCKED')
                attempt = self.app.runs.runs.attempt(unknown['attempt_id'])
                self.assertEqual(attempt['status'], 'UNKNOWN')
                self.assertEqual(attempt['effect_state'], 'UNKNOWN')
                self.assertIsNone(attempt['reconciliation_json'])
                self.app.coordinator.wait(peer['run_id'])

    def test_reconcile_remains_available_while_independent_peer_is_running(self):
        run_id, member, unknown, peer = self._unknown_child_with_live_peer()
        self.assertEqual(self.app.sequences.run_get(run_id)['status'], 'RUNNING')
        self.assertEqual(self.app.runs.stored(peer['run_id'])['status'], 'RUNNING')
        self.app.sequences.run_reconcile(run_id, unknown['attempt_id'], 'not_completed', {'checked': True},
            'reconcile-running-peer', execution_path=member['execution_path'])
        current = self.app.sequences.run_get(run_id)
        self.assertEqual(current['status'], 'RUNNING')
        self.assertIsNone(current['stop_intent'])
        self.assertEqual(self.app.runs.runs.attempt(unknown['attempt_id'])['status'], 'FAILED')
        self.app.sequences.cancel(run_id, 'cleanup-running-peer')
        self.app.coordinator.wait(peer['run_id'])
