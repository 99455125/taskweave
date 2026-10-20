# Task Sequences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save and run ordered groups of existing TaskWeave tasks, with JSON output-to-input mappings and safe durable recovery.

**Architecture:** A sequence definition and sequence run live in the control SQLite database. An application-level driver advances one ordinary child execution at a time. The existing worker runs task steps; the sequence driver owns ordering, input mapping, idempotency and recovery.

**Tech Stack:** Python 3.10+, SQLite, uv, NiceGUI, unittest.

**Spec:** `docs/superpowers/specs/2026-10-20-task-sequences-design.md`

## Global Constraints

- Keep core independent of GUI, SQLite and model SDK; keep presentation independent of desktop.
- Preserve old task package, plugin SDK and independent run behavior.
- Do not replay an uncertain external effect automatically.
- Map JSON values only; treat missing, null, false, zero and empty string distinctly.
- Use the current worktree; leave `tmp/` and the two OCR egg-info modifications intact.
- Run focused tests and project checks. Full test suite requires separate user authorization.

## Review Focus

1. Crash after child creation and before start: no duplicate child; resume from durable association.
2. Crash after start command and before sequence update: inspect receipt and child status; no blind replay.
3. A task or environment changes while an earlier node runs: block the next node before starting it.
4. Pause or cancel at node completion: do not launch the next node.
5. Missing JSON Pointer or invalid target type: block with a clear error; do not use a default.

---

### Task 1: Persistent definitions and run records

**Files:** Create `src/taskweave/core/task_sequences.py`, `src/taskweave/core/sequence_ports.py`, `src/taskweave/infrastructure/repositories/sequences.py`; modify `src/taskweave/infrastructure/sqlite_storage.py`, `src/taskweave/infrastructure/repositories/__init__.py`; test `tests/test_task_sequences_storage.py`.

**Interfaces:** `SequenceRepository.save/get/list/delete_definition`, `create_run/get_run/list_runs`, `attach_child`, `set_node_status`, `set_run_status`, `owner_of_child`. Definition nodes have stable IDs; `(sequence_run_id,node_id)` is unique. Migrate control schema from 17 to 18 without rewriting existing rows.

- [ ] Write repository tests for save/reopen, duplicate IDs, ordering, frozen run snapshot and child association uniqueness.
- [ ] Run tests and confirm failure for missing implementation.
- [ ] Add validation, schema migration, repository and port.
- [ ] Run repository tests and `scripts/check_project.py`.

### Task 2: Sequence use cases, mapping and durable advancement

**Files:** Create `src/taskweave/application/sequences.py`, `src/taskweave/application/sequence_driver.py`; modify `src/taskweave/application/composition.py`, `src/taskweave/application/operations.py`, `src/taskweave/application/service.py`; test `tests/test_task_sequences.py`.

**Interfaces:** Operations `sequence.save/get/list/delete/start/run.get/run.list/run.inputs/run.retry/run.reconcile/run.delete/pause/continue/cancel`. Driver methods `advance(sequence_run_id)`, `recover()` and `close()` use existing run creation/start/wait and query APIs. A stable request ID identifies a sequence start; child `run_id` is stored before worker start. `Application.close()` stops/joins the driver before closing the coordinator; startup calls `runs.recover()` before `sequence.recover()`. Never hold the coordinator lock or a UoW while waiting on a worker.

- [ ] Write tests using real temporary Application for three-node order, non-adjacent and repeated task mapping, missing/type-invalid mapping, replayed start, failure and recovery. Inject failed child creation and assert there is no orphan `task_runs` row.
- [ ] Run tests and confirm missing behavior fails.
- [ ] Implement definition preflight, mapping resolution, frozen fingerprints, atomic child association and background progression.
- [ ] Verify child and sequence status after worker completion, restart and input waits.
- [ ] Run focused application tests and project checks.

### Task 3: Ownership and lifecycle protection

**Files:** Modify `src/taskweave/application/runs.py`, `src/taskweave/application/tasks.py`, `src/taskweave/application/environments.py`, `src/taskweave/infrastructure/repositories/runs.py`, `src/taskweave/infrastructure/repositories/results.py` as required; test `tests/test_task_sequences_lifecycle.py`.

**Interfaces:** Sequence-owned child runs cannot be independently restarted, deleted or cleared. Sequence operations provide inputs, retry, reconciliation and deletion via guarded internal paths. Definition-referenced tasks and history-referenced child runs/results require explicit sequence removal. Pause/cancel intent persists before changing the child. History deletion persists a cleanup intent and resumes across control DB, task DB and file boundaries.

- [ ] Write tests for independent-operation rejection, task/result deletion guards, pause/cancel at transition and UNKNOWN reconciliation.
- [ ] Run tests and confirm failure.
- [ ] Implement ownership checks in shared application operations and transaction-safe cleanup.
- [ ] Run lifecycle tests and existing execution control tests.

### Task 4: Desktop authoring and progress

**Files:** Create `src/taskweave/presentation/sequences.py`, `src/taskweave/desktop/pages/sequences.py`; modify `src/taskweave/desktop/workbench.py`, `src/taskweave/presentation/workspace.py`; tests `tests/ui/test_sequences_page.py` and any affected navigation tests.

**Interfaces:** A new navigation page lists and edits ordered nodes, combination input Schema and launch values, task-level and unbound step-level fields, constant/sequence/output input sources, starts a saved sequence and opens durable run progress and inputs/retry/reconciliation controls. Errors preserve the edit draft; leaving the page does not stop accepted work.

- [ ] Write interaction tests for task selection/reordering, mapping payload, one-click start, progress, blocked-node controls, retained draft after error and late responses.
- [ ] Run tests and confirm failure.
- [ ] Implement plain presentation state and NiceGUI page; wire navigation.
- [ ] Run focused UI tests and a real local browser path: create three nodes, save, start, leave page, return and inspect completed results.

### Task 5: Knowledge, compatibility and final verification

**Files:** Modify `docs/domain.md`, `docs/architecture.md`, `docs/maintenance.md`, `docs/modules/execution.md`, `docs/modules/storage.md`, `docs/contracts/operations.md`, `docs/testing.md` as affected, plus `tests/module-map.json`.

- [ ] Update only changed product facts, interfaces, migration and test mapping.
- [ ] Run focused repository, application, lifecycle, UI and real-worker tests with temporary workspace.
- [ ] Run `uv run python scripts/check_project.py` and `git diff --check`.
- [ ] Ask Astra to review the actual diff and any failed or unverified scenarios; apply required fixes and repeat relevant checks.
- [ ] Confirm CLI/desktop startup and a complete local three-task sequence; then commit and push reviewed files.
