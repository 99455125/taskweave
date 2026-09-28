"""Durable interval scheduling, task operations and desktop API evidence."""
from datetime import datetime
import json
import time
from taskweave.application.service import Application
from taskweave.core.validation import TaskError, normalize_step
from taskweave.infrastructure.storage import uid
from tests._runtime_fixture import RuntimeFixture

class IntervalSchedulerTests(RuntimeFixture):
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

    def test_interval_validation(self):
        for value in [-1, 0.5, True, "30", 86401]:
            with self.assertRaises(TaskError):
                normalize_step({"delay_after_previous_seconds": value})
