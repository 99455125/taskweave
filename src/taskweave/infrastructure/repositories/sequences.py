"""SQLite records for task-sequence definitions and child ownership."""

import json

from taskweave.core.task_sequences import validate_definition
from taskweave.core.sequence_flow import linear_flow
from taskweave.core.task_flow import is_linear_flow
from taskweave.infrastructure.repositories.sequence_instances import SequenceInstances
from taskweave.core.validation import TaskError, dumps, fingerprint
from taskweave.infrastructure.sqlite_storage import SQLiteStorage, now, uid


class SequenceRepository(SequenceInstances):
    def __init__(self, store: SQLiteStorage):
        self.store = store

    @staticmethod
    def _definition(row):
        return {**row, "input_schema": json.loads(row["input_schema_json"]),
                "nodes": json.loads(row["nodes_json"]),
                "flow": json.loads(row["flow_json"]) if row["flow_json"] else linear_flow(json.loads(row["nodes_json"]))}

    def save(self, name, nodes, input_schema, description="", sequence_id=None, expected_revision=None, flow=None):
        flow = flow if flow is not None else linear_flow(nodes)
        validate_definition(name, nodes, input_schema, flow)
        stamp = now()
        with self.store.transaction() as db:
            if sequence_id is None:
                sequence_id = uid()
                db.execute("INSERT INTO task_sequences(sequence_id,name,description,input_schema_json,nodes_json,revision,created_at,updated_at,flow_json) VALUES(?,?,?,?,?,?,?,?,?)",
                           (sequence_id, name.strip(), description, dumps(input_schema), dumps(nodes), 1, stamp, stamp, dumps(flow)))
            else:
                row = db.execute("SELECT revision FROM task_sequences WHERE sequence_id=?", (sequence_id,)).fetchone()
                if row is None:
                    raise TaskError("SEQUENCE_NOT_FOUND")
                if expected_revision != row["revision"]:
                    raise TaskError("EDIT_CONFLICT")
                db.execute("UPDATE task_sequences SET name=?,description=?,input_schema_json=?,nodes_json=?,flow_json=?,revision=revision+1,updated_at=? WHERE sequence_id=?",
                           (name.strip(), description, dumps(input_schema), dumps(nodes), dumps(flow), stamp, sequence_id))
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

    def create_run(self, sequence_id, request_id, inputs, task_hashes, environment_hashes, plugin_versions=None,
                   expected_revision=None, node_inputs=None, node_step_inputs=None, *, mode="EXECUTION"):
        previous = self.replay_start(sequence_id, request_id, inputs, node_inputs, node_step_inputs, mode=mode)
        if previous:
            return previous
        definition = self.get(sequence_id)
        snapshot = {"mode": mode, "name": definition["name"], "revision": definition["revision"],
                    "input_schema": definition["input_schema"], "nodes": definition["nodes"], "flow": definition["flow"],
                    "task_hashes": dict(task_hashes), "environment_hashes": dict(environment_hashes),
                    "plugin_versions": dict(plugin_versions or {}),
                    "node_inputs": node_inputs or {}, "node_step_inputs": node_step_inputs or {}}
        body_hash = fingerprint({"sequence_id": sequence_id, "inputs": inputs,
                                 "node_inputs": node_inputs or {}, "node_step_inputs": node_step_inputs or {}, **({"mode": mode} if mode != "EXECUTION" else {})})
        stamp = now()
        with self.store.transaction() as db:
            previous = db.execute("SELECT sequence_run_id,request_hash FROM sequence_runs WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if previous["request_hash"] != body_hash:
                    raise TaskError("COMMAND_CONFLICT")
                return self.get_run(previous["sequence_run_id"])
            current = db.execute("SELECT revision FROM task_sequences WHERE sequence_id=?", (sequence_id,)).fetchone()
            if current is None or (expected_revision is not None and current["revision"] != expected_revision):
                raise TaskError("EDIT_CONFLICT")
            sequence_run_id = uid()
            db.execute("INSERT INTO sequence_runs(sequence_run_id,sequence_id,request_id,request_hash,status,snapshot_json,inputs_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (sequence_run_id, sequence_id, request_id, body_hash, "READY", dumps(snapshot), dumps(inputs), stamp, stamp))
            if is_linear_flow(definition["flow"]):
                def placed(node, path):
                    if node["kind"] == "sequence":
                        for child in node["children"]:
                            yield from placed(child, path + "/" + child["id"].replace("~", "~0").replace("/", "~1"))
                    else:
                        yield node, path
                configured = {node["node_id"]: node for node in definition["nodes"]}
                for leaf, path in placed(definition["flow"]["root"], "/" + definition["flow"]["root"]["id"]):
                    self.ensure_action(sequence_run_id, {"step_id": leaf["step_id"], "execution_path": path}, configured[leaf["step_id"]]["task_id"])
        return self.get_run(sequence_run_id)

    def replay_start(self, sequence_id, request_id, inputs, node_inputs=None, node_step_inputs=None, *, mode="EXECUTION"):
        row = self.store.query("SELECT sequence_run_id,request_hash FROM sequence_runs WHERE request_id=?", (request_id,))
        if not row:
            return None
        if row[0]["request_hash"] != fingerprint({"sequence_id": sequence_id, "inputs": inputs,
                                 "node_inputs": node_inputs or {}, "node_step_inputs": node_step_inputs or {}, **({"mode": mode} if mode != "EXECUTION" else {})}):
            raise TaskError("COMMAND_CONFLICT")
        return self.get_run(row[0]["sequence_run_id"])

    def get_run(self, sequence_run_id):
        row = self.store.query("SELECT * FROM sequence_runs WHERE sequence_run_id=?", (sequence_run_id,), True)
        if row is None:
            raise TaskError("SEQUENCE_RUN_NOT_FOUND")
        return {**row, "snapshot": json.loads(row["snapshot_json"]), "inputs": json.loads(row["inputs_json"]),
                "cleanup": json.loads(row["cleanup_json"] or "[]"),
                "control_command": (self.commands(sequence_run_id, False) or [None])[-1],
                "nodes": [dict(item, position=index) for index, item in enumerate([item for item in self.instances(sequence_run_id) if item['kind'] == 'action'])],
                "flow_instances": self.instances(sequence_run_id), "cursor": self.cursor(sequence_run_id),
                "commands": self.commands(sequence_run_id),
                "current_execution_path": row["current_path"]}

    def list_runs(self, sequence_id=None):
        rows = self.store.query("SELECT sequence_run_id FROM sequence_runs" + (" WHERE sequence_id=?" if sequence_id else "") + " ORDER BY created_at DESC", (sequence_id,) if sequence_id else ())
        return [self.get_run(row["sequence_run_id"]) for row in rows]

    def set_run_status(self, sequence_run_id, status, current_node_id=None, error_code=None, stop_intent=None, execution_path=None):
        with self.store.transaction() as db:
            row = db.execute("SELECT stop_intent,status FROM sequence_runs WHERE sequence_run_id=?", (sequence_run_id,)).fetchone()
            if row is None:
                raise TaskError("SEQUENCE_RUN_NOT_FOUND")
            if row["status"] == "DELETING" or (row["stop_intent"] and stop_intent is None and status not in {"PAUSED", "CANCELLED"}):
                raise TaskError("SEQUENCE_STOPPED")
            db.execute("UPDATE sequence_runs SET status=?,current_node_id=?,current_path=?,error_code=?,stop_intent=?,updated_at=?,finished_at=? WHERE sequence_run_id=?",
                       (status, current_node_id, execution_path, error_code, stop_intent, now(), now() if status in {"SUCCEEDED", "CANCELLED"} else None, sequence_run_id))

    def resume(self, sequence_run_id, current_node_id=None):
        with self.store.transaction() as db:
            row = db.execute("SELECT status FROM sequence_runs WHERE sequence_run_id=?", (sequence_run_id,)).fetchone()
            if row is None or row["status"] not in {"PAUSED", "BLOCKED"}:
                raise TaskError("SEQUENCE_STATE_INVALID")
            db.execute("UPDATE sequence_runs SET status='RUNNING',current_node_id=?,stop_intent=NULL,error_code=NULL,updated_at=? WHERE sequence_run_id=?",
                       (current_node_id, now(), sequence_run_id))

    def task_is_referenced(self, task_id):
        if self.store.query("SELECT 1 FROM sequence_instances WHERE task_id=? LIMIT 1", (task_id,)):
            return True
        for run in self.list_runs():
            if any(node['task_id'] == task_id for node in run['snapshot']['nodes']):
                return True
        for definition in self.list():
            if any(node["task_id"] == task_id for node in definition["nodes"]):
                return True
        return False

    def environment_is_referenced(self, environment_id):
        for run in self.list_runs():
            if any(node["environment_id"] == environment_id for node in run["snapshot"]["nodes"]):
                return True
        for definition in self.list():
            if any(node["environment_id"] == environment_id for node in definition["nodes"]):
                return True
        return False

    def begin_cleanup(self, sequence_run_id):
        with self.store.transaction() as db:
            row = db.execute("SELECT status,cleanup_json FROM sequence_runs WHERE sequence_run_id=?", (sequence_run_id,)).fetchone()
            if row is None:
                raise TaskError("SEQUENCE_RUN_NOT_FOUND")
            if row["status"] != "DELETING":
                if row["status"] in {"READY", "RUNNING"}:
                    raise TaskError("SEQUENCE_RUN_BUSY")
                children = [item[0] for item in db.execute(
                    "SELECT run_id FROM sequence_instances WHERE sequence_run_id=? AND run_id IS NOT NULL ORDER BY instance_no DESC",
                    (sequence_run_id,)).fetchall()]
                db.execute("UPDATE sequence_runs SET status='DELETING',cleanup_json=?,updated_at=? WHERE sequence_run_id=?",
                           (dumps(children), now(), sequence_run_id))
        return self.get_run(sequence_run_id)["cleanup"]

    def detach_child_for_cleanup(self, sequence_run_id, run_id):
        with self.store.transaction() as db:
            row = db.execute("SELECT status,cleanup_json FROM sequence_runs WHERE sequence_run_id=?", (sequence_run_id,)).fetchone()
            if row is None or row["status"] != "DELETING" or run_id not in json.loads(row["cleanup_json"] or "[]"):
                raise TaskError("SEQUENCE_CLEANUP_INVALID")
            db.execute("UPDATE sequence_instances SET run_id=NULL WHERE sequence_run_id=? AND run_id=?",
                       (sequence_run_id, run_id))

    def finish_cleanup(self, sequence_run_id):
        with self.store.transaction() as db:
            db.execute("DELETE FROM sequence_runs WHERE sequence_run_id=? AND status='DELETING'", (sequence_run_id,))
