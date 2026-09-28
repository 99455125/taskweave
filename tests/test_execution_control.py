"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
import threading
import time
from unittest.mock import patch
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from tests._core_fixture import CoreFixture

class ExecutionControlTests(CoreFixture):
    def test_pause_restart_continue_and_edit_lock(self):
        task = self.task()
        one = self.confirm(self.step(task, bindings={"v": {"literal": 42}}), {"v": 42})
        two = self.confirm(
            self.step(
                task,
                bindings={
                    "v": {
                        "ref": {
                            "source": "step",
                            "step_id": one["step_id"],
                            "pointer": "/v",
                        }
                    }
                },
            ),
            {"v": 42},
        )
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "PAUSED")
        with self.assertRaisesRegex(TaskError, "End the active"):
            self.app.repo.save_step(task, one, one["step_id"], one["content_hash"])
        self.app.close()
        self.app = Application(self.home, registry_factory="taskweave.plugins.demo:build_registry")
        self.app.coordinator.start(run["run_id"], uid())
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED"
        )
        self.assertEqual(
            self.app.repo.read_output(run["run_id"], two["step_id"]), {"v": 42}
        )

    def test_failure_stops_then_explicit_retry_records_attempt(self):
        task = self.task()
        one = self.confirm(self.step(task))
        source = 'async def run(ctx, inputs):\n    assert inputs["good"], "business assertion failed"\n    return ctx.result(data={"ok": True})\n'
        two = self.confirm(
            self.step(
                task,
                source,
                bindings={"good": {"ref": {"source": "task", "pointer": "/good"}}},
            ),
            {"good": True},
        )
        self.confirm(self.step(task))
        run = self.run_task(task, inputs={"good": False})
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(
            [x["step_id"] for x in run["attempts"]], [one["step_id"], two["step_id"]]
        )
        self.app.coordinator.start(run["run_id"], uid(), retry_step_id=two["step_id"])
        again = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(len(again["attempts"]), 3)
        self.assertEqual(
            [
                a["attempt_no"]
                for a in again["attempts"]
                if a["step_id"] == two["step_id"]
            ],
            [1, 2],
        )

    def test_repeated_command_and_trial_are_idempotent(self):
        task = self.task()
        step = self.step(task)
        cmd = uid()
        a = self.app.trial_step(step["step_id"], {}, cmd)
        self.app.coordinator.wait(a["run_id"])
        b = self.app.trial_step(step["step_id"], {}, cmd)
        self.assertEqual(a, b)
        with self.assertRaises(TaskError):
            self.app.trial_step(step["step_id"], {"x": 1}, cmd)
        self.app.confirm_step(
            step["step_id"],
            self.app.repo.run_details(a["run_id"])["attempts"][0]["attempt_id"],
            step["content_hash"],
        )
        run = self.app.create_run(task)
        command = uid()
        responses = []

        def start():
            responses.append(self.app.coordinator.start(run["run_id"], command))

        threads = [threading.Thread(target=start) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(len(done["attempts"]), 1)
        self.assertEqual(len(responses), 4)
        self.assertTrue(all(r == responses[0] for r in responses))
        with self.assertRaises(TaskError):
            self.app.coordinator.start(run["run_id"], command, mode="NEXT")

    def test_single_desktop_instance_and_parallel_formal_runs(self):
        with self.assertRaises(TaskError):
            Application(self.home)
        task = self.task()
        self.confirm(self.step(task))
        self.confirm(self.step(task))
        r1 = self.app.create_run(task)
        r2 = self.app.create_run(task)
        self.app.coordinator.start(r1["run_id"], uid(), mode="NEXT")
        self.app.coordinator.wait(r1["run_id"])
        self.app.coordinator.start(r2["run_id"], uid())
        self.assertEqual(self.app.coordinator.wait(r2["run_id"])["status"], "SUCCEEDED")
        self.assertEqual(self.app.coordinator.describe_run(r1["run_id"])["status"], "PAUSED")
        formal = {item['run_id'] for item in self.app.coordinator.active_instances() if item['instance_type'] == 'execution'}
        self.assertEqual(formal, {r1['run_id'], r2['run_id']})
        self.app.coordinator.control(r1["run_id"], uid(), "abandon")
        self.app.coordinator.control(r2["run_id"], uid(), "abandon")

    def test_executor_concurrency_limit_rejects_excess_run(self):
        task = self.task()
        step = self.step(
            task,
            'async def run(ctx, inputs):\n    await ctx.call("demo.wait", {"seconds": 1})\n    return ctx.result()',
            capabilities=['demo.wait'],
        )
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        self.app.coordinator.set_max_concurrency(1)
        first = self.app.create_run(task)
        second = self.app.create_run(task)
        self.app.coordinator.start(first['run_id'], uid())
        with self.assertRaises(TaskError) as raised:
            self.app.coordinator.start(second['run_id'], uid())
        self.assertEqual(raised.exception.code, 'EXECUTOR_CAPACITY')
        self.assertEqual(self.app.coordinator.wait(first['run_id'])['status'], 'SUCCEEDED')

    def test_worker_kill_unknown_requires_reconciliation(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    await ctx.call("demo.wait", inputs)\n    return ctx.result()\n'
        self.confirm(
            self.step(
                task,
                source,
                capabilities=["demo.wait"],
                bindings={
                    "seconds": {"ref": {"source": "task", "pointer": "/seconds"}}
                },
            ),
            {"seconds": 0},
        )
        run = self.app.create_run(task, {"seconds": 10})
        self.app.coordinator.start(run["run_id"], uid())
        deadline = time.monotonic() + 5
        while not self.app.coordinator.process and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)
        self.app.coordinator.process.terminate()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED", done)
        self.assertEqual(done["attempts"][0]["status"], "UNKNOWN")
        with self.assertRaisesRegex(TaskError, "RECONCILIATION_REQUIRED"):
            self.app.coordinator.start(run["run_id"], uid())
        self.app.coordinator.reconcile(
            done["attempts"][0]["attempt_id"],
            "not_completed",
            {},
            uid(),
        )
        self.app.coordinator.control(run["run_id"], uid(), "abandon")

    def test_pause_cancel_and_timeout(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    await ctx.call("demo.wait", {"seconds": inputs["seconds"]})\n    return ctx.result()\n'
        self.confirm(
            self.step(
                task,
                source,
                capabilities=["demo.wait"],
                bindings={"seconds": {"literal": 1}},
            ),
            {"seconds": 0},
        )
        self.confirm(self.step(task))
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        self.app.coordinator.control(run["run_id"], uid(), "pause")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "PAUSED")
        self.assertEqual(len(done["attempts"]), 1)
        self.app.coordinator.control(run["run_id"], uid(), "abandon")
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        time.sleep(0.2)
        self.app.coordinator.control(run["run_id"], uid(), "cancel")
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "CANCELLED"
        )
        task2 = self.task()
        stuck = self.step(
            task2,
            "async def run(ctx, inputs):\n    while True:\n        pass\n",
            timeout_ms=200,
        )
        trial = self.app.trial_step(stuck["step_id"], {}, uid())
        done = self.app.coordinator.wait(trial["run_id"], 5)
        self.assertEqual(done["status"], "INTERRUPTED")
        self.assertEqual(done["attempts"][0]["error_code"], "WORKER_TIMEOUT")

    def test_upstream_rerun_invalidates_downstream(self):
        task = self.task()
        one = self.confirm(self.step(task, bindings={"v": {"literal": 1}}), {"v": 1})
        two = self.confirm(
            self.step(
                task,
                bindings={
                    "v": {
                        "ref": {
                            "source": "step",
                            "step_id": one["step_id"],
                            "pointer": "/v",
                        }
                    }
                },
            ),
            {"v": 1},
        )
        self.confirm(self.step(task))
        run = self.app.create_run(task)
        self.app.coordinator.start(
            run["run_id"], uid(), mode="UNTIL", target_step_id=two["step_id"]
        )
        self.app.coordinator.wait(run["run_id"])
        self.app.coordinator.start(
            run["run_id"], uid(), mode="NEXT", retry_step_id=one["step_id"]
        )
        done = self.app.coordinator.wait(run["run_id"])
        with self.assertRaises(TaskError):
            self.app.repo.read_output(run["run_id"], two["step_id"])
        self.assertEqual(len(done["attempts"]), 3)
        self.assertEqual(sum(a["valid"] for a in done["attempts"]), 1)

    def test_recovery_after_result_commit_before_control_ack(self):
        task = self.task()
        self.confirm(self.step(task))
        run = self.app.create_run(task)

        def lost_ack(*args):
            raise RuntimeError("Simulated coordinator ACK failure")

        with patch.object(self.app.repo.repositories.runs, "finish_attempt", side_effect=lost_ack):
            self.app.coordinator.start(run["run_id"], uid())
            done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED")
        # The application retains RUNNING when a receipt exists but ACK cannot commit.
        self.assertEqual(done["attempts"][0]["status"], "RUNNING")
        self.app.close()
        self.app = Application(self.home, registry_factory="taskweave.plugins.demo:build_registry")
        self.assertEqual(
            self.app.repo.run_details(run["run_id"])["attempts"][0]["status"],
            "SUCCEEDED",
        )
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED")
        self.assertEqual(len(done["attempts"]), 1)
