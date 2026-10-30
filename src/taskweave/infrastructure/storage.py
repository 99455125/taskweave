"""Compatibility Store facade and worker-side result persistence.

New repository compositions use SQLiteStorage from sqlite_storage directly.
The Store methods and shared connection helpers remain available here.
"""

import json
import os
from pathlib import Path
import re
import shutil

from taskweave.core.validation import TaskError, dumps, valid_id
from taskweave.infrastructure.sqlite_storage import (
    SQLiteStorage, SQLiteUnitOfWork,
    connect, initialize, default_home, workspace_location_file, uid, now,
)


class Store(SQLiteStorage):
    """Retain legacy domain accessors by delegating to their owning repositories."""

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
        from taskweave.infrastructure.datasets import Datasets
        self.datasets = Datasets(home, scope)

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

        return self.persist(requests if isinstance(requests, StepResult) else StepResult(outputs=requests), diagnostic=True)

    def persist(self, result, diagnostic=False):
        if result.data is None and not result.outputs and not result.views and (diagnostic or not self.datasets.pending):
            return []
        initialize(self.path, "task-data")
        refs = []
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
            validate_views(result.data, result.views, self.registry.views, result.outputs)
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
            for view in result.views:
                if 'output' in view:
                    source = next(ref for ref in refs if ref.get('name') == view['output'])
                    if source['kind'] != 'file' or not source['media_type'].startswith('image/'):
                        raise TaskError('RESULT_VIEW_INVALID', '图片展示引用必须是本次保存的图片文件')
            if not diagnostic:
                refs.extend(self.datasets.persist(db, self))
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

    def _json(self, db, name, value):
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise TaskError("NOT_JSON", "Result must contain JSON values") from exc
        db.execute(
            "INSERT INTO step_outputs VALUES(?,?,?,?,?,?)",
            (
                self.scope.run_id,
                self.scope.step_id,
                self.scope.attempt_id,
                name,
                encoded,
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
        if actual != expected:
            raise TaskError(
                "TABLE_SCHEMA_MISMATCH",
                "Custom table schema differs; explicit data maintenance required",
            )
        db.execute(
            "INSERT OR IGNORE INTO plugin_table_schemas(table_name) VALUES(?)", (table,)
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
