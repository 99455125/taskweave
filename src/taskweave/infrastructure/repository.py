"""Task definitions, authoring evidence and durable command state."""

import json
from taskweave.core.validation import (
    TaskError,
    normalize_step,
    fingerprint,
    check_schema,
    check_bindings,
    dumps,
    validate,
)
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.storage import Store, uid, now


class Repository(Store):
    def create_task(self, name, input_schema=None, description=""):
        schema = input_schema if input_schema is not None else {"type": "object"}
        check_schema(schema)
        task_id = uid()
        self.execute(
            "INSERT INTO tasks(task_id,name,description,input_schema_json,graph_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (
                task_id,
                name,
                description,
                dumps(schema),
                dumps({"nodes": [], "entry_node_id": None}),
                now(),
                now(),
            ),
        )
        return self.task(task_id)

    def update_task(self, task_id, name, input_schema, description=""):
        check_schema(input_schema)
        with self.transaction() as db:
            self.assert_unlocked(db, task_id)
            db.execute(
                "UPDATE tasks SET name=?,input_schema_json=?,description=?,updated_at=? WHERE task_id=?",
                (name, dumps(input_schema), description, now(), task_id),
            )
            db.execute(
                "UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL WHERE task_id=?",
                (task_id,),
            )
        return self.task(task_id)

    def save_step(self, task_id, document, step_id=None, expected_hash=None):
        self.task(task_id)
        doc = normalize_step(document)
        ordered = self.steps(task_id)
        if step_id:
            old = self.step(step_id)
            if old["task_id"] != task_id:
                raise TaskError("TASK_MISMATCH")
            position = old["position"]
        else:
            position = len(ordered)
        check_bindings(
            doc["bindings"], {s["step_id"] for s in ordered if s["position"] < position}
        )
        with self.transaction() as db:
            self.assert_unlocked(db, task_id, allow_idle_trial=True)
            if step_id:
                current = db.execute(
                    "SELECT content_hash FROM steps WHERE step_id=?", (step_id,)
                ).fetchone()
                if current[0] != expected_hash:
                    raise TaskError("EDIT_CONFLICT")
                assignments = ",".join(
                    k
                    + (
                        "_json"
                        if k
                        in {
                            "input_schema",
                            "output_schema",
                            "bindings",
                            "capabilities",
                            "plugin_requirements",
                        }
                        else ""
                    )
                    + "=?"
                    for k in doc
                )
                vals = [
                    dumps(v)
                    if k
                    in {
                        "input_schema",
                        "output_schema",
                        "bindings",
                        "capabilities",
                        "plugin_requirements",
                    }
                    else v
                    for k, v in doc.items()
                ]
                db.execute(
                    f"UPDATE steps SET {assignments},content_hash=?,validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?",
                    (*vals, fingerprint(doc), now(), step_id),
                )
            else:
                step_id = uid()
                columns = [
                    k
                    + (
                        "_json"
                        if k
                        in {
                            "input_schema",
                            "output_schema",
                            "bindings",
                            "capabilities",
                            "plugin_requirements",
                        }
                        else ""
                    )
                    for k in doc
                ]
                vals = [
                    dumps(v) if k.endswith("_json") else v
                    for k, v in zip(columns, doc.values())
                ]
                columns += [
                    "step_id",
                    "task_id",
                    "position",
                    "content_hash",
                    "updated_at",
                ]
                vals += [step_id, task_id, position, fingerprint(doc), now()]
                db.execute(
                    "INSERT INTO steps("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join("?" for _ in vals)
                    + ")",
                    vals,
                )
            self._graph(db, task_id)
        return self.step(step_id)

    @staticmethod
    def _graph(db, task_id):
        ids = [
            s[0]
            for s in db.execute(
                "SELECT step_id FROM steps WHERE task_id=? ORDER BY position",
                (task_id,),
            )
        ]
        graph = {
            "entry_node_id": ids[0] if ids else None,
            "nodes": [
                {
                    "id": s,
                    "kind": "action",
                    "config": {"step_id": s},
                    "next": ids[i + 1] if i + 1 < len(ids) else None,
                }
                for i, s in enumerate(ids)
            ],
        }
        db.execute(
            "UPDATE tasks SET graph_json=?,updated_at=? WHERE task_id=?",
            (dumps(graph), now(), task_id),
        )

    def reorder(self, task_id, step_ids):
        steps = self.steps(task_id)
        if len(set(step_ids)) != len(step_ids) or set(step_ids) != {
            s["step_id"] for s in steps
        }:
            raise TaskError("ORDER_INVALID")
        seen = set()
        for sid in step_ids:
            check_bindings(
                next(s for s in steps if s["step_id"] == sid)["bindings"], seen
            )
            seen.add(sid)
        with self.transaction() as db:
            self.assert_unlocked(db, task_id)
            for i, sid in enumerate(step_ids):
                db.execute("UPDATE steps SET position=? WHERE step_id=?", (i, sid))
            self._graph(db, task_id)
        return self.steps(task_id)

    def delete_step(self, step_id):
        step = self.step(step_id)
        with self.transaction() as db:
            self.assert_unlocked(db, step["task_id"])
            if db.execute(
                "SELECT 1 FROM step_attempts WHERE step_id=?", (step_id,)
            ).fetchone():
                raise TaskError(
                    "STEP_HAS_HISTORY",
                    "Delete the entire inactive task to remove execution history",
                )
            for s in self.steps(step["task_id"]):
                if any(
                    v.get("ref", {}).get("step_id") == step_id
                    for v in s["bindings"].values()
                ):
                    raise TaskError("STEP_REFERENCED")
            db.execute("DELETE FROM steps WHERE step_id=?", (step_id,))
            ids = [
                x[0]
                for x in db.execute(
                    "SELECT step_id FROM steps WHERE task_id=? ORDER BY position",
                    (step["task_id"],),
                )
            ]
            for i, sid in enumerate(ids):
                db.execute("UPDATE steps SET position=? WHERE step_id=?", (i, sid))
            self._graph(db, step["task_id"])
        return {"deleted": step_id}

    def save_environment(
        self, name, public_config, secret_refs=None, environment_id=None
    ):
        public_config = dict(public_config)
        secret_refs = dict(secret_refs or {})
        from taskweave.infrastructure.privacy import SENSITIVE
        for key, value in list(public_config.items()):
            if SENSITIVE.search(key) and isinstance(value, str) and value.startswith('env:'):
                secret_refs[key] = value
                del public_config[key]
        secret_refs = secret_refs or {}
        if any(
            not isinstance(v, str) or not v.startswith("env:")
            for v in secret_refs.values()
        ):
            raise TaskError("SECRET_REFERENCE_INVALID")
        environment_id = environment_id or uid()
        with self.transaction() as db:
            if db.execute(
                "SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.environment_id=?",
                (environment_id,),
            ).fetchone():
                raise TaskError("ENVIRONMENT_LOCKED")
            db.execute(
                "INSERT INTO environments VALUES(?,?,?,?) ON CONFLICT(environment_id) DO UPDATE SET name=excluded.name,public_config_json=excluded.public_config_json,secret_refs_json=excluded.secret_refs_json",
                (environment_id, name, dumps(public_config), dumps(secret_refs)),
            )
        return {"environment_id": environment_id}

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
            pending = supplied_step["input_schema"].get("required", [])
            for key in list(values):
                if key in pending and (values[key] is None or values[key] == ""):
                    values.pop(key)
            validate(values, partial_schema)
        return step_inputs

    def create_run(
        self, task_id, inputs, versions, environment_id=None, trial_step_id=None, flow_trial=False, defer_inputs=False, step_inputs=None
    ):
        original_inputs = dict(inputs)
        task = self.task(task_id)
        if task["lifecycle"] != "ACTIVE":
            raise TaskError("TASK_DELETING")
        self.environment(environment_id)
        task_properties = json.loads(task['input_schema_json']).get('properties', {})
        task_defaults = {key: spec['default'] for key, spec in task_properties.items() if 'default' in spec}
        environment, _ = self.environment(environment_id)
        inputs = {**{key: value for key, value in environment.items() if key in task_properties}, **task_defaults, **inputs}
        steps = self.steps(task_id)
        if not steps:
            raise TaskError("EMPTY_TASK")
        if trial_step_id:
            step = self.step(trial_step_id)
            if step["task_id"] != task_id:
                raise TaskError("TASK_MISMATCH")
            if not flow_trial:
                from taskweave.core.validation import automatic_inputs
                environment, _ = self.environment(environment_id)
                task_inputs = {key: value for key, value in inputs.items() if key in task_properties}
                inputs = {**task_inputs, **automatic_inputs(step['input_schema'], environment, inputs)}
            input_schema = json.loads(task["input_schema_json"]) if flow_trial else step["input_schema"]
            validation_inputs = inputs if flow_trial else automatic_inputs(input_schema, environment, inputs)
            validate({key: value for key, value in validation_inputs.items() if key not in input_schema.get("required", []) or (value is not None and value != "")} if defer_inputs else validation_inputs, {**input_schema, "required": []} if defer_inputs else input_schema)
        else:
            task_schema = json.loads(task["input_schema_json"])
            validate({key: value for key, value in inputs.items() if key not in task_schema.get("required", []) or (value is not None and value != "")} if defer_inputs else inputs, {**task_schema, "required": []} if defer_inputs else task_schema)
            for step in steps:
                if (
                    step["validation_state"] != "VALIDATED"
                ):
                    raise TaskError("STEP_NOT_VALIDATED", step["step_id"])
        step_inputs = self.normalize_step_inputs(task_id, step_inputs)
        run_id = uid()
        self.execute(
            "INSERT INTO task_runs(run_id,task_id,environment_id,mode,status,definition_hash,plugin_versions_json,input_summary_json,inputs_json,trial_step_id,request_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                task_id,
                environment_id,
                "TRIAL" if trial_step_id else "EXECUTION",
                "READY",
                self.definition_hash(task_id),
                dumps(versions),
                dumps(redact(inputs)),
                dumps(inputs),
                trial_step_id,
                dumps(
                    {"environment_hash": fingerprint(self.environment(environment_id)), "flow_trial": flow_trial, "step_inputs": step_inputs or {}, "initial_step_inputs": step_inputs or {}, "initial_inputs": original_inputs}
                ),
            ),
        )
        self.execute(
            "UPDATE task_runs SET definition_json=? WHERE run_id=?",
            (dumps({"task": task, "steps": steps}), run_id),
        )
        return self.run(run_id)

    def confirm(self, step_id, attempt_id, expected_hash):
        with self.transaction() as db:
            s = db.execute("SELECT * FROM steps WHERE step_id=?", (step_id,)).fetchone()
            if s is None:
                raise TaskError("NOT_FOUND")
            self.assert_unlocked(db, s["task_id"])
            a = db.execute(
                "SELECT a.*,r.mode,r.environment_id,r.request_json,r.plugin_versions_json FROM step_attempts a JOIN task_runs r USING(run_id) WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if (
                not a
                or a["step_id"] != step_id
                or a["mode"] != "TRIAL"
                or a["status"] != "SUCCEEDED"
                or a["content_hash"] != expected_hash
                or s["content_hash"] != expected_hash
            ):
                raise TaskError("VALIDATION_EVIDENCE_INVALID")
            if json.loads(a["request_json"]).get("environment_hash") != fingerprint(
                self.environment(a["environment_id"])
            ):
                raise TaskError("ENVIRONMENT_CHANGED")
            db.execute(
                "UPDATE steps SET validation_state='VALIDATED',validation_source='TRIAL',verified_hash=content_hash,validated_environment_id=?,validated_at=? WHERE step_id=?",
                (a["environment_id"], now(), step_id),
            )
        return self.step(step_id)

    def confirm_manual(self, step_id, expected_hash, environment_id=None):
        self.environment(environment_id)
        with self.transaction() as db:
            s = db.execute('SELECT * FROM steps WHERE step_id=?', (step_id,)).fetchone()
            if s is None:
                raise TaskError('NOT_FOUND')
            self.assert_unlocked(db, s['task_id'])
            if s['content_hash'] != expected_hash:
                raise TaskError('EDIT_CONFLICT')
            db.execute("UPDATE steps SET validation_state='VALIDATED',validation_source='MANUAL',verified_hash=content_hash,validated_environment_id=?,validated_at=? WHERE step_id=?", (environment_id, now(), step_id))
        return self.step(step_id)

    def run_details(self, run_id):
        run = self.run(run_id)
        run.pop("inputs_json")
        run["attempts"] = self.query(
            "SELECT * FROM step_attempts WHERE run_id=? ORDER BY started_at,attempt_no",
            (run_id,),
        )
        run["results"] = self.query(
            "SELECT * FROM result_refs WHERE run_id=?", (run_id,)
        )
        return run

    def reorder_tasks(self, task_ids):
        with self.transaction() as db:
            actual = {r[0] for r in db.execute("SELECT task_id FROM tasks")}
            if len(task_ids) != len(actual) or set(task_ids) != actual:
                raise TaskError("TASK_ORDER_INVALID")
            for position, task_id in enumerate(task_ids):
                db.execute(
                    "UPDATE tasks SET sort_order=? WHERE task_id=?", (position, task_id)
                )
        return self.list_tasks()

    def copy_task(self, task_id, name=None):
        source = self.task(task_id)
        steps = self.steps(task_id)
        target = self.create_task(
            name or source["name"] + " 副本",
            json.loads(source["input_schema_json"]),
            source["description"],
        )
        mapping = {}
        for step in steps:
            document = normalize_step(step)
            for binding in document["bindings"].values():
                ref = binding.get("ref", {})
                if ref.get("source") == "step":
                    ref["step_id"] = mapping[ref["step_id"]]
            saved = self.save_step(target["task_id"], document)
            mapping[step["step_id"]] = saved["step_id"]
        return target

    def delete_environment(self, environment_id):
        with self.transaction() as db:
            environment = db.execute('SELECT * FROM environments WHERE environment_id=?', (environment_id,)).fetchone()
            if environment is None:
                raise TaskError('NOT_FOUND')
            if db.execute('SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.environment_id=?', (environment_id,)).fetchone():
                raise TaskError('ENVIRONMENT_LOCKED')
            for run in db.execute('SELECT run_id,request_json FROM task_runs WHERE environment_id=?', (environment_id,)).fetchall():
                request = json.loads(run['request_json'])
                request['deleted_environment_name'] = environment['name']
                db.execute('UPDATE task_runs SET environment_id=NULL,request_json=? WHERE run_id=?', (dumps(request), run['run_id']))
            db.execute('UPDATE steps SET validated_environment_id=NULL WHERE validated_environment_id=?', (environment_id,))
            db.execute('DELETE FROM environments WHERE environment_id=?', (environment_id,))
        return {'deleted': True}

    def list_environments(self):
        return self.query("SELECT * FROM environments ORDER BY name")

    def list_tasks(self):
        return self.query("SELECT * FROM tasks ORDER BY sort_order,created_at")

    def list_runs(self, task_id=None):
        return self.query(
            "SELECT run_id,task_id,mode,trial_step_id,status,started_at,finished_at FROM task_runs"
            + (" WHERE task_id=?" if task_id else "")
            + " ORDER BY started_at",
            (task_id,) if task_id else (),
        )

    def list_step_contexts(self, step_id):
        self.step(step_id)
        rows = self.query("SELECT * FROM step_contexts WHERE step_id=? ORDER BY created_at", (step_id,))
        for row in rows:
            row['item'] = json.loads(row.pop('item_json'))
        return rows

    def save_step_context(self, step_id, provider_id, name, source_page, item, context_id=None):
        step = self.step(step_id)
        if source_page not in {'draft', 'trial_feedback'}:
            raise TaskError('FORM_INVALID', '上下文来源无效')
        if not isinstance(name, str) or not name.strip():
            raise TaskError('FORM_INVALID', '上下文名称不能为空')
        context_id = context_id or uid()
        timestamp = now()
        with self.transaction() as db:
            db.execute(
                "INSERT INTO step_contexts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(context_id) DO UPDATE SET name=excluded.name,item_json=excluded.item_json,updated_at=excluded.updated_at",
                (context_id, step_id, provider_id, name.strip(), source_page, dumps(item), timestamp, timestamp),
            )
            db.execute(
                "UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?",
                (timestamp, step_id),
            )
            db.execute("UPDATE tasks SET updated_at=? WHERE task_id=?", (timestamp, step['task_id']))
        return next(row for row in self.list_step_contexts(step_id) if row['context_id'] == context_id)

    def delete_step_context(self, context_id):
        row = self.query('SELECT step_id FROM step_contexts WHERE context_id=?', (context_id,), True)
        step = self.step(row['step_id'])
        timestamp = now()
        with self.transaction() as db:
            db.execute('DELETE FROM step_contexts WHERE context_id=?', (context_id,))
            db.execute(
                "UPDATE steps SET validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?",
                (timestamp, row['step_id']),
            )
            db.execute("UPDATE tasks SET updated_at=? WHERE task_id=?", (timestamp, step['task_id']))
        return {'deleted': context_id}

    def events(self, run_id):
        return self.query(
            "SELECT * FROM run_events WHERE run_id=? ORDER BY created_at", (run_id,)
        )

    def feedback(self, attempt_id):
        a = self.query(
            "SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,), True
        )
        return {
            "format": "taskweave-feedback-1",
            "step_id": a["step_id"],
            "content_hash": a["content_hash"],
            "status": a["status"],
            "effect_state": a["effect_state"],
            "error": redact(
                {k: a[k] for k in ("error_code", "error_phase", "error_summary")}
            ),
            "note": "Only selected error metadata; no business output or page contents included",
        }

    def find_trial_command(self, command_id, step_id, inputs, environment_id):
        rows = self.query(
            "SELECT c.*,r.trial_step_id,r.inputs_json,r.environment_id,r.request_json FROM command_receipts c JOIN task_runs r USING(run_id) WHERE c.command_id=?",
            (command_id,),
        )
        if not rows:
            return None
        row = rows[0]
        expected = fingerprint(
            {"operation": "start", "mode": "ALL", "target": None, "retry": None}
        )
        if (
            row["body_hash"] != expected
            or row["trial_step_id"] != step_id
            or dumps(json.loads(row["request_json"]).get("initial_inputs", json.loads(row["inputs_json"]))) != dumps(inputs)
            or row["environment_id"] != environment_id
        ):
            raise TaskError("COMMAND_CONFLICT")
        return json.loads(row["response_json"])

    def read_result(self, result_id, registry):
        from taskweave.infrastructure.storage import connect

        ref = self.query(
            "SELECT * FROM result_refs WHERE result_id=?", (result_id,), True
        )
        if ref["state"] != "AVAILABLE":
            raise TaskError("RESULT_UNAVAILABLE")
        path = self.task_path(ref["task_id"])
        with connect(path) as db:
            receipt = db.execute('SELECT refs_json FROM result_receipts WHERE attempt_id=?', (ref['attempt_id'],)).fetchone()
        output_name = next((item.get('name', 'data' if item['locator'] == 'data' else item['locator']) for item in json.loads(receipt[0]) if item['result_id'] == result_id), ref['locator']) if receipt else ref['locator']
        if ref["kind"] == "file":
            p = (path.parent / ref["locator"]).resolve()
            if not p.is_relative_to(path.parent.resolve()) or not p.is_file():
                raise TaskError("RESULT_UNAVAILABLE")
            file_info = {
                "name": output_name,
                "path": str(p),
                "media_type": ref["media_type"],
                "size_bytes": p.stat().st_size,
            }
            handler = registry.handlers.get(ref["handler_id"])
            if handler is not None:
                parsed = handler.parse(file_info)
                return {**file_info, "data": parsed, "preview": handler.preview(parsed)}
            return file_info
        with connect(path) as db:
            if ref["kind"] == "json":
                row = db.execute(
                    "SELECT payload_json FROM step_outputs WHERE attempt_id=? AND name=?",
                    (ref["attempt_id"], ref["locator"]),
                ).fetchone()
                if row is None:
                    raise TaskError("RESULT_UNAVAILABLE")
                value = json.loads(row[0])
            else:
                import re

                if not re.fullmatch(r"p_[a-z0-9_]+", ref["locator"]):
                    raise TaskError("TABLE_SCHEMA_INVALID")
                value = [
                    dict(r)
                    for r in db.execute(
                        'SELECT * FROM "'
                        + ref["locator"]
                        + '" WHERE run_id=? AND step_id=? AND attempt_id=?',
                        (ref["run_id"], ref["step_id"], ref["attempt_id"]),
                    )
                ]
        if ref["handler_id"] == "core.json":
            with connect(path) as db:
                metadata = db.execute("SELECT payload_json FROM step_outputs WHERE attempt_id=? AND name=?", (ref["attempt_id"], "__views")).fetchone()
            return {"name": output_name, "data": value, "preview": value, "views": json.loads(metadata[0])["items"] if metadata and ref["locator"] == "data" else []}
        handler = registry.handlers.get(ref["handler_id"])
        if handler is None:
            raise TaskError("HANDLER_UNAVAILABLE")
        parsed = handler.parse(value)
        return {"name": output_name, "data": parsed, "preview": handler.preview(parsed)}

    def delete_result(self, result_id):
        from taskweave.infrastructure.storage import connect

        ref = self.query(
            "SELECT * FROM result_refs WHERE result_id=?", (result_id,), True
        )
        with self.transaction() as db:
            self.assert_unlocked(db, ref["task_id"])
            db.execute(
                "UPDATE result_refs SET state='DELETING' WHERE result_id=?",
                (result_id,),
            )
        path = self.task_path(ref["task_id"])
        with connect(path) as db:
            receipt = db.execute('SELECT refs_json FROM result_receipts WHERE attempt_id=?', (ref['attempt_id'],)).fetchone()
        output_name = next((item.get('name', 'data' if item['locator'] == 'data' else item['locator']) for item in json.loads(receipt[0]) if item['result_id'] == result_id), ref['locator']) if receipt else ref['locator']
        if ref["kind"] == "file":
            p = (path.parent / ref["locator"]).resolve()
            if not p.is_relative_to(path.parent.resolve()):
                raise TaskError("ARTIFACT_INVALID")
            p.unlink(missing_ok=True)
        elif path.exists():
            with connect(path) as db:
                if ref["kind"] == "json":
                    db.execute(
                        "DELETE FROM step_outputs WHERE attempt_id=? AND name=?",
                        (ref["attempt_id"], ref["locator"]),
                    )
                else:
                    import re

                    if not re.fullmatch(r"p_[a-z0-9_]+", ref["locator"]):
                        raise TaskError("TABLE_SCHEMA_INVALID")
                    db.execute(
                        'DELETE FROM "' + ref["locator"] + '" WHERE attempt_id=?',
                        (ref["attempt_id"],),
                    )
        self.execute(
            "UPDATE result_refs SET state='UNAVAILABLE' WHERE result_id=?", (result_id,)
        )
        return {"deleted": result_id}

    def delete_task(self, task_id):
        import shutil

        self.task(task_id)
        with self.transaction() as db:
            self.assert_unlocked(db, task_id)
            db.execute(
                "UPDATE tasks SET lifecycle='DELETING' WHERE task_id=?", (task_id,)
            )
        directory = self.task_path(task_id).parent
        if directory.exists():
            shutil.rmtree(directory)
        with self.transaction() as db:
            for table in ("result_refs", "step_attempts"):
                db.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
            for table in ("run_events", "command_receipts"):
                db.execute(
                    f"DELETE FROM {table} WHERE run_id IN (SELECT run_id FROM task_runs WHERE task_id=?)",
                    (task_id,),
                )
            db.execute("DELETE FROM task_runs WHERE task_id=?", (task_id,))
            db.execute("DELETE FROM steps WHERE task_id=?", (task_id,))
            db.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        return {"deleted": task_id}

    def reset_run_results(self, run_id, from_step_id=None):
        if from_step_id is not None:
            run = self.run(run_id)
            steps = json.loads(run['definition_json'])['steps'] if run['definition_json'] else self.steps(run['task_id'])
            ids = [step['step_id'] for step in steps]
            if from_step_id not in ids:
                raise TaskError('TARGET_INVALID')
            suffix = ids[ids.index(from_step_id):]
            marks = ','.join('?' for _ in suffix)
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
                            if table not in {'step_outputs', 'result_receipts'} and not re.fullmatch(r'p_[a-z0-9_]+', table):
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
                    if not re.fullmatch(r'p_[a-z0-9_]+', row['table_name']):
                        raise TaskError('TABLE_SCHEMA_INVALID')
                    db.execute('DELETE FROM "' + row['table_name'] + '" WHERE run_id=?', (run_id,))
        with self.transaction() as db:
            for table in ('result_refs','step_attempts','run_events','command_receipts'):
                db.execute(f'DELETE FROM {table} WHERE run_id=?', (run_id,))
            request = json.loads(run["request_json"])
            request.pop("waiting_input", None)
            request.pop("step_inputs", None)
            db.execute("UPDATE task_runs SET status='READY',started_at=NULL,finished_at=NULL,waiting_step_id=NULL,wait_until=NULL,request_json=? WHERE run_id=?", (dumps(request), run_id))

    def finish_pending_deletions(self):
        for task in self.query("SELECT task_id FROM tasks WHERE lifecycle='DELETING'"):
            self.delete_task(task["task_id"])
        for ref in self.query(
            "SELECT result_id FROM result_refs WHERE state='DELETING'"
        ):
            self.delete_result(ref["result_id"])

    def attempt_versions(self, attempt_id):
        row = self.query(
            "SELECT r.plugin_versions_json FROM task_runs r JOIN step_attempts a USING(run_id) WHERE a.attempt_id=?",
            (attempt_id,),
            True,
        )
        return json.loads(row["plugin_versions_json"])
