"""A completed worker action is not sent again after cursor commit fails."""

from unittest.mock import patch

from taskweave.infrastructure.storage import uid
from tests._core_fixture import CoreFixture
from tests.test_flow_execution import sequence, action


class FlowRecoveryTests(CoreFixture):
    def confirmed_step(self, task):
        step = self.step(task)
        self.app.confirm_step_manual(step["step_id"], step["content_hash"])
        return step

    def save_flow(self, task, root):
        self.app.repo.tasks.save_flow(task, {"version": 2, "root": root}, self.app.repo.tasks.definition_hash(task))
        self.app.repo.tasks.confirm_flow(task, self.app.repo.tasks.definition_hash(task))

    def test_success_before_cursor_commit_advances_without_reexecution(self):
        task = self.task()
        first = self.confirmed_step(task)
        second = self.confirmed_step(task)
        self.save_flow(task, sequence({
            "id": "repeat", "kind": "foreach", "items": {"literal": [0, 1]},
            "body": sequence(action(first), node_id="body"),
        }, action(second)))
        run = self.app.create_run(task)
        store = self.app.runs.flow_runs
        original = store.commit_transition
        injected = False

        def fail_once(run_id, previous, transition):
            nonlocal injected
            if (not injected and any(item["kind"] == "action" and item["status"] == "SUCCEEDED"
                                     for item in transition["instances"])):
                injected = True
                raise RuntimeError("simulated cursor commit crash")
            return original(run_id, previous, transition)

        with patch.object(store, "commit_transition", side_effect=fail_once):
            self.app.coordinator.start(run["run_id"], uid())
            interrupted = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(interrupted["status"], "INTERRUPTED")
        self.assertEqual(len(interrupted["attempts"]), 1)
        self.assertEqual(interrupted["attempts"][0]["status"], "SUCCEEDED")

        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(len([a for a in done["attempts"] if a["step_id"] == first["step_id"]]), 2)
        self.assertEqual(len(done["attempts"]), 3)
