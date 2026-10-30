"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
from contextlib import closing
import asyncio
from pathlib import Path
import sqlite3
from taskweave.core.ports import Scope, StepResult, ResultRequest
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid, Results
from taskweave.infrastructure.sqlite_storage import initialize
from tests._core_fixture import CoreFixture

class StorageIntegrityTests(CoreFixture):
    def test_state_only_run_does_not_write_business_results(self):
        task = self.task()
        self.confirm(self.step(task, "async def run(ctx, inputs):\n    return ctx.result()\n"))
        self.assertEqual(self.run_task(task)["status"], "SUCCEEDED")
        # The coordinator prepares the shared database before workers start.
        with closing(sqlite3.connect(self.app.repo.task_path(task))) as db:
            self.assertEqual(db.execute("SELECT * FROM step_outputs").fetchall(), [])
            self.assertEqual(db.execute("SELECT * FROM result_receipts").fetchall(), [])

    def test_empty_result_persistence_does_not_initialize_database(self):
        task = self.task()
        results = Results(self.home, Scope(task, uid(), uid(), uid()), self.app.registry)
        self.assertEqual(results.persist(StepResult()), [])
        self.assertFalse(results.path.exists())

    def test_custom_table_isolation_parsing_cleanup(self):
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": inputs["v"]}])])\n'
        tasks = []
        for v in ("first", "second"):
            task = self.task()
            tasks.append(task)
            self.confirm(
                self.step(
                    task,
                    source,
                    bindings={"v": {"literal": v}},
                    capabilities=["demo.table"],
                ),
                {"v": v},
            )
            run = self.run_task(task)
            ref = run["results"][0]
            self.assertEqual(
                self.app.repo.read_result(ref["result_id"], self.app.registry)["data"],
                [v],
            )
            self.app.repo.delete_result(ref["result_id"])
            with self.assertRaises(TaskError):
                self.app.repo.read_result(ref["result_id"], self.app.registry)
        self.app.repo.delete_task(tasks[0])
        self.assertFalse(self.app.repo.task_path(tasks[0]).exists())
        self.assertTrue(self.app.repo.task_path(tasks[1]).exists())

    def test_existing_unknown_schema_is_preserved(self):
        path = self.home / "unknown.db"
        with closing(sqlite3.connect(path)) as db:
            db.executescript('CREATE TABLE original(value TEXT); INSERT INTO original VALUES("kept");')
        before = path.read_bytes()
        with self.assertRaises(TaskError) as error:
            initialize(path, "task-data")
        self.assertEqual(error.exception.code, "SCHEMA_MAINTENANCE_REQUIRED")
        self.assertEqual(path.read_bytes(), before)

    def test_result_save_failure_does_not_retry_business(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": inputs["v"]}])])\n'
        self.confirm(
            self.step(
                task,
                source,
                bindings={"v": {"ref": {"source": "task", "pointer": "/v"}}},
                capabilities=["demo.table"],
            ),
            {"v": "valid"},
        )
        # JSON object cannot be bound as a SQLite TEXT scalar: persistence fails after execution.
        done = self.run_task(task, inputs={"v": {"invalid": "row value"}})
        self.assertEqual(done["status"], "FAILED")
        self.assertEqual(done["attempts"][0]["error_code"], "RESULT_SAVE_FAILED")
        self.assertEqual(done["attempts"][0]["effect_state"], "SUCCEEDED")
        with self.assertRaisesRegex(TaskError, "RECONCILIATION_REQUIRED"):
            self.app.coordinator.start(
                done["run_id"], uid(), retry_step_id=done["attempts"][0]["step_id"]
            )

    def test_file_storage_and_invalid_staged_token(self):
        from taskweave.core.ports import PreparedResult

        class FileHandler:
            def prepare(self, request):
                return PreparedResult(
                    "file", staged_token=request.payload, media_type="text/plain"
                )

        self.app.registry.handlers["file.text"] = FileHandler()
        task = self.task()
        scope = Scope(task, uid(), uid(), uid())
        result_store = Results(self.home, scope, self.app.registry)
        staged = asyncio.run(result_store.allocate_file("report"))
        Path(staged.local_path).write_text("business output")
        refs = result_store.persist(
            StepResult(outputs=[ResultRequest("file.text", "report", staged.token)])
        )
        self.assertEqual(
            (result_store.root / refs[0]["locator"]).read_text(), "business output"
        )
        self.assertEqual(len(refs[0]["checksum"]), 64)
        second = Results(self.home, Scope(task, uid(), uid(), uid()), self.app.registry)
        with self.assertRaises(TaskError):
            second.persist(
                StepResult(outputs=[ResultRequest("file.text", "bad", staged.token)])
            )
