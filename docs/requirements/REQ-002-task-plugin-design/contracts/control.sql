PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
BEGIN;
CREATE TABLE environments (
 environment_id TEXT PRIMARY KEY, name TEXT NOT NULL,
 public_config_json TEXT NOT NULL DEFAULT '{}', secret_refs_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE tasks (
 task_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 input_schema_json TEXT NOT NULL DEFAULT '{}', graph_json TEXT NOT NULL,
 ui_layout_json TEXT NOT NULL DEFAULT '{}', lifecycle TEXT NOT NULL DEFAULT 'ACTIVE'
 CHECK(lifecycle IN ('ACTIVE','DELETING')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE steps (
 step_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
 name TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL CHECK(position>=0),
 content_format TEXT NOT NULL DEFAULT 'python-async-v1', step_content TEXT NOT NULL,
 input_schema_json TEXT NOT NULL, output_schema_json TEXT NOT NULL,
 bindings_json TEXT NOT NULL DEFAULT '{}', capabilities_json TEXT NOT NULL DEFAULT '[]',
 plugin_requirements_json TEXT NOT NULL DEFAULT '{}', timeout_ms INTEGER NOT NULL DEFAULT 60000 CHECK(timeout_ms>0),
 validation_state TEXT NOT NULL DEFAULT 'DRAFT' CHECK(validation_state IN ('DRAFT','VALIDATED')),
 content_hash TEXT NOT NULL, verified_hash TEXT,
 validated_environment_id TEXT REFERENCES environments(environment_id), validated_at TEXT,
 updated_at TEXT NOT NULL, UNIQUE(task_id,step_id),
 CHECK(validation_state='DRAFT' OR (verified_hash IS NOT NULL AND verified_hash=content_hash))
);
CREATE INDEX steps_task_order ON steps(task_id,position);
CREATE TABLE task_runs (
 run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
 parent_run_id TEXT REFERENCES task_runs(run_id), environment_id TEXT REFERENCES environments(environment_id),
 mode TEXT NOT NULL CHECK(mode IN ('TRIAL','EXECUTION')),
 status TEXT NOT NULL CHECK(status IN ('READY','RUNNING','PAUSED','FAILED','INTERRUPTED','SUCCEEDED','CANCELLED')),
 definition_hash TEXT NOT NULL, plugin_versions_json TEXT NOT NULL DEFAULT '{}',
 input_summary_json TEXT NOT NULL DEFAULT '{}', started_at TEXT, finished_at TEXT,
 UNIQUE(run_id,task_id)
);
CREATE TABLE step_attempts (
 attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
 execution_path TEXT NOT NULL, attempt_no INTEGER NOT NULL CHECK(attempt_no>0),
 content_hash TEXT NOT NULL, input_summary_json TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')),
 effect_state TEXT NOT NULL CHECK(effect_state IN ('NOT_STARTED','SUCCEEDED','FAILED','UNKNOWN')),
 error_code TEXT, error_phase TEXT, error_summary TEXT, started_at TEXT NOT NULL, finished_at TEXT,
 FOREIGN KEY(run_id,task_id) REFERENCES task_runs(run_id,task_id),
 FOREIGN KEY(task_id,step_id) REFERENCES steps(task_id,step_id),
 UNIQUE(run_id,execution_path,attempt_no), UNIQUE(attempt_id,task_id,run_id,step_id)
);
CREATE TABLE result_refs (
 result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL, step_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
 handler_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('json','table','file')),
 locator TEXT NOT NULL, media_type TEXT NOT NULL, checksum TEXT, size_bytes INTEGER,
 state TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK(state IN ('AVAILABLE','DELETING','UNAVAILABLE')),
 FOREIGN KEY(attempt_id,task_id,run_id,step_id) REFERENCES step_attempts(attempt_id,task_id,run_id,step_id)
);
CREATE TABLE command_receipts (
 command_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES task_runs(run_id),
 body_hash TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('ACCEPTED','DONE','FAILED')),
 response_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE runtime_lease (
 slot INTEGER PRIMARY KEY CHECK(slot=1), run_id TEXT NOT NULL UNIQUE REFERENCES task_runs(run_id),
 owner_id TEXT NOT NULL, heartbeat_at TEXT NOT NULL
);
PRAGMA user_version=1;
COMMIT;
