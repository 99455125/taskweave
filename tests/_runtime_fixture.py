"""Durable interval scheduling, task operations and desktop API evidence."""
import tempfile
import time
import unittest
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid

SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"

class RuntimeFixture(unittest.TestCase):
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
