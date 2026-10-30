"""SQLite persistence for ordered task steps and their task graph."""

from taskweave.core.validation import TaskError, normalize_step, fingerprint, check_bindings, dumps
from taskweave.core.task_flow import normalize_flow, is_linear_flow, conditional_branches
import json
from taskweave.infrastructure.sqlite_storage import SQLiteStorage, uid, now


class StepRepository:
    def __init__(self, store: SQLiteStorage, environments):
        self.store = store
        self.environments = environments

    def transaction(self):
        return self.store.transaction()

    def _assert_unlocked(self, db, task_id, allow_idle_trial=False):
        if db.execute(
            "SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.task_id=? AND (?=0 OR r.mode<>'TRIAL' OR r.status NOT IN ('FAILED','SUCCEEDED'))",
            (task_id, int(allow_idle_trial)),
        ).fetchone():
            raise TaskError("TASK_LOCKED", "End the active run before editing")

    def environment(self, environment_id):
        return self.environments.environment(environment_id)

    def step(self, step_id):
        row = self.store.query("SELECT * FROM steps WHERE step_id=?", (step_id,), True)
        return self.decode_step(row)

    def steps(self, task_id):
        return [self.decode_step(row) for row in self.store.query("SELECT * FROM steps WHERE task_id=? ORDER BY position", (task_id,))]

    @staticmethod
    def decode_step(row):
        import json
        for key in ("input_schema", "output_schema", "bindings", "capabilities", "plugin_requirements"):
            row[key] = json.loads(row.pop(key + "_json"))
        return row

    def save_step(self, task_id, document, step_id=None, expected_hash=None):
        self.store.query("SELECT task_id FROM tasks WHERE task_id=?", (task_id,), True)
        doc = normalize_step(document)
        ordered = self.steps(task_id)
        if step_id:
            old = self.step(step_id)
            if old["task_id"] != task_id:
                raise TaskError("TASK_MISMATCH")
            position = old["position"]
        else:
            position = len(ordered)
        graph = json.loads(self.store.query("SELECT graph_json FROM tasks WHERE task_id=?", (task_id,), True)["graph_json"])
        controlled = not is_linear_flow(graph)
        check_bindings(doc["bindings"], ({s["step_id"] for s in ordered if s["step_id"] != step_id}
                                         if controlled else {s["step_id"] for s in ordered if s["position"] < position}))
        with self.store.transaction() as db:
            self._assert_unlocked(db, task_id, allow_idle_trial=True)
            if step_id:
                current = db.execute("SELECT content_hash FROM steps WHERE step_id=?", (step_id,)).fetchone()
                if current[0] != expected_hash:
                    raise TaskError("EDIT_CONFLICT")
                json_fields = {"input_schema", "output_schema", "bindings", "capabilities", "plugin_requirements"}
                assignments = ",".join(k + ("_json" if k in json_fields else "") + "=?" for k in doc)
                vals = [dumps(v) if k in json_fields else v for k, v in doc.items()]
                db.execute(
                    f"UPDATE steps SET {assignments},content_hash=?,validation_state='DRAFT',validation_source=NULL,verified_hash=NULL,updated_at=? WHERE step_id=?",
                    (*vals, fingerprint(doc), now(), step_id),
                )
            else:
                json_fields = {"input_schema", "output_schema", "bindings", "capabilities", "plugin_requirements"}
                columns = [k + ("_json" if k in json_fields else "") for k in doc]
                vals = [dumps(v) if k in json_fields else v for k, v in doc.items()]
                columns += ["step_id", "task_id", "position", "content_hash", "updated_at"]
                vals += [uid(), task_id, position, fingerprint(doc), now()]
                step_id = vals[-5]
                db.execute("INSERT INTO steps(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in vals) + ")", vals)
            self._sync_task_graph(db, task_id)
        return self.step(step_id)

    @staticmethod
    def _sync_task_graph(db, task_id):
        ids = [s[0] for s in db.execute("SELECT step_id FROM steps WHERE task_id=? ORDER BY position", (task_id,))]
        task = db.execute("SELECT graph_json FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        current = json.loads(task[0])
        graph = json.loads(task[0])
        if is_linear_flow(graph):
            graph["root"] = {"id": "root", "kind": "sequence", "children": [
                {"id": sid, "kind": "action", "step_id": sid} for sid in ids
            ]}
        else:
            available = set(ids)
            def retain(node):
                if node["kind"] == "action":
                    return node if node["step_id"] in available else None
                if node["kind"] == "sequence":
                    node["children"] = [item for child in node["children"]
                                        if (item := retain(child)) is not None]
                elif node["kind"] == "if":
                    for _, body in conditional_branches(node):
                        retain(body)
                elif node["kind"] in {"foreach", "loop"}:
                    node["body"] = retain(node["body"])
                return node
            graph["root"] = retain(graph["root"])
            def placed(node):
                if node["kind"] == "action":
                    return {node["step_id"]}
                if node["kind"] == "sequence":
                    return set().union(*(placed(child) for child in node["children"]))
                if node["kind"] == "if":
                    return set().union(*(placed(body) for _, body in conditional_branches(node)))
                return placed(node["body"])
            for sid in ids:
                if sid not in placed(graph["root"]):
                    graph["root"]["children"].append({"id": sid, "kind": "action", "step_id": sid})
        normalize_flow(graph, [{"step_id": sid} for sid in ids])
        encoded = dumps(graph)
        if encoded != task[0]:
            linear = is_linear_flow(graph)
            db.execute(
                "UPDATE tasks SET graph_json=?,flow_validation_state=?,flow_verified_hash=?,updated_at=? WHERE task_id=?",
                (encoded, "VALIDATED" if linear else "DRAFT",
                 fingerprint(graph) if linear else None, now(), task_id),
            )

    def reorder(self, task_id, step_ids):
        steps = self.steps(task_id)
        if len(set(step_ids)) != len(step_ids) or set(step_ids) != {s["step_id"] for s in steps}:
            raise TaskError("ORDER_INVALID")
        seen = set()
        task_graph = json.loads(self.store.query("SELECT graph_json FROM tasks WHERE task_id=?", (task_id,), True)["graph_json"])
        if not is_linear_flow(task_graph):
            raise TaskError("FLOW_REORDER_USE_EDITOR", "请在流程树中移动完整节点")
        for sid in step_ids:
            check_bindings(next(s for s in steps if s["step_id"] == sid)["bindings"], seen)
            seen.add(sid)
        with self.store.transaction() as db:
            self._assert_unlocked(db, task_id)
            for i, sid in enumerate(step_ids):
                db.execute("UPDATE steps SET position=? WHERE step_id=?", (i, sid))
            self._sync_task_graph(db, task_id)
        return self.steps(task_id)

    def delete_step(self, step_id):
        step = self.step(step_id)
        with self.store.transaction() as db:
            self._assert_unlocked(db, step["task_id"])
            if db.execute("SELECT 1 FROM step_attempts WHERE step_id=?", (step_id,)).fetchone():
                raise TaskError("STEP_HAS_HISTORY", "Delete the entire inactive task to remove execution history")
            for candidate in self.steps(step["task_id"]):
                if any(v.get("ref", {}).get("step_id") == step_id for v in candidate["bindings"].values()):
                    raise TaskError("STEP_REFERENCED")
            db.execute("DELETE FROM steps WHERE step_id=?", (step_id,))
            ids = [x[0] for x in db.execute("SELECT step_id FROM steps WHERE task_id=? ORDER BY position", (step["task_id"],))]
            for i, sid in enumerate(ids):
                db.execute("UPDATE steps SET position=? WHERE step_id=?", (i, sid))
            self._sync_task_graph(db, step["task_id"])
        return {"deleted": step_id}

    def confirm(self, step_id, attempt_id, expected_hash):
        with self.transaction() as db:
            s = db.execute('SELECT * FROM steps WHERE step_id=?', (step_id,)).fetchone()
            if s is None:
                raise TaskError('NOT_FOUND')
            self._assert_unlocked(db, s['task_id'])
            a = db.execute('SELECT a.*,r.mode,r.environment_id,r.request_json,r.plugin_versions_json FROM step_attempts a JOIN task_runs r USING(run_id) WHERE attempt_id=?', (attempt_id,)).fetchone()
            if not a or a['step_id'] != step_id or a['mode'] != 'TRIAL' or (a['status'] != 'SUCCEEDED') or (a['content_hash'] != expected_hash) or (s['content_hash'] != expected_hash):
                raise TaskError('VALIDATION_EVIDENCE_INVALID')
            if json.loads(a['request_json']).get('environment_hash') != fingerprint(self.environment(a['environment_id'])):
                raise TaskError('ENVIRONMENT_CHANGED')
            db.execute("UPDATE steps SET validation_state='VALIDATED',validation_source='TRIAL',verified_hash=content_hash,validated_environment_id=?,validated_at=? WHERE step_id=?", (a['environment_id'], now(), step_id))
        return self.step(step_id)

    def confirm_manual(self, step_id, expected_hash, environment_id=None):
        self.environment(environment_id)
        with self.transaction() as db:
            s = db.execute('SELECT * FROM steps WHERE step_id=?', (step_id,)).fetchone()
            if s is None:
                raise TaskError('NOT_FOUND')
            self._assert_unlocked(db, s['task_id'])
            if s['content_hash'] != expected_hash:
                raise TaskError('EDIT_CONFLICT')
            db.execute("UPDATE steps SET validation_state='VALIDATED',validation_source='MANUAL',verified_hash=content_hash,validated_environment_id=?,validated_at=? WHERE step_id=?", (environment_id, now(), step_id))
        return self.step(step_id)

    def confirm_imported(self, step_id, expected_hash):
        """Restore an exported confirmation without copying runtime evidence."""
        with self.transaction() as db:
            step = db.execute('SELECT content_hash FROM steps WHERE step_id=?', (step_id,)).fetchone()
            if step is None or step[0] != expected_hash:
                raise TaskError('EDIT_CONFLICT')
            db.execute("UPDATE steps SET validation_state='VALIDATED',validation_source='IMPORTED',verified_hash=content_hash,validated_environment_id=NULL,validated_at=? WHERE step_id=?", (now(), step_id))
        return self.step(step_id)
