"""Durable control visits and individually owned task-call instances."""

import json

from taskweave.core.validation import TaskError, dumps, fingerprint
from taskweave.infrastructure.sqlite_storage import now


class SequenceInstances:
    def instances(self, run_id):
        return [{**row, "payload": json.loads(row["payload_json"])} for row in self.store.query(
            "SELECT * FROM sequence_instances WHERE sequence_run_id=? ORDER BY instance_no", (run_id,))]

    def cursor(self, run_id):
        row = self.store.query("SELECT cursor_json FROM sequence_runs WHERE sequence_run_id=?", (run_id,), True)
        if row is None:
            raise TaskError("SEQUENCE_RUN_NOT_FOUND")
        return json.loads(row["cursor_json"]) if row["cursor_json"] else None

    def commit_transition(self, run_id, previous, transition):
        with self.store.transaction() as db:
            row = db.execute("SELECT cursor_json FROM sequence_runs WHERE sequence_run_id=?", (run_id,)).fetchone()
            if row is None:
                raise TaskError("SEQUENCE_RUN_NOT_FOUND")
            if (json.loads(row[0]) if row[0] else None) != previous:
                return False
            for visit in transition.get("instances", []):
                db.execute("""INSERT INTO sequence_instances
                    (sequence_run_id,execution_path,node_id,kind,status,parent_path,payload_json,attempt_id,error_code,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sequence_run_id,execution_path) DO UPDATE SET
                    status=excluded.status,payload_json=excluded.payload_json,attempt_id=excluded.attempt_id,
                    error_code=excluded.error_code,updated_at=excluded.updated_at""",
                    (run_id, visit["execution_path"], visit["node_id"], visit["kind"], visit["status"],
                     visit.get("parent_path"), dumps(visit.get("payload", {})), visit.get("attempt_id"),
                     visit.get("error_code"), now()))
            db.execute("UPDATE sequence_runs SET cursor_json=?,updated_at=? WHERE sequence_run_id=?",
                       (dumps(transition["cursor"]), now(), run_id))
        return True

    def ensure_action(self, run_id, action, task_id):
        with self.store.transaction() as db:
            db.execute("""INSERT INTO sequence_instances
                (sequence_run_id,execution_path,node_id,kind,status,task_id,updated_at)
                VALUES(?,?,?,'action','PENDING',?,?) ON CONFLICT(sequence_run_id,execution_path)
                DO UPDATE SET node_id=excluded.node_id,task_id=excluded.task_id""",
                (run_id, action["execution_path"], action["step_id"], task_id, now()))

    def _path(self, run_id, identity):
        found = self.store.query("SELECT execution_path FROM sequence_instances WHERE sequence_run_id=? AND execution_path=?",
                                 (run_id, identity))
        if found:
            return identity
        found = self.store.query("SELECT execution_path FROM sequence_instances WHERE sequence_run_id=? AND node_id=? AND kind='action'",
                                 (run_id, identity))
        if len(found) != 1:
            raise TaskError("SEQUENCE_INSTANCE_REQUIRED")
        return found[0]["execution_path"]

    def attach_child(self, sequence_run_id, node_id, run_id, inputs, step_inputs):
        path = self._path(sequence_run_id, node_id)
        with self.store.transaction() as db:
            row = db.execute("SELECT run_id FROM sequence_instances WHERE sequence_run_id=? AND execution_path=?",
                             (sequence_run_id, path)).fetchone()
            if row["run_id"] is not None:
                raise TaskError("SEQUENCE_CHILD_EXISTS")
            db.execute("""UPDATE sequence_instances SET run_id=?,status='RUNNING',
                resolved_inputs_json=?,resolved_step_inputs_json=?,updated_at=?
                WHERE sequence_run_id=? AND execution_path=?""",
                (run_id, dumps(inputs), dumps(step_inputs), now(), sequence_run_id, path))

    def set_node_status(self, run_id, identity, status, error_code=None):
        path = self._path(run_id, identity)
        self.store.execute("UPDATE sequence_instances SET status=?,error_code=?,updated_at=? WHERE sequence_run_id=? AND execution_path=?",
                           (status, error_code, now(), run_id, path))

    def set_command_id(self, run_id, identity, command_id):
        self.store.execute("UPDATE sequence_instances SET command_id=?,updated_at=? WHERE sequence_run_id=? AND execution_path=?",
                           (command_id, now(), run_id, self._path(run_id, identity)))

    def command(self, run_id, command_id, kind, payload):
        path = payload.get("execution_path")
        if not path:
            row = self.store.query("SELECT current_path FROM sequence_runs WHERE sequence_run_id=?", (run_id,), True)
            path = row["current_path"] or ""
        with self.store.transaction() as db:
            previous = db.execute("SELECT * FROM sequence_commands WHERE command_id=?", (command_id,)).fetchone()
            if previous:
                if (previous["sequence_run_id"] != run_id or previous["kind"] != kind
                        or fingerprint(json.loads(previous["payload_json"])) != fingerprint(payload)):
                    raise TaskError("COMMAND_CONFLICT")
                if previous["phase"] == "failed":
                    raise TaskError(previous["error_code"])
                return dict(previous)
            state = db.execute('SELECT status,stop_intent FROM sequence_runs WHERE sequence_run_id=?', (run_id,)).fetchone()
            if state is None:
                raise TaskError('SEQUENCE_RUN_NOT_FOUND')
            if state['status'] in {'SUCCEEDED', 'CANCELLED', 'DELETING'} or (state['stop_intent'] and kind != 'continue'):
                raise TaskError('SEQUENCE_STATE_INVALID')
            db.execute("INSERT INTO sequence_commands VALUES(?,?,?,?,?,'pending',NULL,?)",
                       (command_id, run_id, path, kind, dumps(payload), now()))
            db.execute("UPDATE sequence_runs SET status='RUNNING',stop_intent=NULL,updated_at=? WHERE sequence_run_id=?",
                       (now(), run_id))
        return {"id": command_id, "kind": kind, "payload": payload, "phase": "pending"}

    def commands(self, run_id, pending=True):
        return [{**row, "id": row["command_id"], "payload": json.loads(row["payload_json"])} for row in self.store.query(
            "SELECT * FROM sequence_commands WHERE sequence_run_id=?" + (" AND phase='pending'" if pending else "") + " ORDER BY created_at",
            (run_id,))]

    def finish_command(self, run_id, command_id, error_code=None):
        self.store.execute("UPDATE sequence_commands SET phase=?,error_code=? WHERE sequence_run_id=? AND command_id=?",
                           ("failed" if error_code else "done", error_code, run_id, command_id))

    def owner_of_child(self, run_id):
        found = self.store.query("SELECT sequence_run_id,execution_path FROM sequence_instances WHERE run_id=?", (run_id,))
        if found:
            owner = found[0]
            # The public guard needs only ownership; exact paths remain available
            # for control operations, including repeated occurrences of one node.
            return owner["sequence_run_id"], owner["execution_path"]
        for run in self.store.query("SELECT sequence_run_id,cleanup_json FROM sequence_runs WHERE status='DELETING'"):
            if run_id in json.loads(run["cleanup_json"] or "[]"):
                return run["sequence_run_id"], None
        return None
