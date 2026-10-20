"""SQLite records for task-sequence definitions and child ownership."""

import json

from taskweave.core.task_sequences import validate_definition
from taskweave.core.validation import TaskError, dumps, fingerprint
from taskweave.infrastructure.sqlite_storage import SQLiteStorage, now, uid


class SequenceRepository:
    def __init__(self, store: SQLiteStorage):
        self.store = store

    @staticmethod
    def _definition(row):
        return {**row, "input_schema": json.loads(row["input_schema_json"]),
                "nodes": json.loads(row["nodes_json"])}

    def save(self, name, nodes, input_schema, description="", sequence_id=None, expected_revision=None):
        validate_definition(name, nodes, input_schema)
        stamp = now()
        with self.store.transaction() as db:
            if sequence_id is None:
                sequence_id = uid()
                db.execute("INSERT INTO task_sequences VALUES(?,?,?,?,?,?,?,?)",
                           (sequence_id, name.strip(), description, dumps(input_schema), dumps(nodes), 1, stamp, stamp))
            else:
                row = db.execute("SELECT revision FROM task_sequences WHERE sequence_id=?", (sequence_id,)).fetchone()
                if row is None:
                    raise TaskError("SEQUENCE_NOT_FOUND")
                if expected_revision != row["revision"]:
                    raise TaskError("EDIT_CONFLICT")
                db.execute("UPDATE task_sequences SET name=?,description=?,input_schema_json=?,nodes_json=?,revision=revision+1,updated_at=? WHERE sequence_id=?",
                           (name.strip(), description, dumps(input_schema), dumps(nodes), stamp, sequence_id))
        return self.get(sequence_id)

    def get(self, sequence_id):
        row = self.store.query("SELECT * FROM task_sequences WHERE sequence_id=?", (sequence_id,), True)
        if row is None:
            raise TaskError("SEQUENCE_NOT_FOUND")
        return self._definition(row)

    def list(self):
        return [self._definition(row) for row in self.store.query("SELECT * FROM task_sequences ORDER BY updated_at DESC")]

    def delete_definition(self, sequence_id, expected_revision):
        with self.store.transaction() as db:
            row = db.execute("SELECT revision FROM task_sequences WHERE sequence_id=?", (sequence_id,)).fetchone()
            if row is None:
                raise TaskError("SEQUENCE_NOT_FOUND")
            if row["revision"] != expected_revision:
                raise TaskError("EDIT_CONFLICT")
            db.execute("DELETE FROM task_sequences WHERE sequence_id=?", (sequence_id,))
        return {"deleted": sequence_id}

    def create_run(self, sequence_id, request_id, inputs, task_hashes, environment_hashes):
        definition = self.get(sequence_id)
        snapshot = {"name": definition["name"], "revision": definition["revision"],
                    "input_schema": definition["input_schema"], "nodes": definition["nodes"],
                    "task_hashes": dict(task_hashes), "environment_hashes": dict(environment_hashes)}
        body_hash = fingerprint({"sequence_id": sequence_id, "inputs": inputs})
        stamp = now()
        with self.store.transaction() as db:
            previous = db.execute("SELECT sequence_run_id,request_hash FROM sequence_runs WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if previous["request_hash"] != body_hash:
                    raise TaskError("COMMAND_CONFLICT")
                return self.get_run(previous["sequence_run_id"])
            sequence_run_id = uid()
            db.execute("INSERT INTO sequence_runs(sequence_run_id,sequence_id,request_id,request_hash,status,snapshot_json,inputs_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (sequence_run_id, sequence_id, request_id, body_hash, "READY", dumps(snapshot), dumps(inputs), stamp, stamp))
            for position, node in enumerate(definition["nodes"]):
                db.execute("INSERT INTO sequence_run_nodes(sequence_run_id,node_id,position,task_id,status,updated_at) VALUES(?,?,?,?,?,?)",
                           (sequence_run_id, node["node_id"], position, node["task_id"], "PENDING", stamp))
        return self.get_run(sequence_run_id)

    def get_run(self, sequence_run_id):
        row = self.store.query("SELECT * FROM sequence_runs WHERE sequence_run_id=?", (sequence_run_id,), True)
        if row is None:
            raise TaskError("SEQUENCE_RUN_NOT_FOUND")
        return {**row, "snapshot": json.loads(row["snapshot_json"]), "inputs": json.loads(row["inputs_json"]),
                "nodes": self.store.query("SELECT * FROM sequence_run_nodes WHERE sequence_run_id=? ORDER BY position", (sequence_run_id,))}

    def list_runs(self, sequence_id=None):
        rows = self.store.query("SELECT sequence_run_id FROM sequence_runs" + (" WHERE sequence_id=?" if sequence_id else "") + " ORDER BY created_at DESC", (sequence_id,) if sequence_id else ())
        return [self.get_run(row["sequence_run_id"]) for row in rows]

    def attach_child(self, sequence_run_id, node_id, run_id, inputs, step_inputs):
        with self.store.transaction() as db:
            row = db.execute("SELECT run_id FROM sequence_run_nodes WHERE sequence_run_id=? AND node_id=?", (sequence_run_id, node_id)).fetchone()
            if row is None:
                raise TaskError("SEQUENCE_NODE_NOT_FOUND")
            if row["run_id"] is not None:
                raise TaskError("SEQUENCE_CHILD_EXISTS")
            db.execute("UPDATE sequence_run_nodes SET run_id=?,status='RUNNING',resolved_inputs_json=?,resolved_step_inputs_json=?,updated_at=? WHERE sequence_run_id=? AND node_id=?",
                       (run_id, dumps(inputs), dumps(step_inputs), now(), sequence_run_id, node_id))

    def set_node_status(self, sequence_run_id, node_id, status, error_code=None):
        with self.store.transaction() as db:
            db.execute("UPDATE sequence_run_nodes SET status=?,error_code=?,updated_at=? WHERE sequence_run_id=? AND node_id=?",
                       (status, error_code, now(), sequence_run_id, node_id))

    def set_run_status(self, sequence_run_id, status, current_node_id=None, error_code=None, stop_intent=None):
        with self.store.transaction() as db:
            db.execute("UPDATE sequence_runs SET status=?,current_node_id=?,error_code=?,stop_intent=?,updated_at=?,finished_at=? WHERE sequence_run_id=?",
                       (status, current_node_id, error_code, stop_intent, now(), now() if status in {"SUCCEEDED", "CANCELLED"} else None, sequence_run_id))

    def owner_of_child(self, run_id):
        row = self.store.query("SELECT sequence_run_id,node_id FROM sequence_run_nodes WHERE run_id=?", (run_id,))
        return (row[0]["sequence_run_id"], row[0]["node_id"]) if row else None
