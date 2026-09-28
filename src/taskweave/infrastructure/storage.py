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
from taskweave.infrastructure.unit_of_work import SQLiteUnitOfWork


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def default_home():
    if os.getenv("TASKWEAVE_HOME"):
        return Path(os.environ["TASKWEAVE_HOME"]).expanduser()
    if sys.platform == "win32":
        standard = Path(os.environ["LOCALAPPDATA"]) / "TaskWeave"
    elif sys.platform == "darwin":
        standard = Path.home() / "Library/Application Support/TaskWeave"
    else:
        standard = (
        Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "taskweave"
        )
    location = standard.parent / "taskweave-location.json"
    if location.exists():
        try:
            configured = Path(json.loads(location.read_text(encoding="utf-8"))["workspace_home"]).expanduser().resolve()
            return configured
        except (ValueError, KeyError, TypeError):
            pass
    return standard


def workspace_location_file():
    if sys.platform == "win32":
        standard = Path(os.environ["LOCALAPPDATA"]) / "TaskWeave"
    elif sys.platform == "darwin":
        standard = Path.home() / "Library/Application Support/TaskWeave"
    else:
        standard = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "taskweave"
    return standard.parent / "taskweave-location.json"


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
CONTROL_V7 = "ALTER TABLE steps ADD COLUMN ai_authoring_notes TEXT NOT NULL DEFAULT '';"
CONTROL_V8 = "ALTER TABLE environments ADD COLUMN descriptions_json TEXT NOT NULL DEFAULT '{}';"
CONTROL_V9 = """
ALTER TABLE steps RENAME COLUMN goal TO step_description;
ALTER TABLE steps RENAME COLUMN ai_authoring_notes TO step_notes;
"""
CONTROL_V10 = """
CREATE TABLE plans (
 plan_id TEXT PRIMARY KEY, name TEXT NOT NULL, plan_description TEXT NOT NULL DEFAULT '',
 environment_id TEXT REFERENCES environments(environment_id) ON DELETE SET NULL,
 plugin_ids_json TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE plan_contexts (
 context_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, name TEXT NOT NULL, context_notes TEXT NOT NULL DEFAULT '',
 order_index INTEGER NOT NULL, captured_at TEXT NOT NULL, source_session_id TEXT NOT NULL,
 item_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX plan_contexts_plan_order ON plan_contexts(plan_id,order_index);
CREATE TABLE plan_generations (
 generation_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
 plan_revision INTEGER NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('api','web_chat')),
 request_snapshot_path TEXT NOT NULL, response_path TEXT,
 status TEXT NOT NULL CHECK(status IN ('GENERATING','READY','BLOCKED','FAILED','IMPORTED')),
 candidate_json TEXT, diagnostics_json TEXT NOT NULL DEFAULT '[]', imported_task_id TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX plan_generations_plan_created ON plan_generations(plan_id,created_at);
"""
CONTROL_V11 = "ALTER TABLE step_contexts ADD COLUMN context_notes TEXT NOT NULL DEFAULT '';"
CONTROL_V12 = """
ALTER TABLE plans ADD COLUMN plan_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE plan_contexts ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE plan_contexts ADD COLUMN views_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE plan_contexts ADD COLUMN include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1));
ALTER TABLE step_contexts ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE step_contexts ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE step_contexts ADD COLUMN views_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE step_contexts ADD COLUMN include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1));
ALTER TABLE step_contexts ADD COLUMN captured_at TEXT NOT NULL DEFAULT '';
UPDATE step_contexts AS target SET order_index=(
 SELECT COUNT(*)-1 FROM step_contexts AS prior
 WHERE prior.step_id=target.step_id AND (
  prior.created_at<target.created_at OR
  (prior.created_at=target.created_at AND prior.context_id<=target.context_id)
 )
);
UPDATE step_contexts SET captured_at=updated_at WHERE captured_at='';
CREATE INDEX step_contexts_step_order ON step_contexts(step_id,order_index);
"""
CONTROL_V13 = """
CREATE TABLE step_contexts_new (
 context_id TEXT PRIMARY KEY,
 step_id TEXT NOT NULL REFERENCES steps(step_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, name TEXT NOT NULL,
 source_page TEXT NOT NULL CHECK(source_page IN ('draft','trial_feedback','planning_import')),
 item_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 context_notes TEXT NOT NULL DEFAULT '', order_index INTEGER NOT NULL DEFAULT 0,
 request_json TEXT NOT NULL DEFAULT '{}', views_json TEXT NOT NULL DEFAULT '[]',
 include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1)),
 captured_at TEXT NOT NULL DEFAULT ''
);
INSERT INTO step_contexts_new SELECT context_id,step_id,provider_id,name,source_page,item_json,
 created_at,updated_at,context_notes,order_index,request_json,views_json,include_view,captured_at
 FROM step_contexts;
DROP TABLE step_contexts;
ALTER TABLE step_contexts_new RENAME TO step_contexts;
CREATE INDEX step_contexts_step_created ON step_contexts(step_id,created_at);
CREATE INDEX step_contexts_step_order ON step_contexts(step_id,order_index);
"""

# Capture payloads live in child rows so summary reads never load previews.
CONTROL_V14 = """
CREATE TABLE _step_context_capture_migration AS
 SELECT context_id || ':capture:1' AS capture_id,context_id,0 AS order_index,'' AS label,request_json,item_json AS items_json,views_json,include_view,captured_at,NULL AS source_session_id,source_page,created_at,updated_at FROM step_contexts;
CREATE TABLE _plan_context_capture_migration AS
 SELECT context_id || ':capture:1' AS capture_id,context_id,0 AS order_index,'' AS label,request_json,item_json AS items_json,views_json,include_view,captured_at,source_session_id,NULL AS source_page,created_at,updated_at FROM plan_contexts;
CREATE TABLE step_contexts_new (
 context_id TEXT PRIMARY KEY, step_id TEXT NOT NULL REFERENCES steps(step_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, name TEXT NOT NULL, context_notes TEXT NOT NULL DEFAULT '',
 order_index INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1
);
INSERT INTO step_contexts_new(context_id,step_id,provider_id,name,context_notes,order_index,created_at,updated_at)
 SELECT context_id,step_id,provider_id,name,context_notes,order_index,created_at,updated_at FROM step_contexts;
CREATE TABLE plan_contexts_new (
 context_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, name TEXT NOT NULL, context_notes TEXT NOT NULL DEFAULT '',
 order_index INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO plan_contexts_new(context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at)
 SELECT context_id,plan_id,provider_id,name,context_notes,order_index,created_at,updated_at FROM plan_contexts;
DROP TABLE step_contexts;
ALTER TABLE step_contexts_new RENAME TO step_contexts;
DROP TABLE plan_contexts;
ALTER TABLE plan_contexts_new RENAME TO plan_contexts;
CREATE INDEX step_contexts_step_created ON step_contexts(step_id,created_at);
CREATE INDEX step_contexts_step_order ON step_contexts(step_id,order_index);
CREATE INDEX plan_contexts_plan_order ON plan_contexts(plan_id,order_index);
CREATE TABLE step_context_captures (
 capture_id TEXT PRIMARY KEY, context_id TEXT NOT NULL REFERENCES step_contexts(context_id) ON DELETE CASCADE,
 order_index INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL DEFAULT '{}',
 items_json TEXT NOT NULL, views_json TEXT NOT NULL DEFAULT '[]', include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1)),
 captured_at TEXT NOT NULL, source_session_id TEXT, source_page TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX step_context_captures_group_order ON step_context_captures(context_id,order_index);
CREATE TABLE plan_context_captures (
 capture_id TEXT PRIMARY KEY, context_id TEXT NOT NULL REFERENCES plan_contexts(context_id) ON DELETE CASCADE,
 order_index INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL DEFAULT '{}',
 items_json TEXT NOT NULL, views_json TEXT NOT NULL DEFAULT '[]', include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1)),
 captured_at TEXT NOT NULL, source_session_id TEXT, source_page TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX plan_context_captures_group_order ON plan_context_captures(context_id,order_index);
INSERT INTO step_context_captures SELECT * FROM _step_context_capture_migration;
INSERT INTO plan_context_captures SELECT * FROM _plan_context_capture_migration;
DROP TABLE _step_context_capture_migration;
DROP TABLE _plan_context_capture_migration;
"""

# Keep task_id as historical text so deleting a task does not erase its import receipt.
CONTROL_V15 = """
CREATE TABLE plan_generation_imports (
 import_id TEXT PRIMARY KEY,
 generation_id TEXT NOT NULL REFERENCES plan_generations(generation_id) ON DELETE CASCADE,
 task_id TEXT NOT NULL,
 imported_at TEXT NOT NULL,
 UNIQUE(generation_id, task_id)
);
CREATE INDEX plan_generation_imports_generation ON plan_generation_imports(generation_id, imported_at, import_id);
INSERT OR IGNORE INTO plan_generation_imports(import_id,generation_id,task_id,imported_at)
 SELECT 'legacy:' || generation_id,generation_id,imported_task_id,updated_at
 FROM plan_generations WHERE imported_task_id IS NOT NULL;
"""
CONTROL_V16 = """
CREATE TABLE organization_categories (
 category_id TEXT PRIMARY KEY,
 name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
ALTER TABLE tasks ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1));
ALTER TABLE tasks ADD COLUMN category_id TEXT REFERENCES organization_categories(category_id) ON DELETE SET NULL;
ALTER TABLE plans ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1));
ALTER TABLE plans ADD COLUMN category_id TEXT REFERENCES organization_categories(category_id) ON DELETE SET NULL;
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


CONTROL_V17 = """
ALTER TABLE step_context_captures ADD COLUMN operation_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE step_context_captures ADD COLUMN send_preview INTEGER NOT NULL DEFAULT 0 CHECK(send_preview IN (0,1));
ALTER TABLE plan_context_captures ADD COLUMN operation_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE plan_context_captures ADD COLUMN send_preview INTEGER NOT NULL DEFAULT 0 CHECK(send_preview IN (0,1));
"""


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
            17 if name == "control" else 2,
            {2: CONTROL_V2 if name == "control" else TASK_V2, 3: CONTROL_V3, 4: CONTROL_V4, 5: CONTROL_V5, 6: CONTROL_V6, 7: CONTROL_V7, 8: CONTROL_V8, 9: CONTROL_V9, 10: CONTROL_V10, 11: CONTROL_V11, 12: CONTROL_V12, 13: CONTROL_V13, 14: CONTROL_V14, 15: CONTROL_V15, 16: CONTROL_V16, 17: CONTROL_V17},
        )


class Store:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "taskweave.db"
        initialize(self.path, "control")
        self.unit_of_work = SQLiteUnitOfWork(self.path)

    @contextmanager
    def transaction(self):
        with self.unit_of_work.transaction() as db:
            yield db

    def query(self, sql, args=(), one=False):
        active = self.unit_of_work.current_connection()
        if active is not None:
            rows = [dict(x) for x in active.execute(sql, args)]
        else:
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

    def _repository_adapter(self, name):
        attributes = {
            "tasks": "tasks",
            "steps": "step_repository",
            "environments": "environment_repository",
            "runs": "run_repository",
            "results": "result_repository",
            "step_contexts": "context_repository",
        }
        attribute = attributes[name]
        existing = getattr(self, attribute, None)
        if existing is not None:
            return existing
        adapters = getattr(self, "_storage_adapters", None)
        if adapters is None:
            from taskweave.infrastructure.repositories import build_sqlite_repositories

            repositories = build_sqlite_repositories(self)
            adapters = {
                "tasks": repositories.tasks,
                "steps": repositories.steps,
                "environments": repositories.environments,
                "runs": repositories.runs,
                "results": repositories.results,
                "step_contexts": repositories.step_contexts,
            }
            self._storage_adapters = adapters
        return adapters[name]

    def task(self, task_id):
        return self._repository_adapter("tasks").task(task_id)

    def steps(self, task_id):
        return self._repository_adapter("steps").steps(task_id)

    def step(self, step_id):
        return self._repository_adapter("steps").step(step_id)

    @staticmethod
    def decode_step(row):
        from taskweave.infrastructure.repositories.steps import StepRepository

        return StepRepository.decode_step(row)

    def run(self, run_id):
        return self._repository_adapter("runs").run(run_id)

    def definition_hash(self, task_id):
        return self._repository_adapter("tasks").definition_hash(task_id)

    @staticmethod
    def assert_unlocked(db, task_id, allow_idle_trial=False):
        from taskweave.infrastructure.repositories.tasks import TaskRepository

        return TaskRepository.assert_unlocked(db, task_id, allow_idle_trial)

    def event(self, run_id, kind, payload, attempt_id=None, event_id=None):
        return self._repository_adapter("runs").event(run_id, kind, payload, attempt_id, event_id)

    def environment(self, environment_id):
        return self._repository_adapter("environments").environment(environment_id)

    def task_path(self, task_id):
        return self.home / "tasks" / valid_id(task_id) / "data.db"

    def read_output(self, run_id, step_id, output="data", registry=None):
        return self._repository_adapter("results").read_output(run_id, step_id, output, registry)

    def receipt(self, attempt):
        return self._repository_adapter("results").receipt(attempt)

    def register_refs(self, attempt_id, refs):
        return self._repository_adapter("runs").register_refs(attempt_id, refs)

    def finish_attempt(self, attempt_id, refs):
        return self._repository_adapter("runs").finish_attempt(attempt_id, refs)

    def recover(self):
        return self._repository_adapter("runs").recover()


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
