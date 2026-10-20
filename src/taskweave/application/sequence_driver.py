"""Advance one ordinary execution at a time for each sequence run."""

import asyncio
import json
import threading
import time
from uuid import NAMESPACE_URL, uuid5

from taskweave.core.validation import TaskError, fingerprint, pointer, validate


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

    def _read_source(self, sequence_run, source):
        kind = source["kind"]
        if kind == "literal":
            return source["value"]
        if kind == "sequence":
            return pointer(sequence_run["inputs"], source["pointer"])
        origin = next(node for node in sequence_run["nodes"] if node["node_id"] == source["node_id"])
        if origin["status"] != "SUCCEEDED" or not origin["run_id"]:
            raise TaskError("SEQUENCE_SOURCE_UNAVAILABLE")
        output_name = source["output"]
        runs = self.use_cases.runs
        if output_name != "data":
            attempts = [attempt for attempt in runs.runs.run_details(origin["run_id"])["attempts"]
                        if attempt["step_id"] == source["step_id"] and attempt["valid"]
                        and attempt["status"] == "SUCCEEDED"]
            if not attempts:
                raise TaskError("SEQUENCE_OUTPUT_NOT_JSON")
            for attempt in attempts:
                refs = runs.results.receipt(attempt) or []
                ref = next((item for item in refs if item.get("name") == output_name), None)
                if ref is None or ref.get("kind") != "json":
                    raise TaskError("SEQUENCE_OUTPUT_NOT_JSON")
        value = runs.output(origin["run_id"], source["step_id"], output_name,
                            item_pointer=source.get("item_pointer"),
                            loop_node_id=source.get("loop_node_id"))
        return pointer(value, source["pointer"])

    def _resolve(self, sequence_run, node):
        inputs = {key: self._read_source(sequence_run, source) for key, source in node["inputs"].items()}
        step_inputs = {step_id: {key: self._read_source(sequence_run, source) for key, source in values.items()}
                       for step_id, values in node["step_inputs"].items()}
        return inputs, step_inputs

    def _create_child(self, sequence_run, node, inputs, step_inputs):
        app = self.use_cases
        node_id = node["node_id"]
        with self.store.transaction():
            current = app.repository.get_run(sequence_run["sequence_run_id"])
            if self.stopping.is_set() or current["status"] not in {"READY", "RUNNING"} or current["stop_intent"]:
                raise TaskError("SEQUENCE_STOPPED")
            member = next(item for item in current["nodes"] if item["node_id"] == node_id)
            if member["run_id"]:
                return member["run_id"]
            if app.tasks.definition_hash(node["task_id"]) != current["snapshot"]["task_hashes"][node_id]:
                raise TaskError("RUN_CONFIG_CHANGED")
            if fingerprint(app.environments.environment(node["environment_id"])) != current["snapshot"]["environment_hashes"][node_id]:
                raise TaskError("ENVIRONMENT_CHANGED")
            if app.registry.versions != current["snapshot"]["plugin_versions"]:
                raise TaskError("PLUGIN_VERSION_MISMATCH")
            created = app.runs.runs.create_run(node["task_id"], inputs, app.registry.versions,
                                               node["environment_id"], defer_inputs=True, step_inputs=step_inputs)
            app.repository.attach_child(sequence_run["sequence_run_id"], node_id, created["run_id"], inputs, step_inputs)
            command_id = str(uuid5(NAMESPACE_URL, f"taskweave:sequence:{sequence_run['sequence_run_id']}:{node_id}:start"))
            app.repository.set_command_id(sequence_run["sequence_run_id"], node_id, command_id)
            return created["run_id"]

    def _lint_child(self, node):
        app = self.use_cases
        for step in app.steps.steps(node["task_id"]):
            diagnostics = asyncio.run(app.runs.authoring.validate_step(step))
            if any(item["severity"] == "error" for item in diagnostics):
                raise TaskError("PLUGIN_LINT_FAILED")

    def _apply_command(self, sequence_run):
        command = sequence_run["control_command"]
        if not command or command["phase"] != "pending":
            return False
        app = self.use_cases
        member = next(item for item in sequence_run["nodes"] if item["node_id"] == sequence_run["current_node_id"])
        child_id = member["run_id"]
        kind, payload, command_id = command["kind"], command["payload"], command["id"]
        child = app.runs.stored(child_id)
        if kind == "inputs":
            if child["status"] == "PAUSED":
                app.runs._managed_provide_inputs(child_id, command_id, payload["inputs"],
                                                  payload.get("step_inputs"), payload.get("expected_input_id"))
            start_id = str(uuid5(NAMESPACE_URL, f"taskweave:sequence:{sequence_run['sequence_run_id']}:{command_id}:resume"))
            child = app.runs.stored(child_id)
            if child["status"] in {"PAUSED", "READY", "INTERRUPTED"}:
                app.runs._managed_start(child_id, start_id)
        elif kind in {"retry", "continue"}:
            if child["status"] in {"PAUSED", "READY", "FAILED", "INTERRUPTED"}:
                app.runs._managed_start(child_id, command_id,
                                        retry_step_id=payload.get("retry_step_id"),
                                        retry_execution_path=payload.get("retry_execution_path"))
        app.repository.finish_command(sequence_run["sequence_run_id"], command_id)
        app.repository.set_node_status(sequence_run["sequence_run_id"], member["node_id"], "RUNNING")
        return True

    def advance(self, sequence_run_id):
        app = self.use_cases
        repo = app.repository
        try:
            while not self.stopping.is_set():
                preview = repo.get_run(sequence_run_id)
                preview_member = next((item for item in preview["nodes"] if item["status"] != "SUCCEEDED"), None)
                if (preview["status"] in {"READY", "RUNNING"} and preview_member
                        and not preview_member["run_id"]):
                    try:
                        self._lint_child(preview["snapshot"]["nodes"][preview_member["position"]])
                    except TaskError as exc:
                        with self.guard(sequence_run_id):
                            current = repo.get_run(sequence_run_id)
                            if current["status"] not in {"READY", "RUNNING"} or current["stop_intent"] or self.stopping.is_set():
                                return
                            repo.set_node_status(sequence_run_id, preview_member["node_id"], "BLOCKED", exc.code)
                            repo.set_run_status(sequence_run_id, "BLOCKED", preview_member["node_id"], exc.code)
                        return
                with self.guard(sequence_run_id):
                    sequence_run = repo.get_run(sequence_run_id)
                    if sequence_run["status"] in {"SUCCEEDED", "CANCELLED", "BLOCKED", "WAITING_INPUT", "PAUSED", "DELETING"}:
                        return
                    if sequence_run["stop_intent"]:
                        return
                    member = next((item for item in sequence_run["nodes"] if item["status"] != "SUCCEEDED"), None)
                    if member is None:
                        repo.set_run_status(sequence_run_id, "SUCCEEDED")
                        return
                    node = sequence_run["snapshot"]["nodes"][member["position"]]
                    node_id = node["node_id"]
                    try:
                        if sequence_run["control_command"] and sequence_run["control_command"]["phase"] == "pending":
                            self._apply_command(sequence_run)
                            continue
                        if not member["run_id"]:
                            inputs, step_inputs = self._resolve(sequence_run, node)
                            run_id = self._create_child(sequence_run, node, inputs, step_inputs)
                            sequence_run = repo.get_run(sequence_run_id)
                            member = sequence_run["nodes"][member["position"]]
                        else:
                            run_id = member["run_id"]
                        child = app.runs.stored(run_id)
                        if child["status"] == "READY":
                            if self.stopping.is_set():
                                return
                            try:
                                app.runs._managed_start(run_id, member["command_id"])
                            except TaskError as exc:
                                if exc.code == "EXECUTOR_CAPACITY":
                                    time.sleep(0.2)
                                    continue
                                raise
                            repo.set_run_status(sequence_run_id, "RUNNING", node_id)
                            continue
                        if child["status"] == "RUNNING":
                            pass
                        elif child["status"] == "SUCCEEDED":
                            if not app.runs.coordinator.release_completed_run(run_id):
                                continue
                            repo.set_node_status(sequence_run_id, node_id, "SUCCEEDED")
                            continue
                        elif child["status"] == "PAUSED":
                            status = "WAITING_INPUT" if json.loads(child["request_json"]).get("waiting_input") else "PAUSED"
                            repo.set_node_status(sequence_run_id, node_id, status)
                            repo.set_run_status(sequence_run_id, status, node_id)
                            return
                        elif child["status"] == "CANCELLED":
                            repo.set_node_status(sequence_run_id, node_id, "CANCELLED")
                            repo.set_run_status(sequence_run_id, "CANCELLED", node_id)
                            return
                        else:
                            raise TaskError("SEQUENCE_CHILD_" + child["status"])
                    except TaskError as exc:
                        if exc.code == "SEQUENCE_STOPPED":
                            return
                        if sequence_run["control_command"] and sequence_run["control_command"]["phase"] == "pending":
                            if exc.code == "EXECUTOR_CAPACITY":
                                time.sleep(0.2)
                                continue
                            repo.finish_command(sequence_run_id, sequence_run["control_command"]["id"], exc.code)
                            if sequence_run["control_command"]["kind"] == "inputs":
                                child_request = json.loads(app.runs.stored(member["run_id"])["request_json"])
                                status = "WAITING_INPUT" if child_request.get("waiting_input") else "BLOCKED"
                                repo.set_node_status(sequence_run_id, node_id, status, exc.code)
                                repo.set_run_status(sequence_run_id, status, node_id, exc.code)
                                return
                            if sequence_run["control_command"]["kind"] == "continue":
                                repo.set_node_status(sequence_run_id, node_id, "PAUSED", exc.code)
                                repo.set_run_status(sequence_run_id, "PAUSED", node_id, exc.code)
                                return
                        repo.set_node_status(sequence_run_id, node_id, "BLOCKED", exc.code)
                        repo.set_run_status(sequence_run_id, "BLOCKED", node_id, exc.code)
                        return
                time.sleep(0.05)
        except Exception as exc:
            try:
                repo.set_run_status(sequence_run_id, "BLOCKED", error_code=getattr(exc, "code", type(exc).__name__))
            except TaskError:
                pass
