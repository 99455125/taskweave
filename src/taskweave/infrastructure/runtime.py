"""Durable sequential coordinator; one spawn worker per active run."""

from datetime import datetime, timezone, timedelta
import json
import multiprocessing
import os
from pathlib import Path
import threading
import time
from taskweave.core.validation import TaskError, dumps, fingerprint, resolve, validate
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, RunRepository, StepRepository, TaskRepository
from taskweave.infrastructure.storage import now, uid, valid_id
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.worker import worker_main


class Coordinator:
    def __init__(self, runs: RunRepository, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, results: ResultRepository, registry, factory, home, recover=True):
        self.runs, self.tasks, self.steps, self.environments, self.results = runs, tasks, steps, environments, results
        self.registry, self.factory = registry, factory
        self.home = Path(home).resolve()
        self.task_data_root = self.home / "tasks"
        self.lock = threading.RLock()
        self.process = self.pipe = self.thread = None
        self.session_key = self.session_run_id = None
        self.context_session_id = None
        self.pause_requested = threading.Event()
        self.cancel = multiprocessing.get_context("spawn").Event()
        self.closing = False
        if recover:
            self.runs.recover()

    @staticmethod
    def lease_slot(run):
        return "trial:" + run["task_id"] if run["mode"] == "TRIAL" else "execution:" + run["run_id"]

    def _worker(self):
        if self.process and self.process.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self.pipe, child = ctx.Pipe()
        self.process = ctx.Process(
            target=worker_main,
            args=(child, self.cancel, str(self.home), self.factory, os.getpid()),
            daemon=True,
        )
        self.process.start()
        self.context_session_id = uid()
        child.close()

    def _stop_worker(self, force=False):
        self.session_key = self.session_run_id = None
        self.context_session_id = None
        if self.process:
            if self.process.is_alive() and not force:
                try:
                    self.pipe.send(dumps({"kind": "close"}))
                except (OSError, EOFError):
                    pass
                self.process.join(2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.process.close()
            self.process = None
        if self.pipe:
            self.pipe.close()
            self.pipe = None

    def _done(self, run_id, status):
        terminal = status in {"SUCCEEDED", "CANCELLED"}
        self.runs.finish_run(run_id, status, now() if terminal else None, terminal)
        if status == "CANCELLED":
            self._stop_worker()

    def _receipt(self, command_id, run_id, body, operation):
        return self.runs.command_receipt(command_id, run_id, body, operation)

    def start(
        self, run_id, command_id, mode="ALL", target_step_id=None, retry_step_id=None, start_step_id=None
    ):
        with self.lock:
            started = []
            body = {
                "operation": "start",
                "mode": mode,
                "target": target_step_id,
                "retry": retry_step_id,
            }

            if start_step_id is not None:
                body['from'] = start_step_id

            def operation():
                run = self.runs.run(run_id)
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
                if self.runs.has_unresolved_attempts(run_id):
                    raise TaskError("RECONCILIATION_REQUIRED")
                steps = self.steps.steps(run["task_id"])
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
                if retry_step_id:
                    if retry_step_id not in ids:
                        raise TaskError("TARGET_INVALID")
                    retry_ids = ids[ids.index(retry_step_id) :]
                elif run["status"] == "FAILED":
                    raise TaskError("EXPLICIT_RETRY_REQUIRED")
                slot = self.lease_slot(run)
                if not self.runs.start_run(run_id, body, slot, str(os.getpid()), now(), retry_ids):
                    raise TaskError("RUN_LEASE_BUSY")
                started.append(True)
                return {"run_id": run_id, "status": "RUNNING", "command_id": command_id}

            response = self._receipt(command_id, run_id, body, operation)
            if started:
                run = self.runs.run(run_id)
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
                run = self.runs.run(run_id)
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
                    owned.extend([True] if self.runs.runtime_lease(run_id) else [])
                    self.runs.cancel_run(run_id, now(), run['status'] == 'SUCCEEDED')
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
            runs = self.runs.runs_for_task(task_id)
            ids = {run['run_id'] for run in runs}
            if any(run['status'] == 'RUNNING' for run in runs) or (self.session_run_id in ids and self.thread and self.thread.is_alive()):
                raise TaskError('RUN_BUSY', '请先暂停或结束正在执行的步骤，再清理任务')
            if self.session_run_id in ids:
                self._stop_worker()
            self.runs.clear_task_run_records(task_id)
            directory = self.task_data_root / valid_id(task_id)
            if directory.exists():
                shutil.rmtree(directory)
            return {'task_id': task_id, 'deleted_runs': len(runs)}

    def delete_run(self, run_id):
        with self.lock:
            run = self.runs.run(run_id)
            if run['status'] == 'RUNNING' or (self.thread and self.thread.is_alive() and self.session_run_id == run_id):
                raise TaskError('RUN_BUSY', '请先结束正在执行的步骤，再删除执行')
            if self.session_run_id == run_id:
                self._stop_worker()
            self.runs.release_lease(run_id)
            self.runs.reset_run_results(run_id)
            self.runs.delete_run_record(run_id)
            return {'deleted': run_id}

    def restart(self, run_id, command_id, target_step_id, start_step_id=None):
        with self.lock:
            if self.runs.has_command_receipt(command_id):
                return self.start(run_id, command_id, mode='UNTIL', target_step_id=target_step_id, start_step_id=start_step_id)
            run = self.runs.run(run_id)
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
                    if not self.runs.has_successful_attempt(run_id, sid):
                        raise TaskError('TARGET_INVALID', '请从前面尚未完成的步骤开始')
            else:
                self._stop_worker()
            self.runs.release_lease(run_id)
            self.runs.reset_run_results(run_id, from_step_id=start_step_id)
            return self.start(run_id, command_id, mode='UNTIL', target_step_id=target_step_id, start_step_id=start_step_id)

    def reconcile(self, attempt_id, decision, evidence, command_id):
        if decision not in {"not_completed", "completed"}:
            raise TaskError("RECONCILIATION_INVALID")
        evidence = evidence or {}
        a = self.runs.attempt(attempt_id)
        with self.lock:

            def apply():
                run = self.runs.run(a["run_id"])
                if run["status"] not in {"INTERRUPTED", "FAILED"}:
                    raise TaskError("RUN_STATE_INVALID")
                current = self.runs.attempt(attempt_id)
                if not current["valid"] or (
                    current["status"] != "UNKNOWN"
                    and not (
                        current["status"] == "FAILED"
                        and current["effect_state"] in {"SUCCEEDED", "UNKNOWN"}
                    )
                ):
                    raise TaskError("RECONCILIATION_INVALID")
                from taskweave.infrastructure.privacy import redact

                self.runs.update_attempt_reconciliation(
                    attempt_id,
                    "SUCCEEDED" if decision == "completed" else "FAILED",
                    "SUCCEEDED" if decision == "completed" else "NOT_STARTED",
                    dumps(redact({"decision": decision, "evidence": evidence})),
                    now() if decision == "completed" else None,
                )
                self.runs.set_run_status(a["run_id"], "PAUSED")
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

    def wait_for_inputs(self, run, scope, step, schema, values, missing):
        request = json.loads(self.runs.run(run['run_id'])['request_json'])
        editable = {key: spec for key, spec in schema.get('properties', {}).items()
                    if scope == 'task' or key not in step['bindings']}
        request['waiting_input'] = {'id': uid(), 'scope': scope, 'step_id': step['step_id'],
            'schema': {**schema, 'properties': editable,
                       'required': [key for key in schema.get('required', []) if key in editable]},
            'values': {key: values[key] for key in editable if key in values}, 'missing': missing}
        self.runs.update_run_request(run['run_id'], dumps(request))
        self.runs.event(run['run_id'], 'InputRequested', {'scope': scope, 'step_id': step['step_id'], 'missing': missing})
        self._done(run['run_id'], 'PAUSED')

    def provide_inputs(self, run_id, command_id, inputs, step_inputs=None):
        with self.lock:
            def apply():
                run = self.runs.run(run_id)
                request = json.loads(run['request_json'])
                waiting = request.get('waiting_input')
                if run['status'] != 'PAUSED' or not waiting or (self.thread and self.thread.is_alive()):
                    raise TaskError('RUN_STATE_INVALID')
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
                    request.setdefault('step_inputs', {}).setdefault(waiting['step_id'], {}).update(inputs)
                    task_inputs_json = input_summary_json = None
                if step_inputs is not None:
                    if waiting['scope'] != 'task' or set(step_inputs) != {waiting['step_id']}:
                        raise TaskError('INPUT_INVALID')
                    normalized = self.runs.normalize_step_inputs(run['task_id'], step_inputs)
                    for sid, supplied in normalized.items():
                        request.setdefault('step_inputs', {}).setdefault(sid, {}).update(supplied)
                request.pop('waiting_input', None)
                self.runs.provide_run_inputs(
                    run_id, task_inputs_json, input_summary_json, dumps(request),
                    uid(), dumps({'scope': waiting['scope'], 'step_id': waiting['step_id'], 'keys': list(inputs)}), now(),
                )
                return {'run_id': run_id, 'status': 'PAUSED'}
            return self._receipt(command_id, run_id, {'operation': 'inputs', 'inputs': inputs, **({'step_inputs': step_inputs} if step_inputs is not None else {})}, apply)

    def _drive(self, run_id, mode, target):
        try:
            run = self.runs.run(run_id)
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
                latest = self.runs.latest_attempt(run_id, step["step_id"])
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
                run = self.runs.run(run_id)
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
                self.runs.has_successful_attempt(run_id, s["step_id"])
                for s in steps
            )
            self._done(run_id, "SUCCEEDED" if complete else "PAUSED")
        except Exception as exc:
            self.runs.event(
                run_id,
                "CoordinatorError",
                {"code": getattr(exc, "code", type(exc).__name__)},
            )
            for a in self.runs.attempts_with_status(run_id, "RUNNING"):
                refs = self.results.receipt(a)
                if refs is not None:
                    try:
                        self.runs.finish_attempt(a["attempt_id"], refs)
                        continue
                    except Exception:
                        pass  # Leave durable RUNNING evidence for restart reconciliation.
                else:
                    self.runs.mark_attempt_unknown(a["attempt_id"], "COORDINATOR_ERROR", None)
            self._done(run_id, "INTERRUPTED")
            self._stop_worker(force=True)

    def _wait_interval(self, run_id, step, previous):
        seconds = step.get("delay_after_previous_seconds", 0)
        if not seconds:
            self.runs.clear_waiting_step(run_id)
            return True
        attempt = self.runs.latest_attempt(run_id, previous["step_id"])
        if attempt is None:
            raise TaskError("NOT_FOUND")
        if attempt["status"] != "SUCCEEDED" or not attempt["finished_at"]:
            raise TaskError("PREVIOUS_STEP_NOT_SUCCEEDED")
        deadline = datetime.fromisoformat(attempt["finished_at"]) + timedelta(
            seconds=seconds
        )
        self.runs.set_waiting_step(run_id, step["step_id"], deadline.isoformat())
        heartbeat = 0
        while datetime.now(timezone.utc) < deadline:
            if self.cancel.is_set():
                self._done(run_id, "CANCELLED")
                return False
            if self.pause_requested.is_set() or self.closing:
                self._done(run_id, "PAUSED")
                return False
            if time.monotonic() >= heartbeat:
                self.runs.heartbeat(run_id, now())
                heartbeat = time.monotonic() + 1
            self.cancel.wait(0.05)
        self.runs.clear_waiting_step(run_id)
        return True

    def _attempt(self, run, step):
        run_id = run["run_id"]
        attempt_id = uid()
        self.runs.create_attempt(attempt_id, run["task_id"], run_id, step["step_id"], step["content_hash"], now())
        try:
            self.registry.check(step)
            environment, secret_refs = self.environments.environment(run["environment_id"])
            inputs = self.effective_inputs(self.runs.run(run_id), step)
            validate(inputs, step["input_schema"])
        except TaskError as exc:
            self._fail(attempt_id, run_id, exc.code, "resolve", "NOT_STARTED", str(exc))
            return False
        self.runs.set_attempt_input_summary(attempt_id, dumps(redact(inputs)))
        self._worker()
        task_schema = json.loads(self.tasks.task(run['task_id'])['input_schema_json'])
        task_parameters = {key: spec['default'] for key, spec in task_schema.get('properties', {}).items() if 'default' in spec}
        task_parameters.update({key: value for key, value in json.loads(run['inputs_json']).items()
                                if key in task_schema.get('properties', {})})
        self.pipe.send(
            dumps(
                {
                    "kind": "execute",
                    "scope": {
                        "task_id": run["task_id"],
                        "run_id": run_id,
                        "step_id": step["step_id"],
                        "attempt_id": attempt_id,
                    },
                    "step": step,
                    "inputs": inputs,
                    "environment": environment,
                    "secret_refs": secret_refs,
                    "task_parameters": task_parameters,
                }
            )
        )
        deadline = time.monotonic() + step["timeout_ms"] / 1000
        last_heartbeat = time.monotonic()
        timed_out = False
        while True:
            if self.pipe.poll(0.05):
                try:
                    event = json.loads(self.pipe.recv())
                except (EOFError, OSError):
                    break
                if event["attempt_id"] != attempt_id:
                    continue
                last_heartbeat = time.monotonic()
                kind, payload = event["kind"], event["payload"]
                if kind == "Heartbeat":
                    self.runs.heartbeat(run_id, now())
                    continue
                self.runs.event(run_id, kind, payload, attempt_id, event["event_id"])
                if kind == "AttemptCompleted":
                    self.runs.finish_attempt(attempt_id, payload["refs"])
                    return True
                if kind == "AttemptFailed":
                    self.runs.register_refs(attempt_id, payload.get("refs", []))
                    if (
                        payload["code"] == "CANCELLED"
                        and payload["effect_state"] == "NOT_STARTED"
                    ):
                        self.runs.mark_attempt_cancelled(attempt_id, now())
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
        a = self.runs.attempt(attempt_id)
        refs = self.results.receipt(a)
        if refs is not None:
            self.runs.finish_attempt(attempt_id, refs)
            self._done(run_id, "INTERRUPTED")
        else:
            self.runs.mark_attempt_unknown(
                attempt_id, "WORKER_TIMEOUT" if timed_out else "WORKER_LOST", "execute", now()
            )
            self._done(run_id, "INTERRUPTED")
        return False

    def _fail(self, attempt_id, run_id, code, phase, effect, message):
        self.runs.mark_attempt_failed(attempt_id, effect, code, phase, message[:4096], now())
        self._done(run_id, "FAILED")

    def describe_run(self, run_id):
        with self.lock:
            run = self.runs.run_details(run_id)
            retained = self.session_run_id == run_id and self.process is not None and self.process.is_alive()
            leased = bool(self.runs.runtime_lease(run_id))
            run['can_end'] = run['status'] != 'CANCELLED' and (retained or leased)
            return run

    def context_sessions(self, task_id):
        with self.lock:
            if not self.session_run_id or not self.process or not self.process.is_alive():
                return []
            run = self.runs.run(self.session_run_id)
            if run['task_id'] != task_id or run['status'] not in {'PAUSED', 'FAILED', 'SUCCEEDED'} or (self.thread and self.thread.is_alive()):
                return []
            return [self.runs.run_details(run['run_id'])]

    def collect_context(self, run_id, step_id, provider_id, request=None, expected_session_id=None, include_view=True):
        return self._observe_context(run_id, step_id, provider_id, request, expected_session_id=expected_session_id, include_view=include_view)

    def context_targets(self, run_id, step_id, provider_id, request=None):
        return self._observe_context(run_id, step_id, provider_id, request, targets=True)

    def _observe_context(self, run_id, step_id, provider_id, request=None, targets=False, expected_session_id=None, include_view=True):
        if not self.lock.acquire(blocking=False):
            raise TaskError("CONTEXT_SESSION_BUSY", "该实例正在执行或采集上下文")
        try:
            run = self.runs.run(run_id)
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
            environment, secret_refs = self.environments.environment(run["environment_id"])
            request_id = uid()
            self.pipe.send(
                dumps(
                    {
                        "kind": "context_targets" if targets else "context",
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
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.pipe.poll(0.1):
                    event = json.loads(self.pipe.recv())
                    if event["attempt_id"] != request_id:
                        continue
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
            if self.runs.run(run_id)["status"] != "RUNNING":
                if self.thread:
                    self.thread.join(3)
                return self.runs.run_details(run_id)
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
                self.process.terminate()
                self.thread.join(5)
        self._stop_worker()
        if not (self.thread and self.thread.is_alive()):
            if owned_run:
                self.runs.release_lease(owned_run)


class CoordinatorPool:
    """Route each task trial and each formal execution to an isolated coordinator.

    Core owns lifecycle only; plugin resources remain inside each coordinator's
    worker and are still opened/closed exclusively by ResourceProvider hooks.
    """
    def __init__(self, runs: RunRepository, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, results: ResultRepository, registry, factory, home, max_concurrency=8):
        self.runs, self.tasks, self.steps, self.environments, self.results = runs, tasks, steps, environments, results
        self._registry, self.factory = registry, factory
        self.home = Path(home).resolve()
        self.task_data_root = self.home / "tasks"
        self.lock = threading.RLock()
        self.max_concurrency = max_concurrency
        self.instances = {}
        self.last = None
        self.runs.recover()

    @property
    def registry(self): return self._registry

    @registry.setter
    def registry(self, value):
        self._registry = value
        for coordinator in self.instances.values():
            coordinator.registry = value

    def _key(self, run):
        return ('trial', run['task_id']) if run['mode'] == 'TRIAL' else ('execution', run['run_id'])

    def _for_run(self, run_id, create=True):
        run = self.runs.run(run_id)
        key = self._key(run)
        coordinator = self.instances.get(key)
        if coordinator is None and create:
            coordinator = Coordinator(
                self.runs, self.tasks, self.steps, self.environments, self.results,
                self.registry, self.factory, self.home, recover=False,
            )
            self.instances[key] = coordinator
        if coordinator is not None:
            self.last = coordinator
        return coordinator

    @property
    def process(self): return self.last.process if self.last else None
    @property
    def thread(self): return self.last.thread if self.last else None
    @property
    def session_run_id(self): return self.last.session_run_id if self.last else None
    @session_run_id.setter
    def session_run_id(self, value):
        if self.last is None:
            run = self.runs.run(value)
            self.last = self._for_run(run['run_id'])
        self.last.session_run_id = value

    def start(self, run_id, *args, **kwargs):
        with self.lock:
            coordinator = self._for_run(run_id)
            active = sum(bool(item.thread and item.thread.is_alive()) for item in self.instances.values())
            if not (coordinator.thread and coordinator.thread.is_alive()) and active >= self.max_concurrency:
                raise TaskError('EXECUTOR_CAPACITY', f'执行器已达并发上限 {self.max_concurrency}')
            return coordinator.start(run_id, *args, **kwargs)

    def set_max_concurrency(self, value):
        value = int(value)
        if not 1 <= value <= 8:
            raise TaskError('FORM_INVALID', '执行器并发线程数必须在 1 到 8 之间')
        self.max_concurrency = value
        return value
    def control(self, run_id, *args, **kwargs): return self._for_run(run_id).control(run_id, *args, **kwargs)
    def restart(self, run_id, *args, **kwargs): return self._for_run(run_id).restart(run_id, *args, **kwargs)
    def reconcile(self, attempt_id, *args, **kwargs):
        run_id = self.runs.attempt_run_id(attempt_id)
        return self._for_run(run_id).reconcile(attempt_id, *args, **kwargs)
    def provide_inputs(self, run_id, *args, **kwargs): return self._for_run(run_id).provide_inputs(run_id, *args, **kwargs)
    def wait(self, run_id, *args, **kwargs): return self._for_run(run_id).wait(run_id, *args, **kwargs)
    def describe_run(self, run_id):
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            run = self.runs.run_details(run_id)
            run['can_end'] = bool(self.runs.runtime_lease(run_id))
            return run
        return coordinator.describe_run(run_id)
    def collect_context(self, run_id, *args, **kwargs):
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            code = "CONTEXT_SESSION_CHANGED" if kwargs.get("expected_session_id") else "SESSION_NOT_AVAILABLE"
            raise TaskError(code, "采集实例已结束或变化，请刷新后重新选择")
        return coordinator.collect_context(run_id, *args, **kwargs)
    def context_targets(self, run_id, step_id, provider_id, request=None):
        step = self.steps.step(step_id)
        if step["task_id"] != self.runs.run(run_id)["task_id"]:
            raise TaskError("CONTEXT_RUN_STATE_INVALID")
        if not any(provider_id in p.authoring(step["capabilities"]).context_provider_ids for p in self.registry.selected_plugins(step["capabilities"])):
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            return {"session_id": None, "targets": []}
        return coordinator.context_targets(run_id, step_id, provider_id, request)
    def context_sessions(self, task_id):
        result = []
        for (kind, owner), coordinator in list(self.instances.items()):
            if (kind == 'trial' and owner == task_id) or kind == 'execution':
                result.extend(coordinator.context_sessions(task_id))
        return result
    def active_instances(self):
        rows = []
        for key, coordinator in self.instances.items():
            if coordinator.process and coordinator.process.is_alive() and coordinator.session_run_id:
                run = coordinator.describe_run(coordinator.session_run_id)
                rows.append({**run, 'instance_type': key[0]})
        return rows
    def delete_run(self, run_id):
        run = self.runs.run(run_id)
        key = self._key(run)
        coordinator = self._for_run(run_id)
        result = coordinator.delete_run(run_id)
        coordinator.close()
        self.instances.pop(key, None)
        return result
    def clear_task_runs(self, task_id):
        for key, coordinator in list(self.instances.items()):
            belongs = key == ('trial', task_id)
            if not belongs and coordinator.session_run_id:
                try:
                    belongs = self.runs.run(coordinator.session_run_id)['task_id'] == task_id
                except TaskError as exc:
                    if exc.code != 'NOT_FOUND':
                        raise
                    belongs = True  # stale instance whose run was already removed
            if belongs:
                coordinator.close()
                self.instances.pop(key, None)
        helper = Coordinator(
            self.runs, self.tasks, self.steps, self.environments, self.results,
            self.registry, self.factory, self.home, recover=False,
        )
        return helper.clear_task_runs(task_id)
    def _stop_worker(self, force=False):
        if self.last: self.last._stop_worker(force)
    def close(self):
        for coordinator in list(self.instances.values()): coordinator.close()
        self.instances.clear()
