"""SQLite persistence for task metadata and task lifecycle."""

from taskweave.core.validation import TaskError, check_schema, dumps, fingerprint
from taskweave.infrastructure.storage import now, uid


class TaskRepository:
    def __init__(self, store, steps, step_contexts):
        self.store = store
        self.steps = steps
        self.step_contexts = step_contexts

    def create_task(self, name, input_schema=None, description=""):
        schema = input_schema if input_schema is not None else {"type": "object"}
        check_schema(schema)
        task_id = uid()
        stamp = now()
        self.store.execute(
            "INSERT INTO tasks(task_id,name,description,input_schema_json,graph_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (task_id, name, description, dumps(schema), dumps({"nodes": [], "entry_node_id": None}), stamp, stamp),
        )
        return self.task(task_id)

    def task(self, task_id):
        return self.store.query("SELECT * FROM tasks WHERE task_id=?", (task_id,), True)

    def definition_hash(self, task_id):
        task = self.task(task_id)
        steps = self.steps.steps(task_id)
        return fingerprint({"input_schema": task["input_schema_json"], "graph": task["graph_json"], "steps": [(step["step_id"], step["content_hash"]) for step in steps]})

    @staticmethod
    def assert_unlocked(db, task_id, allow_idle_trial=False):
        if db.execute(
            "SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.task_id=? AND (?=0 OR r.mode<>'TRIAL' OR r.status NOT IN ('FAILED','SUCCEEDED'))",
            (task_id, int(allow_idle_trial)),
        ).fetchone():
            raise TaskError("TASK_LOCKED", "End the active run before editing")

    def update_task(self, task_id, name, input_schema, description=""):
        check_schema(input_schema)
        with self.store.transaction() as db:
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

    def list_tasks(self):
        return self.store.query("SELECT * FROM tasks ORDER BY created_at DESC,task_id DESC")

    def copy_task(self, task_id, name=None):
        with self.store.transaction():
            return self._copy_task(task_id, name)

    def _copy_task(self, task_id, name=None):
        import json
        from taskweave.core.validation import normalize_step

        source = self.task(task_id)
        steps = self.steps.steps(task_id)
        target = self.create_task(name or source["name"] + " 副本", json.loads(source["input_schema_json"]), source["description"])
        self.store.execute("UPDATE tasks SET category_id=? WHERE task_id=?", (source.get("category_id"), target["task_id"]))
        mapping = {}
        for step in steps:
            document = normalize_step(step)
            for binding in document["bindings"].values():
                ref = binding.get("ref", {})
                if ref.get("source") == "step":
                    ref["step_id"] = mapping[ref["step_id"]]
            saved = self.steps.save_step(target["task_id"], document)
            mapping[step["step_id"]] = saved["step_id"]
        for source_step_id, target_step_id in mapping.items():
            for group in self.step_contexts.list_step_contexts(source_step_id):
                cloned = self.step_contexts.create_step_context_group(target_step_id, group["provider_id"], group["name"], group.get("context_notes", ""))
                for summary in group["captures"]:
                    capture = self.step_contexts.get_step_context_capture(group["context_id"], summary["capture_id"])
                    self.step_contexts.append_step_context_capture(cloned["context_id"], capture, request=capture["request"], include_view=capture["include_view"], source_page=capture["source_page"], label=capture["label"], captured_at=capture["captured_at"])
        return self.task(target["task_id"])

    def delete_task(self, task_id):
        import shutil

        self.task(task_id)
        with self.store.transaction() as db:
            self.assert_unlocked(db, task_id)
            db.execute("UPDATE tasks SET lifecycle='DELETING' WHERE task_id=?", (task_id,))
        directory = self.store.task_path(task_id).parent
        if directory.exists():
            shutil.rmtree(directory)
        with self.store.transaction() as db:
            for table in ("result_refs", "step_attempts"):
                db.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,))
            for table in ("run_events", "command_receipts"):
                db.execute(f"DELETE FROM {table} WHERE run_id IN (SELECT run_id FROM task_runs WHERE task_id=?)", (task_id,))
            db.execute("DELETE FROM task_runs WHERE task_id=?", (task_id,))
            db.execute("DELETE FROM steps WHERE task_id=?", (task_id,))
            db.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        return {"deleted": task_id}
