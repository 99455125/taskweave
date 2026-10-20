"""SQLite connections, schema migrations and shared transaction storage.

This layer does not import or construct domain repositories. Composition belongs
to callers of build_sqlite_repositories; legacy Store lives in storage.py.
"""

from contextlib import contextmanager, closing
from datetime import datetime, timezone
from importlib.resources import files
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from taskweave.core.validation import TaskError, valid_id
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

CONTROL_V18 = """
CREATE TABLE task_sequences (
 sequence_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 input_schema_json TEXT NOT NULL, nodes_json TEXT NOT NULL, revision INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE sequence_runs (
 sequence_run_id TEXT PRIMARY KEY,
 sequence_id TEXT REFERENCES task_sequences(sequence_id) ON DELETE SET NULL,
 request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 status TEXT NOT NULL, snapshot_json TEXT NOT NULL, inputs_json TEXT NOT NULL,
 current_node_id TEXT, stop_intent TEXT, error_code TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE sequence_run_nodes (
 sequence_run_id TEXT NOT NULL REFERENCES sequence_runs(sequence_run_id) ON DELETE CASCADE,
 node_id TEXT NOT NULL, position INTEGER NOT NULL, task_id TEXT NOT NULL,
 run_id TEXT UNIQUE REFERENCES task_runs(run_id), status TEXT NOT NULL,
 resolved_inputs_json TEXT, resolved_step_inputs_json TEXT,
 command_id TEXT, error_code TEXT, updated_at TEXT NOT NULL,
 PRIMARY KEY(sequence_run_id,node_id), UNIQUE(sequence_run_id,position)
);
CREATE INDEX sequence_nodes_task ON sequence_run_nodes(task_id);
"""

CONTROL_V19 = "ALTER TABLE sequence_runs ADD COLUMN cleanup_json TEXT;"
CONTROL_V20 = "ALTER TABLE sequence_runs ADD COLUMN control_command_json TEXT;"
CONTROL_V21 = """
ALTER TABLE tasks ADD COLUMN flow_validation_state TEXT NOT NULL DEFAULT 'VALIDATED'
 CHECK(flow_validation_state IN ('DRAFT','VALIDATED'));
ALTER TABLE tasks ADD COLUMN flow_verified_hash TEXT;
"""
CONTROL_V22 = """
ALTER TABLE task_runs ADD COLUMN flow_cursor_json TEXT;
CREATE TABLE flow_instances (
 instance_no INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id TEXT NOT NULL REFERENCES task_runs(run_id) ON DELETE CASCADE,
 execution_path TEXT NOT NULL, node_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('sequence','action','if','foreach','loop','iteration','control')),
 status TEXT NOT NULL, parent_path TEXT,
 payload_json TEXT NOT NULL DEFAULT '{}', attempt_id TEXT,
 error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(run_id,execution_path)
);
CREATE INDEX flow_instances_run_order ON flow_instances(run_id,instance_no);
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
            22 if name == "control" else 2,
            {2: CONTROL_V2 if name == "control" else TASK_V2, 3: CONTROL_V3, 4: CONTROL_V4, 5: CONTROL_V5, 6: CONTROL_V6, 7: CONTROL_V7, 8: CONTROL_V8, 9: CONTROL_V9, 10: CONTROL_V10, 11: CONTROL_V11, 12: CONTROL_V12, 13: CONTROL_V13, 14: CONTROL_V14, 15: CONTROL_V15, 16: CONTROL_V16, 17: CONTROL_V17, 18: CONTROL_V18, 19: CONTROL_V19, 20: CONTROL_V20, 21: CONTROL_V21, 22: CONTROL_V22},
        )


class SQLiteStorage:
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

    def task_path(self, task_id):
        return self.home / "tasks" / valid_id(task_id) / "data.db"
