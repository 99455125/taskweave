# Planning Drafts and Plan Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Generate importable planning drafts despite local evidence gaps, carry referenced contexts into steps, and copy plans with their captured contexts.

**Architecture:** Keep the portable task package unchanged. The planning-only response accepts optional `plan_context_refs`, stores a frozen raw context snapshot with the generation, and strips refs before normal package validation. Copy operates on plan and context rows without copying live sessions or generation records.

**Tech Stack:** Python, SQLite, NiceGUI, unittest.

**Spec:** `docs/superpowers/specs/2026-09-24-planning-drafts-and-copy-design.md`

## Global Constraints

- AI-generated steps remain `DRAFT`; empty code cannot be validated, confirmed or executed.
- Full test suite requires user approval; run targeted tests only.
- No fabricated selectors, placeholder success, copied live sessions or generated history.

## Review Focus

- A changed/deleted plan context after generation must not change what imports.
- Invalid or foreign context refs must fail with a clear error.
- Nonempty generated code must keep strict validation.
- Copy must preserve order and content while assigning fresh IDs.
- Import failure must not leave a partial task.

---

### Task 1: Draft package validation

**Files:** `src/taskweave/application/task_transfer.py`, `src/taskweave/application/service.py`, `tests/test_planning.py`

- [x] Write failing tests for empty AI DRAFT code, invalid nonempty code, and manual confirmation rejection.
- [x] Run targeted tests and observe the failure.
- [x] Allow only AI DRAFT empty code to bypass code parsing; keep schema/binding/plugin checks.
- [x] Guard all confirmation paths against empty code; run targeted tests.

### Task 2: Planning candidate and context transfer

**Files:** `src/taskweave/application/planning.py`, `src/taskweave/infrastructure/plan_repository.py`, `src/taskweave/infrastructure/repository.py`, `src/taskweave/infrastructure/storage.py`, `src/taskweave/desktop/contexts.py`, `tests/test_planning.py`

- [x] Write failing tests for frozen context refs, invalid refs, step context copy, and failed import rollback.
- [x] Run targeted tests and observe the failure.
- [x] Add generation-only response extension and frozen context snapshot, preserving AI redaction setting.
- [x] Validate/strip refs and atomically import step contexts with provenance.
- [x] Run targeted tests.

### Task 3: Plan copy

**Files:** `src/taskweave/infrastructure/plan_repository.py`, `src/taskweave/application/planning.py`, `src/taskweave/application/service.py`, `src/taskweave/desktop/planning.py`, `tests/test_planning.py`

- [x] Write failing tests for field/context copy, fresh IDs, independent updates, absent generations/sessions.
- [x] Run targeted tests and observe the failure.
- [x] Implement transactional copy API and list action; run targeted tests.

### Task 4: Prompt and preview

**Files:** `src/taskweave/application/prompts.py`, `src/taskweave/desktop/planning.py`, `tests/test_planning.py`, relevant planning docs.

- [x] Write failing assertions for local gaps, empty code, context refs, and preview status.
- [x] Run targeted tests and observe the failure.
- [x] Update planning-only prompt and preview; run targeted tests.
- [x] Run project check and `git diff --check`; report test scope and limits.
