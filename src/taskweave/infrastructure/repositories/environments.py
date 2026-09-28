"""SQLite persistence for execution environments and their history links."""

from taskweave.core.validation import TaskError, dumps
from taskweave.infrastructure.storage import uid


class EnvironmentRepository:
    def __init__(self, store):
        self.store = store

    def save_environment(self, name, public_config, secret_refs=None, environment_id=None, descriptions=None):
        public_config = dict(public_config)
        secret_refs = dict(secret_refs or {})
        from taskweave.infrastructure.privacy import SENSITIVE
        for key, value in list(public_config.items()):
            if SENSITIVE.search(key) and isinstance(value, str) and value.startswith("env:"):
                secret_refs[key] = value
                del public_config[key]
        if any(not isinstance(v, str) or not v.startswith("env:") for v in secret_refs.values()):
            raise TaskError("SECRET_REFERENCE_INVALID")
        environment_id = environment_id or uid()
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.environment_id=?", (environment_id,)).fetchone():
                raise TaskError("ENVIRONMENT_LOCKED")
            db.execute(
                "INSERT INTO environments(environment_id,name,public_config_json,secret_refs_json,descriptions_json) VALUES(?,?,?,?,?) ON CONFLICT(environment_id) DO UPDATE SET name=excluded.name,public_config_json=excluded.public_config_json,secret_refs_json=excluded.secret_refs_json,descriptions_json=excluded.descriptions_json",
                (environment_id, name, dumps(public_config), dumps(secret_refs), dumps(descriptions or {})),
            )
        return {"environment_id": environment_id}

    def list_environments(self):
        return self.store.query("SELECT * FROM environments ORDER BY name")

    def environment(self, environment_id):
        import json
        if environment_id is None:
            return {}, {}
        row = self.store.query("SELECT * FROM environments WHERE environment_id=?", (environment_id,), True)
        return json.loads(row["public_config_json"]), json.loads(row["secret_refs_json"])

    def delete_environment(self, environment_id):
        with self.store.transaction() as db:
            environment = db.execute("SELECT * FROM environments WHERE environment_id=?", (environment_id,)).fetchone()
            if environment is None:
                raise TaskError("NOT_FOUND")
            if db.execute("SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.environment_id=?", (environment_id,)).fetchone():
                raise TaskError("ENVIRONMENT_LOCKED")
            import json
            for run in db.execute("SELECT run_id,request_json FROM task_runs WHERE environment_id=?", (environment_id,)).fetchall():
                request = json.loads(run["request_json"])
                request["deleted_environment_name"] = environment["name"]
                db.execute("UPDATE task_runs SET environment_id=NULL,request_json=? WHERE run_id=?", (dumps(request), run["run_id"]))
            db.execute("UPDATE steps SET validated_environment_id=NULL WHERE validated_environment_id=?", (environment_id,))
            db.execute("DELETE FROM environments WHERE environment_id=?", (environment_id,))
        return {"deleted": True}
