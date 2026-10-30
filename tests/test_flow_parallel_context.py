"""Retained parallel resource ownership through public context APIs."""
from tests import test_flow_parallel as parallel
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid


class ParallelContextTests(parallel.ParallelFixture):
    def setUp(self):
        super().setUp()
        self.app.close()
        self.app = Application(self.home, registry_factory="tests.test_context_recording_runtime:build_registry")

    def paused_group(self):
        task = self.task()
        a, a2, b, b2 = [self.confirmed_step(task, capabilities=["demo.echo"]) for _ in range(4)]
        self.install_group(task, [("a", [a, a2]), ("b", [b, b2])])
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "PAUSED")
        return task, done, a, b

    def test_sessions_read_and_targets_route_to_independent_retained_workers(self):
        task, run, a, b = self.paused_group()
        sessions = self.app.dispatch("run.context.sessions", {"task_id": task})
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len({s["session_id"] for s in sessions}), 2)
        by_owner = {s["resource_path"]: s for s in sessions}
        for name, step in (("a", a), ("b", b)):
            session = by_owner["/root/choose/" + name]
            path = next(item["execution_path"] for item in session["execution_paths"] if item["step_id"] == step["step_id"])
            params = {"run_id": run["run_id"], "step_id": step["step_id"], "provider_id": "demo.page"}
            result = self.app.dispatch("context.read", {**params, "request": {"role": name}})
            self.assertEqual(result["items"][0]["content"], name)
            targets = self.app.dispatch("context.targets", {**params, "execution_path": path})
            self.assertEqual(targets["session_id"], session["session_id"])
            self.assertEqual([t["target_id"] for t in targets["targets"]], [name])
            with self.assertRaises(TaskError) as stale:
                self.app.dispatch("context.read", {**params, "execution_path": path, "expected_session_id": "stale"})
            self.assertEqual(stale.exception.code, "CONTEXT_SESSION_CHANGED")

    def test_branch_recording_lifecycle_protects_parent_run(self):
        task, run, a, _ = self.paused_group()
        params = {"run_id": run["run_id"], "step_id": a["step_id"], "provider_id": "demo.page"}
        started = self.app.dispatch("context.record", {**params, "operation": "start"})
        options = {**params, "recording_id": started["recording_id"], "expected_session_id": started["session_id"]}
        read = self.app.dispatch("context.record", {**options, "operation": "read"})
        self.assertEqual(read["recording_id"], started["recording_id"])
        for operation in (lambda: self.app.coordinator.start(run["run_id"], uid()),
                          lambda: self.app.coordinator.control(run["run_id"], uid(), "abandon"),
                          lambda: self.app.coordinator.delete_run(run["run_id"]),
                          lambda: self.app.coordinator.clear_task_runs(task)):
            with self.assertRaises(TaskError) as pending:
                operation()
            self.assertEqual(pending.exception.code, "CONTEXT_RECORDING_PENDING")
        self.app.dispatch("context.record", {**options, "operation": "stop"})
        self.app.dispatch("context.record", {**options, "operation": "ack", "through": read["cursor"]})
        self.app.coordinator.start(run["run_id"], uid())
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED")

    def test_loop_occurrences_require_current_path_and_reject_stale_session(self):
        task = self.task()
        tick, after = [self.confirmed_step(task, capabilities=["demo.echo"]) for _ in range(2)]
        node = parallel.group(True)
        node["cases"] = node["cases"][:1]
        node["cases"][0]["body"]["children"] = [
            {"id": "each", "kind": "foreach", "items": parallel.literal([1, 2]),
             "body": parallel.sequence(parallel.action(tick["step_id"]), node_id="each_body")},
            parallel.action(after["step_id"])]
        node["default"]["body"]["children"] = []
        self.save_flow(task, parallel.sequence(node))
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        paused = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(paused["status"], "PAUSED")
        old_path = paused["attempts"][0]["execution_path"]
        session = self.app.dispatch("run.context.sessions", {"task_id": task})[0]
        path = next(p["execution_path"] for p in session["execution_paths"] if p["step_id"] == tick["step_id"])
        self.assertNotEqual(old_path, path)
        params = {"run_id": run["run_id"], "step_id": tick["step_id"], "provider_id": "demo.page"}
        for operation in ("context.read", "context.targets"):
            with self.assertRaises(TaskError) as ambiguous:
                self.app.dispatch(operation, params)
            self.assertEqual(ambiguous.exception.code, "FLOW_INSTANCE_REQUIRED")
            with self.assertRaises(TaskError) as stale:
                self.app.dispatch(operation, {**params, "execution_path": old_path, "expected_session_id": session["session_id"]})
            self.assertEqual(stale.exception.code, "CONTEXT_SESSION_CHANGED")
            current = self.app.dispatch(operation, {**params, "execution_path": path, "expected_session_id": session["session_id"]})
            self.assertEqual(current["execution_path"], path)
            with self.assertRaises(TaskError) as stale_session:
                self.app.dispatch(operation, {**params, "expected_session_id": "obsolete"})
            self.assertEqual(stale_session.exception.code, "CONTEXT_SESSION_CHANGED")

    def test_target_request_rejects_expired_session_after_application_restart(self):
        task, run, a, _ = self.paused_group()
        session = next(s for s in self.app.dispatch("run.context.sessions", {"task_id": task})
                       if s["resource_path"] == "/root/choose/a")
        path = next(p["execution_path"] for p in session["execution_paths"] if p["step_id"] == a["step_id"])
        self.app.close()
        self.app = Application(self.home, registry_factory="tests.test_context_recording_runtime:build_registry")
        with self.assertRaises(TaskError) as stale:
            self.app.dispatch("context.targets", {"run_id": run["run_id"], "step_id": a["step_id"],
                "provider_id": "demo.page", "expected_session_id": session["session_id"], "execution_path": path})
        self.assertEqual(stale.exception.code, "CONTEXT_SESSION_CHANGED")
