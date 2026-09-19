"""Durable sequential coordinator; one spawn worker per active run."""

from datetime import datetime, timezone, timedelta
import json
import multiprocessing
import os
import threading
import time
from taskweave.core.validation import TaskError, dumps, fingerprint, resolve, validate
from taskweave.infrastructure.storage import now, uid
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.worker import worker_main


class Coordinator:
    def __init__(self, repository, registry, factory):
        self.repo, self.registry, self.factory = repository, registry, factory
        self.lock = threading.RLock()
        self.process = self.pipe = self.thread = None
        self.session_key = self.session_run_id = None
        self.pause_requested = threading.Event()
        self.cancel = multiprocessing.get_context("spawn").Event()
        self.closing = False
        self.repo.recover()

    def _worker(self):
        if self.process and self.process.is_alive():
            return
        ctx = multiprocessing.get_context("spawn")
        self.pipe, child = ctx.Pipe()
        self.process = ctx.Process(
            target=worker_main,
            args=(child, self.cancel, str(self.repo.home), self.factory, os.getpid()),
            daemon=True,
        )
        self.process.start()
        child.close()

    def _stop_worker(self, force=False):
        self.session_key = self.session_run_id = None
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
        with self.repo.transaction() as db:
            db.execute(
                "UPDATE task_runs SET status=?,finished_at=? WHERE run_id=?",
                (status, now() if terminal else None, run_id),
            )
            if terminal:
                db.execute(
                    "UPDATE task_runs SET waiting_step_id=NULL,wait_until=NULL WHERE run_id=?",
                    (run_id,),
                )
                db.execute("DELETE FROM runtime_lease WHERE run_id=?", (run_id,))
        if status == "CANCELLED":
            self._stop_worker()

    def _receipt(self, command_id, run_id, body, operation):
        body_hash = fingerprint(body)
        with self.repo.transaction() as db:
            existing = db.execute(
                "SELECT * FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone()
            if existing:
                if existing["body_hash"] != body_hash or existing["run_id"] != run_id:
                    raise TaskError("COMMAND_CONFLICT")
                return json.loads(existing["response_json"] or "{}")
            response = operation(db)
            db.execute(
                "INSERT INTO command_receipts VALUES(?,?,?,?,?,?)",
                (command_id, run_id, body_hash, "DONE", dumps(response), now()),
            )
            return response

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

            def operation(db):
                run = self.repo.run(run_id)
                if mode not in {"NEXT", "UNTIL", "ALL"}:
                    raise TaskError("MODE_INVALID")
                if run["status"] not in {"READY", "PAUSED", "FAILED", "INTERRUPTED"}:
                    raise TaskError("RUN_STATE_INVALID")
                if self.thread and self.thread.is_alive():
                    raise TaskError("RUN_BUSY")
                if run["definition_hash"] != self.repo.definition_hash(run["task_id"]):
                    raise TaskError("RUN_CONFIG_CHANGED")
                if json.loads(run["request_json"]).get(
                    "environment_hash"
                ) != fingerprint(self.repo.environment(run["environment_id"])):
                    raise TaskError("ENVIRONMENT_CHANGED")
                if json.loads(run["plugin_versions_json"]) != self.registry.versions:
                    raise TaskError("PLUGIN_VERSION_MISMATCH")
                if db.execute(
                    "SELECT 1 FROM step_attempts WHERE run_id=? AND valid=1 AND (status='UNKNOWN' OR (status='FAILED' AND effect_state IN ('UNKNOWN','SUCCEEDED')))",
                    (run_id,),
                ).fetchone():
                    raise TaskError("RECONCILIATION_REQUIRED")
                steps = self.repo.steps(run["task_id"])
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
                if retry_step_id:
                    if retry_step_id not in ids:
                        raise TaskError("TARGET_INVALID")
                    selected = ids[ids.index(retry_step_id) :]
                    db.execute(
                        "UPDATE step_attempts SET valid=0 WHERE run_id=? AND step_id IN ("
                        + ",".join("?" for _ in selected)
                        + ")",
                        (run_id, *selected),
                    )
                elif run["status"] == "FAILED":
                    raise TaskError("EXPLICIT_RETRY_REQUIRED")
                lease = db.execute("SELECT * FROM runtime_lease").fetchone()
                if lease and lease["run_id"] != run_id:
                    raise TaskError("RUN_LEASE_BUSY")
                db.execute(
                    "INSERT INTO runtime_lease VALUES(1,?,?,?) ON CONFLICT(slot) DO UPDATE SET owner_id=excluded.owner_id,heartbeat_at=excluded.heartbeat_at",
                    (run_id, str(os.getpid()), now()),
                )
                db.execute(
                    "UPDATE task_runs SET status='RUNNING',started_at=COALESCE(started_at,?),request_json=? WHERE run_id=?",
                    (
                        now(),
                        dumps(
                            {**json.loads(run["request_json"]), "last_command": body}
                        ),
                        run_id,
                    ),
                )
                started.append(True)
                return {"run_id": run_id, "status": "RUNNING", "command_id": command_id}

            response = self._receipt(command_id, run_id, body, operation)
            if started:
                run = self.repo.run(run_id)
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

            def apply(db):
                run = self.repo.run(run_id)
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
                    owned.extend(
                        db.execute(
                            "SELECT 1 FROM runtime_lease WHERE run_id=?", (run_id,)
                        ).fetchall()
                    )
                    if run['status'] != 'SUCCEEDED':
                        db.execute(
                            "UPDATE task_runs SET status='CANCELLED',finished_at=? WHERE run_id=?",
                            (now(), run_id),
                        )
                    db.execute("DELETE FROM runtime_lease WHERE run_id=?", (run_id,))
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
            self.repo.task(task_id)
            runs = self.repo.query('SELECT run_id,status FROM task_runs WHERE task_id=?', (task_id,))
            ids = {run['run_id'] for run in runs}
            if any(run['status'] == 'RUNNING' for run in runs) or (self.session_run_id in ids and self.thread and self.thread.is_alive()):
                raise TaskError('RUN_BUSY', '请先暂停或结束正在执行的步骤，再清理任务')
            if self.session_run_id in ids:
                self._stop_worker()
            with self.repo.transaction() as db:
                db.execute('DELETE FROM runtime_lease WHERE run_id IN (SELECT run_id FROM task_runs WHERE task_id=?)', (task_id,))
                for table in ('result_refs', 'step_attempts'):
                    db.execute(f'DELETE FROM {table} WHERE task_id=?', (task_id,))
                for table in ('run_events', 'command_receipts'):
                    db.execute(f'DELETE FROM {table} WHERE run_id IN (SELECT run_id FROM task_runs WHERE task_id=?)', (task_id,))
                db.execute('UPDATE task_runs SET parent_run_id=NULL WHERE parent_run_id IN (SELECT run_id FROM task_runs WHERE task_id=?)', (task_id,))
                db.execute('DELETE FROM task_runs WHERE task_id=?', (task_id,))
            directory = self.repo.task_path(task_id).parent
            if directory.exists():
                shutil.rmtree(directory)
            return {'task_id': task_id, 'deleted_runs': len(runs)}

    def delete_run(self, run_id):
        with self.lock:
            run = self.repo.run(run_id)
            if run['status'] == 'RUNNING' or (self.thread and self.thread.is_alive() and self.session_run_id == run_id):
                raise TaskError('RUN_BUSY', '请先结束正在执行的步骤，再删除执行')
            if self.session_run_id == run_id:
                self._stop_worker()
            self.repo.execute('DELETE FROM runtime_lease WHERE run_id=?', (run_id,))
            self.repo.reset_run_results(run_id)
            self.repo.execute('DELETE FROM task_runs WHERE run_id=?', (run_id,))
            return {'deleted': run_id}

    def restart(self, run_id, command_id, target_step_id, start_step_id=None):
        with self.lock:
            if self.repo.query('SELECT 1 FROM command_receipts WHERE command_id=?', (command_id,)):
                return self.start(run_id, command_id, mode='UNTIL', target_step_id=target_step_id, start_step_id=start_step_id)
            run = self.repo.run(run_id)
            if run['mode'] != 'EXECUTION' or run['status'] == 'RUNNING' or (self.thread and self.thread.is_alive()):
                raise TaskError('RUN_BUSY', '请先暂停或结束正在执行的步骤')
            if run['definition_hash'] != self.repo.definition_hash(run['task_id']):
                raise TaskError('RUN_CONFIG_CHANGED')
            if json.loads(run['request_json']).get('environment_hash') != fingerprint(self.repo.environment(run['environment_id'])):
                raise TaskError('ENVIRONMENT_CHANGED')
            if json.loads(run['plugin_versions_json']) != self.registry.versions:
                raise TaskError('PLUGIN_VERSION_MISMATCH')
            if any(s['validation_state'] != 'VALIDATED' for s in self.repo.steps(run['task_id'])):
                raise TaskError('STEP_NOT_VALIDATED')
            if target_step_id not in {s['step_id'] for s in self.repo.steps(run['task_id'])}:
                raise TaskError('TARGET_INVALID')
            if self.repo.query('SELECT 1 FROM runtime_lease WHERE run_id<>?', (run_id,)):
                raise TaskError('RUN_LEASE_BUSY')
            if start_step_id is not None:
                ids = [step['step_id'] for step in self.repo.steps(run['task_id'])]
                if start_step_id not in ids or ids.index(start_step_id) > ids.index(target_step_id):
                    raise TaskError('TARGET_INVALID')
                for sid in ids[:ids.index(start_step_id)]:
                    if not self.repo.query("SELECT 1 FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 AND status='SUCCEEDED'", (run_id, sid)):
                        raise TaskError('TARGET_INVALID', '请从前面尚未完成的步骤开始')
            else:
                self._stop_worker()
            self.repo.execute('DELETE FROM runtime_lease WHERE run_id=?', (run_id,))
            self.repo.reset_run_results(run_id, from_step_id=start_step_id)
            return self.start(run_id, command_id, mode='UNTIL', target_step_id=target_step_id, start_step_id=start_step_id)

    def reconcile(self, attempt_id, decision, evidence, command_id):
        if decision not in {"not_completed", "completed"}:
            raise TaskError("RECONCILIATION_INVALID")
        evidence = evidence or {}
        a = self.repo.query(
            "SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,), True
        )
        with self.lock:

            def apply(db):
                run = self.repo.run(a["run_id"])
                if run["status"] not in {"INTERRUPTED", "FAILED"}:
                    raise TaskError("RUN_STATE_INVALID")
                current = db.execute(
                    "SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,)
                ).fetchone()
                if not current["valid"] or (
                    current["status"] != "UNKNOWN"
                    and not (
                        current["status"] == "FAILED"
                        and current["effect_state"] in {"SUCCEEDED", "UNKNOWN"}
                    )
                ):
                    raise TaskError("RECONCILIATION_INVALID")
                from taskweave.infrastructure.privacy import redact

                db.execute(
                    "UPDATE step_attempts SET status=?,effect_state=?,reconciliation_json=? WHERE attempt_id=?",
                    (
                        "SUCCEEDED" if decision == "completed" else "FAILED",
                        "SUCCEEDED" if decision == "completed" else "NOT_STARTED",
                        dumps(redact({"decision": decision, "evidence": evidence})),
                        attempt_id,
                    ),
                )
                if decision == "completed":
                    db.execute(
                        "UPDATE step_attempts SET finished_at=COALESCE(finished_at,?) WHERE attempt_id=?",
                        (now(), attempt_id),
                    )
                db.execute(
                    "UPDATE task_runs SET status='PAUSED' WHERE run_id=?",
                    (a["run_id"],),
                )
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
        environment, _ = self.repo.environment(run['environment_id'])
        schema = json.loads(self.repo.task(run['task_id'])['input_schema_json'])
        task = {key: spec['default'] for key, spec in schema.get('properties', {}).items() if 'default' in spec}
        task.update(json.loads(run['inputs_json']))
        request = json.loads(run['request_json'])
        values = (json.loads(run['inputs_json']) if run['mode'] == 'TRIAL' and not request.get('flow_trial')
                  else resolve(step['bindings'], task, environment,
                      lambda sid, output: self.repo.read_output(run['run_id'], sid, output, self.registry)))
        values.update(request.get('step_inputs', {}).get(step['step_id'], {}))
        return automatic_inputs(step['input_schema'], environment, task, values)

    def wait_for_inputs(self, run, scope, step, schema, values, missing):
        request = json.loads(self.repo.run(run['run_id'])['request_json'])
        editable = {key: spec for key, spec in schema.get('properties', {}).items()
                    if scope == 'task' or key not in step['bindings']}
        request['waiting_input'] = {'id': uid(), 'scope': scope, 'step_id': step['step_id'],
            'schema': {**schema, 'properties': editable,
                       'required': [key for key in schema.get('required', []) if key in editable]},
            'values': {key: values[key] for key in editable if key in values}, 'missing': missing}
        self.repo.execute("UPDATE task_runs SET request_json=? WHERE run_id=?", (dumps(request), run['run_id']))
        self.repo.event(run['run_id'], 'InputRequested', {'scope': scope, 'step_id': step['step_id'], 'missing': missing})
        self._done(run['run_id'], 'PAUSED')

    def provide_inputs(self, run_id, command_id, inputs, step_inputs=None):
        with self.lock:
            def apply(db):
                run = self.repo.run(run_id)
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
                    db.execute('UPDATE task_runs SET inputs_json=?,input_summary_json=? WHERE run_id=?',
                        (dumps(task_values), dumps(redact(task_values)), run_id))
                else:
                    request.setdefault('step_inputs', {}).setdefault(waiting['step_id'], {}).update(inputs)
                if step_inputs is not None:
                    if waiting['scope'] != 'task' or set(step_inputs) != {waiting['step_id']}:
                        raise TaskError('INPUT_INVALID')
                    normalized = self.repo.normalize_step_inputs(run['task_id'], step_inputs)
                    for sid, supplied in normalized.items():
                        request.setdefault('step_inputs', {}).setdefault(sid, {}).update(supplied)
                request.pop('waiting_input', None)
                db.execute('UPDATE task_runs SET request_json=? WHERE run_id=?', (dumps(request), run_id))
                db.execute('INSERT INTO run_events VALUES(?,?,?,?,?,?)', (uid(), run_id, None, 'InputProvided', dumps({'scope': waiting['scope'], 'step_id': waiting['step_id'], 'keys': list(inputs)}), now()))
                return {'run_id': run_id, 'status': 'PAUSED'}
            return self._receipt(command_id, run_id, {'operation': 'inputs', 'inputs': inputs, **({'step_inputs': step_inputs} if step_inputs is not None else {})}, apply)

    def _drive(self, run_id, mode, target):
        try:
            run = self.repo.run(run_id)
            steps = self.repo.steps(run["task_id"])
            if run["trial_step_id"]:
                if json.loads(run['request_json']).get('flow_trial'):
                    steps = steps[:next(i for i, s in enumerate(steps) if s['step_id'] == run['trial_step_id']) + 1]
                else:
                    steps = [s for s in steps if s["step_id"] == run["trial_step_id"]]
            task_schema = json.loads(self.repo.task(run['task_id'])['input_schema_json'])
            task_values = json.loads(run['inputs_json'])
            missing = self.missing_inputs(task_schema, task_values)
            if missing and (run['mode'] == 'EXECUTION' or json.loads(run['request_json']).get('flow_trial') or steps[0]['position'] == 0):
                self.wait_for_inputs(run, 'task', steps[0], task_schema, task_values, missing)
                return
            for position, step in enumerate(steps):
                latest = self.repo.query(
                    "SELECT * FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 ORDER BY attempt_no DESC LIMIT 1",
                    (run_id, step["step_id"]),
                )
                if latest and latest[0]["status"] == "SUCCEEDED":
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
                run = self.repo.run(run_id)
                try:
                    effective = self.effective_inputs(run, step)
                except TaskError:
                    effective = None  # Let the normal attempt report invalid dependencies.
                missing = [key for key in self.missing_inputs(step['input_schema'], effective) if key not in step['bindings']] if effective is not None else []
                if missing:
                    self.wait_for_inputs(run, 'step', step, step['input_schema'], effective, missing)
                    return
                if not self._attempt(run, step):
                    # A trial is a bounded invocation; release its lease on known failure.
                    if (
                        run["mode"] == "TRIAL"
                        and self.repo.run(run_id)["status"] == "FAILED"
                    ):
                        a = self.repo.query(
                            "SELECT * FROM step_attempts WHERE run_id=? ORDER BY started_at DESC LIMIT 1",
                            (run_id,),
                            True,
                        )
                        if a["effect_state"] == "NOT_STARTED":
                            self.repo.execute(
                                "DELETE FROM runtime_lease WHERE run_id=?", (run_id,)
                            )
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
                self.repo.query(
                    "SELECT 1 FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 AND status='SUCCEEDED'",
                    (run_id, s["step_id"]),
                )
                for s in steps
            )
            self._done(run_id, "SUCCEEDED" if complete else "PAUSED")
        except Exception as exc:
            self.repo.event(
                run_id,
                "CoordinatorError",
                {"code": getattr(exc, "code", type(exc).__name__)},
            )
            for a in self.repo.query(
                "SELECT * FROM step_attempts WHERE run_id=? AND status='RUNNING'",
                (run_id,),
            ):
                refs = self.repo.receipt(a)
                if refs is not None:
                    try:
                        self.repo.finish_attempt(a["attempt_id"], refs)
                        continue
                    except Exception:
                        pass  # Leave durable RUNNING evidence for restart reconciliation.
                else:
                    self.repo.execute(
                        "UPDATE step_attempts SET status='UNKNOWN',effect_state='UNKNOWN',error_code='COORDINATOR_ERROR' WHERE attempt_id=?",
                        (a["attempt_id"],),
                    )
            self._done(run_id, "INTERRUPTED")
            self._stop_worker(force=True)

    def _wait_interval(self, run_id, step, previous):
        seconds = step.get("delay_after_previous_seconds", 0)
        if not seconds:
            self.repo.execute(
                "UPDATE task_runs SET waiting_step_id=NULL,wait_until=NULL WHERE run_id=?",
                (run_id,),
            )
            return True
        attempt = self.repo.query(
            "SELECT * FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 ORDER BY attempt_no DESC LIMIT 1",
            (run_id, previous["step_id"]),
            True,
        )
        if attempt["status"] != "SUCCEEDED" or not attempt["finished_at"]:
            raise TaskError("PREVIOUS_STEP_NOT_SUCCEEDED")
        deadline = datetime.fromisoformat(attempt["finished_at"]) + timedelta(
            seconds=seconds
        )
        self.repo.execute(
            "UPDATE task_runs SET waiting_step_id=?,wait_until=? WHERE run_id=?",
            (step["step_id"], deadline.isoformat(), run_id),
        )
        heartbeat = 0
        while datetime.now(timezone.utc) < deadline:
            if self.cancel.is_set():
                self._done(run_id, "CANCELLED")
                return False
            if self.pause_requested.is_set() or self.closing:
                self._done(run_id, "PAUSED")
                return False
            if time.monotonic() >= heartbeat:
                self.repo.execute(
                    "UPDATE runtime_lease SET heartbeat_at=? WHERE run_id=?",
                    (now(), run_id),
                )
                heartbeat = time.monotonic() + 1
            self.cancel.wait(0.05)
        self.repo.execute(
            "UPDATE task_runs SET waiting_step_id=NULL,wait_until=NULL WHERE run_id=?",
            (run_id,),
        )
        return True

    def _attempt(self, run, step):
        run_id = run["run_id"]
        attempt_id = uid()
        with self.repo.transaction() as db:
            n = db.execute(
                "SELECT COALESCE(MAX(attempt_no),0)+1 FROM step_attempts WHERE run_id=? AND step_id=?",
                (run_id, step["step_id"]),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO step_attempts(attempt_id,task_id,run_id,step_id,execution_path,attempt_no,content_hash,status,effect_state,started_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    run["task_id"],
                    run_id,
                    step["step_id"],
                    "/main/" + step["step_id"],
                    n,
                    step["content_hash"],
                    "RUNNING",
                    "NOT_STARTED",
                    now(),
                ),
            )
        try:
            self.registry.check(step)
            environment, secret_refs = self.repo.environment(run["environment_id"])
            inputs = self.effective_inputs(self.repo.run(run_id), step)
            validate(inputs, step["input_schema"])
        except TaskError as exc:
            self._fail(attempt_id, run_id, exc.code, "resolve", "NOT_STARTED", str(exc))
            return False
        self.repo.execute(
            "UPDATE step_attempts SET input_summary_json=? WHERE attempt_id=?",
            (dumps(redact(inputs)), attempt_id),
        )
        self._worker()
        task_schema = json.loads(self.repo.task(run['task_id'])['input_schema_json'])
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
                    self.repo.execute(
                        "UPDATE runtime_lease SET heartbeat_at=? WHERE run_id=?",
                        (now(), run_id),
                    )
                    continue
                self.repo.event(run_id, kind, payload, attempt_id, event["event_id"])
                if kind == "AttemptCompleted":
                    self.repo.finish_attempt(attempt_id, payload["refs"])
                    return True
                if kind == "AttemptFailed":
                    self.repo.register_refs(attempt_id, payload.get("refs", []))
                    if (
                        payload["code"] == "CANCELLED"
                        and payload["effect_state"] == "NOT_STARTED"
                    ):
                        self.repo.execute(
                            "UPDATE step_attempts SET status='CANCELLED',finished_at=? WHERE attempt_id=?",
                            (now(), attempt_id),
                        )
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
        a = self.repo.query(
            "SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,), True
        )
        refs = self.repo.receipt(a)
        if refs is not None:
            self.repo.finish_attempt(attempt_id, refs)
            self._done(run_id, "INTERRUPTED")
        else:
            self.repo.execute(
                "UPDATE step_attempts SET status='UNKNOWN',effect_state='UNKNOWN',error_code=?,error_phase='execute',finished_at=? WHERE attempt_id=?",
                ("WORKER_TIMEOUT" if timed_out else "WORKER_LOST", now(), attempt_id),
            )
            self._done(run_id, "INTERRUPTED")
        return False

    def _fail(self, attempt_id, run_id, code, phase, effect, message):
        self.repo.execute(
            "UPDATE step_attempts SET status='FAILED',effect_state=?,error_code=?,error_phase=?,error_summary=?,finished_at=? WHERE attempt_id=?",
            (effect, code, phase, message[:4096], now(), attempt_id),
        )
        self._done(run_id, "FAILED")

    def describe_run(self, run_id):
        with self.lock:
            run = self.repo.run_details(run_id)
            retained = self.session_run_id == run_id and self.process is not None and self.process.is_alive()
            leased = bool(self.repo.query('SELECT 1 FROM runtime_lease WHERE run_id=?', (run_id,)))
            run['can_end'] = run['status'] != 'CANCELLED' and (retained or leased)
            return run

    def context_sessions(self, task_id):
        with self.lock:
            if not self.session_run_id or not self.process or not self.process.is_alive():
                return []
            run = self.repo.run(self.session_run_id)
            if run['task_id'] != task_id or run['status'] not in {'PAUSED', 'FAILED', 'SUCCEEDED'} or (self.thread and self.thread.is_alive()):
                return []
            return [self.repo.run_details(run['run_id'])]

    def collect_context(self, run_id, step_id, provider_id, request=None):
        with self.lock:
            run = self.repo.run(run_id)
            step = self.repo.step(step_id)
            lease = self.repo.query(
                "SELECT * FROM runtime_lease WHERE run_id=?", (run_id,)
            )
            if (
                run["status"] not in {"PAUSED", "FAILED", "SUCCEEDED"}
                or step["task_id"] != run["task_id"]
            ):
                raise TaskError("CONTEXT_RUN_STATE_INVALID")
            if self.thread and self.thread.is_alive():
                raise TaskError("RUN_BUSY")
            if self.session_run_id != run_id or not self.process or not self.process.is_alive():
                raise TaskError(
                    "SESSION_NOT_AVAILABLE",
                    "Browser resources were lost; restart in an explicit trial",
                )
            environment, secret_refs = self.repo.environment(run["environment_id"])
            request_id = uid()
            self.pipe.send(
                dumps(
                    {
                        "kind": "context",
                        "provider_id": provider_id,
                        "request": request or {},
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
                        return event["payload"]["items"]
                    if event["kind"] == "AttemptFailed":
                        raise TaskError(
                            event["payload"]["code"], event["payload"]["message"]
                        )
                if not self.process.is_alive():
                    break
            self._stop_worker(force=True)
            self._done(run_id, "INTERRUPTED")
            raise TaskError("CONTEXT_TIMEOUT")

    def wait(self, run_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.repo.run(run_id)["status"] != "RUNNING":
                if self.thread:
                    self.thread.join(3)
                return self.repo.run_details(run_id)
            time.sleep(0.02)
        raise TaskError("WAIT_TIMEOUT")

    def close(self):
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
            self.repo.execute("DELETE FROM runtime_lease")
