PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
BEGIN;
CREATE TABLE step_outputs (
 run_id TEXT NOT NULL, step_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
 name TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(attempt_id,name)
);
CREATE TABLE result_receipts (
 attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('PREPARED','COMMITTED')),
 refs_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
PRAGMA user_version=1;
COMMIT;
