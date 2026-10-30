CREATE TABLE environments (
 environment_id TEXT PRIMARY KEY, name TEXT NOT NULL,
 public_config_json TEXT NOT NULL DEFAULT '{}', secret_refs_json TEXT NOT NULL DEFAULT '{}'
, descriptions_json TEXT NOT NULL DEFAULT '{}');

CREATE TABLE tasks (
 task_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 input_schema_json TEXT NOT NULL DEFAULT '{}', graph_json TEXT NOT NULL,
 ui_layout_json TEXT NOT NULL DEFAULT '{}', lifecycle TEXT NOT NULL DEFAULT 'ACTIVE'
 CHECK(lifecycle IN ('ACTIVE','DELETING')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
, sort_order INTEGER NOT NULL DEFAULT 0, is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1)), category_id TEXT REFERENCES organization_categories(category_id) ON DELETE SET NULL, flow_validation_state TEXT NOT NULL DEFAULT 'VALIDATED'
 CHECK(flow_validation_state IN ('DRAFT','VALIDATED')), flow_verified_hash TEXT);

CREATE TABLE steps (
 step_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
 name TEXT NOT NULL, step_description TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL CHECK(position>=0),
 content_format TEXT NOT NULL DEFAULT 'python-async-v1', step_content TEXT NOT NULL,
 input_schema_json TEXT NOT NULL, output_schema_json TEXT NOT NULL,
 bindings_json TEXT NOT NULL DEFAULT '{}', capabilities_json TEXT NOT NULL DEFAULT '[]',
 plugin_requirements_json TEXT NOT NULL DEFAULT '{}', timeout_ms INTEGER NOT NULL DEFAULT 60000 CHECK(timeout_ms>0),
 validation_state TEXT NOT NULL DEFAULT 'DRAFT' CHECK(validation_state IN ('DRAFT','VALIDATED')),
 content_hash TEXT NOT NULL, verified_hash TEXT,
 validated_environment_id TEXT REFERENCES environments(environment_id), validated_at TEXT,
 updated_at TEXT NOT NULL, delay_after_previous_seconds INTEGER NOT NULL DEFAULT 0 CHECK(delay_after_previous_seconds BETWEEN 0 AND 86400), validation_source TEXT, step_notes TEXT NOT NULL DEFAULT '', UNIQUE(task_id,step_id),
 CHECK(validation_state='DRAFT' OR (verified_hash IS NOT NULL AND verified_hash=content_hash))
);

CREATE INDEX steps_task_order ON steps(task_id,position);

CREATE TABLE task_runs (
 run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
 parent_run_id TEXT REFERENCES task_runs(run_id), environment_id TEXT REFERENCES environments(environment_id),
 mode TEXT NOT NULL CHECK(mode IN ('TRIAL','EXECUTION')),
 status TEXT NOT NULL CHECK(status IN ('READY','RUNNING','PAUSED','FAILED','INTERRUPTED','SUCCEEDED','CANCELLED')),
 definition_hash TEXT NOT NULL, plugin_versions_json TEXT NOT NULL DEFAULT '{}',
 input_summary_json TEXT NOT NULL DEFAULT '{}', started_at TEXT, finished_at TEXT, inputs_json TEXT NOT NULL DEFAULT '{}', trial_step_id TEXT, request_json TEXT NOT NULL DEFAULT '{}', definition_json TEXT, waiting_step_id TEXT, wait_until TEXT, flow_cursor_json TEXT,
 UNIQUE(run_id,task_id)
);

CREATE TABLE step_attempts (
 attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
 execution_path TEXT NOT NULL, attempt_no INTEGER NOT NULL CHECK(attempt_no>0),
 content_hash TEXT NOT NULL, input_summary_json TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')),
 effect_state TEXT NOT NULL CHECK(effect_state IN ('NOT_STARTED','SUCCEEDED','FAILED','UNKNOWN')),
 error_code TEXT, error_phase TEXT, error_summary TEXT, started_at TEXT NOT NULL, finished_at TEXT, valid INTEGER NOT NULL DEFAULT 1 CHECK(valid IN (0,1)), reconciliation_json TEXT,
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

CREATE TABLE run_events (
 event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES task_runs(run_id),
 attempt_id TEXT, kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE "runtime_lease" (
 slot TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES task_runs(run_id),
 owner_id TEXT NOT NULL, heartbeat_at TEXT NOT NULL
);

CREATE TABLE plans (
 plan_id TEXT PRIMARY KEY, name TEXT NOT NULL, plan_description TEXT NOT NULL DEFAULT '',
 environment_id TEXT REFERENCES environments(environment_id) ON DELETE SET NULL,
 plugin_ids_json TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
, plan_notes TEXT NOT NULL DEFAULT '', is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1)), category_id TEXT REFERENCES organization_categories(category_id) ON DELETE SET NULL);

CREATE TABLE plan_generations (
 generation_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
 plan_revision INTEGER NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('api','web_chat')),
 request_snapshot_path TEXT NOT NULL, response_path TEXT,
 status TEXT NOT NULL CHECK(status IN ('GENERATING','READY','BLOCKED','FAILED','IMPORTED')),
 candidate_json TEXT, diagnostics_json TEXT NOT NULL DEFAULT '[]', imported_task_id TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE INDEX plan_generations_plan_created ON plan_generations(plan_id,created_at);

CREATE TABLE "step_contexts" (
 context_id TEXT PRIMARY KEY, step_id TEXT NOT NULL REFERENCES steps(step_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, name TEXT NOT NULL, context_notes TEXT NOT NULL DEFAULT '',
 order_index INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE "plan_contexts" (
 context_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
 provider_id TEXT NOT NULL, name TEXT NOT NULL, context_notes TEXT NOT NULL DEFAULT '',
 order_index INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE INDEX step_contexts_step_created ON step_contexts(step_id,created_at);

CREATE INDEX step_contexts_step_order ON step_contexts(step_id,order_index);

CREATE INDEX plan_contexts_plan_order ON plan_contexts(plan_id,order_index);

CREATE TABLE step_context_captures (
 capture_id TEXT PRIMARY KEY, context_id TEXT NOT NULL REFERENCES step_contexts(context_id) ON DELETE CASCADE,
 order_index INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL DEFAULT '{}',
 items_json TEXT NOT NULL, views_json TEXT NOT NULL DEFAULT '[]', include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1)),
 captured_at TEXT NOT NULL, source_session_id TEXT, source_page TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
, operation_notes TEXT NOT NULL DEFAULT '', send_preview INTEGER NOT NULL DEFAULT 0 CHECK(send_preview IN (0,1)));

CREATE INDEX step_context_captures_group_order ON step_context_captures(context_id,order_index);

CREATE TABLE plan_context_captures (
 capture_id TEXT PRIMARY KEY, context_id TEXT NOT NULL REFERENCES plan_contexts(context_id) ON DELETE CASCADE,
 order_index INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL DEFAULT '{}',
 items_json TEXT NOT NULL, views_json TEXT NOT NULL DEFAULT '[]', include_view INTEGER NOT NULL DEFAULT 1 CHECK(include_view IN (0,1)),
 captured_at TEXT NOT NULL, source_session_id TEXT, source_page TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
, operation_notes TEXT NOT NULL DEFAULT '', send_preview INTEGER NOT NULL DEFAULT 0 CHECK(send_preview IN (0,1)));

CREATE INDEX plan_context_captures_group_order ON plan_context_captures(context_id,order_index);

CREATE TABLE plan_generation_imports (
 import_id TEXT PRIMARY KEY,
 generation_id TEXT NOT NULL REFERENCES plan_generations(generation_id) ON DELETE CASCADE,
 task_id TEXT NOT NULL,
 imported_at TEXT NOT NULL,
 UNIQUE(generation_id, task_id)
);

CREATE INDEX plan_generation_imports_generation ON plan_generation_imports(generation_id, imported_at, import_id);

CREATE TABLE organization_categories (
 category_id TEXT PRIMARY KEY,
 name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);

CREATE TABLE task_sequences (
 sequence_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 input_schema_json TEXT NOT NULL, nodes_json TEXT NOT NULL, revision INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
, flow_json TEXT);

CREATE TABLE sequence_runs (
 sequence_run_id TEXT PRIMARY KEY,
 sequence_id TEXT REFERENCES task_sequences(sequence_id) ON DELETE SET NULL,
 request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 status TEXT NOT NULL, snapshot_json TEXT NOT NULL, inputs_json TEXT NOT NULL,
 current_node_id TEXT, stop_intent TEXT, error_code TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT
, cleanup_json TEXT, control_command_json TEXT, cursor_json TEXT, current_path TEXT);

CREATE TABLE sequence_run_nodes (
 sequence_run_id TEXT NOT NULL REFERENCES sequence_runs(sequence_run_id) ON DELETE CASCADE,
 node_id TEXT NOT NULL, position INTEGER NOT NULL, task_id TEXT NOT NULL,
 run_id TEXT UNIQUE REFERENCES task_runs(run_id), status TEXT NOT NULL,
 resolved_inputs_json TEXT, resolved_step_inputs_json TEXT,
 command_id TEXT, error_code TEXT, updated_at TEXT NOT NULL,
 PRIMARY KEY(sequence_run_id,node_id), UNIQUE(sequence_run_id,position)
);

CREATE INDEX sequence_nodes_task ON sequence_run_nodes(task_id);

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

CREATE TABLE agent_requests (
 request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('PENDING','COMPLETED')),
 result_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_records (
 category TEXT NOT NULL, identity TEXT NOT NULL, value_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(category,identity)
);

CREATE TABLE sequence_instances (
 instance_no INTEGER PRIMARY KEY AUTOINCREMENT,
 sequence_run_id TEXT NOT NULL REFERENCES sequence_runs(sequence_run_id) ON DELETE CASCADE,
 execution_path TEXT NOT NULL, node_id TEXT NOT NULL, kind TEXT NOT NULL,
 status TEXT NOT NULL, parent_path TEXT, payload_json TEXT NOT NULL DEFAULT '{}',
 task_id TEXT, run_id TEXT UNIQUE REFERENCES task_runs(run_id),
 resolved_inputs_json TEXT, resolved_step_inputs_json TEXT, command_id TEXT,
 attempt_id TEXT, error_code TEXT, updated_at TEXT NOT NULL,
 UNIQUE(sequence_run_id, execution_path)
);

CREATE TABLE sequence_commands (
 command_id TEXT PRIMARY KEY,
 sequence_run_id TEXT NOT NULL REFERENCES sequence_runs(sequence_run_id) ON DELETE CASCADE,
 execution_path TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
 phase TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL
);
