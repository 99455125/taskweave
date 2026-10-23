"""AI receipts and immutable snapshots in the control database's shared UoW."""

import json

from taskweave.core.validation import TaskError, dumps


class AgentStore:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def _identity(request_id):
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
            raise TaskError("AGENT_REQUEST_INVALID", "request_id 必须为 1–200 字符")

    def request(self, request_id):
        self._identity(request_id)
        rows = self.storage.query("SELECT * FROM agent_requests WHERE request_id=?", (request_id,))
        if not rows:
            return None
        row = rows[0]
        return {"request_id": request_id, "fingerprint": row["fingerprint"],
                "state": row["state"], "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    @staticmethod
    def _replay(row, fingerprint):
        if row["fingerprint"] != fingerprint:
            raise TaskError("COMMAND_CONFLICT", "此 request_id 已用于不同内容")
        if row["state"] != "COMPLETED":
            raise TaskError("AGENT_REQUEST_UNCERTAIN", "请求已接受但尚无完成回执，请查询原请求和运行事实，勿换 ID 重发")
        return row["result"]

    def atomic(self, request_id, fingerprint, operation):
        self._identity(request_id)
        with self.storage.transaction() as db:
            previous = self.request(request_id)
            if previous:
                return self._replay(previous, fingerprint)
            # A local definition and its receipt commit or roll back together.
            result = operation()
            db.execute("INSERT INTO agent_requests(request_id,fingerprint,state,result_json) VALUES(?,?,'COMPLETED',?)",
                       (request_id, fingerprint, dumps(result)))
            return result

    def claim(self, request_id, fingerprint):
        self._identity(request_id)
        with self.storage.transaction() as db:
            previous = self.request(request_id)
            if previous:
                return self._replay(previous, fingerprint)
            db.execute("INSERT INTO agent_requests(request_id,fingerprint,state) VALUES(?,?,'PENDING')",
                       (request_id, fingerprint))
            return None

    def finish(self, request_id, fingerprint, result):
        with self.storage.transaction() as db:
            previous = self.request(request_id)
            if previous is None:
                raise TaskError("AGENT_REQUEST_NOT_FOUND")
            if previous["fingerprint"] != fingerprint:
                raise TaskError("COMMAND_CONFLICT")
            if previous["state"] == "COMPLETED":
                if dumps(previous["result"]) != dumps(result):
                    raise TaskError("COMMAND_CONFLICT")
                return previous["result"]
            db.execute("UPDATE agent_requests SET state='COMPLETED',result_json=?,updated_at=CURRENT_TIMESTAMP WHERE request_id=?",
                       (dumps(result), request_id))
            return result

    def put(self, category, identity, value):
        payload = dumps(value)
        with self.storage.transaction() as db:
            previous = db.execute("SELECT value_json FROM agent_records WHERE category=? AND identity=?",
                                  (category, identity)).fetchone()
            if previous:
                if previous[0] != payload:
                    raise TaskError("AGENT_SNAPSHOT_IMMUTABLE", "已冻结的材料不能覆盖")
                return value
            db.execute("INSERT INTO agent_records(category,identity,value_json) VALUES(?,?,?)", (category, identity, payload))
            return value

    def get(self, category, identity):
        rows = self.storage.query("SELECT value_json FROM agent_records WHERE category=? AND identity=?", (category, identity))
        if not rows:
            raise TaskError("AGENT_RECORD_NOT_FOUND")
        return json.loads(rows[0]["value_json"])

    def find(self, category, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TaskError("AGENT_LIMIT_INVALID")
        return [json.loads(row["value_json"]) for row in self.storage.query(
            "SELECT value_json FROM agent_records WHERE category=? ORDER BY rowid DESC LIMIT ?", (category, limit))]
