"""Durable control-flow instance identities in the real control database."""

from pathlib import Path
import tempfile
import unittest

from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.sqlite_storage import uid, now
from tests._core_fixture import CoreFixture


SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class FlowStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.repo = Repository(self.home)
        self.task_id = self.repo.create_task("iterate")["task_id"]
        self.step = self.repo.save_step(self.task_id, {"step_content": SOURCE})
        self.repo.confirm_manual(self.step["step_id"], self.step["content_hash"])
        self.run_id = self.repo.create_run(self.task_id, {}, {})["run_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_attempt_numbers_are_scoped_to_execution_path(self):
        runs = self.repo.repositories.runs
        first, second, retry = uid(), uid(), uid()
        paths = ["/root/each/0/step", "/root/each/1/step"]
        runs.create_attempt(first, self.task_id, self.run_id, self.step["step_id"], self.step["content_hash"], now(), execution_path=paths[0])
        runs.create_attempt(second, self.task_id, self.run_id, self.step["step_id"], self.step["content_hash"], now(), execution_path=paths[1])
        runs.create_attempt(retry, self.task_id, self.run_id, self.step["step_id"], self.step["content_hash"], now(), execution_path=paths[1])
        self.assertEqual([runs.attempt(a)["attempt_no"] for a in (first, second, retry)], [1, 1, 2])
        self.assertEqual(runs.latest_attempt_for_instance(self.run_id, paths[0])["attempt_id"], first)
        self.assertEqual(runs.latest_attempt_for_instance(self.run_id, paths[1])["attempt_id"], retry)

    def test_transition_records_frozen_list_once_and_persists_cursor(self):
        flows = self.repo.repositories.flow_runs
        start = {"frames": [{"node_id": "each", "index": 0}]}
        transition = {"cursor": start, "instances": [{
            "execution_path": "/root/each", "node_id": "each", "kind": "foreach",
            "status": "RUNNING", "payload": {"items": [1, 1, 2], "index": 0},
        }]}
        self.assertTrue(flows.commit_transition(self.run_id, None, transition))
        self.assertFalse(flows.commit_transition(self.run_id, None, transition))
        reopened = Repository(self.home)
        self.assertEqual(reopened.repositories.flow_runs.cursor(self.run_id), start)
        self.assertEqual(reopened.repositories.flow_runs.instance(self.run_id, "/root/each")["payload"],
                         {"items": [1, 1, 2], "index": 0})
        self.assertEqual(len(reopened.repositories.flow_runs.instances(self.run_id)), 1)

    def test_retry_third_iteration_preserves_earlier_successes(self):
        runs = self.repo.repositories.runs
        flows = self.repo.repositories.flow_runs
        paths = [f"/root/each/{index}/step" for index in range(3)]
        attempt_ids = []
        for index, path in enumerate(paths):
            attempt_id = uid()
            attempt_ids.append(attempt_id)
            runs.create_attempt(attempt_id, self.task_id, self.run_id, self.step["step_id"], self.step["content_hash"], now(), execution_path=path)
            self.repo.execute("UPDATE step_attempts SET status=? WHERE attempt_id=?", ("FAILED" if index == 2 else "SUCCEEDED", attempt_id))
        flows.retry_instance(self.run_id, paths[2])
        self.assertEqual([runs.attempt(a)["valid"] for a in attempt_ids], [1, 1, 0])
        self.assertIsNone(runs.latest_attempt_for_instance(self.run_id, paths[2]))


class AttemptOutputTests(CoreFixture):
    def test_result_repository_reads_exact_successful_attempt(self):
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    return ctx.result(data={"value": 7})\n')
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        run = self.run_task(task)
        attempt_id = run['attempts'][0]['attempt_id']
        self.assertEqual(self.app.repo.repositories.results.read_attempt_output(attempt_id), {'value': 7})

    def test_exact_attempt_reader_supports_named_json_output(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": 9}])])\n'
        step = self.step(task, source=source, capabilities=['demo.table'])
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        run = self.run_task(task)
        attempt_id = run['attempts'][0]['attempt_id']
        results = self.app.repo.repositories.results
        self.assertEqual(results.read_attempt_output(attempt_id, 'items', self.app.registry),
                         results.read_output(run['run_id'], step['step_id'], 'items', self.app.registry))


if __name__ == "__main__":
    unittest.main()
