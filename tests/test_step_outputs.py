"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
from contextlib import closing
import sqlite3
from taskweave.application.demo import run_demo
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from tests._core_fixture import CoreFixture

class StepOutputsTests(CoreFixture):
    def test_five_steps_use_persisted_output_after_worker_replacement(self):
        result = run_demo(self.app)
        self.assertEqual(result["step_5_output"], {"received_order_id": "ORD-1001"})
        with closing(sqlite3.connect(result["task_db"])) as db:
            count = db.execute(
                "SELECT count(*) FROM step_outputs WHERE run_id=?", (result["run_id"],)
            ).fetchone()[0]
            self.assertEqual(count, 5)
        with closing(sqlite3.connect(result["control_db"])) as db:
            self.assertNotIn(
                "step_versions",
                [
                    x[0]
                    for x in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ],
            )

    def test_missing_reference_fails_before_worker(self):
        task = self.task()
        self.confirm(
            self.step(
                task, bindings={"x": {"ref": {"source": "task", "pointer": "/missing"}}}
            ),
            {"x": 1},
        )
        run = self.run_task(task)
        self.assertEqual(run["attempts"][0]["error_code"], "INPUT_MISSING")
        self.assertEqual(run["attempts"][0]["effect_state"], "NOT_STARTED")
        self.assertIsNone(self.app.coordinator.process)

    def test_named_plugin_result_can_feed_next_step(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": "stored"}])])\n'
        one = self.confirm(self.step(task, source, capabilities=["demo.table"]))
        two = self.confirm(
            self.step(
                task,
                bindings={
                    "value": {
                        "ref": {
                            "source": "step",
                            "step_id": one["step_id"],
                            "output": "items",
                            "pointer": "/0",
                        }
                    }
                },
            ),
            {"value": "stored"},
        )
        done = self.run_task(task)
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(
            self.app.repo.read_output(done["run_id"], two["step_id"]),
            {"value": "stored"},
        )

    def test_output_run_isolation_and_stale_definition(self):
        task = self.task()
        step = self.confirm(
            self.step(
                task, bindings={"v": {"ref": {"source": "task", "pointer": "/v"}}}
            ),
            {"v": "sample"},
        )
        first = self.run_task(task, inputs={"v": "first"})
        second = self.run_task(task, inputs={"v": "second"})
        self.assertEqual(
            self.app.repo.read_output(first["run_id"], step["step_id"]), {"v": "first"}
        )
        self.assertEqual(
            self.app.repo.read_output(second["run_id"], step["step_id"]),
            {"v": "second"},
        )
        pending = self.app.create_run(task, {"v": "later"})
        self.app.repo.save_step(
            task, {**step, "step_description": "changed"}, step["step_id"], step["content_hash"]
        )
        with self.assertRaisesRegex(TaskError, "RUN_CONFIG_CHANGED"):
            self.app.coordinator.start(pending["run_id"], uid())
