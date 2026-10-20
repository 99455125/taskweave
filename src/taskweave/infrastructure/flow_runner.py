"""Drive a structured task using durable action and control instances."""

import json
from datetime import datetime, timedelta, timezone
import time

from taskweave.core.flow_machine import FlowDecisionError, advance_after_action, next_action
from taskweave.core.flow_values import aggregate_branch_output, aggregate_output
from taskweave.core.validation import TaskError, automatic_inputs, pointer
from taskweave.infrastructure.sqlite_storage import now


class FlowRunner:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def _read(self, run, cursor, binding, pending_visits=()):
        c = self.coordinator
        if "literal" in binding:
            return binding["literal"]
        ref = binding["ref"]
        source = ref["source"]
        if source == "task":
            task = c.tasks.task(run["task_id"])
            schema = json.loads(task["input_schema_json"])
            value = {key: spec["default"] for key, spec in schema.get("properties", {}).items() if "default" in spec}
            value.update(json.loads(run["inputs_json"]))
        elif source == "environment":
            value = c.environments.environment(run["environment_id"])[0]
        elif source == "loop":
            frame = next((frame for frame in reversed(cursor["frames"])
                          if frame["node_id"] == ref["node_id"]), None)
            if frame is None:
                raise TaskError("FLOW_REFERENCE_INVALID")
            field = ref["field"]
            if field == "item":
                value = frame["items"][frame["index"]]
            elif field == "index":
                value = frame["index"]
            else:
                value = frame["state"]
        elif source == "step":
            flow = json.loads(run["definition_json"])["flow"]
            visits = {item["execution_path"]: item for item in c.flow_runs.instances(run["run_id"])}
            visits.update({item["execution_path"]: item for item in pending_visits})
            value = aggregate_output(flow, list(visits.values()), ref["step_id"],
                                     ref.get("output", "data"),
                                     lambda aid, name: c.results.read_attempt_output(aid, name, c.registry),
                                     active_frames=cursor["frames"],
                                     item_pointer=ref.get("item_pointer"),
                                     loop_node_id=ref.get("loop_node_id"))
        elif source == "branch":
            flow = json.loads(run["definition_json"])["flow"]
            by_path = {item["execution_path"]: item for item in c.flow_runs.instances(run["run_id"])}
            by_path.update({item["execution_path"]: item for item in pending_visits})
            visits = list(by_path.values())

            def mapped(binding, branch_path, selected):
                if "literal" in binding:
                    return binding["literal"]
                frames = []
                for item in visits:
                    if item["kind"] not in {"foreach", "loop"}:
                        continue
                    prefix = item["execution_path"] + "/"
                    if branch_path.startswith(prefix):
                        rest = branch_path[len(prefix):].split("/", 1)[0]
                        if rest.isdigit():
                            index = int(rest)
                            historical = {"kind": item["kind"], "node_id": item["node_id"],
                                          "path": item["execution_path"], "index": index}
                            if item["kind"] == "foreach":
                                historical["items"] = item["payload"]["items"]
                            else:
                                iteration = next((visit for visit in visits
                                                  if visit["kind"] == "iteration" and
                                                  visit["execution_path"] == item["execution_path"] + "/" + rest), None)
                                current = next((frame for frame in cursor["frames"]
                                                if frame["path"] == item["execution_path"] and frame["index"] == index), None)
                                if iteration:
                                    historical["state"] = iteration["payload"].get("state_before", {})
                                elif current:
                                    historical["state"] = current["state"]
                                else:
                                    raise TaskError("FLOW_REFERENCE_INVALID")
                            frames.append(historical)
                return self._read(run, {**cursor, "frames": [*cursor["frames"], *frames]},
                                  binding, pending_visits)

            value = aggregate_branch_output(flow, visits, ref["node_id"], ref["output"], mapped,
                                            active_frames=cursor["frames"])
        else:
            raise TaskError("FLOW_REFERENCE_INVALID")
        return pointer(value, ref.get("pointer", ""))

    def _inputs(self, run, step, cursor):
        c = self.coordinator
        schema = json.loads(c.tasks.task(run["task_id"])["input_schema_json"])
        task = {key: spec["default"] for key, spec in schema.get("properties", {}).items() if "default" in spec}
        task.update(json.loads(run["inputs_json"]))
        environment = c.environments.environment(run["environment_id"])[0]
        request = json.loads(run["request_json"])
        values = {name: self._read(run, cursor, binding) for name, binding in step["bindings"].items()}
        values.update(request.get("step_inputs", {}).get(step["step_id"], {}))
        pending = cursor.get("pending") or {}
        values.update(request.get("instance_inputs", {}).get(pending.get("execution_path"), {}))
        return automatic_inputs(step["input_schema"], environment, task, values)

    def _decide(self, run, flow):
        c = self.coordinator
        run_id = run["run_id"]
        previous = c.flow_runs.cursor(run_id)
        try:
            transition = next_action(flow, previous,
                                     lambda binding, cursor: self._read(run, cursor, binding),
                                     read_with_pending=lambda binding, cursor, visits:
                                         self._read(run, cursor, binding, visits))
        except FlowDecisionError as exc:
            failed = {"execution_path": exc.execution_path + "/$error", "node_id": exc.node_id,
                      "kind": "control", "status": "FAILED", "error_code": exc.code,
                      "payload": {}}
            c.flow_runs.commit_transition(run_id, previous,
                                          {"cursor": exc.cursor, "instances": [*exc.instances, failed]})
            c.events.event(run_id, "FlowDecisionFailed",
                           {"node_id": exc.node_id, "execution_path": exc.execution_path, "code": exc.code})
            c._done(run_id, "FAILED")
            return None
        if not c.flow_runs.commit_transition(run_id, previous, transition):
            raise TaskError("FLOW_CURSOR_CONFLICT")
        return transition

    def _boundary(self, run, flow, mode, target, reached):
        c = self.coordinator
        while True:
            if c.cancel.is_set():
                c._done(run["run_id"], "CANCELLED")
                return
            if c.pause_requested.is_set() or c.closing:
                c._done(run["run_id"], "PAUSED")
                return
            transition = self._decide(run, flow)
            if transition is None:
                return
            if transition["done"]:
                if mode == "UNTIL" and not reached:
                    c.events.event(run["run_id"], "TargetNotReached", {"step_id": target})
                c._done(run["run_id"], "SUCCEEDED")
                return
            if transition["action"] is not None:
                c._done(run["run_id"], "PAUSED")
                return
            c.leases.heartbeat(run["run_id"], now())

    def _wait_interval(self, run_id, step):
        c = self.coordinator
        seconds = step.get("delay_after_previous_seconds", 0)
        prior = c.queries.latest_successful_attempt(run_id)
        if not seconds or prior is None:
            c.writes.clear_waiting_step(run_id)
            return True
        deadline = datetime.fromisoformat(prior["finished_at"]) + timedelta(seconds=seconds)
        c.writes.set_waiting_step(run_id, step["step_id"], deadline.isoformat())
        heartbeat = 0
        while datetime.now(timezone.utc) < deadline:
            if c.cancel.is_set():
                c._done(run_id, "CANCELLED")
                return False
            if c.pause_requested.is_set() or c.closing:
                c._done(run_id, "PAUSED")
                return False
            if time.monotonic() >= heartbeat:
                c.leases.heartbeat(run_id, now())
                heartbeat = time.monotonic() + 1
            c.cancel.wait(0.05)
        c.writes.clear_waiting_step(run_id)
        return True

    def drive(self, run_id, mode, target):
        c = self.coordinator
        run = c.queries.run(run_id)
        definition = json.loads(run["definition_json"])
        flow = definition["flow"]
        trial_target = (run["trial_step_id"] if run["mode"] == "TRIAL"
                        and json.loads(run["request_json"]).get("flow_trial") else None)
        steps = {step["step_id"]: step for step in c.steps.steps(run["task_id"])}
        task_schema = json.loads(c.tasks.task(run["task_id"])["input_schema_json"])
        task_values = json.loads(run["inputs_json"])
        task_missing = c.missing_inputs(task_schema, task_values)
        if task_missing and steps:
            c.wait_for_inputs(run, "task", next(iter(steps.values())), task_schema,
                              task_values, task_missing)
            return
        while True:
            if c.cancel.is_set():
                c._done(run_id, "CANCELLED")
                return
            if c.pause_requested.is_set() or c.closing:
                c._done(run_id, "PAUSED")
                return
            transition = self._decide(run, flow)
            if transition is None:
                return
            if transition["done"]:
                if mode == "UNTIL":
                    c.events.event(run_id, "TargetNotReached", {"step_id": target})
                c._done(run_id, "SUCCEEDED")
                return
            if transition["action"] is None:
                c.leases.heartbeat(run_id, now())
                continue
            action = transition["action"]
            path = action["execution_path"]
            prior = c.queries.latest_attempt_for_instance(run_id, path)
            if prior:
                if prior["status"] == "SUCCEEDED":
                    advanced = advance_after_action(flow, transition["cursor"], prior["attempt_id"])
                    if not c.flow_runs.commit_transition(run_id, transition["cursor"], advanced):
                        raise TaskError("FLOW_CURSOR_CONFLICT")
                    if trial_target and action["step_id"] == trial_target:
                        c._done(run_id, "SUCCEEDED")
                        return
                    if mode == "NEXT" or mode == "UNTIL" and action["step_id"] == target:
                        self._boundary(run, flow, mode, target, action["step_id"] == target)
                        return
                    continue
                if prior["status"] in {"UNKNOWN", "RUNNING"} or prior["effect_state"] in {"UNKNOWN", "SUCCEEDED"}:
                    c._done(run_id, "INTERRUPTED")
                    return
                c._done(run_id, "FAILED")
                return
            if c.queries.attempt_count(run_id) >= 100_000:
                c.events.event(run_id, "FlowDecisionFailed", {"code": "LOOP_LIMIT_EXCEEDED", "execution_path": path})
                c._done(run_id, "FAILED")
                return
            step = steps[action["step_id"]]
            try:
                effective = self._inputs(run, step, transition["cursor"])
            except TaskError:
                effective = None
            missing = ([name for name in c.missing_inputs(step["input_schema"], effective)
                        if name not in step["bindings"]] if effective is not None else [])
            if missing:
                c.wait_for_inputs(run, "step", step, step["input_schema"], effective, missing, path)
                return
            if not self._wait_interval(run_id, step):
                return
            if not c._attempt(run, step, execution_path=path,
                              input_resolver=lambda current, action_step: self._inputs(current, action_step,
                                                                                         transition["cursor"])):
                failed_attempt = c.queries.latest_attempt_for_instance(run_id, path)
                if failed_attempt is not None:
                    c.flow_runs.commit_transition(run_id, transition["cursor"], {
                        "cursor": transition["cursor"], "instances": [{
                            "execution_path": path, "node_id": action["node_id"], "kind": "action",
                            "status": failed_attempt["status"], "attempt_id": failed_attempt["attempt_id"],
                            "error_code": failed_attempt["error_code"], "payload": {},
                        }],
                    })
                return
            attempt = c.queries.latest_attempt_for_instance(run_id, path)
            advanced = advance_after_action(flow, transition["cursor"], attempt["attempt_id"])
            if not c.flow_runs.commit_transition(run_id, transition["cursor"], advanced):
                raise TaskError("FLOW_CURSOR_CONFLICT")
            if trial_target and action["step_id"] == trial_target:
                c._done(run_id, "SUCCEEDED")
                return
            if mode == "NEXT" or mode == "UNTIL" and action["step_id"] == target:
                self._boundary(run, flow, mode, target, action["step_id"] == target)
                return
