"""Definition, launch and query use cases for serial task sequences."""

import asyncio
import json

from taskweave.core.validation import TaskError, fingerprint, pointer, validate
from taskweave.core.task_sequences import validate_definition
from taskweave.core.sequence_flow import linear_flow, flow_operands


class SequenceUseCases:
    def __init__(self, repository, runs, tasks, steps, environments, registry):
        self.repository = repository
        self.runs = runs
        self.tasks = tasks
        self.steps = steps
        self.environments = environments
        self.registry = registry
        self.driver = None

    def _preflight(self, nodes, sequence_inputs=None, *, lint=False, flow=None, require_confirmed=True):
        if flow is not None:
            configured = {node['node_id']: node for node in nodes}
            for value in flow_operands(flow):
                if isinstance(value, dict):
                    ref = value.get('ref', {})
                    if isinstance(ref, dict) and ref.get('source') == 'node':
                        origin = configured.get(ref.get('node_id'))
                        if origin is None or ref.get('step_id') not in {step['step_id'] for step in self.steps.steps(origin['task_id'])}:
                            raise TaskError('SEQUENCE_SOURCE_INVALID')
        for node in nodes:
            task = self.tasks.task(node["task_id"])
            if task["lifecycle"] != "ACTIVE":
                raise TaskError("TASK_DELETING")
            self.environments.environment(node["environment_id"])
            task_schema = json.loads(task["input_schema_json"])
            if set(node["inputs"]) - set(task_schema.get("properties", {})):
                raise TaskError("INPUT_INVALID", "Unknown task input")
            steps = self.steps.steps(node["task_id"])
            if not steps or (require_confirmed and any(step["validation_state"] != "VALIDATED" for step in steps)):
                raise TaskError("STEP_NOT_VALIDATED")
            if require_confirmed and not self.tasks.flow_is_confirmed(node['task_id']):
                raise TaskError('FLOW_NOT_CONFIRMED')
            for step_id, sources in node["step_inputs"].items():
                step = next((step for step in steps if step["step_id"] == step_id), None)
                if step is None or set(sources) & set(step["bindings"]):
                    raise TaskError("INPUT_INVALID", "Invalid step input")
                if set(sources) - set(step["input_schema"].get("properties", {})):
                    raise TaskError("INPUT_INVALID", "Unknown step input")
            for sources in [node["inputs"], *node["step_inputs"].values()]:
                for source in sources.values():
                    if source["kind"] == "output":
                        origin = next(n for n in nodes if n["node_id"] == source["node_id"])
                        if source["step_id"] not in {step["step_id"] for step in self.steps.steps(origin["task_id"])}:
                            raise TaskError("SEQUENCE_SOURCE_INVALID")
            targets = [(node["inputs"], task_schema)] + [
                (node["step_inputs"][step["step_id"]], step["input_schema"])
                for step in steps if step["step_id"] in node["step_inputs"]]
            for sources, schema in targets:
                known = {}
                for key, source in sources.items():
                    if source["kind"] == "literal":
                        known[key] = source["value"]
                    elif source["kind"] == "sequence" and sequence_inputs is not None:
                        known[key] = pointer(sequence_inputs, source["pointer"])
                partial_schema = {key: schema[key] for key in
                                  ("$schema", "$defs", "definitions", "type", "properties", "additionalProperties")
                                  if key in schema}
                partial_schema["required"] = [key for key in schema.get("required", []) if key in known]
                validate(known, partial_schema)
            if lint:
                for step in steps:
                    diagnostics = asyncio.run(self.runs.authoring.validate_step(step))
                    if any(item["severity"] == "error" for item in diagnostics):
                        raise TaskError("PLUGIN_LINT_FAILED")

    def save(self, name, nodes, input_schema, description="", sequence_id=None, expected_revision=None, flow=None):
        flow = flow if flow is not None else linear_flow(nodes)
        validate_definition(name, nodes, input_schema, flow)
        self._preflight(nodes, flow=flow, require_confirmed=False)
        return self.repository.save(name, nodes, input_schema, description, sequence_id, expected_revision, flow=flow)

    def get(self, sequence_id):
        return self.repository.get(sequence_id)

    def list(self):
        return self.repository.list()

    def delete(self, sequence_id, expected_revision):
        return self.repository.delete_definition(sequence_id, expected_revision)

    def _validate_startup(self, definition, node_inputs, node_step_inputs):
        nodes = {node["node_id"]: node for node in definition["nodes"]}
        if not isinstance(node_inputs, dict) or not isinstance(node_step_inputs, dict):
            raise TaskError("INPUT_INVALID", "启动输入必须按任务节点提供")
        if (set(node_inputs) | set(node_step_inputs)) - set(nodes):
            raise TaskError("INPUT_INVALID", "未知任务节点")

        def check(values, schema, bindings, mappings):
            if not isinstance(values, dict):
                raise TaskError("INPUT_INVALID", "启动输入必须是对象")
            automatic = set(bindings) | {key for key, source in mappings.items() if source["kind"] != "literal"}
            if set(values) - set(schema.get("properties", {})) or set(values) & automatic:
                raise TaskError("INPUT_INVALID", "启动输入包含未知字段或自动来源字段")
            validate(values, {**schema, "required": [key for key in schema.get("required", []) if key in values]})

        for nid in set(node_inputs) | set(node_step_inputs):
            node = nodes[nid]
            task = self.tasks.task(node["task_id"])
            check(node_inputs.get(nid, {}), json.loads(task["input_schema_json"]), {}, node["inputs"])
            steps = {step["step_id"]: step for step in self.steps.steps(node["task_id"])}
            supplied = node_step_inputs.get(nid, {})
            if not isinstance(supplied, dict) or set(supplied) - set(steps):
                raise TaskError("INPUT_INVALID", "未知步骤")
            for sid, values in supplied.items():
                step = steps[sid]
                check(values, step["input_schema"], step["bindings"], node["step_inputs"].get(sid, {}))

    def start(self, sequence_id, request_id, inputs, node_inputs=None, node_step_inputs=None):
        started = self.prepare_start(sequence_id, request_id, inputs, node_inputs, node_step_inputs)
        self.driver.wake(started["sequence_run_id"])
        return started

    def trial(self, sequence_id, request_id, inputs, node_inputs=None, node_step_inputs=None):
        started = self.prepare_start(sequence_id, request_id, inputs, node_inputs, node_step_inputs, mode="TRIAL")
        self.driver.wake(started["sequence_run_id"])
        return started

    def prepare_start(self, sequence_id, request_id, inputs, node_inputs=None, node_step_inputs=None, *, mode="EXECUTION"):
        """Create the durable launch without waking a worker before outer commit."""
        previous = self.repository.replay_start(sequence_id, request_id, inputs, node_inputs, node_step_inputs, mode=mode)
        if previous:
            return previous
        definition = self.repository.get(sequence_id)
        validate(inputs, definition["input_schema"])
        self._validate_startup(definition, {} if node_inputs is None else node_inputs,
                               {} if node_step_inputs is None else node_step_inputs)
        self._preflight(definition["nodes"], inputs, lint=True, flow=definition['flow'], require_confirmed=mode == 'EXECUTION')
        task_hashes = {node["node_id"]: self.tasks.definition_hash(node["task_id"]) for node in definition["nodes"]}
        environment_hashes = {node["node_id"]: fingerprint(self.environments.environment(node["environment_id"])) for node in definition["nodes"]}
        started = self.repository.create_run(sequence_id, request_id, inputs, task_hashes, environment_hashes,
                                             self.registry.versions, expected_revision=definition["revision"],
                                             node_inputs=node_inputs, node_step_inputs=node_step_inputs, mode=mode)
        return started

    def run_get(self, sequence_run_id):
        return self.repository.get_run(sequence_run_id)

    def run_list(self, sequence_id=None):
        return self.repository.list_runs(sequence_id)

    def _current_child(self, sequence_run_id, execution_path=None, statuses=None):
        run = self.repository.get_run(sequence_run_id)
        candidates = [item for item in run["nodes"] if item["run_id"]
                      and (execution_path is None or item["execution_path"] == execution_path)
                      and (statuses is None or item["status"] in statuses)]
        if len(candidates) != 1:
            raise TaskError("SEQUENCE_INSTANCE_REQUIRED" if candidates or execution_path is None else "SEQUENCE_CHILD_NOT_READY")
        return run, candidates[0]

    def _queue(self, sequence_run_id, command_id, kind, payload, execution_path, statuses):
        with self.driver.guard(sequence_run_id):
            previous = next((item for item in self.repository.commands(sequence_run_id, False) if item["id"] == command_id), None)
            if previous:
                prior_path = previous["execution_path"]
                if execution_path is not None and execution_path != prior_path:
                    raise TaskError("COMMAND_CONFLICT")
                self.repository.command(sequence_run_id, command_id, kind, {**payload, "execution_path": prior_path})
            else:
                run, member = self._current_child(sequence_run_id, execution_path, statuses)
                if run['status'] in {'SUCCEEDED', 'CANCELLED', 'DELETING'} or run['stop_intent']:
                    raise TaskError('SEQUENCE_STATE_INVALID')
                self.repository.command(sequence_run_id, command_id, kind, {**payload, "execution_path": member["execution_path"]})
        self.driver.wake(sequence_run_id)
        return self.run_get(sequence_run_id)

    def run_inputs(self, sequence_run_id, command_id, inputs, step_inputs=None, expected_input_id=None, execution_path=None):
        return self._queue(sequence_run_id, command_id, "inputs", {
            "inputs": inputs, "step_inputs": step_inputs, "expected_input_id": expected_input_id},
            execution_path, {"WAITING_INPUT"})

    def run_retry(self, sequence_run_id, command_id, retry_step_id=None, retry_execution_path=None, execution_path=None):
        if bool(retry_step_id) == bool(retry_execution_path):
            raise TaskError("SEQUENCE_RETRY_TARGET_INVALID")
        return self._queue(sequence_run_id, command_id, "retry", {
            "retry_step_id": retry_step_id, "retry_execution_path": retry_execution_path}, execution_path, {"BLOCKED"})

    def run_reconcile(self, sequence_run_id, attempt_id, decision, evidence, command_id, execution_path=None):
        with self.driver.guard(sequence_run_id):
            run, member = self._current_child(sequence_run_id, execution_path, {"BLOCKED"})
            if run['status'] in {'SUCCEEDED', 'CANCELLED', 'DELETING'} or run['stop_intent']:
                raise TaskError('SEQUENCE_STATE_INVALID')
            if self.runs.runs.attempt_run_id(attempt_id) != member["run_id"]:
                raise TaskError("SEQUENCE_CHILD_MISMATCH")
            result = self.runs._managed_reconcile(attempt_id, decision, evidence, command_id)
            self.repository.set_node_status(sequence_run_id, member["execution_path"], "PAUSED")
            if run["status"] != "RUNNING":
                self.repository.set_run_status(sequence_run_id, "PAUSED", member["node_id"], execution_path=member["execution_path"])
            return result

    def _stop(self, sequence_run_id, command_id, operation):
        from uuid import NAMESPACE_URL, uuid5
        with self.driver.guard(sequence_run_id):
            run = self.repository.get_run(sequence_run_id)
            if (operation == "pause" and run["status"] not in {"READY", "RUNNING"}
                    or operation == "cancel" and run["status"] in {"SUCCEEDED", "CANCELLED", "DELETING"}):
                raise TaskError("SEQUENCE_STATE_INVALID")
            self.repository.set_run_status(sequence_run_id, "PAUSED" if operation == "pause" else "CANCELLED",
                run["current_node_id"], stop_intent=operation, execution_path=run["current_execution_path"])
            for member in run["nodes"]:
                if member["run_id"] and self.runs.stored(member["run_id"])["status"] == "RUNNING":
                    try:
                        self.runs._managed_control(member["run_id"], str(uuid5(NAMESPACE_URL,
                            f"taskweave:sequence:{sequence_run_id}:{command_id}:{member['execution_path']}")), operation)
                    except TaskError as exc:
                        # A child can finish outside the combination guard after
                        # the read above. Verify that boundary before continuing
                        # the already-persisted stop across the remaining paths.
                        if (exc.code != "RUN_STATE_INVALID" or self.runs.stored(member["run_id"])["status"]
                                not in {"SUCCEEDED", "FAILED", "INTERRUPTED", "PAUSED", "CANCELLED"}):
                            raise
        return self.run_get(sequence_run_id)

    def pause(self, sequence_run_id, command_id):
        return self._stop(sequence_run_id, command_id, "pause")

    def cancel(self, sequence_run_id, command_id):
        return self._stop(sequence_run_id, command_id, "cancel")

    def continue_run(self, sequence_run_id, command_id, execution_path=None):
        from uuid import NAMESPACE_URL, uuid5
        with self.driver.guard(sequence_run_id):
            run = self.repository.get_run(sequence_run_id)
            previous = next((item for item in self.repository.commands(sequence_run_id, False) if item["id"] == command_id), None)
            if previous:
                self.repository.command(sequence_run_id, command_id, "continue", previous["payload"])
            else:
                if run["status"] not in {"PAUSED", "BLOCKED", "RUNNING"}:
                    raise TaskError("SEQUENCE_STATE_INVALID")
                members = [item for item in run["nodes"] if item["status"] != "SUCCEEDED"
                           and (execution_path is None or item["execution_path"] == execution_path)]
                if execution_path is not None and not members:
                    raise TaskError("SEQUENCE_CHILD_NOT_READY")
                for member in members:
                    if member["run_id"]:
                        child = self.runs.stored(member["run_id"])
                        if child["status"] == 'RUNNING' or child['status'] == 'FAILED' and run['status'] != 'PAUSED':
                            raise TaskError("SEQUENCE_RETRY_REQUIRED")
                    elif member["error_code"] not in {None, "RUN_CONFIG_CHANGED", "ENVIRONMENT_CHANGED", "PLUGIN_VERSION_MISMATCH"}:
                        raise TaskError("SEQUENCE_RETRY_REQUIRED")
                if not members and run["status"] != "PAUSED":
                    raise TaskError("SEQUENCE_RETRY_REQUIRED")
                for member in members:
                    if member["run_id"]:
                        if self.runs.stored(member['run_id'])['status'] == 'FAILED':
                            continue
                        identity = command_id if len(members) == 1 else str(uuid5(NAMESPACE_URL, command_id + member["execution_path"]))
                        self.repository.command(sequence_run_id, identity, "continue", {"execution_path": member["execution_path"]})
                if self.repository.get_run(sequence_run_id)["status"] in {"PAUSED", "BLOCKED"}:
                    self.repository.resume(sequence_run_id, run["current_node_id"])
        self.driver.wake(sequence_run_id)
        return self.run_get(sequence_run_id)

    def run_delete(self, sequence_run_id):
        with self.driver.guard(sequence_run_id):
            run = self.repository.get_run(sequence_run_id)
            for member in run["nodes"]:
                if member["run_id"] and self.runs.stored(member["run_id"])["status"] == "RUNNING":
                    raise TaskError("SEQUENCE_RUN_BUSY")
            children = self.repository.begin_cleanup(sequence_run_id)
            self._finish_delete(sequence_run_id, children)
        return {"deleted": sequence_run_id}

    def _finish_delete(self, sequence_run_id, children=None):
        if children is None:
            children = self.repository.get_run(sequence_run_id)["cleanup"]
        for child_id in children:
            if self.runs.runs.run_exists(child_id):
                if self.runs.stored(child_id)["status"] == "RUNNING":
                    raise TaskError("SEQUENCE_RUN_BUSY")
                self.repository.detach_child_for_cleanup(sequence_run_id, child_id)
                self.runs.coordinator.delete_run(child_id)
        self.repository.finish_cleanup(sequence_run_id)
