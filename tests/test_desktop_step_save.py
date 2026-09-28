"""Durable interval scheduling, task operations and desktop API evidence."""
import asyncio
import json
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController
from tests._runtime_fixture import RuntimeFixture

class DesktopStepSaveTests(RuntimeFixture):
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
