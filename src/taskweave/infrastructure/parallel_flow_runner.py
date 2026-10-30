"""One durable run, independently owned branch workers, and a bounded leaf scheduler."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta, timezone
import json

from taskweave.core.flow_machine import action_cursor, advance_after_action, live_resource_paths, _nodes, _part
from taskweave.core.validation import TaskError
from taskweave.infrastructure.flow_runner import FlowRunner
from taskweave.infrastructure.run_coordinator import Coordinator
from taskweave.infrastructure.sqlite_storage import now


class BranchWorker(Coordinator):
    """Execute attempts without letting one branch finish the shared run."""
    def _done(self, run_id, status):
        self.outcome = status


class ParallelFlowRunner(FlowRunner):
    def _delay_deadline(self, run_id, step, context, flow):
        seconds = step.get("delay_after_previous_seconds", 0)
        if not seconds:
            return None
        nodes = _nodes(flow)
        prefixes = []
        for frame in context["frames"]:
            if frame["kind"] == "sequence":
                prefixes.extend(frame["path"] + "/" + _part(child["id"]) + "/"
                                for child in nodes[frame["node_id"]]["children"][:frame["index"]])
            elif frame["kind"] in {"foreach", "loop"} and frame.get("index", 0):
                prefixes.append(frame["path"] + "/" + str(frame["index"] - 1) + "/")
        prior = [attempt for attempt in self.coordinator.queries.attempts_with_status(run_id, "SUCCEEDED")
                 if attempt["valid"] and attempt["finished_at"]
                 and any((attempt["execution_path"] + "/").startswith(prefix) for prefix in prefixes)]
        if not prior:
            return None
        return max(datetime.fromisoformat(attempt["finished_at"]) for attempt in prior) + timedelta(seconds=seconds)

    def _worker_for(self, resource_path):
        c = self.coordinator
        if resource_path not in c.branch_workers:
            c.branch_workers[resource_path] = BranchWorker(
                c.runs, c.tasks, c.steps, c.environments, c.results, c.registry, c.factory, c.home,
                recover=False, queries=c.queries, events=c.events, leases=c.leases,
                writes=c.writes, flow_runs=c.flow_runs)
            c.branch_workers[resource_path].execution_capacity = c.execution_capacity
            worker = c.branch_workers[resource_path]
            if resource_path == '/' and c.explicit_scene:
                # The outer lane is the selected scene; parallel child lanes
                # continue to acquire their own independent resources.
                worker.transport, worker.cancel = c.transport, c.cancel
                worker.context_session_id = c.transport.session_id
                worker.context_recordings = c.context_recordings
                worker.context_recording_delivered = c.context_recording_delivered
                worker.context_recording_capabilities = c.context_recording_capabilities
            else:
                worker.transport.parents = (*c.transport.parents, c.transport)
        return c.branch_workers[resource_path]

    def _consume(self, run_id, flow, action, attempt):
        c = self.coordinator
        previous = c.flow_runs.cursor(run_id)
        if attempt["status"] == "SUCCEEDED":
            transition = advance_after_action(flow, previous, attempt["attempt_id"],
                                              execution_path=action["execution_path"])
        else:
            transition = {"cursor": previous, "instances": [{
                "execution_path": action["execution_path"], "node_id": action["node_id"],
                "kind": "action", "status": attempt["status"], "attempt_id": attempt["attempt_id"],
                "error_code": attempt["error_code"], "payload": {}}]}
        if not c.flow_runs.commit_transition(run_id, previous, transition):
            raise TaskError("FLOW_CURSOR_CONFLICT")

    def drive(self, run_id, mode, target):
        c = self.coordinator
        run = c.queries.run(run_id)
        flow = json.loads(run["definition_json"])["flow"]
        steps = {step["step_id"]: step for step in c.steps.steps(run["task_id"])}
        task_schema = json.loads(c.tasks.task(run["task_id"])["input_schema_json"])
        task_values = json.loads(run["inputs_json"])
        missing = c.missing_inputs(task_schema, task_values)
        if missing and steps:
            c.wait_for_inputs(run, "task", next(iter(steps.values())), task_schema, task_values, missing)
            return
        trial_target = run["trial_step_id"] if run["mode"] == "TRIAL" else None
        blocked = {}
        waiting = {}
        active = {}
        stopped = False
        reached = False
        capacity = c.max_parallel_actions
        with ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="flow-branch") as executor:
            while True:
                # Only this scheduler commits cursors; worker threads persist their own attempts.
                for future in tuple(active):
                    if not future.done():
                        continue
                    action, worker = active.pop(future)
                    future.result()
                    attempt = c.queries.latest_attempt_for_instance(run_id, action["execution_path"])
                    if attempt is None:
                        raise TaskError("FLOW_INSTANCE_REQUIRED")
                    self._consume(run_id, flow, action, attempt)
                    if attempt["status"] != "SUCCEEDED":
                        blocked[action["execution_path"]] = worker.outcome or "FAILED"
                    elif mode == "NEXT" or action["step_id"] in {target, trial_target}:
                        stopped = True
                        reached = action["step_id"] in {target, trial_target}
                if c.cancel.is_set():
                    for worker in list(c.branch_workers.values()):
                        worker.cancel.set()
                halted = stopped or c.cancel.is_set() or c.pause_requested.is_set() or c.closing
                if halted and not active:
                    if blocked and not c.cancel.is_set():
                        c._done(run_id, "INTERRUPTED" if "INTERRUPTED" in blocked.values() else "FAILED")
                        return
                    if stopped and not c.cancel.is_set() and not c.pause_requested.is_set() and not c.closing and not trial_target:
                        while True:
                            boundary = self._decide(run, flow)
                            if boundary is None:
                                return
                            if boundary.get("errors"):
                                c._done(run_id, "FAILED")
                                return
                            if boundary["done"] or boundary["actions"]:
                                c._done(run_id, "SUCCEEDED" if boundary["done"] else "PAUSED")
                                return
                    c._done(run_id, "CANCELLED" if c.cancel.is_set() else
                            "SUCCEEDED" if trial_target and reached else "PAUSED")
                    return
                if halted:
                    wait(active, timeout=0.05, return_when=FIRST_COMPLETED)
                    continue
                transition = self._decide(run, flow)
                if transition is None:
                    return
                actions = transition["actions"]
                for error in transition.get("errors", []):
                    blocked[error["execution_path"]] = "FAILED"
                live_owners = live_resource_paths(transition["cursor"])
                busy = {id(worker) for _, worker in active.values()}
                for owner, worker in list(c.branch_workers.items()):
                    if owner not in live_owners and id(worker) not in busy:
                        worker._stop_worker()
                        del c.branch_workers[owner]
                if transition["done"]:
                    if mode == "UNTIL" and not reached:
                        c.events.event(run_id, "TargetNotReached", {"step_id": target})
                    c._done(run_id, "SUCCEEDED")
                    return
                running_paths = {a["execution_path"] for a, _ in active.values()}
                changed = False
                delayed = False
                capacity_waiting = False
                for action in actions:
                    path = action["execution_path"]
                    if path in running_paths or path in blocked or path in waiting:
                        continue
                    prior = c.queries.latest_attempt_for_instance(run_id, path)
                    if prior:
                        self._consume(run_id, flow, action, prior)
                        if prior["status"] == "SUCCEEDED":
                            changed = True
                            if mode == "NEXT" or action["step_id"] in {target, trial_target}:
                                stopped = True
                                reached = action["step_id"] in {target, trial_target}
                                break
                        else:
                            blocked[path] = ("INTERRUPTED" if prior["status"] in {"UNKNOWN", "RUNNING"}
                                             or prior["effect_state"] in {"UNKNOWN", "SUCCEEDED"} else "FAILED")
                        continue
                    if len(active) >= capacity:
                        break
                    if c.queries.attempt_count(run_id) + len(active) >= 100_000:
                        blocked[path] = "FAILED"
                        c.events.event(run_id, "FlowDecisionFailed", {"code": "LOOP_LIMIT_EXCEEDED", "execution_path": path})
                        continue
                    context = action_cursor(transition["cursor"], path)
                    step = steps[action["step_id"]]
                    try:
                        effective = self._inputs(c.queries.run(run_id), step, context)
                    except TaskError:
                        effective = None
                    missing = ([name for name in c.missing_inputs(step["input_schema"], effective)
                                if name not in step["bindings"]] if effective is not None else [])
                    if missing:
                        waiting[path] = (step, effective, missing)
                        continue
                    deadline = self._delay_deadline(run_id, step, context, flow)
                    if deadline is not None and datetime.now(timezone.utc) < deadline:
                        delayed = True
                        c.writes.set_waiting_step(run_id, step["step_id"], deadline.isoformat())
                        continue
                    with c.lock:
                        if c.cancel.is_set() or c.pause_requested.is_set() or c.closing:
                            break
                        if c.execution_capacity is not None and not c.execution_capacity.try_acquire():
                            capacity_waiting = True
                            continue
                        try:
                            worker = self._worker_for(context.get("resource_path", "/"))
                            worker.session_run_id = run_id
                            worker.session_key = c.session_key
                            worker.resource_path = context.get("resource_path", "/")
                            worker.cancel.clear()
                            worker.outcome = None
                            future = executor.submit(worker._attempt, run, step, execution_path=path,
                                execution_slot_reserved=True,
                                input_resolver=lambda current, action_step, context=context: self._inputs(current, action_step, context))
                        except BaseException:
                            if c.execution_capacity is not None:
                                c.execution_capacity.release()
                            raise
                        active[future] = (action, worker)
                if changed:
                    continue
                if active:
                    wait(active, timeout=0.05, return_when=FIRST_COMPLETED)
                elif delayed or capacity_waiting:
                    c.cancel.wait(0.05)
                elif waiting:
                    path, (step, effective, missing) = next(iter(waiting.items()))
                    c.wait_for_inputs(run, "step", step, step["input_schema"], effective, missing, path)
                    return
                elif blocked:
                    c._done(run_id, "INTERRUPTED" if "INTERRUPTED" in blocked.values() else "FAILED")
                    return
                c.leases.heartbeat(run_id, now())
