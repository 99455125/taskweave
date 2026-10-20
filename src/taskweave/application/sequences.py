"""Definition, launch and query use cases for serial task sequences."""

import asyncio
import json

from taskweave.core.validation import TaskError, fingerprint, pointer, validate
from taskweave.core.task_sequences import validate_definition


class SequenceUseCases:
    def __init__(self, repository, runs, tasks, steps, environments, registry):
        self.repository = repository
        self.runs = runs
        self.tasks = tasks
        self.steps = steps
        self.environments = environments
        self.registry = registry
        self.driver = None

    def _preflight(self, nodes, sequence_inputs=None, *, lint=False):
        for node in nodes:
            task = self.tasks.task(node["task_id"])
            if task["lifecycle"] != "ACTIVE":
                raise TaskError("TASK_DELETING")
            self.environments.environment(node["environment_id"])
            task_schema = json.loads(task["input_schema_json"])
            if set(node["inputs"]) - set(task_schema.get("properties", {})):
                raise TaskError("INPUT_INVALID", "Unknown task input")
            steps = self.steps.steps(node["task_id"])
            if not steps or any(step["validation_state"] != "VALIDATED" for step in steps):
                raise TaskError("STEP_NOT_VALIDATED")
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

    def save(self, name, nodes, input_schema, description="", sequence_id=None, expected_revision=None):
        validate_definition(name, nodes, input_schema)
        self._preflight(nodes)
        return self.repository.save(name, nodes, input_schema, description, sequence_id, expected_revision)

    def get(self, sequence_id):
        return self.repository.get(sequence_id)

    def list(self):
        return self.repository.list()

    def delete(self, sequence_id, expected_revision):
        return self.repository.delete_definition(sequence_id, expected_revision)

    def start(self, sequence_id, request_id, inputs):
        previous = self.repository.replay_start(sequence_id, request_id, inputs)
        if previous:
            return previous
        definition = self.repository.get(sequence_id)
        validate(inputs, definition["input_schema"])
        self._preflight(definition["nodes"], inputs, lint=True)
        task_hashes = {node["node_id"]: self.tasks.definition_hash(node["task_id"]) for node in definition["nodes"]}
        environment_hashes = {node["node_id"]: fingerprint(self.environments.environment(node["environment_id"])) for node in definition["nodes"]}
        started = self.repository.create_run(sequence_id, request_id, inputs, task_hashes, environment_hashes,
                                             self.registry.versions, expected_revision=definition["revision"])
        self.driver.wake(started["sequence_run_id"])
        return started

    def run_get(self, sequence_run_id):
        return self.repository.get_run(sequence_run_id)

    def run_list(self, sequence_id=None):
        return self.repository.list_runs(sequence_id)

    def _current_child(self, sequence_run_id):
        run = self.repository.get_run(sequence_run_id)
        member = next((item for item in run["nodes"] if item["node_id"] == run["current_node_id"]), None)
        if member is None or member["run_id"] is None:
            raise TaskError("SEQUENCE_CHILD_NOT_READY")
        return run, member

    def run_inputs(self, sequence_run_id, command_id, inputs, step_inputs=None, expected_input_id=None):
        payload = {"inputs": inputs, "step_inputs": step_inputs, "expected_input_id": expected_input_id}
        with self.driver.guard(sequence_run_id):
            sequence_run, member = self._current_child(sequence_run_id)
            previous = sequence_run["control_command"]
            if sequence_run["status"] != "WAITING_INPUT" and not (previous and previous["id"] == command_id):
                raise TaskError("SEQUENCE_STATE_INVALID")
            self.repository.command(sequence_run_id, command_id, "inputs", payload)
        self.driver.wake(sequence_run_id)
        return self.run_get(sequence_run_id)

    def run_retry(self, sequence_run_id, command_id, retry_step_id=None, retry_execution_path=None):
        if bool(retry_step_id) == bool(retry_execution_path):
            raise TaskError("SEQUENCE_RETRY_TARGET_INVALID")
        with self.driver.guard(sequence_run_id):
            sequence_run, member = self._current_child(sequence_run_id)
            previous = sequence_run["control_command"]
            if sequence_run["status"] != "BLOCKED" and not (previous and previous["id"] == command_id):
                raise TaskError("SEQUENCE_STATE_INVALID")
            self.repository.command(sequence_run_id, command_id, "retry", {
                "retry_step_id": retry_step_id, "retry_execution_path": retry_execution_path})
        self.driver.wake(sequence_run_id)
        return self.run_get(sequence_run_id)

    def run_reconcile(self, sequence_run_id, attempt_id, decision, evidence, command_id):
        with self.driver.guard(sequence_run_id):
            sequence_run, member = self._current_child(sequence_run_id)
            if sequence_run["status"] != "BLOCKED":
                raise TaskError("SEQUENCE_STATE_INVALID")
            if self.runs.runs.attempt_run_id(attempt_id) != member["run_id"]:
                raise TaskError("SEQUENCE_CHILD_MISMATCH")
            result = self.runs._managed_reconcile(attempt_id, decision, evidence, command_id)
            self.repository.set_run_status(sequence_run_id, "PAUSED", member["node_id"])
            return result

    def pause(self, sequence_run_id, command_id):
        with self.driver.guard(sequence_run_id):
            run = self.repository.get_run(sequence_run_id)
            if run["status"] not in {"READY", "RUNNING"}:
                raise TaskError("SEQUENCE_STATE_INVALID")
            self.repository.set_run_status(sequence_run_id, "PAUSED", run["current_node_id"], stop_intent="pause")
            if run["current_node_id"]:
                _, member = self._current_child(sequence_run_id)
                if self.runs.stored(member["run_id"])["status"] == "RUNNING":
                    self.runs._managed_control(member["run_id"], command_id, "pause")
        return self.run_get(sequence_run_id)

    def cancel(self, sequence_run_id, command_id):
        with self.driver.guard(sequence_run_id):
            run = self.repository.get_run(sequence_run_id)
            if run["status"] in {"SUCCEEDED", "CANCELLED", "DELETING"}:
                raise TaskError("SEQUENCE_STATE_INVALID")
            self.repository.set_run_status(sequence_run_id, "CANCELLED", run["current_node_id"], stop_intent="cancel")
            if run["current_node_id"]:
                _, member = self._current_child(sequence_run_id)
                if self.runs.stored(member["run_id"])["status"] == "RUNNING":
                    self.runs._managed_control(member["run_id"], command_id, "cancel")
        return self.run_get(sequence_run_id)

    def continue_run(self, sequence_run_id, command_id):
        with self.driver.guard(sequence_run_id):
            run = self.repository.get_run(sequence_run_id)
            previous = run["control_command"]
            if run["status"] not in {"PAUSED", "BLOCKED"} and not (previous and previous["id"] == command_id):
                raise TaskError("SEQUENCE_STATE_INVALID")
            if run["status"] == "PAUSED" and previous and previous["phase"] == "pending":
                self.repository.resume(sequence_run_id, run["current_node_id"])
                self.driver.wake(sequence_run_id)
                return self.run_get(sequence_run_id)
            if run["status"] == "BLOCKED" and run["error_code"] not in {"SEQUENCE_CHILD_INTERRUPTED", "RUN_CONFIG_CHANGED", "ENVIRONMENT_CHANGED", "PLUGIN_VERSION_MISMATCH"}:
                raise TaskError("SEQUENCE_RETRY_REQUIRED")
            if run["current_node_id"]:
                member = next(item for item in run["nodes"] if item["node_id"] == run["current_node_id"])
                if member["run_id"]:
                    child = self.runs.stored(member["run_id"])
                    if child["status"] in {"FAILED", "RUNNING"}:
                        raise TaskError("SEQUENCE_RETRY_REQUIRED")
                    self.repository.command(sequence_run_id, command_id, "continue", {})
                else:
                    self.repository.resume(sequence_run_id, member["node_id"])
            else:
                self.repository.resume(sequence_run_id)
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
