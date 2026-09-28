"""SQLite persistence for run creation and run-facing read models."""

import json
from taskweave.core.validation import TaskError, fingerprint, dumps, validate
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.storage import uid, now


class RunRepository:
    def __init__(self, store, tasks, steps, environments, results):
        self.store = store
        self.tasks = tasks
        self.step_repository = steps
        self.environments = environments
        self.results = results

    @property
    def home(self):
        return self.store.home


    def task_path(self, task_id):
        return self.store.task_path(task_id)

    def transaction(self):
        return self.store.transaction()

    def delete_result(self, result_id):
        return self.results.delete_result(result_id)

    def delete_task(self, task_id):
        return self.tasks.delete_task(task_id)

    def task(self, task_id):
        return self.tasks.task(task_id)

    def step(self, step_id):
        return self.step_repository.step(step_id)

    def steps(self, task_id):
        return self.step_repository.steps(task_id)

    def environment(self, environment_id):
        return self.environments.environment(environment_id)

    def definition_hash(self, task_id):
        return self.tasks.definition_hash(task_id)

    def run(self, run_id):
        return self.store.query("SELECT * FROM task_runs WHERE run_id=?", (run_id,), True)

    def command_receipt(self, command_id, run_id, body, operation):
        """Atomically apply a runtime command and persist its idempotency receipt."""
        body_hash = fingerprint(body)
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone()
            if existing:
                if existing["body_hash"] != body_hash or existing["run_id"] != run_id:
                    raise TaskError("COMMAND_CONFLICT")
                return json.loads(existing["response_json"] or "{}")
            response = operation()
            db.execute(
                "INSERT INTO command_receipts VALUES(?,?,?,?,?,?)",
                (command_id, run_id, body_hash, "DONE", dumps(response), now()),
            )
            return response

    def has_command_receipt(self, command_id):
        return bool(self.query("SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)))

    def has_unresolved_attempts(self, run_id):
        return bool(self.query(
            "SELECT 1 FROM step_attempts WHERE run_id=? AND valid=1 AND "
            "(status='UNKNOWN' OR (status='FAILED' AND effect_state IN ('UNKNOWN','SUCCEEDED')))",
            (run_id,),
        ))

    def has_successful_attempt(self, run_id, step_id):
        return bool(self.query(
            "SELECT 1 FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 AND status='SUCCEEDED'",
            (run_id, step_id),
        ))

    def latest_attempt(self, run_id, step_id):
        rows = self.query(
            "SELECT * FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 "
            "ORDER BY attempt_no DESC LIMIT 1",
            (run_id, step_id),
        )
        return rows[0] if rows else None

    def attempts_with_status(self, run_id, status):
        return self.query(
            "SELECT * FROM step_attempts WHERE run_id=? AND status=? ORDER BY attempt_no",
            (run_id, status),
        )

    def attempt(self, attempt_id):
        return self.query("SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,), True)

    def attempt_run_id(self, attempt_id):
        return self.query("SELECT run_id FROM step_attempts WHERE attempt_id=?", (attempt_id,), True)["run_id"]

    def runtime_lease(self, run_id):
        rows = self.query("SELECT * FROM runtime_lease WHERE run_id=?", (run_id,))
        return rows[0] if rows else None

    def lease_for_slot(self, slot):
        rows = self.query("SELECT * FROM runtime_lease WHERE slot=?", (slot,))
        return rows[0] if rows else None

    def start_run(self, run_id, command, slot, owner_id, stamp, retry_step_ids=None):
        """Claim the slot and transition the run in the command's transaction."""
        run = self.run(run_id)
        with self.transaction() as db:
            if retry_step_ids:
                marks = ",".join("?" for _ in retry_step_ids)
                db.execute(
                    f"UPDATE step_attempts SET valid=0 WHERE run_id=? AND step_id IN ({marks})",
                    (run_id, *retry_step_ids),
                )
            lease = db.execute("SELECT * FROM runtime_lease WHERE slot=?", (slot,)).fetchone()
            if lease and lease["run_id"] != run_id:
                return False
            db.execute(
                "INSERT INTO runtime_lease VALUES(?,?,?,?) "
                "ON CONFLICT(slot) DO UPDATE SET run_id=excluded.run_id,"
                "owner_id=excluded.owner_id,heartbeat_at=excluded.heartbeat_at",
                (slot, run_id, owner_id, stamp),
            )
            request = {**json.loads(run["request_json"]), "last_command": command}
            db.execute(
                "UPDATE task_runs SET status='RUNNING',started_at=COALESCE(started_at,?),request_json=? WHERE run_id=?",
                (stamp, dumps(request), run_id),
            )
            return True

    def finish_run(self, run_id, status, finished_at, terminal):
        with self.transaction() as db:
            db.execute(
                "UPDATE task_runs SET status=?,finished_at=? WHERE run_id=?",
                (status, finished_at if terminal else None, run_id),
            )
            if terminal:
                db.execute(
                    "UPDATE task_runs SET waiting_step_id=NULL,wait_until=NULL WHERE run_id=?",
                    (run_id,),
                )
                db.execute("DELETE FROM runtime_lease WHERE run_id=?", (run_id,))

    def cancel_run(self, run_id, finished_at, succeeded):
        with self.transaction() as db:
            if not succeeded:
                db.execute(
                    "UPDATE task_runs SET status='CANCELLED',finished_at=? WHERE run_id=?",
                    (finished_at, run_id),
                )
            db.execute("DELETE FROM runtime_lease WHERE run_id=?", (run_id,))

    def set_run_status(self, run_id, status):
        return self.store.execute("UPDATE task_runs SET status=? WHERE run_id=?", (status, run_id))

    def run_has_succeeded_attempts(self, run_id, step_ids):
        return {step_id for step_id in step_ids if self.has_successful_attempt(run_id, step_id)}

    def clear_task_run_records(self, task_id):
        with self.transaction() as db:
            db.execute(
                "DELETE FROM runtime_lease WHERE run_id IN "
                "(SELECT run_id FROM task_runs WHERE task_id=?)", (task_id,),
            )
            for table in ("result_refs", "step_attempts"):
                db.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
            for table in ("run_events", "command_receipts"):
                db.execute(
                    f"DELETE FROM {table} WHERE run_id IN "
                    "(SELECT run_id FROM task_runs WHERE task_id=?)", (task_id,),
                )
            db.execute(
                "UPDATE task_runs SET parent_run_id=NULL WHERE parent_run_id IN "
                "(SELECT run_id FROM task_runs WHERE task_id=?)", (task_id,),
            )
            db.execute("DELETE FROM task_runs WHERE task_id=?", (task_id,))

    def delete_run_record(self, run_id):
        self.store.execute("DELETE FROM runtime_lease WHERE run_id=?", (run_id,))
        self.store.execute("DELETE FROM task_runs WHERE run_id=?", (run_id,))

    def receipt(self, attempt):
        return self.results.receipt(attempt)

    def read_output(self, run_id, step_id, output="data", registry=None):
        return self.results.read_output(run_id, step_id, output, registry)

    def update_attempt_reconciliation(self, attempt_id, status, effect_state, reconciliation_json, finished_at=None):
        self.store.execute(
            "UPDATE step_attempts SET status=?,effect_state=?,reconciliation_json=? WHERE attempt_id=?",
            (status, effect_state, reconciliation_json, attempt_id),
        )
        if finished_at is not None:
            self.store.execute(
                "UPDATE step_attempts SET finished_at=COALESCE(finished_at,?) WHERE attempt_id=?",
                (finished_at, attempt_id),
            )

    def update_run_request(self, run_id, request_json):
        return self.store.execute("UPDATE task_runs SET request_json=? WHERE run_id=?", (request_json, run_id))

    def provide_run_inputs(self, run_id, task_inputs_json, input_summary_json, request_json, event_id, event_json, created_at):
        with self.transaction() as db:
            if task_inputs_json is not None:
                db.execute(
                    "UPDATE task_runs SET inputs_json=?,input_summary_json=? WHERE run_id=?",
                    (task_inputs_json, input_summary_json, run_id),
                )
            db.execute("UPDATE task_runs SET request_json=? WHERE run_id=?", (request_json, run_id))
            db.execute(
                "INSERT INTO run_events VALUES(?,?,?,?,?,?)",
                (event_id, run_id, None, "InputProvided", event_json, created_at),
            )

    def set_waiting_step(self, run_id, step_id, wait_until):
        return self.store.execute(
            "UPDATE task_runs SET waiting_step_id=?,wait_until=? WHERE run_id=?",
            (step_id, wait_until, run_id),
        )

    def clear_waiting_step(self, run_id):
        return self.store.execute(
            "UPDATE task_runs SET waiting_step_id=NULL,wait_until=NULL WHERE run_id=?", (run_id,)
        )

    def heartbeat(self, run_id, stamp):
        return self.store.execute("UPDATE runtime_lease SET heartbeat_at=? WHERE run_id=?", (stamp, run_id))

    def create_attempt(self, attempt_id, task_id, run_id, step_id, content_hash, stamp):
        with self.transaction() as db:
            number = db.execute(
                "SELECT COALESCE(MAX(attempt_no),0)+1 FROM step_attempts WHERE run_id=? AND step_id=?",
                (run_id, step_id),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO step_attempts(attempt_id,task_id,run_id,step_id,execution_path,attempt_no,content_hash,status,effect_state,started_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, task_id, run_id, step_id, "/main/" + step_id, number,
                 content_hash, "RUNNING", "NOT_STARTED", stamp),
            )

    def set_attempt_input_summary(self, attempt_id, summary_json):
        return self.store.execute(
            "UPDATE step_attempts SET input_summary_json=? WHERE attempt_id=?",
            (summary_json, attempt_id),
        )

    def mark_attempt_cancelled(self, attempt_id, finished_at):
        return self.store.execute(
            "UPDATE step_attempts SET status='CANCELLED',finished_at=? WHERE attempt_id=?",
            (finished_at, attempt_id),
        )

    def mark_attempt_unknown(self, attempt_id, error_code, error_phase, finished_at=None):
        if finished_at is None:
            return self.store.execute(
                "UPDATE step_attempts SET status='UNKNOWN',effect_state='UNKNOWN',error_code=? WHERE attempt_id=?",
                (error_code, attempt_id),
            )
        return self.store.execute(
            "UPDATE step_attempts SET status='UNKNOWN',effect_state='UNKNOWN',error_code=?,error_phase=?,finished_at=? WHERE attempt_id=?",
            (error_code, error_phase, finished_at, attempt_id),
        )

    def mark_attempt_failed(self, attempt_id, effect_state, error_code, error_phase, summary, finished_at):
        return self.store.execute(
            "UPDATE step_attempts SET status='FAILED',effect_state=?,error_code=?,error_phase=?,error_summary=?,finished_at=? WHERE attempt_id=?",
            (effect_state, error_code, error_phase, summary, finished_at, attempt_id),
        )

    def private_run_request(self, run_id):
        return json.loads(self.run(run_id)["request_json"])

    def private_run_inputs(self, run_id):
        run = self.run(run_id)
        request = json.loads(run["request_json"])
        return {
            "task": json.loads(run["inputs_json"]),
            "steps": request.get("step_inputs", {}),
        }

    def query(self, sql, args=(), one=False):
        return self.store.query(sql, args, one)

    def execute(self, sql, args=()):
        return self.store.execute(sql, args)

    def normalize_step_inputs(self, task_id, step_inputs):
        steps = self.steps(task_id)
        step_inputs = {sid: dict(values) if isinstance(values, dict) else values for sid, values in (step_inputs or {}).items()}
        for step_id, values in step_inputs.items():
            supplied_step = next((s for s in steps if s['step_id'] == step_id), None)
            if supplied_step is None or not isinstance(values, dict):
                raise TaskError('INPUT_INVALID')
            if set(values) & set(supplied_step['bindings']):
                raise TaskError('INPUT_INVALID', '不能覆盖已绑定的输入')
            if set(values) - set(supplied_step['input_schema'].get('properties', {})):
                raise TaskError('INPUT_INVALID', '未知步骤输入')
            partial_schema = {**supplied_step['input_schema'], 'required': []}
            pending = supplied_step['input_schema'].get('required', [])
            for key in list(values):
                if key in pending and (values[key] is None or values[key] == ''):
                    values.pop(key)
            validate(values, partial_schema)
        return step_inputs

    def create_run(self, task_id, inputs, versions, environment_id=None, trial_step_id=None, flow_trial=False, defer_inputs=False, step_inputs=None):
        original_inputs = dict(inputs)
        task = self.task(task_id)
        if task['lifecycle'] != 'ACTIVE':
            raise TaskError('TASK_DELETING')
        self.environment(environment_id)
        task_properties = json.loads(task['input_schema_json']).get('properties', {})
        task_defaults = {key: spec['default'] for key, spec in task_properties.items() if 'default' in spec}
        environment, _ = self.environment(environment_id)
        inputs = {**{key: value for key, value in environment.items() if key in task_properties}, **task_defaults, **inputs}
        steps = self.steps(task_id)
        if not steps:
            raise TaskError('EMPTY_TASK')
        if trial_step_id:
            step = self.step(trial_step_id)
            if step['task_id'] != task_id:
                raise TaskError('TASK_MISMATCH')
            if not flow_trial:
                from taskweave.core.validation import automatic_inputs
                environment, _ = self.environment(environment_id)
                task_inputs = {key: value for key, value in inputs.items() if key in task_properties}
                inputs = {**task_inputs, **automatic_inputs(step['input_schema'], environment, inputs)}
            input_schema = json.loads(task['input_schema_json']) if flow_trial else step['input_schema']
            validation_inputs = inputs if flow_trial else automatic_inputs(input_schema, environment, inputs)
            validate({key: value for key, value in validation_inputs.items() if key not in input_schema.get('required', []) or (value is not None and value != '')} if defer_inputs else validation_inputs, {**input_schema, 'required': []} if defer_inputs else input_schema)
        else:
            task_schema = json.loads(task['input_schema_json'])
            validate({key: value for key, value in inputs.items() if key not in task_schema.get('required', []) or (value is not None and value != '')} if defer_inputs else inputs, {**task_schema, 'required': []} if defer_inputs else task_schema)
            for step in steps:
                if step['validation_state'] != 'VALIDATED':
                    raise TaskError('STEP_NOT_VALIDATED', step['step_id'])
        step_inputs = self.normalize_step_inputs(task_id, step_inputs)
        run_id = uid()
        self.execute('INSERT INTO task_runs(run_id,task_id,environment_id,mode,status,definition_hash,plugin_versions_json,input_summary_json,inputs_json,trial_step_id,request_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (run_id, task_id, environment_id, 'TRIAL' if trial_step_id else 'EXECUTION', 'READY', self.definition_hash(task_id), dumps(versions), dumps(redact(inputs)), dumps(inputs), trial_step_id, dumps({'environment_hash': fingerprint(self.environment(environment_id)), 'flow_trial': flow_trial, 'step_inputs': step_inputs or {}, 'initial_step_inputs': step_inputs or {}, 'initial_inputs': original_inputs})))
        self.execute('UPDATE task_runs SET definition_json=? WHERE run_id=?', (dumps({'task': task, 'steps': steps}), run_id))
        return self.run(run_id)

    def run_details(self, run_id):
        run = self.run(run_id)
        run.pop('inputs_json')
        run['attempts'] = self.query('SELECT * FROM step_attempts WHERE run_id=? ORDER BY started_at,attempt_no', (run_id,))
        run['results'] = self.query('SELECT * FROM result_refs WHERE run_id=?', (run_id,))
        return run

    def list_runs(self, task_id=None):
        return self.query('SELECT run_id,task_id,mode,trial_step_id,status,started_at,finished_at FROM task_runs' + (' WHERE task_id=?' if task_id else '') + ' ORDER BY started_at', (task_id,) if task_id else ())

    def events(self, run_id):
        return self.query('SELECT * FROM run_events WHERE run_id=? ORDER BY created_at', (run_id,))

    def feedback(self, attempt_id):
        a = self.query('SELECT * FROM step_attempts WHERE attempt_id=?', (attempt_id,), True)
        return {'format': 'taskweave-feedback-1', 'step_id': a['step_id'], 'content_hash': a['content_hash'], 'status': a['status'], 'effect_state': a['effect_state'], 'error': redact({k: a[k] for k in ('error_code', 'error_phase', 'error_summary')}), 'note': 'Only selected error metadata; no business output or page contents included'}

    def find_trial_command(self, command_id, step_id, inputs, environment_id):
        rows = self.query('SELECT c.*,r.trial_step_id,r.inputs_json,r.environment_id,r.request_json FROM command_receipts c JOIN task_runs r USING(run_id) WHERE c.command_id=?', (command_id,))
        if not rows:
            return None
        row = rows[0]
        expected = fingerprint({'operation': 'start', 'mode': 'ALL', 'target': None, 'retry': None})
        if row['body_hash'] != expected or row['trial_step_id'] != step_id or dumps(json.loads(row['request_json']).get('initial_inputs', json.loads(row['inputs_json']))) != dumps(inputs) or (row['environment_id'] != environment_id):
            raise TaskError('COMMAND_CONFLICT')
        return json.loads(row['response_json'])

    def reset_run_results(self, run_id, from_step_id=None):
        if from_step_id is not None:
            run = self.run(run_id)
            steps = json.loads(run['definition_json'])['steps'] if run['definition_json'] else self.steps(run['task_id'])
            ids = [step['step_id'] for step in steps]
            if from_step_id not in ids:
                raise TaskError('TARGET_INVALID')
            suffix = ids[ids.index(from_step_id):]
            marks = ','.join(('?' for _ in suffix))
            attempts = self.query(f'SELECT attempt_id FROM step_attempts WHERE run_id=? AND step_id IN ({marks})', (run_id, *suffix))
            for attempt in attempts:
                aid = attempt['attempt_id']
                for ref in self.query('SELECT result_id FROM result_refs WHERE attempt_id=?', (aid,)):
                    self.delete_result(ref['result_id'])
                from taskweave.infrastructure.storage import connect
                import re
                path = self.task_path(run['task_id'])
                if path.exists():
                    with connect(path) as db:
                        for table in ['step_outputs', 'result_receipts'] + [row['table_name'] for row in db.execute('SELECT table_name FROM plugin_table_schemas')]:
                            if table not in {'step_outputs', 'result_receipts'} and (not re.fullmatch('p_[a-z0-9_]+', table)):
                                raise TaskError('TABLE_SCHEMA_INVALID')
                            db.execute(f'DELETE FROM "{table}" WHERE attempt_id=?', (aid,))
                with self.transaction() as db:
                    db.execute('DELETE FROM result_refs WHERE attempt_id=?', (aid,))
                    db.execute('DELETE FROM run_events WHERE attempt_id=?', (aid,))
                    db.execute('DELETE FROM step_attempts WHERE attempt_id=?', (aid,))
            request = json.loads(run['request_json'])
            request.pop('waiting_input', None)
            request['step_inputs'] = {sid: values for sid, values in request.get('step_inputs', {}).items() if sid not in suffix}
            self.execute("UPDATE task_runs SET status='READY',finished_at=NULL,waiting_step_id=NULL,wait_until=NULL,request_json=? WHERE run_id=?", (dumps(request), run_id))
            return
        from taskweave.infrastructure.storage import connect
        import shutil
        run = self.run(run_id)
        attempts = self.query('SELECT attempt_id FROM step_attempts WHERE run_id=?', (run_id,))
        for ref in self.query('SELECT result_id FROM result_refs WHERE run_id=?', (run_id,)):
            self.delete_result(ref['result_id'])
        path = self.task_path(run['task_id'])
        shutil.rmtree(path.parent / 'artifacts' / run_id, ignore_errors=True)
        for attempt in attempts:
            shutil.rmtree(path.parent / 'staging' / attempt['attempt_id'], ignore_errors=True)
        if path.exists():
            with connect(path) as db:
                db.execute('DELETE FROM step_outputs WHERE run_id=?', (run_id,))
                db.execute('DELETE FROM result_receipts WHERE run_id=?', (run_id,))
                import re
                for row in db.execute('SELECT table_name FROM plugin_table_schemas'):
                    if not re.fullmatch('p_[a-z0-9_]+', row['table_name']):
                        raise TaskError('TABLE_SCHEMA_INVALID')
                    db.execute('DELETE FROM "' + row['table_name'] + '" WHERE run_id=?', (run_id,))
        with self.transaction() as db:
            for table in ('result_refs', 'step_attempts', 'run_events', 'command_receipts'):
                db.execute(f'DELETE FROM {table} WHERE run_id=?', (run_id,))
            request = json.loads(run['request_json'])
            request.pop('waiting_input', None)
            request.pop('step_inputs', None)
            db.execute("UPDATE task_runs SET status='READY',started_at=NULL,finished_at=NULL,waiting_step_id=NULL,wait_until=NULL,request_json=? WHERE run_id=?", (dumps(request), run_id))

    def finish_pending_deletions(self):
        for task in self.query("SELECT task_id FROM tasks WHERE lifecycle='DELETING'"):
            self.delete_task(task['task_id'])
        for ref in self.query("SELECT result_id FROM result_refs WHERE state='DELETING'"):
            self.delete_result(ref['result_id'])

    def attempt_versions(self, attempt_id):
        row = self.query('SELECT r.plugin_versions_json FROM task_runs r JOIN step_attempts a USING(run_id) WHERE a.attempt_id=?', (attempt_id,), True)
        return json.loads(row['plugin_versions_json'])

    def trial_lease_for_task(self, task_id):
        rows = self.store.query("SELECT l.* FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.mode='TRIAL' AND r.task_id=?", (task_id,))
        return rows[0] if rows else None

    def trial_leases_for_task(self, task_id):
        return self.store.query("SELECT l.* FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.mode='TRIAL' AND r.task_id=?", (task_id,))

    def has_unsafe_attempts(self, run_id):
        return bool(self.store.query("SELECT 1 FROM step_attempts WHERE run_id=? AND valid=1 AND (status='UNKNOWN' OR (status='FAILED' AND effect_state IN ('UNKNOWN','SUCCEEDED')))", (run_id,)))

    def release_lease(self, run_id):
        return self.store.execute("DELETE FROM runtime_lease WHERE run_id=?", (run_id,))

    def runs_for_environment(self, environment_id):
        return self.store.query("SELECT run_id,status FROM task_runs WHERE environment_id=?", (environment_id,))

    def has_runtime_lease(self):
        return bool(self.store.query("SELECT 1 FROM runtime_lease LIMIT 1"))

    def runs_for_task(self, task_id):
        return self.store.query("SELECT run_id,status FROM task_runs WHERE task_id=?", (task_id,))

    def event(self, run_id, kind, payload, attempt_id=None, event_id=None):
        self.execute('INSERT OR IGNORE INTO run_events VALUES(?,?,?,?,?,?)', (event_id or uid(), run_id, attempt_id, kind, dumps(redact(payload)), now()))

    def register_refs(self, attempt_id, refs):
        with self.transaction() as db:
            a = dict(db.execute('SELECT * FROM step_attempts WHERE attempt_id=?', (attempt_id,)).fetchone())
            for ref in refs:
                db.execute('INSERT OR IGNORE INTO result_refs(result_id,task_id,run_id,step_id,attempt_id,handler_id,kind,locator,media_type,checksum,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (ref['result_id'], a['task_id'], a['run_id'], a['step_id'], attempt_id, ref['handler_id'], ref['kind'], ref['locator'], ref['media_type'], ref.get('checksum'), ref.get('size_bytes')))

    def finish_attempt(self, attempt_id, refs):
        with self.transaction() as db:
            a = dict(db.execute('SELECT * FROM step_attempts WHERE attempt_id=?', (attempt_id,)).fetchone())
            for ref in refs:
                db.execute('INSERT OR IGNORE INTO result_refs(result_id,task_id,run_id,step_id,attempt_id,handler_id,kind,locator,media_type,checksum,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (ref['result_id'], a['task_id'], a['run_id'], a['step_id'], attempt_id, ref['handler_id'], ref['kind'], ref['locator'], ref['media_type'], ref.get('checksum'), ref.get('size_bytes')))
            db.execute("UPDATE step_attempts SET status='SUCCEEDED',effect_state='SUCCEEDED',error_code=NULL,error_phase=NULL,error_summary=NULL,finished_at=? WHERE attempt_id=?", (now(), attempt_id))

    def recover(self):
        for a in self.query("SELECT * FROM step_attempts WHERE status='RUNNING'"):
            refs = self.results.receipt(a)
            if refs is not None:
                self.finish_attempt(a['attempt_id'], refs)
            else:
                self.execute("UPDATE step_attempts SET status='UNKNOWN',effect_state='UNKNOWN',error_code='WORKER_LOST',error_phase='execute',finished_at=? WHERE attempt_id=?", (now(), a['attempt_id']))
        self.execute("UPDATE task_runs SET status='INTERRUPTED' WHERE status='RUNNING'")
        self.execute('DELETE FROM runtime_lease')
        self.execute("UPDATE command_receipts SET state='FAILED',response_json=? WHERE state='ACCEPTED'", (dumps({'code': 'COORDINATOR_RESTARTED'}),))
