# REQ-010 D Test Mapping Implementation Plan

> **For agentic workers:** execute inline as already directed; keep each step testable and record exact results.

**Goal:** Add accurate module based test selection and update requirement/docs mappings for REQ-010 D.

**Architecture:** A JSON manifest maps product source globs to explicit unittest targets, dependency edges, and optional browser targets. A small CLI validates complete product source coverage, selects modules via reverse dependency closure, deduplicates targets, and invokes only explicitly listed tests.

**Tech Stack:** Python 3.10+, stdlib argparse/json/unittest/pathlib/fnmatch, uv; no new dependencies.

**Spec:** `docs/requirements/REQ-010-ddd-modularization/design.md` §6 and `docs/requirements/REQ-010-ddd-modularization/plan.md` §D.

## Global Constraints

- Preserve all existing workspace edits and data; do not reset, clean, stash, or overwrite unrelated files.
- Do not run full test discovery or A/B large test groups.
- Default selection excludes browser targets; browser tests run only with `--include-browser`.
- Unknown `src/taskweave` or `plugins` product paths fail with nonzero status and actionable unmapped-path output.
- All module targets are explicit unittest module/class/method names; never default to the `tests` root.

## Review Focus

1. `ui.tasks` source selection must not pull unrelated `ui.settings`; test exact independence.
2. Shared contract changes must select all direct and transitive dependents; test reverse closure and step-port consumers.
3. Unmapped source paths must fail instead of silently selecting zero tests; test unknown application and plugin paths.
4. Duplicate targets reached through multiple selected modules must run once; test stable deduplication.
5. Browser targets must be omitted by default and included only with `--include-browser`; test both dry-run selections without launching a browser.

## Tasks

### Task 1: Pure selection contract

Files: create `tests/module-map.json`, `tests/test_module_selection.py`; create `scripts/test_modules.py` after observing test failures.

- Define documented module keys, explicit source globs, explicit fast targets, `depends_on`, and `browser_targets`.
- Test list/lookup, direct source selection, reverse dependency closure, plugin path selection, UI task/settings separation, unknown source error, and stable target deduplication.
- Test default dry-run excludes browser targets; browser flag adds the selected modules' browser targets.

### Task 2: CLI behavior

- Implement `--list`, `--module`, `--changed PATH...`, `--dry-run`, and `--include-browser`.
- Validate manifest schema, graph references/cycles, source coverage, and target syntax before running.
- Print selected modules/reasons/unique targets. Dry-run never executes. Invalid empty or unknown input exits nonzero.
- Execute exact unittest targets only, using module/class/method names from JSON.

### Task 3: Coverage and documentation

Files: update `tests/module-map.json`, `tests/README.md`, `docs/testing.md`, `scripts/README.md`, `docs/requirements/REQ-010-ddd-modularization/{README.md,code-mapping.md,progress.md,validation.md}`, and the affected REQ mapping files.

- Map every `src/taskweave/**/*.py` and `plugins/*/src/**/*.py` product file; CI-style selector test asserts no unmapped files.
- Document actual invocation examples and current limitations; update status to say C-R1..R5 closed and D implementation/review status accurately, without marking REQ-010 complete.
- Run module selector tests, `scripts/check_project.py`, then only mapped D-affected quick targets. Deliver frozen snapshot to the designated supervisor and repair any findings.
