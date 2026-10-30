"""Advance one ordinary execution at a time for each sequence run."""

import asyncio
import json
import threading
import time
from uuid import NAMESPACE_URL, uuid5

from taskweave.core.validation import TaskError, fingerprint, pointer, validate
from taskweave.core.flow_machine import FlowDecisionError, next_action, advance_after_action
from taskweave.core.sequence_flow import machine_flow
from taskweave.application.sequence_values import SequenceValues


class SequenceDriver:
    def __init__(self, use_cases, store):
        self.use_cases = use_cases
        self.store = store
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.threads = {}
        self.run_locks = {}
        self.signals = {}

    def guard(self, sequence_run_id):
        with self.lock:
            return self.run_locks.setdefault(sequence_run_id, threading.RLock())

    def wake(self, sequence_run_id):
        with self.lock:
            if self.stopping.is_set():
                return
            signal = self.signals.setdefault(sequence_run_id, threading.Event())
            signal.set()
            old = self.threads.get(sequence_run_id)
            if old and old.is_alive():
                return
            thread = threading.Thread(target=self._run, args=(sequence_run_id,), daemon=True)
            self.threads[sequence_run_id] = thread
            thread.start()

    def _run(self, sequence_run_id):
        while not self.stopping.is_set():
            with self.lock:
                self.signals[sequence_run_id].clear()
            self.advance(sequence_run_id)
            with self.lock:
                if self.signals[sequence_run_id].is_set() and not self.stopping.is_set():
                    continue
                self.threads.pop(sequence_run_id, None)
                return

    def recover(self):
        for row in self.use_cases.repository.list_runs():
            if row["status"] == "DELETING":
                try:
                    self.use_cases._finish_delete(row["sequence_run_id"])
                except TaskError:
                    # Keep the cleanup manifest and child ownership for explicit retry.
                    pass
                continue
            if row["status"] in {"READY", "RUNNING"}:
                self.wake(row["sequence_run_id"])

    def close(self):
        self.stopping.set()
        with self.lock:
            threads = list(self.threads.values())
        for thread in threads:
            thread.join()

    def _read_source(self, sequence_run, source, cursor=None):
        return SequenceValues(self.use_cases, sequence_run, cursor or sequence_run.get("cursor") or {}).source(source)

    def _resolve(self, run, node, cursor):
        values = SequenceValues(self.use_cases, run, cursor)
        inputs = {key: values.source(source) for key, source in node["inputs"].items()}
        step_inputs = {sid: {key: values.source(source) for key, source in sources.items()}
                       for sid, sources in node["step_inputs"].items()}
        inputs.update(run["snapshot"].get("node_inputs", {}).get(node["node_id"], {}))
        for sid, supplied in run["snapshot"].get("node_step_inputs", {}).get(node["node_id"], {}).items():
            step_inputs.setdefault(sid, {}).update(supplied)
        return inputs, step_inputs

    def _create_child(self, sequence_run, node, inputs, step_inputs):
        app = self.use_cases
        owner = sequence_run["sequence_run_id"]
        path = node.get("execution_path") or app.repository._path(owner, node["node_id"])
        with self.store.transaction():
            current = app.repository.get_run(owner)
            if self.stopping.is_set() or current["status"] not in {"READY", "RUNNING"} or current["stop_intent"]:
                raise TaskError("SEQUENCE_STOPPED")
            member = next(item for item in current["nodes"] if item["execution_path"] == path)
            if member["run_id"]:
                return member["run_id"]
            nid = node["node_id"]
            if app.tasks.definition_hash(node["task_id"]) != current["snapshot"]["task_hashes"][nid]:
                raise TaskError("RUN_CONFIG_CHANGED")
            if fingerprint(app.environments.environment(node["environment_id"])) != current["snapshot"]["environment_hashes"][nid]:
                raise TaskError("ENVIRONMENT_CHANGED")
            if app.registry.versions != current["snapshot"]["plugin_versions"]:
                raise TaskError("PLUGIN_VERSION_MISMATCH")
            created = app.runs.runs.create_run(node["task_id"], inputs, app.registry.versions,
                                               node["environment_id"], defer_inputs=True, step_inputs=step_inputs,
                                               trial=current["snapshot"].get("mode") == "TRIAL")
            app.repository.attach_child(owner, path, created["run_id"], inputs, step_inputs)
            app.repository.set_command_id(owner, path, str(uuid5(NAMESPACE_URL, f"taskweave:sequence:{owner}:{path}:start")))
            return created["run_id"]

    def _lint_child(self, node):
        app = self.use_cases
        for step in app.steps.steps(node["task_id"]):
            diagnostics = asyncio.run(app.runs.authoring.validate_step(step))
            if any(item["severity"] == "error" for item in diagnostics):
                raise TaskError("PLUGIN_LINT_FAILED")

    def _apply_command(self, sequence_run, command):
        app = self.use_cases
        owner = sequence_run["sequence_run_id"]
        path = command["execution_path"]
        member = next((item for item in sequence_run["nodes"] if item["execution_path"] == path), None)
        if member is None or not member["run_id"]:
            raise TaskError("SEQUENCE_CHILD_NOT_READY")
        run_id = member["run_id"]
        child = app.runs.stored(run_id)
        payload = command["payload"]
        command_id = command["id"]
        if command["kind"] == "inputs":
            if child["status"] == "PAUSED":
                app.runs._managed_provide_inputs(run_id, command_id, payload["inputs"], payload.get("step_inputs"), payload.get("expected_input_id"))
            child = app.runs.stored(run_id)
            if child["status"] in {"PAUSED", "READY", "INTERRUPTED"}:
                app.runs._managed_start(run_id, str(uuid5(NAMESPACE_URL, f"taskweave:sequence:{owner}:{command_id}:resume")))
        elif command["kind"] in {"retry", "continue"}:
            if child["status"] in {"PAUSED", "READY", "FAILED", "INTERRUPTED"}:
                app.runs._managed_start(run_id, command_id, retry_step_id=payload.get("retry_step_id"),
                                        retry_execution_path=payload.get("retry_execution_path"))
        app.repository.finish_command(owner, command_id)
        app.repository.set_node_status(owner, path, "RUNNING")

    @staticmethod
    def _action_cursor(cursor, path):
        from taskweave.core import flow_machine
        resolver = getattr(flow_machine, "action_cursor", None)
        return resolver(cursor, path) if resolver is not None else cursor

    def _decide(self, run):
        app = self.use_cases
        previous = run["cursor"]
        flow = machine_flow(run["snapshot"]["flow"])
        transition = next_action(flow, previous,
                                 lambda binding, cursor: SequenceValues(app, run, cursor).read(binding),
                                 read_with_pending=lambda binding, cursor, visits: SequenceValues(app, run, cursor, visits).read(binding))
        if not app.repository.commit_transition(run["sequence_run_id"], previous, transition):
            raise TaskError("FLOW_CURSOR_CONFLICT")
        return transition, flow

    def advance(self, sequence_run_id):
        app, repo = self.use_cases, self.use_cases.repository
        linted = {}
        try:
            while not self.stopping.is_set():
                # Plugin lint may be slow; keep pause/cancel available while
                # it runs and recheck stop intent in the creation transaction.
                preview = repo.get_run(sequence_run_id)
                if preview["status"] not in {"READY", "RUNNING"} or preview["stop_intent"]:
                    return
                configs = {node["node_id"]: node for node in preview["snapshot"]["nodes"]}
                for item in preview["nodes"]:
                    path = item["execution_path"]
                    if not item["run_id"] and path not in linted:
                        try:
                            self._lint_child(configs[item["node_id"]])
                            linted[path] = None
                        except TaskError as exc:
                            linted[path] = exc
                with self.guard(sequence_run_id):
                    run = repo.get_run(sequence_run_id)
                    if run["status"] not in {"READY", "RUNNING"} or run["stop_intent"]:
                        return
                    for command in repo.commands(sequence_run_id):
                        try:
                            self._apply_command(run, command)
                        except TaskError as exc:
                            if exc.code == "EXECUTOR_CAPACITY":
                                continue
                            repo.finish_command(sequence_run_id, command["id"], exc.code)
                            repo.set_node_status(sequence_run_id, command["execution_path"], "BLOCKED", exc.code)
                    run = repo.get_run(sequence_run_id)
                    try:
                        transition, flow = self._decide(run)
                    except FlowDecisionError as exc:
                        repo.commit_transition(sequence_run_id, run["cursor"], {"cursor": exc.cursor, "instances": [*exc.instances, {
                            "execution_path": exc.execution_path + "/$error", "node_id": exc.node_id,
                            "kind": "control", "status": "FAILED", "error_code": exc.code}]})
                        repo.set_run_status(sequence_run_id, "BLOCKED", exc.node_id, exc.code, execution_path=exc.execution_path)
                        return
                    if transition["done"]:
                        repo.set_run_status(sequence_run_id, "SUCCEEDED")
                        return
                    actions = transition.get("actions") or ([transition["action"]] if transition.get("action") else [])
                    decision_errors = transition.get("errors", [])
                    if not actions and decision_errors:
                        error = decision_errors[0]
                        repo.set_run_status(sequence_run_id, "BLOCKED", error["node_id"], error["error_code"],
                                            execution_path=error["execution_path"])
                        return
                    waiting, active, consumed = [], [], False
                    run = repo.get_run(sequence_run_id)
                    configurations = {node["node_id"]: node for node in run["snapshot"]["nodes"]}
                    for action in actions:
                        path = action["execution_path"]
                        config = configurations[action["step_id"]]
                        repo.ensure_action(sequence_run_id, action, config["task_id"])
                        member = next(item for item in repo.get_run(sequence_run_id)["nodes"] if item["execution_path"] == path)
                        try:
                            if not member["run_id"]:
                                if path not in linted:
                                    active.append(member)
                                    continue
                                if linted[path] is not None:
                                    raise linted[path]
                                if sum(item['run_id'] is not None for item in run['nodes']) >= 100_000:
                                    raise TaskError("SEQUENCE_INSTANCE_LIMIT_EXCEEDED")
                                inputs, step_inputs = self._resolve(run, config, self._action_cursor(transition["cursor"], path))
                                self._create_child(run, {**config, "execution_path": path}, inputs, step_inputs)
                                member = next(item for item in repo.get_run(sequence_run_id)["nodes"] if item["execution_path"] == path)
                            child = app.runs.stored(member["run_id"])
                            status = child["status"]
                            if status == "SUCCEEDED":
                                if not app.runs.coordinator.release_completed_run(member["run_id"]):
                                    active.append(member)
                                    continue
                                if "actions" in transition:
                                    advanced = advance_after_action(flow, transition["cursor"], member["run_id"], execution_path=path)
                                else:
                                    advanced = advance_after_action(flow, transition["cursor"], member["run_id"])
                                if not repo.commit_transition(sequence_run_id, transition["cursor"], advanced):
                                    raise TaskError("FLOW_CURSOR_CONFLICT")
                                consumed = True
                                break
                            if status == "READY":
                                try:
                                    app.runs._managed_start(member["run_id"], member["command_id"])
                                except TaskError as exc:
                                    if exc.code != "EXECUTOR_CAPACITY":
                                        raise
                                active.append(member)
                            elif status == "RUNNING":
                                active.append(member)
                            elif status == "PAUSED":
                                waiting.append((member, "WAITING_INPUT" if json.loads(child["request_json"]).get("waiting_input") else "PAUSED", None))
                            elif status == "CANCELLED":
                                waiting.append((member, "CANCELLED", None))
                            else:
                                waiting.append((member, "BLOCKED", "SEQUENCE_CHILD_" + status))
                        except TaskError as exc:
                            if exc.code == "SEQUENCE_STOPPED":
                                return
                            waiting.append((member, "BLOCKED", exc.code))
                    if consumed:
                        continue
                    for member, status, code in waiting:
                        repo.set_node_status(sequence_run_id, member["execution_path"], status, code)
                    if active or not actions or repo.commands(sequence_run_id):
                        current = active[0] if active else None
                        repo.set_run_status(sequence_run_id, "RUNNING", current["node_id"] if current else None,
                                            execution_path=current["execution_path"] if current else None)
                    else:
                        rank = {"CANCELLED": 0, "BLOCKED": 1, "WAITING_INPUT": 2, "PAUSED": 3}
                        member, status, code = min(waiting, key=lambda item: rank[item[1]])
                        repo.set_run_status(sequence_run_id, status, member["node_id"], code, execution_path=member["execution_path"])
                        return
                self.stopping.wait(.05)
        except Exception as exc:
            try:
                repo.set_run_status(sequence_run_id, "BLOCKED", error_code=getattr(exc, "code", type(exc).__name__))
            except TaskError:
                pass
