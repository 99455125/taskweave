"""Durable interval scheduling, task operations and desktop API evidence."""

import asyncio
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import socket
import tempfile
import time
import unittest

from taskweave.application.service import Application
from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.launcher import select_local_port
from taskweave.infrastructure.storage import uid

SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class DesktopPortTests(unittest.TestCase):
    def test_selected_port_can_bind_exact_server_address(self):
        port = select_local_port()
        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))


class IntervalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.task = self.app.repo.create_task("Interval")["task_id"]

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def step(self, delay=0, name="Step", source=SOURCE):
        saved = self.app.repo.save_step(
            self.task,
            {
                "name": name,
                "step_content": source,
                "delay_after_previous_seconds": delay,
            },
        )
        run = self.app.trial_step(saved["step_id"], {}, uid())
        result = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(result["status"], "SUCCEEDED")
        saved = self.app.confirm_step(
            saved["step_id"], result["attempts"][0]["attempt_id"], saved["content_hash"]
        )
        return saved

    def wait_interval(self, run_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = self.app.repo.run_details(run_id)
            if run["waiting_step_id"]:
                return run
            time.sleep(0.02)
        self.fail("interval not entered")

    def test_interval_is_durable_and_no_attempt_created_until_due(self):
        first = self.step(30)
        second = self.step(1)
        run = self.app.create_run(self.task)
        self.app.coordinator.start(run["run_id"], uid())
        waiting = self.wait_interval(run["run_id"])
        self.assertEqual(waiting["waiting_step_id"], second["step_id"])
        self.assertEqual(
            len(waiting["attempts"]), 1
        )  # first step does not wait 30 seconds
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED")
        gap = (
            datetime.fromisoformat(done["attempts"][1]["started_at"])
            - datetime.fromisoformat(done["attempts"][0]["finished_at"])
        ).total_seconds()
        self.assertGreaterEqual(gap, 1)
        self.assertIsNone(done["wait_until"])
        self.assertEqual(
            json.loads(done["definition_json"])["steps"][0]["step_id"], first["step_id"]
        )

    def test_pause_wait_and_resume_after_deadline_no_full_wait_again(self):
        self.step()
        self.step(2)
        run = self.app.create_run(self.task)
        self.app.coordinator.start(run["run_id"], uid())
        self.wait_interval(run["run_id"])
        self.app.coordinator.control(run["run_id"], uid(), "pause")
        paused = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(paused["status"], "PAUSED")
        self.assertEqual(len(paused["attempts"]), 1)
        time.sleep(2.1)
        started = time.monotonic()
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED")
        self.assertLess(time.monotonic() - started, 1.8)

    def test_cancel_wait_does_not_execute_next(self):
        self.step()
        self.step(30)
        run = self.app.create_run(self.task)
        self.app.coordinator.start(run["run_id"], uid())
        self.wait_interval(run["run_id"])
        self.app.coordinator.control(run["run_id"], uid(), "cancel")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "CANCELLED")
        self.assertEqual(len(done["attempts"]), 1)

    def test_next_then_resume_waits_remaining_interval(self):
        self.step()
        self.step(1)
        run = self.app.create_run(self.task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "PAUSED")
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.wait_interval(run["run_id"])
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED"
        )

    def test_failed_previous_does_not_start_next(self):
        first = self.step(
            source='async def run(ctx, inputs):\n    assert inputs.get("pass", True), "business failure"\n    return ctx.result(data={})\n'
        )
        self.step(1)
        # Trial passes but formal binding deliberately fails.
        first = self.app.repo.save_step(
            self.task,
            {**first, "bindings": {"pass": {"literal": False}}},
            first["step_id"],
            first["content_hash"],
        )
        trial = self.app.trial_step(first["step_id"], {"pass": True}, uid())
        trial = self.app.coordinator.wait(trial["run_id"])
        self.app.confirm_step(
            first["step_id"], trial["attempts"][0]["attempt_id"], first["content_hash"]
        )
        run = self.app.create_run(self.task)
        self.app.coordinator.start(run["run_id"], uid())
        failed = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(len(failed["attempts"]), 1)
        self.assertIsNone(failed["wait_until"])

    def test_copy_remaps_dependencies_and_keeps_history_out(self):
        first = self.step()
        self.app.repo.save_step(
            self.task,
            {
                "step_content": SOURCE,
                "bindings": {
                    "x": {
                        "ref": {
                            "source": "step",
                            "step_id": first["step_id"],
                            "pointer": "",
                            "output": "data",
                        }
                    }
                },
                "delay_after_previous_seconds": 30,
            },
        )
        target = self.app.dispatch("task.copy", {"task_id": self.task})
        steps = self.app.repo.steps(target["task_id"])
        self.assertNotEqual(steps[0]["step_id"], first["step_id"])
        self.assertEqual(
            steps[1]["bindings"]["x"]["ref"]["step_id"], steps[0]["step_id"]
        )
        self.assertEqual(steps[1]["delay_after_previous_seconds"], 30)
        self.assertEqual(steps[0]["validation_state"], "DRAFT")
        self.assertFalse(self.app.repo.list_runs(target["task_id"]))
        ordered = self.app.dispatch(
            "task.reorder", {"task_ids": [target["task_id"], self.task]}
        )
        self.assertEqual(ordered[0]["task_id"], target["task_id"])

    def test_desktop_noop_save_keeps_validation_edit_requires_new_trial(self):
        step = self.step()
        controller = DesktopController(self.app)
        same = asyncio.run(controller.save_draft(self.task, step, step))
        self.assertEqual(same["validation_state"], "VALIDATED")
        changed = asyncio.run(
            controller.save_draft(
                self.task, {**step, "delay_after_previous_seconds": 30}, step
            )
        )
        self.assertEqual(changed["validation_state"], "DRAFT")
        old = self.app.repo.list_runs(self.task)[0]
        with self.assertRaises(TaskError):
            asyncio.run(controller.confirm(changed, old["run_id"]))
        self.assertEqual(
            json.loads(self.app.repo.run(old["run_id"])["definition_json"])["steps"][0][
                "delay_after_previous_seconds"
            ],
            0,
        )

    def test_v2_migration_backup_and_default_interval(self):
        self.app.close()
        path = Path(self.temp.name) / "taskweave.db"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("ALTER TABLE steps DROP COLUMN delay_after_previous_seconds")
            db.execute("ALTER TABLE steps DROP COLUMN validation_source")
            db.execute("ALTER TABLE steps DROP COLUMN ai_authoring_notes")
            db.execute("ALTER TABLE tasks DROP COLUMN sort_order")
            db.execute("ALTER TABLE task_runs DROP COLUMN definition_json")
            db.execute("ALTER TABLE task_runs DROP COLUMN waiting_step_id")
            db.execute("ALTER TABLE task_runs DROP COLUMN wait_until")
            db.execute("DROP TABLE step_contexts")
            db.execute("PRAGMA user_version=2")
        self.app = Application(self.temp.name)
        self.assertTrue(Path(str(path) + ".v2.bak").exists())
        self.assertEqual(self.app.repo.task(self.task)["name"], "Interval")
        self.assertEqual(
            self.app.repo.query("PRAGMA user_version")[0]["user_version"], 7
        )

    def test_restart_while_paused_keeps_original_deadline_and_success(self):
        self.step()
        self.step(2)
        run = self.app.create_run(self.task)
        self.app.coordinator.start(run["run_id"], uid())
        waiting = self.wait_interval(run["run_id"])
        self.app.coordinator.control(run["run_id"], uid(), "pause")
        self.app.coordinator.wait(run["run_id"])
        self.app.close()
        self.app = Application(self.temp.name)
        self.app.coordinator.start(run["run_id"], uid())
        resumed = self.wait_interval(run["run_id"])
        self.assertEqual(resumed["wait_until"], waiting["wait_until"])
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED")
        self.assertEqual(len(done["attempts"]), 2)

    def test_model_secret_is_persisted_and_restored_for_same_url(self):
        controller = DesktopController(self.app)
        asyncio.run(
            controller.save_model(
                "https://model.example/v1/chat/completions",
                "fixture",
                "",
                "test-session-secret",
            )
        )
        stored = Path(self.temp.name, "model.json").read_text()
        self.assertEqual(json.loads(stored)["api_key"], "test-session-secret")
        self.assertEqual(self.app.authoring.model.api_key, "test-session-secret")
        self.app.authoring.model = None
        asyncio.run(
            controller.save_model(
                "https://model.example/v1/chat/completions", "fixture", ""
            )
        )
        self.assertEqual(self.app.authoring.model.api_key, "test-session-secret")
        asyncio.run(
            controller.save_model(
                "https://another-model.example/v1/chat/completions", "fixture", ""
            )
        )
        self.assertIsNone(self.app.authoring.model.api_key)

    def test_restart_removes_dead_executor_lease_preserves_run(self):
        step = self.step()
        run = self.app.create_run(self.task)
        self.app.close()
        with closing(sqlite3.connect(Path(self.temp.name) / 'taskweave.db')) as db:
            with db:
                db.execute("INSERT INTO runtime_lease VALUES(1,?,?,?)", (run['run_id'],'dead-owner','2020-01-01'))
        self.app = Application(self.temp.name)
        self.assertFalse(self.app.repo.query('SELECT * FROM runtime_lease'))
        self.assertEqual(self.app.repo.run(run['run_id'])['status'],'READY')
        trial = self.app.trial_step(step['step_id'],{},uid())
        self.assertEqual(self.app.coordinator.wait(trial['run_id'])['status'],'SUCCEEDED')

    def test_interval_validation(self):
        for value in [-1, 0.5, True, "30", 86401]:
            with self.assertRaises(TaskError):
                normalize_step({"delay_after_previous_seconds": value})


if __name__ == "__main__":
    unittest.main()
