"""Durable execution instances and compare-and-set flow transitions."""

import json

from taskweave.core.validation import TaskError, dumps
from taskweave.infrastructure.sqlite_storage import SQLiteStorage, now


class FlowRunRepository:
    def __init__(self, store: SQLiteStorage):
        self.store = store

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def cursor(self, run_id):
        row = self.store.query("SELECT flow_cursor_json FROM task_runs WHERE run_id=?", (run_id,), True)
        return json.loads(row["flow_cursor_json"]) if row["flow_cursor_json"] else None

    def instance(self, run_id, execution_path):
        rows = self.store.query(
            "SELECT * FROM flow_instances WHERE run_id=? AND execution_path=?",
            (run_id, execution_path),
        )
        return self._decode(rows[0]) if rows else None

    def instances(self, run_id):
        return [self._decode(row) for row in self.store.query(
            "SELECT * FROM flow_instances WHERE run_id=? ORDER BY instance_no", (run_id,)
        )]

    def commit_transition(self, run_id, expected_cursor, transition):
        """Persist visits and the next cursor in one control-library transaction."""
        with self.store.transaction() as db:
            row = db.execute("SELECT flow_cursor_json FROM task_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise TaskError("NOT_FOUND")
            actual = json.loads(row[0]) if row[0] else None
            if actual != expected_cursor:
                return False
            stamp = now()
            for visit in transition.get("instances", []):
                path = visit["execution_path"]
                existing = db.execute(
                    "SELECT instance_no FROM flow_instances WHERE run_id=? AND execution_path=?",
                    (run_id, path),
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE flow_instances SET status=?,payload_json=?,attempt_id=?,error_code=?,updated_at=? WHERE run_id=? AND execution_path=?",
                        (visit["status"], dumps(visit.get("payload", {})), visit.get("attempt_id"),
                         visit.get("error_code"), stamp, run_id, path),
                    )
                else:
                    db.execute(
                        "INSERT INTO flow_instances(run_id,execution_path,node_id,kind,status,parent_path,payload_json,attempt_id,error_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (run_id, path, visit["node_id"], visit["kind"], visit["status"],
                         visit.get("parent_path"), dumps(visit.get("payload", {})),
                         visit.get("attempt_id"), visit.get("error_code"), stamp, stamp),
                    )
            db.execute(
                "UPDATE task_runs SET flow_cursor_json=? WHERE run_id=?",
                (dumps(transition["cursor"]) if transition.get("cursor") is not None else None, run_id),
            )
            return True

    def retry_instance(self, run_id, execution_path):
        """Invalidate attempts of one failed occurrence, preserving other rounds."""
        with self.store.transaction() as db:
            latest = db.execute(
                "SELECT * FROM step_attempts WHERE run_id=? AND execution_path=? AND valid=1 ORDER BY attempt_no DESC LIMIT 1",
                (run_id, execution_path),
            ).fetchone()
            if latest is None or latest["status"] != "FAILED" or latest["effect_state"] not in {"NOT_STARTED", "FAILED"}:
                raise TaskError("EXPLICIT_RETRY_REQUIRED")
            db.execute(
                "UPDATE step_attempts SET valid=0 WHERE run_id=? AND execution_path=?",
                (run_id, execution_path),
            )
            db.execute(
                "UPDATE flow_instances SET status='READY',attempt_id=NULL,error_code=NULL,updated_at=? WHERE run_id=? AND execution_path=?",
                (now(), run_id, execution_path),
            )
