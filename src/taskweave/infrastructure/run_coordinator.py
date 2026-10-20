"""Durable sequential coordinator; one spawn worker per active run."""

from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import threading
import time
from taskweave.core.validation import TaskError, dumps, fingerprint, resolve, validate
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, RunRepository, StepRepository, TaskRepository
from taskweave.infrastructure.sqlite_storage import now, uid, valid_id
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.worker_transport import WorkerTransport
from taskweave.core.run_ports import RunQueries, RunEvents, RunLeases, RunWrites
from taskweave.core.task_flow import is_linear_flow


class Coordinator:
    def __init__(self, runs: RunRepository | None, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, results: ResultRepository, registry, factory, home, recover=True, *, queries: RunQueries | None = None, events: RunEvents | None = None, leases: RunLeases | None = None, writes: RunWrites | None = None, flow_runs=None):
        self.runs, self.tasks, self.steps, self.environments, self.results = runs, tasks, steps, environments, results
        self.queries: RunQueries = queries if queries is not None else runs
        self.events: RunEvents = events if events is not None else runs
        self.leases: RunLeases = leases if leases is not None else runs
        self.writes: RunWrites = writes if writes is not None else runs
        self.flow_runs = flow_runs
        self.registry, self.factory = registry, factory
        self.home = Path(home).resolve()
        self.task_data_root = self.home / "tasks"
        self.lock = threading.RLock()
        self.transport = WorkerTransport(self.home, self.factory)
        self.thread = None
        self.session_key = self.session_run_id = None
        self.context_session_id = None
        self.context_recordings = set()
        self.context_recording_delivered = {}
        self.context_recording_capabilities = {}
        self.pause_requested = threading.Event()
        self.cancel = self.transport.cancel
        self.closing = False
        if recover:
            self.leases.recover()

    @staticmethod
    def lease_slot(run):
        return "trial:" + run["task_id"] if run["mode"] == "TRIAL" else "execution:" + run["run_id"]

    @property
    def process(self):
        return self.transport.process

    @process.setter
    def process(self, value):
        self.transport.process = value

    @property
    def pipe(self):
        return self.transport.pipe

    @pipe.setter
    def pipe(self, value):
        self.transport.pipe = value

    def _worker(self):
        if self.transport.start():
            self.context_session_id = uid()

    def _stop_worker(self, force=False):
        self.context_recordings.clear()
        self.context_recording_delivered.clear()
        self.context_recording_capabilities.clear()
        self.session_key = self.session_run_id = None
        self.context_session_id = None
        self.transport.stop(force)

    def _done(self, run_id, status):
        terminal = status in {"SUCCEEDED", "CANCELLED"}
        self.writes.finish_run(run_id, status, now() if terminal else None, terminal)
        if status == "CANCELLED":
            self._stop_worker()

    def _receipt(self, command_id, run_id, body, operation):
        return self.leases.command_receipt(command_id, run_id, body, operation)

    def start(
        self, run_id, command_id, mode="ALL", target_step_id=None, retry_step_id=None, start_step_id=None,
        retry_execution_path=None,
    ):
        with self.lock:
            started = []
            body = {
                "operation": "start",
                "mode": mode,
                "target": target_step_id,
                "retry": retry_step_id,
            }
            if retry_execution_path is not None:
                body["retry_execution_path"] = retry_execution_path

            if start_step_id is not None:
                body['from'] = start_step_id

            def operation():
                if self.context_recordings:
                    raise TaskError('CONTEXT_RECORDING_PENDING', '请先保存确认或丢弃录制，再运行步骤')
                run = self.queries.run(run_id)
                if mode not in {"NEXT", "UNTIL", "ALL"}:
                    raise TaskError("MODE_INVALID")
                if run["status"] not in {"READY", "PAUSED", "FAILED", "INTERRUPTED"}:
                    raise TaskError("RUN_STATE_INVALID")
                if self.thread and self.thread.is_alive():
                    raise TaskError("RUN_BUSY")
                if run["definition_hash"] != self.tasks.definition_hash(run["task_id"]):
                    raise TaskError("RUN_CONFIG_CHANGED")
                if json.loads(run["request_json"]).get(
                    "environment_hash"
                ) != fingerprint(self.environments.environment(run["environment_id"])):
                    raise TaskError("ENVIRONMENT_CHANGED")
                if json.loads(run["plugin_versions_json"]) != self.registry.versions:
                    raise TaskError("PLUGIN_VERSION_MISMATCH")
                if self.queries.has_unresolved_attempts(run_id):
                    raise TaskError("RECONCILIATION_REQUIRED")
                steps = self.steps.steps(run["task_id"])
                frozen_flow = json.loads(run["definition_json"]).get("flow") if run["definition_json"] else None
                controlled = (frozen_flow is not None and not is_linear_flow(frozen_flow)
                              and (run["mode"] != "TRIAL" or json.loads(run["request_json"]).get("flow_trial")))
                if run["trial_step_id"]:
                    if json.loads(run['request_json']).get('flow_trial'):
                        steps = steps[:next(i for i, s in enumerate(steps) if s['step_id'] == run['trial_step_id']) + 1]
                    else:
                        steps = [s for s in steps if s["step_id"] == run["trial_step_id"]]
                elif any(
                    s["validation_state"] != "VALIDATED"
                    for s in steps
                ):
                    raise TaskError("STEP_NOT_VALIDATED")
                ids = [s["step_id"] for s in steps]
                if mode == "UNTIL" and target_step_id not in ids:
                    raise TaskError("TARGET_INVALID")
                retry_ids = []
                if controlled:
                    if retry_step_id or start_step_id:
                        raise TaskError("FLOW_INSTANCE_REQUIRED")
                    if run["status"] == "FAILED" and not retry_execution_path:
                        raise TaskError("EXPLICIT_RETRY_REQUIRED")
                    if retry_execution_path:
                        instance = self.flow_runs.instance(run_id, retry_execution_path)
                        if instance is None or instance["kind"] != "action":
                            raise TaskError("FLOW_INSTANCE_REQUIRED")
                        self.flow_runs.retry_instance(run_id, retry_execution_path)
                elif retry_step_id:
                    if retry_step_id not in ids:
                        raise TaskError("TARGET_INVALID")
                    retry_ids = ids[ids.index(retry_step_id) :]
                elif run["status"] == "FAILED":
                    raise TaskError("EXPLICIT_RETRY_REQUIRED")
                slot = self.lease_slot(run)
                if not self.writes.start_run(run_id, body, slot, str(os.getpid()), now(), retry_ids):
                    raise TaskError("RUN_LEASE_BUSY")
                started.append(True)
                return {"run_id": run_id, "status": "RUNNING", "command_id": command_id}

            response = self._receipt(command_id, run_id, body, operation)
            if started:
                run = self.queries.run(run_id)
                key = (run['task_id'], run['mode'],
                       run['environment_id'], json.loads(run['request_json']).get('environment_hash'),
                       None if run['mode'] == 'TRIAL' else run_id)
                if self.session_key is not None and self.session_key != key:
                    self._stop_worker()
                self.session_key, self.session_run_id = key, run_id
                self.pause_requested.clear()
                self.cancel.clear()
                self.thread = threading.Thread(
                    target=self._drive, args=(run_id, mode, target_step_id), daemon=True
                )
                self.thread.start()
            return response

    def control(self, run_id, command_id, operation):
        with self.lock:
            owned = []

            def apply():
                if self.context_recordings and operation == 'abandon':
                    raise TaskError('CONTEXT_RECORDING_PENDING', '请先保存确认或丢弃录制，再结束实例')
                run = self.queries.run(run_id)
                if operation == "pause":
                    if run["status"] != "RUNNING":
                        raise TaskError("RUN_STATE_INVALID")
                    self.pause_requested.set()
                elif operation == "cancel":
                    if run["status"] != "RUNNING":
                        raise TaskError("RUN_STATE_INVALID")
                    self.cancel.set()
                elif operation == "abandon":
                    if run["status"] == "RUNNING":
                        raise TaskError("RUN_BUSY", "Cancel active execution first")
                    if run["status"] == "CANCELLED":
                        raise TaskError("RUN_STATE_INVALID")
                    if self.session_run_id == run_id:
                        owned.append(True)
                    owned.extend([True] if self.leases.runtime_lease(run_id) else [])
                    self.writes.cancel_run(run_id, now(), run['status'] == 'SUCCEEDED')
                else:
                    raise TaskError("COMMAND_INVALID")
                return {"run_id": run_id, "requested": operation}

            response = self._receipt(
                command_id, run_id, {"operation": operation}, apply
            )
            if (
                operation == "abandon"
                and owned
                and not (self.thread and self.thread.is_alive())
            ):
                self._stop_worker()
            return response

    def clear_task_runs(self, task_id):
        import shutil
        with self.lock:
            self.tasks.task(task_id)
            runs = self.queries.runs_for_task(task_id)
            ids = {run['run_id'] for run in runs}
            if any(run['status'] == 'RUNNING' for run in runs) or (self.session_run_id in ids and self.thread and self.thread.is_alive()):
                raise TaskError('RUN_BUSY', '请先暂停或结束正在执行的步骤，再清理任务')
            if self.session_run_id in ids:
                if self.context_recordings:
                    raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理未保存录制，再清理运行')
                self._stop_worker()
            self.writes.clear_task_run_records(task_id)
            directory = self.task_data_root / valid_id(task_id)
            if directory.exists():
                shutil.rmtree(directory)
            return {'task_id': task_id, 'deleted_runs': len(runs)}

    def delete_run(self, run_id):
        with self.lock:
            run = self.queries.run(run_id)
            if run['status'] == 'RUNNING' or (self.thread and self.thread.is_alive() and self.session_run_id == run_id):
                raise TaskError('RUN_BUSY', '请先结束正在执行的步骤，再删除执行')
            if self.session_run_id == run_id:
                if self.context_recordings:
                    raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理未保存录制，再删除运行')
                self._stop_worker()
            self.leases.release_lease(run_id)
            self.writes.reset_run_results(run_id)
            self.writes.delete_run_record(run_id)
            return {'deleted': run_id}

    def restart(self, run_id, command_id, target_step_id, start_step_id=None):
        with self.lock:
            if self.context_recordings:
                raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理未保存录制，再重新运行')
            if self.leases.has_command_receipt(command_id):
                return self.start(run_id, command_id, mode='UNTIL', target_step_id=target_step_id, start_step_id=start_step_id)
            run = self.queries.run(run_id)
            frozen_flow = json.loads(run["definition_json"]).get("flow") if run["definition_json"] else None
            if frozen_flow is not None and not is_linear_flow(frozen_flow):
                raise TaskError("FLOW_RESTART_NEW_RUN", "含条件或循环的流程请新建执行后从头运行")
            if run['mode'] != 'EXECUTION' or run['status'] == 'RUNNING' or (self.thread and self.thread.is_alive()):
                raise TaskError('RUN_BUSY', '请先暂停或结束正在执行的步骤')
            if run['definition_hash'] != self.tasks.definition_hash(run['task_id']):
                raise TaskError('RUN_CONFIG_CHANGED')
            if json.loads(run['request_json']).get('environment_hash') != fingerprint(self.environments.environment(run['environment_id'])):
                raise TaskError('ENVIRONMENT_CHANGED')
            if json.loads(run['plugin_versions_json']) != self.registry.versions:
                raise TaskError('PLUGIN_VERSION_MISMATCH')
            if any(s['validation_state'] != 'VALIDATED' for s in self.steps.steps(run['task_id'])):
                raise TaskError('STEP_NOT_VALIDATED')
            if target_step_id not in {s['step_id'] for s in self.steps.steps(run['task_id'])}:
                raise TaskError('TARGET_INVALID')
            if start_step_id is not None:
                ids = [step['step_id'] for step in self.steps.steps(run['task_id'])]
                if start_step_id not in ids or ids.index(start_step_id) > ids.index(target_step_id):
                    raise TaskError('TARGET_INVALID')
                for sid in ids[:ids.index(start_step_id)]:
                    if not self.queries.has_successful_attempt(run_id, sid):
                        raise TaskError('TARGET_INVALID', '请从前面尚未完成的步骤开始')
            else:
                self._stop_worker()
            self.leases.release_lease(run_id)
            self.writes.reset_run_results(run_id, from_step_id=start_step_id)
            return self.start(run_id, command_id, mode='UNTIL', target_step_id=target_step_id, start_step_id=start_step_id)

    def reconcile(self, attempt_id, decision, evidence, command_id):
        if decision not in {"not_completed", "completed"}:
            raise TaskError("RECONCILIATION_INVALID")
        evidence = evidence or {}
        a = self.queries.attempt(attempt_id)
        with self.lock:

            def apply():
                run = self.queries.run(a["run_id"])
                if run["status"] not in {"INTERRUPTED", "FAILED"}:
                    raise TaskError("RUN_STATE_INVALID")
                current = self.queries.attempt(attempt_id)
                if not current["valid"] or (
                    current["status"] != "UNKNOWN"
                    and not (
                        current["status"] == "FAILED"
                        and current["effect_state"] in {"SUCCEEDED", "UNKNOWN"}
                    )
                ):
                    raise TaskError("RECONCILIATION_INVALID")
                from taskweave.infrastructure.privacy import redact

                self.writes.update_attempt_reconciliation(
                    attempt_id,
                    "SUCCEEDED" if decision == "completed" else "FAILED",
                    "SUCCEEDED" if decision == "completed" else "NOT_STARTED",
                    dumps(redact({"decision": decision, "evidence": evidence})),
                    now() if decision == "completed" else None,
                )
                self.writes.set_run_status(a["run_id"], "PAUSED")
                return {"attempt_id": attempt_id, "decision": decision}

            return self._receipt(
                command_id,
                a["run_id"],
                {
                    "operation": "reconcile",
                    "attempt_id": attempt_id,
                    "decision": decision,
                    "evidence": evidence,
                },
                apply,
            )

    @staticmethod
    def missing_inputs(schema, values):
        return [key for key in schema.get('required', [])
                if key not in values or values[key] is None or values[key] == '']

    def effective_inputs(self, run, step):
        from taskweave.core.validation import automatic_inputs
        environment, _ = self.environments.environment(run['environment_id'])
        schema = json.loads(self.tasks.task(run['task_id'])['input_schema_json'])
        task = {key: spec['default'] for key, spec in schema.get('properties', {}).items() if 'default' in spec}
        task.update(json.loads(run['inputs_json']))
        request = json.loads(run['request_json'])
        values = (json.loads(run['inputs_json']) if run['mode'] == 'TRIAL' and not request.get('flow_trial')
                  else resolve(step['bindings'], task, environment,
                      lambda sid, output: self.results.read_output(run['run_id'], sid, output, self.registry)))
        values.update(request.get('step_inputs', {}).get(step['step_id'], {}))
        return automatic_inputs(step['input_schema'], environment, task, values)

    def wait_for_inputs(self, run, scope, step, schema, values, missing, execution_path=None):
        request = json.loads(self.queries.run(run['run_id'])['request_json'])
        editable = {key: spec for key, spec in schema.get('properties', {}).items()
                    if scope == 'task' or key not in step['bindings']}
        request['waiting_input'] = {'id': uid(), 'scope': scope, 'step_id': step['step_id'],
            'schema': {**schema, 'properties': editable,
                       'required': [key for key in schema.get('required', []) if key in editable]},
            'values': {key: values[key] for key in editable if key in values}, 'missing': missing}
        if execution_path is not None:
            request['waiting_input']['execution_path'] = execution_path
        self.writes.update_run_request(run['run_id'], dumps(request))
        self.events.event(run['run_id'], 'InputRequested', {'scope': scope, 'step_id': step['step_id'], 'missing': missing})
        self._done(run['run_id'], 'PAUSED')

    def provide_inputs(self, run_id, command_id, inputs, step_inputs=None, *, expected_input_id=None):
        with self.lock:
            def apply():
                run = self.queries.run(run_id)
                request = json.loads(run['request_json'])
                waiting = request.get('waiting_input')
                if run['status'] != 'PAUSED' or not waiting or (self.thread and self.thread.is_alive()):
                    raise TaskError('RUN_STATE_INVALID')
                if expected_input_id is not None and waiting.get('id') != expected_input_id:
                    raise TaskError('INPUT_REQUEST_STALE', '补参请求已变化，请重新打开补参窗口')
                if set(inputs) - set(waiting['schema'].get('properties', {})):
                    raise TaskError('INPUT_INVALID', '仅能填写当前请求的参数')
                values = {**waiting['values'], **inputs}
                if self.missing_inputs(waiting['schema'], values):
                    raise TaskError('INPUT_REQUIRED', '请填写必填参数')
                validate(values, {**waiting['schema'], 'additionalProperties': True})
                if waiting['scope'] == 'task':
                    task_values = {**json.loads(run['inputs_json']), **inputs}
                    task_inputs_json = dumps(task_values)
                    input_summary_json = dumps(redact(task_values))
                else:
                    if waiting.get('execution_path'):
                        request.setdefault('instance_inputs', {}).setdefault(waiting['execution_path'], {}).update(inputs)
                    else:
                        request.setdefault('step_inputs', {}).setdefault(waiting['step_id'], {}).update(inputs)
                    task_inputs_json = input_summary_json = None
                if step_inputs is not None:
                    if waiting['scope'] != 'task' or set(step_inputs) != {waiting['step_id']}:
                        raise TaskError('INPUT_INVALID')
                    normalized = self.writes.normalize_step_inputs(run['task_id'], step_inputs)
                    for sid, supplied in normalized.items():
                        request.setdefault('step_inputs', {}).setdefault(sid, {}).update(supplied)
                request.pop('waiting_input', None)
                self.writes.provide_run_inputs(
                    run_id, task_inputs_json, input_summary_json, dumps(request),
                    uid(), dumps({'scope': waiting['scope'], 'step_id': waiting['step_id'], 'keys': list(inputs)}), now(),
                )
                return {'run_id': run_id, 'status': 'PAUSED'}
            return self._receipt(command_id, run_id, {'operation': 'inputs', 'inputs': inputs,
                **({'step_inputs': step_inputs} if step_inputs is not None else {}),
                **({'expected_input_id': expected_input_id} if expected_input_id is not None else {})}, apply)

    def _drive(self, run_id, mode, target):
        try:
            run = self.queries.run(run_id)
            frozen_flow = json.loads(run["definition_json"]).get("flow") if run["definition_json"] else None
            if (self.flow_runs is not None and frozen_flow is not None and not is_linear_flow(frozen_flow)
                    and (run["mode"] != "TRIAL" or json.loads(run["request_json"]).get("flow_trial"))):
                from taskweave.infrastructure.flow_runner import FlowRunner
                FlowRunner(self).drive(run_id, mode, target)
                return
            steps = self.steps.steps(run["task_id"])
            if run["trial_step_id"]:
                if json.loads(run['request_json']).get('flow_trial'):
                    steps = steps[:next(i for i, s in enumerate(steps) if s['step_id'] == run['trial_step_id']) + 1]
                else:
                    steps = [s for s in steps if s["step_id"] == run["trial_step_id"]]
            start_step_id = json.loads(run['request_json']).get('last_command', {}).get('from')
            if start_step_id:
                ids = [step['step_id'] for step in steps]
                if start_step_id not in ids:
                    raise TaskError('TARGET_INVALID')
                steps = steps[ids.index(start_step_id):]
            task_schema = json.loads(self.tasks.task(run['task_id'])['input_schema_json'])
            task_values = json.loads(run['inputs_json'])
            missing = self.missing_inputs(task_schema, task_values)
            if missing and (run['mode'] == 'EXECUTION' or json.loads(run['request_json']).get('flow_trial') or steps[0]['position'] == 0):
                self.wait_for_inputs(run, 'task', steps[0], task_schema, task_values, missing)
                return
            for position, step in enumerate(steps):
                latest = self.queries.latest_attempt(run_id, step["step_id"])
                if latest and latest["status"] == "SUCCEEDED":
                    if mode == "UNTIL" and step["step_id"] == target:
                        break
                    continue
                if self.cancel.is_set():
                    self._done(run_id, "CANCELLED")
                    return
                if (
                    position
                    and (run["mode"] != "TRIAL" or json.loads(run["request_json"]).get("flow_trial"))
                    and not self._wait_interval(run_id, step, steps[position - 1])
                ):
                    return
                if self.cancel.is_set() or (position and self.pause_requested.is_set()):
                    self._done(
                        run_id, "CANCELLED" if self.cancel.is_set() else "PAUSED"
                    )
                    return
                run = self.queries.run(run_id)
                try:
                    effective = self.effective_inputs(run, step)
                except TaskError:
                    effective = None  # Let the normal attempt report invalid dependencies.
                missing = [key for key in self.missing_inputs(step['input_schema'], effective) if key not in step['bindings']] if effective is not None else []
                if missing:
                    self.wait_for_inputs(run, 'step', step, step['input_schema'], effective, missing)
                    return
                if not self._attempt(run, step):
                    return
                if self.cancel.is_set():
                    self._done(run_id, "CANCELLED")
                    return
                if (
                    self.pause_requested.is_set()
                    or mode == "NEXT"
                    or (mode == "UNTIL" and step["step_id"] == target)
                ):
                    break
            complete = all(
                self.queries.has_successful_attempt(run_id, s["step_id"])
                for s in steps
            )
            self._done(run_id, "SUCCEEDED" if complete else "PAUSED")
        except Exception as exc:
            self.events.event(
                run_id,
                "CoordinatorError",
                {"code": getattr(exc, "code", type(exc).__name__)},
            )
            for a in self.queries.attempts_with_status(run_id, "RUNNING"):
                refs = self.results.receipt(a)
                if refs is not None:
                    try:
                        self.writes.finish_attempt(a["attempt_id"], refs)
                        continue
                    except Exception:
                        pass  # Leave durable RUNNING evidence for restart reconciliation.
                else:
                    self.writes.mark_attempt_unknown(a["attempt_id"], "COORDINATOR_ERROR", None)
            self._done(run_id, "INTERRUPTED")
            self._stop_worker(force=True)

    def _wait_interval(self, run_id, step, previous):
        seconds = step.get("delay_after_previous_seconds", 0)
        if not seconds:
            self.writes.clear_waiting_step(run_id)
            return True
        attempt = self.queries.latest_attempt(run_id, previous["step_id"])
        if attempt is None:
            raise TaskError("NOT_FOUND")
        if attempt["status"] != "SUCCEEDED" or not attempt["finished_at"]:
            raise TaskError("PREVIOUS_STEP_NOT_SUCCEEDED")
        deadline = datetime.fromisoformat(attempt["finished_at"]) + timedelta(
            seconds=seconds
        )
        self.writes.set_waiting_step(run_id, step["step_id"], deadline.isoformat())
        heartbeat = 0
        while datetime.now(timezone.utc) < deadline:
            if self.cancel.is_set():
                self._done(run_id, "CANCELLED")
                return False
            if self.pause_requested.is_set() or self.closing:
                self._done(run_id, "PAUSED")
                return False
            if time.monotonic() >= heartbeat:
                self.leases.heartbeat(run_id, now())
                heartbeat = time.monotonic() + 1
            self.cancel.wait(0.05)
        self.writes.clear_waiting_step(run_id)
        return True

    def _attempt(self, run, step, execution_path=None, input_resolver=None):
        run_id = run["run_id"]
        attempt_id = uid()
        self.writes.create_attempt(attempt_id, run["task_id"], run_id, step["step_id"], step["content_hash"], now(), execution_path=execution_path)
        try:
            self.registry.check(step)
            environment, secret_refs = self.environments.environment(run["environment_id"])
            inputs = (input_resolver(self.queries.run(run_id), step)
                      if input_resolver is not None else self.effective_inputs(self.queries.run(run_id), step))
            validate(inputs, step["input_schema"])
        except TaskError as exc:
            self._fail(attempt_id, run_id, exc.code, "resolve", "NOT_STARTED", str(exc))
            return False
        self.writes.set_attempt_input_summary(attempt_id, dumps(redact(inputs)))
        self._worker()
        task_schema = json.loads(self.tasks.task(run['task_id'])['input_schema_json'])
        task_parameters = {key: spec['default'] for key, spec in task_schema.get('properties', {}).items() if 'default' in spec}
        task_parameters.update({key: value for key, value in json.loads(run['inputs_json']).items()
                                if key in task_schema.get('properties', {})})
        self.transport.send(
            {
            "kind": "execute",
            "scope": {
                "task_id": run["task_id"],
                "run_id": run_id,
                "step_id": step["step_id"],
                "attempt_id": attempt_id,
                "execution_path": execution_path,
            },
            "step": step,
            "inputs": inputs,
            "environment": environment,
            "secret_refs": secret_refs,
            "task_parameters": task_parameters,
        }
        )
        deadline = time.monotonic() + step["timeout_ms"] / 1000
        last_heartbeat = time.monotonic()
        timed_out = False
        while True:
            if self.transport.poll(0.05):
                try:
                    event = self.transport.receive()
                except (EOFError, OSError):
                    break
                if event["attempt_id"] != attempt_id:
                    continue
                last_heartbeat = time.monotonic()
                kind, payload = event["kind"], event["payload"]
                if kind == "Heartbeat":
                    self.leases.heartbeat(run_id, now())
                    continue
                self.events.event(run_id, kind, payload, attempt_id, event["event_id"])
                if kind == "AttemptCompleted":
                    self.writes.finish_attempt(attempt_id, payload["refs"])
                    return True
                if kind == "AttemptFailed":
                    self.writes.register_refs(attempt_id, payload.get("refs", []))
                    if (
                        payload["code"] == "CANCELLED"
                        and payload["effect_state"] == "NOT_STARTED"
                    ):
                        self.writes.mark_attempt_cancelled(attempt_id, now())
                        self._done(run_id, "CANCELLED")
                        return False
                    self._fail(
                        attempt_id,
                        run_id,
                        payload["code"],
                        payload["phase"],
                        payload["effect_state"],
                        payload["message"],
                    )
                    return False
            if not self.process.is_alive():
                break
            if time.monotonic() > deadline or time.monotonic() - last_heartbeat > 10:
                if not timed_out:
                    self.cancel.set()
                    deadline = time.monotonic() + 1
                    last_heartbeat = time.monotonic()
                    timed_out = True
                else:
                    break
        self._stop_worker(force=True)
        a = self.queries.attempt(attempt_id)
        refs = self.results.receipt(a)
        if refs is not None:
            self.writes.finish_attempt(attempt_id, refs)
            self._done(run_id, "INTERRUPTED")
        else:
            self.writes.mark_attempt_unknown(
                attempt_id, "WORKER_TIMEOUT" if timed_out else "WORKER_LOST", "execute", now()
            )
            self._done(run_id, "INTERRUPTED")
        return False

    def _fail(self, attempt_id, run_id, code, phase, effect, message):
        self.writes.mark_attempt_failed(attempt_id, effect, code, phase, message[:4096], now())
        self._done(run_id, "FAILED")

    def describe_run(self, run_id):
        with self.lock:
            run = self.queries.run_details(run_id)
            retained = self.session_run_id == run_id and self.process is not None and self.process.is_alive()
            leased = bool(self.leases.runtime_lease(run_id))
            run['can_end'] = run['status'] != 'CANCELLED' and (retained or leased)
            return run

    def context_sessions(self, task_id):
        with self.lock:
            if not self.session_run_id or not self.process or not self.process.is_alive():
                return []
            run = self.queries.run(self.session_run_id)
            if run['task_id'] != task_id or run['status'] not in {'PAUSED', 'FAILED', 'SUCCEEDED'} or (self.thread and self.thread.is_alive()):
                return []
            return [self.queries.run_details(run['run_id'])]

    def collect_context(self, run_id, step_id, provider_id, request=None, expected_session_id=None, include_view=True):
        return self._observe_context(run_id, step_id, provider_id, request, expected_session_id=expected_session_id, include_view=include_view)

    def record_context(self, run_id, step_id, provider_id, operation, *, recording_id=None,
                       after=0, through=None, limit=100, request=None,
                       expected_session_id=None, include_view=True):
        from taskweave.core.context_recording import recording_command
        command = recording_command(operation, recording_id=recording_id, after=after,
                                    through=through, limit=limit)
        if operation != 'start' and not expected_session_id:
            raise TaskError('CONTEXT_SESSION_CHANGED', '录制命令必须核对原运行实例')
        return self._observe_context(run_id, step_id, provider_id, request,
            expected_session_id=expected_session_id, include_view=include_view, recording=command)

    def context_targets(self, run_id, step_id, provider_id, request=None):
        return self._observe_context(run_id, step_id, provider_id, request, targets=True)

    def _observe_context(self, run_id, step_id, provider_id, request=None, targets=False, expected_session_id=None, include_view=True, recording=None):
        if not self.lock.acquire(blocking=False):
            raise TaskError("CONTEXT_SESSION_BUSY", "该实例正在执行或采集上下文")
        try:
            run = self.queries.run(run_id)
            step = self.steps.step(step_id)
            if (
                run["status"] not in {"PAUSED", "FAILED", "SUCCEEDED"}
                or step["task_id"] != run["task_id"]
            ):
                raise TaskError("CONTEXT_RUN_STATE_INVALID")
            if self.thread and self.thread.is_alive():
                raise TaskError("RUN_BUSY")
            retained = self.session_run_id == run_id and self.process is not None and self.process.is_alive()
            if expected_session_id and (not retained or self.context_session_id != expected_session_id):
                raise TaskError("CONTEXT_SESSION_CHANGED", "采集实例已结束或变化，请刷新后重新选择")
            if targets and not retained:
                return {"session_id": None, "targets": []}
            if self.session_run_id != run_id or not self.process or not self.process.is_alive():
                raise TaskError(
                    "SESSION_NOT_AVAILABLE",
                    "Browser resources were lost; restart in an explicit trial",
                )
            if recording is not None:
                key = (step_id, provider_id, recording.recording_id)
                if recording.operation == 'start' and len(self.context_recordings) >= 16:
                    raise TaskError('CONTEXT_RECORDING_PENDING')
                if (recording.operation != 'start' and key not in self.context_recordings
                        and not (recording.operation == 'ack' and key in self.context_recording_delivered)):
                    raise TaskError('CONTEXT_RECORDING_UNAVAILABLE')
                if recording.operation == 'ack' and recording.through > self.context_recording_delivered.get(key, 0):
                    raise TaskError('CONTEXT_RECORDING_REQUEST_INVALID', '不能确认未读取证据')
                if recording.operation != 'start':
                    # Only the already-owned recording keeps its original
                    # provider authority. New sessions use the edited step.
                    step = {**step, 'capabilities': self.context_recording_capabilities[key]}
            environment, secret_refs = self.environments.environment(run["environment_id"])
            request_id = uid()
            self.transport.send(
                {
                "kind": "context_record" if recording is not None else "context_targets" if targets else "context",
                **({"recording": asdict(recording)} if recording is not None else {}),
                "provider_id": provider_id,
                "request": request or {},
                "include_view": include_view,
                "scope": {
                    "task_id": run["task_id"],
                    "run_id": run_id,
                    "step_id": step_id,
                    "attempt_id": request_id,
                },
                "step": step,
                "inputs": {},
                "environment": environment,
                "secret_refs": secret_refs,
                "task_parameters": json.loads(run["inputs_json"]),
            }
            )
            deadline = time.monotonic() + (60 if recording is not None else 30)
            while time.monotonic() < deadline:
                if self.transport.poll(0.1):
                    event = self.transport.receive()
                    if event["attempt_id"] != request_id:
                        continue
                    if event['kind'] == 'ContextRecordingCompleted':
                        result = event['payload']
                        key = (step_id, provider_id, result['recording_id'])
                        if recording.operation == 'start':
                            self.context_recordings.add(key)
                            self.context_recording_delivered[key] = 0
                            self.context_recording_capabilities[key] = list(step['capabilities'])
                            for previous in list(self.context_recording_delivered):
                                if len(self.context_recording_delivered) <= 64: break
                                if previous not in self.context_recordings:
                                    del self.context_recording_delivered[previous]
                                    self.context_recording_capabilities.pop(previous, None)
                        elif recording.operation == 'read':
                            self.context_recording_delivered[key] = max(self.context_recording_delivered.get(key, 0), result['cursor'])
                        elif result['state'] == 'DISCARDED' or (recording.operation == 'ack'
                                and result['state'] == 'STOPPED' and result['available_after'] == result['cursor']):
                            self.context_recordings.discard(key)
                            if result['state'] == 'DISCARDED':
                                self.context_recording_delivered.pop(key, None)
                                self.context_recording_capabilities.pop(key, None)
                        return {**result, 'session_id': self.context_session_id}
                    if event["kind"] == "ContextCompleted":
                        return event["payload"]
                    if event["kind"] == "ContextTargetsCompleted":
                        return {"session_id": self.context_session_id, "targets": event["payload"]["targets"]}
                    if event["kind"] == "AttemptFailed":
                        raise TaskError(
                            event["payload"]["code"], event["payload"]["message"]
                        )
                if not self.process.is_alive():
                    break
            self._stop_worker(force=True)
            self._done(run_id, "INTERRUPTED")
            raise TaskError("CONTEXT_TIMEOUT")
        finally:
            self.lock.release()

    def wait(self, run_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.queries.run(run_id)["status"] != "RUNNING":
                if self.thread:
                    self.thread.join(3)
                return self.queries.run_details(run_id)
            time.sleep(0.02)
        raise TaskError("WAIT_TIMEOUT")

    def close(self):
        owned_run = self.session_run_id
        with self.lock:
            self.closing = True
            self.pause_requested.set()
            self.cancel.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(2)
            if self.thread.is_alive() and self.process and self.process.is_alive():
                self.transport.terminate()
                self.thread.join(5)
        self._stop_worker()
        if not (self.thread and self.thread.is_alive()):
            if owned_run:
                self.leases.release_lease(owned_run)
