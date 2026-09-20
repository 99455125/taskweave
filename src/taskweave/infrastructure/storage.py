"""SQLite repositories and host-owned result persistence."""

from contextlib import contextmanager, closing
from datetime import datetime, timezone
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from uuid import uuid4

from taskweave.core.validation import TaskError, dumps, valid_id, fingerprint
from taskweave.infrastructure.privacy import redact


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def default_home():
    if os.getenv("TASKWEAVE_HOME"):
        return Path(os.environ["TASKWEAVE_HOME"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "TaskWeave"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/TaskWeave"
    return (
        Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "taskweave"
    )


CONTROL_V2 = """
ALTER TABLE task_runs ADD COLUMN inputs_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE task_runs ADD COLUMN trial_step_id TEXT;
ALTER TABLE task_runs ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE step_attempts ADD COLUMN valid INTEGER NOT NULL DEFAULT 1 CHECK(valid IN (0,1));
ALTER TABLE step_attempts ADD COLUMN reconciliation_json TEXT;
CREATE TABLE run_events (
 event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES task_runs(run_id),
 attempt_id TEXT, kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


CONTROL_V3 = """
ALTER TABLE steps ADD COLUMN delay_after_previous_seconds INTEGER NOT NULL DEFAULT 0 CHECK(delay_after_previous_seconds BETWEEN 0 AND 86400);
ALTER TABLE tasks ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_runs ADD COLUMN definition_json TEXT;
ALTER TABLE task_runs ADD COLUMN waiting_step_id TEXT;
ALTER TABLE task_runs ADD COLUMN wait_until TEXT;
"""

TASK_V2 = "CREATE TABLE IF NOT EXISTS plugin_table_schemas(table_name TEXT PRIMARY KEY,version INTEGER NOT NULL);"
CONTROL_V4 = "ALTER TABLE steps ADD COLUMN validation_source TEXT; UPDATE steps SET validation_source='TRIAL' WHERE validation_state='VALIDATED';"
CONTROL_V5 = """
CREATE TABLE step_contexts (
 context_id TEXT PRIMARY KEY,
 step_id TEXT NOT NULL REFERENCES steps(step_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL,
 name TEXT NOT NULL,
 source_page TEXT NOT NULL CHECK(source_page IN ('draft','trial_feedback')),
 item_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX step_contexts_step_created ON step_contexts(step_id,created_at);
"""
CONTROL_V6 = """
CREATE TABLE runtime_lease_new (
 slot TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES task_runs(run_id),
 owner_id TEXT NOT NULL, heartbeat_at TEXT NOT NULL
);
INSERT INTO runtime_lease_new(slot,run_id,owner_id,heartbeat_at)
 SELECT CAST(slot AS TEXT),run_id,owner_id,heartbeat_at FROM runtime_lease;
DROP TABLE runtime_lease;
ALTER TABLE runtime_lease_new RENAME TO runtime_lease;
"""


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        with db:
            yield db
    finally:
        db.close()


def migrate(db, path, target, migrations):
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if current > target:
        raise TaskError(
            "SCHEMA_TOO_NEW", f"Database schema {current}, supported {target}"
        )
    if current == 0:
        raise TaskError("SCHEMA_UNRECOGNIZED", "Existing database has no known schema")
    if current == target:
        return
    backup_path = Path(str(path) + f".v{current}.bak")
    with closing(sqlite3.connect(backup_path)) as backup:
        db.backup(backup)
    try:
        script = "\n".join(migrations[v] for v in range(current + 1, target + 1))
        db.executescript(
            f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version={target};\nCOMMIT;"
        )
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


def initialize(path, name):
    path = Path(path)
    fresh = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        if fresh:
            db.executescript(
                files("taskweave.infrastructure")
                .joinpath(f"sql/{name}.sql")
                .read_text()
            )
        migrate(
            db,
            path,
            6 if name == "control" else 2,
            {2: CONTROL_V2 if name == "control" else TASK_V2, 3: CONTROL_V3, 4: CONTROL_V4, 5: CONTROL_V5, 6: CONTROL_V6},
        )


class Store:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "taskweave.db"
        initialize(self.path, "control")

    @contextmanager
    def transaction(self):
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def query(self, sql, args=(), one=False):
        with connect(self.path) as db:
            rows = [dict(x) for x in db.execute(sql, args)]
        if one:
            if not rows:
                raise TaskError("NOT_FOUND")
            return rows[0]
        return rows

    def execute(self, sql, args=()):
        with self.transaction() as db:
            return db.execute(sql, args).rowcount

    def task(self, task_id):
        return self.query("SELECT * FROM tasks WHERE task_id=?", (task_id,), True)

    def steps(self, task_id):
        return [
            self.decode_step(s)
            for s in self.query(
                "SELECT * FROM steps WHERE task_id=? ORDER BY position", (task_id,)
            )
        ]

    def step(self, step_id):
        return self.decode_step(
            self.query("SELECT * FROM steps WHERE step_id=?", (step_id,), True)
        )

    @staticmethod
    def decode_step(row):
        for key in (
            "input_schema",
            "output_schema",
            "bindings",
            "capabilities",
            "plugin_requirements",
        ):
            row[key] = json.loads(row.pop(key + "_json"))
        return row

    def run(self, run_id):
        return self.query("SELECT * FROM task_runs WHERE run_id=?", (run_id,), True)

    def definition_hash(self, task_id):
        task = self.task(task_id)
        return fingerprint(
            {
                "input_schema": task["input_schema_json"],
                "graph": task["graph_json"],
                "steps": [
                    (s["step_id"], s["content_hash"]) for s in self.steps(task_id)
                ],
            }
        )

    @staticmethod
    def assert_unlocked(db, task_id, allow_idle_trial=False):
        if db.execute(
            "SELECT 1 FROM runtime_lease l JOIN task_runs r USING(run_id) WHERE r.task_id=? AND (?=0 OR r.mode<>'TRIAL' OR r.status NOT IN ('FAILED','SUCCEEDED'))",
            (task_id, int(allow_idle_trial)),
        ).fetchone():
            raise TaskError("TASK_LOCKED", "End the active run before editing")

    def event(self, run_id, kind, payload, attempt_id=None, event_id=None):
        self.execute(
            "INSERT OR IGNORE INTO run_events VALUES(?,?,?,?,?,?)",
            (
                event_id or uid(),
                run_id,
                attempt_id,
                kind,
                dumps(redact(payload)),
                now(),
            ),
        )

    def environment(self, environment_id):
        if environment_id is None:
            return {}, {}
        row = self.query(
            "SELECT * FROM environments WHERE environment_id=?", (environment_id,), True
        )
        return json.loads(row["public_config_json"]), json.loads(
            row["secret_refs_json"]
        )

    def task_path(self, task_id):
        return self.home / "tasks" / valid_id(task_id) / "data.db"

    def read_output(self, run_id, step_id, output="data", registry=None):
        run = self.run(run_id)
        attempts = self.query(
            "SELECT * FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 ORDER BY attempt_no DESC LIMIT 1",
            (run_id, step_id),
        )
        if not attempts or attempts[0]["status"] != "SUCCEEDED":
            raise TaskError("OUTPUT_NOT_AVAILABLE")
        if output != "data":
            refs = self.receipt(attempts[0]) or []
            ref = next((r for r in refs if r.get("name") == output), None)
            if ref is None:
                raise TaskError("OUTPUT_NOT_AVAILABLE")
            if registry is None:
                raise TaskError("HANDLER_UNAVAILABLE")
            if (
                ref["handler_id"] != "core.json"
                and ref["handler_id"] not in registry.handlers
            ):
                raise TaskError("HANDLER_UNAVAILABLE")
            return self.read_result(ref["result_id"], registry)["data"]
        path = self.task_path(run["task_id"])
        if not path.exists():
            raise TaskError("OUTPUT_NOT_AVAILABLE")
        with connect(path) as db:
            row = db.execute(
                "SELECT payload_json FROM step_outputs WHERE run_id=? AND step_id=? AND attempt_id=? AND name='data'",
                (run_id, step_id, attempts[0]["attempt_id"]),
            ).fetchone()
        if row is None:
            raise TaskError("OUTPUT_NOT_AVAILABLE")
        return json.loads(row[0])

    def receipt(self, attempt):
        path = self.task_path(attempt["task_id"])
        if not path.exists():
            return None
        with connect(path) as db:
            row = db.execute(
                "SELECT refs_json FROM result_receipts WHERE attempt_id=? AND run_id=? AND step_id=? AND state='COMMITTED'",
                (attempt["attempt_id"], attempt["run_id"], attempt["step_id"]),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def register_refs(self, attempt_id, refs):
        with self.transaction() as db:
            a = dict(
                db.execute(
                    "SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,)
                ).fetchone()
            )
            for ref in refs:
                db.execute(
                    "INSERT OR IGNORE INTO result_refs(result_id,task_id,run_id,step_id,attempt_id,handler_id,kind,locator,media_type,checksum,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ref["result_id"],
                        a["task_id"],
                        a["run_id"],
                        a["step_id"],
                        attempt_id,
                        ref["handler_id"],
                        ref["kind"],
                        ref["locator"],
                        ref["media_type"],
                        ref.get("checksum"),
                        ref.get("size_bytes"),
                    ),
                )

    def finish_attempt(self, attempt_id, refs):
        with self.transaction() as db:
            a = dict(
                db.execute(
                    "SELECT * FROM step_attempts WHERE attempt_id=?", (attempt_id,)
                ).fetchone()
            )
            for ref in refs:
                db.execute(
                    "INSERT OR IGNORE INTO result_refs(result_id,task_id,run_id,step_id,attempt_id,handler_id,kind,locator,media_type,checksum,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ref["result_id"],
                        a["task_id"],
                        a["run_id"],
                        a["step_id"],
                        attempt_id,
                        ref["handler_id"],
                        ref["kind"],
                        ref["locator"],
                        ref["media_type"],
                        ref.get("checksum"),
                        ref.get("size_bytes"),
                    ),
                )
            db.execute(
                "UPDATE step_attempts SET status='SUCCEEDED',effect_state='SUCCEEDED',error_code=NULL,error_phase=NULL,error_summary=NULL,finished_at=? WHERE attempt_id=?",
                (now(), attempt_id),
            )

    def recover(self):
        # Called only after acquiring the OS coordinator lock and stopping stale workers.
        for a in self.query("SELECT * FROM step_attempts WHERE status='RUNNING'"):
            refs = self.receipt(a)
            if refs is not None:
                self.finish_attempt(a["attempt_id"], refs)
            else:
                self.execute(
                    "UPDATE step_attempts SET status='UNKNOWN',effect_state='UNKNOWN',error_code='WORKER_LOST',error_phase='execute',finished_at=? WHERE attempt_id=?",
                    (now(), a["attempt_id"]),
                )
        self.execute("UPDATE task_runs SET status='INTERRUPTED' WHERE status='RUNNING'")
        # The OS coordinator lock is held: no previous process owns these leases.
        # Keep attempts (including UNKNOWN effects) for explicit reconciliation.
        self.execute("DELETE FROM runtime_lease")
        self.execute(
            "UPDATE command_receipts SET state='FAILED',response_json=? WHERE state='ACCEPTED'",
            (dumps({"code": "COORDINATOR_RESTARTED"}),),
        )


class Results:
    """Worker-side host adapter. Plugins supply declarations, never connections."""

    def __init__(self, home, scope, registry):
        self.scope, self.registry = scope, registry
        self.root = Path(home) / "tasks" / valid_id(scope.task_id)
        self.path = self.root / "data.db"
        self.staging = self.root / "staging" / valid_id(scope.attempt_id)
        self.tokens = {}

    async def allocate_file(self, name):
        from taskweave.core.ports import StagedFile

        self.staging.mkdir(parents=True, exist_ok=True)
        token = uid()
        path = self.staging / token
        self.tokens[token] = path
        return StagedFile(token, str(path))

    def persist_diagnostics(self, requests):
        # Diagnostic receipts must never imply successful business execution.
        from taskweave.core.ports import StepResult

        return self.persist(StepResult(outputs=requests), diagnostic=True)

    def persist(self, result, diagnostic=False):
        if result.data is None and not result.outputs and not result.views:
            return []
        initialize(self.path, "task-data")
        refs = []
        self._backup_plugin_migrations(result.outputs)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = (
                None
                if diagnostic
                else db.execute(
                    "SELECT refs_json FROM result_receipts WHERE attempt_id=?",
                    (self.scope.attempt_id,),
                ).fetchone()
            )
            if existing:
                return json.loads(existing[0])
            if result.data is not None or result.views:
                self._json(db, "data", result.data)
                refs.append(self._ref("core.json", "json", "data"))
            from taskweave.core.result_views import validate_views
            validate_views(result.data, result.views, self.registry.views)
            if result.views:
                self._json(db, "__views", {"version": 1, "items": result.views})
            names = {"data", "__views"}
            for request in result.outputs:
                if request.name in names or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_-]{0,63}", request.name
                ):
                    raise TaskError("RESULT_NAME_INVALID")
                names.add(request.name)
                handler = self.registry.handlers.get(request.handler_id)
                if handler is None:
                    raise TaskError("HANDLER_UNAVAILABLE")
                prepared = handler.prepare(request)
                if prepared.kind == "json":
                    self._json(db, request.name, prepared.payload)
                    ref = self._ref(request.handler_id, "json", request.name)
                elif prepared.kind == "table":
                    self._table(db, request.handler_id, handler.schema(), prepared)
                    ref = self._ref(request.handler_id, "table", prepared.table_name)
                elif prepared.kind == "file":
                    source = self.tokens.get(prepared.staged_token)
                    if (
                        source is None
                        or source.is_symlink()
                        or not source.is_file()
                        or source.resolve().parent != self.staging.resolve()
                    ):
                        raise TaskError("ARTIFACT_INVALID")
                    dest = (
                        self.root
                        / "artifacts"
                        / self.scope.run_id
                        / self.scope.attempt_id
                        / request.name
                    )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with source.open("rb") as stream:
                        os.fsync(stream.fileno())
                    source.replace(dest)
                    ref = self._ref(
                        request.handler_id, "file", str(dest.relative_to(self.root))
                    )
                    ref["size_bytes"] = dest.stat().st_size
                    import hashlib

                    with dest.open("rb") as stream:
                        digest = hashlib.sha256()
                        for block in iter(lambda: stream.read(65536), b""):
                            digest.update(block)
                    ref["checksum"] = digest.hexdigest()
                else:
                    raise TaskError("RESULT_KIND_INVALID")
                ref["name"] = request.name
                ref["media_type"] = prepared.media_type
                refs.append(ref)
            if not diagnostic:
                db.execute(
                    "INSERT INTO result_receipts VALUES(?,?,?,?,?,?)",
                    (
                        self.scope.attempt_id,
                        self.scope.run_id,
                        self.scope.step_id,
                        "COMMITTED",
                        dumps(refs),
                        now(),
                    ),
                )
        return refs

    def _backup_plugin_migrations(self, requests):
        with connect(self.path) as db:
            known = db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='plugin_table_schemas'"
            ).fetchone()
            versions = (
                dict(db.execute("SELECT table_name,version FROM plugin_table_schemas"))
                if known
                else {}
            )
            for request in requests:
                handler = self.registry.handlers.get(request.handler_id)
                if handler is None:
                    continue
                if not hasattr(handler, "schema"):
                    continue
                schema = handler.schema()
                if any(
                    schema.get("version", 1) > versions.get(table, 1)
                    for table in schema.get("tables", {})
                ):
                    backup_dir = self.root / "backups"
                    backup_dir.mkdir(exist_ok=True)
                    with closing(
                        sqlite3.connect(
                            backup_dir
                            / (
                                "before-plugin-migration-"
                                + self.scope.attempt_id
                                + ".db"
                            )
                        )
                    ) as backup:
                        db.backup(backup)
                    return

    def _json(self, db, name, value):
        db.execute(
            "INSERT INTO step_outputs VALUES(?,?,?,?,?,?)",
            (
                self.scope.run_id,
                self.scope.step_id,
                self.scope.attempt_id,
                name,
                dumps(value),
                now(),
            ),
        )

    def _ref(self, handler, kind, locator):
        return {
            "result_id": uid(),
            "handler_id": handler,
            "kind": kind,
            "locator": locator,
            "media_type": "application/json",
        }

    def _table(self, db, handler_id, schema, prepared):
        table = prepared.table_name
        owners = [
            name for name in self.registry.versions if handler_id.startswith(name + ".")
        ]
        owner = max(owners, key=len) if owners else handler_id.split(".")[0]
        prefix = "p_" + owner.replace("-", "_").replace(".", "_") + "_"
        columns = schema.get("tables", {}).get(table)
        if (
            not isinstance(table, str)
            or not table.startswith(prefix)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", table)
            or not columns
        ):
            raise TaskError("TABLE_SCHEMA_INVALID")
        for col, kind in columns.items():
            if (
                not re.fullmatch(r"[a-z][a-z0-9_]*", col)
                or col in {"run_id", "step_id", "attempt_id"}
                or kind not in {"TEXT", "INTEGER", "REAL", "BLOB"}
            ):
                raise TaskError("TABLE_SCHEMA_INVALID")
        expected = {
            "run_id": "TEXT",
            "step_id": "TEXT",
            "attempt_id": "TEXT",
            **columns,
        }
        db.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" ('
            + ",".join(f'"{k}" {v}' for k, v in expected.items())
            + ")"
        )
        actual = {row[1]: row[2] for row in db.execute(f'PRAGMA table_info("{table}")')}
        db.execute(
            "CREATE TABLE IF NOT EXISTS plugin_table_schemas(table_name TEXT PRIMARY KEY,version INTEGER NOT NULL)"
        )
        version = schema.get("version", 1)
        if type(version) is not int or version < 1:
            raise TaskError("TABLE_SCHEMA_INVALID")
        tracked = db.execute(
            "SELECT version FROM plugin_table_schemas WHERE table_name=?", (table,)
        ).fetchone()
        current = tracked[0] if tracked else 1
        if current > version:
            raise TaskError("TABLE_SCHEMA_TOO_NEW")
        if actual != expected and version > current:
            for target in range(current + 1, version + 1):
                migration = schema.get("migrations", {}).get(str(target))
                if not migration:
                    raise TaskError("TABLE_MIGRATION_REQUIRED")
                additions = migration.get("add_columns", {}).get(table, {})
                for column, kind in additions.items():
                    if (
                        column not in columns
                        or kind != columns[column]
                        or column in actual
                    ):
                        raise TaskError("TABLE_MIGRATION_INVALID")
                    db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {kind}')
                    actual[column] = kind
        if actual != expected:
            raise TaskError(
                "TABLE_MIGRATION_REQUIRED",
                "Custom table schema changed; explicit migration required",
            )
        db.execute(
            "INSERT INTO plugin_table_schemas VALUES(?,?) ON CONFLICT(table_name) DO UPDATE SET version=excluded.version",
            (table, version),
        )
        for index in schema.get("indexes", {}).get(table, []):
            if not index or any(c not in expected for c in index):
                raise TaskError("TABLE_INDEX_INVALID")
            index_name = table + "_" + "_".join(index) + "_idx"
            db.execute(
                f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ('
                + ",".join('"' + c + '"' for c in index)
                + ")"
            )
        for row in prepared.rows:
            if set(row) != set(columns):
                raise TaskError("TABLE_ROW_INVALID")
            vals = [self.scope.run_id, self.scope.step_id, self.scope.attempt_id] + [
                row[c] for c in columns
            ]
            db.execute(
                f'INSERT INTO "{table}" ('
                + ",".join('"' + c + '"' for c in expected)
                + ") VALUES("
                + ",".join("?" for _ in vals)
                + ")",
                vals,
            )

    def cleanup_staging(self):
        if self.staging.exists():
            shutil.rmtree(self.staging)
