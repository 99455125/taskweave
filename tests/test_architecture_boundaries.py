"""Enforce the application and runtime persistence boundaries from REQ-010."""
import ast
import inspect
import unittest
from pathlib import Path

from taskweave.application.service import Application
from taskweave.infrastructure.context_sessions import ContextSessions
from scripts.check_project import (
    application_boundary_violations,
    controller_boundary_violations,
    dialog_prop_violations,
    runtime_boundary_violations,
)


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_coordinator_and_pool_do_not_issue_persistence_sql(self):
        tree = ast.parse((ROOT / "src/taskweave/infrastructure/runtime.py").read_text(encoding="utf-8"))
        self.assertEqual(runtime_boundary_violations(tree), [])

    def test_desktop_controller_uses_application_queries_not_repository_facade(self):
        tree = ast.parse((ROOT / "src/taskweave/desktop/controller.py").read_text(encoding="utf-8"))
        self.assertEqual(controller_boundary_violations(tree), [])

    def test_application_has_no_embedded_sql_execution(self):
        root = ROOT / "src/taskweave/application"
        offenders = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders.extend(application_boundary_violations(tree))
        self.assertEqual(offenders, [])

    def test_boundary_guards_reject_actual_bypass_shapes(self):
        runtime = ast.parse("def probe(self):\n self.runs.query('SELECT 1')\n self.runs.execute('UPDATE x')\n self.runs.transaction()\n")
        controller = ast.parse("def probe(self):\n return self.application.runs.runs.run('x')\n")
        application = ast.parse("def probe(self, table):\n return self.runs.query(f'SELECT * FROM {table}')\n")
        self.assertEqual(len(runtime_boundary_violations(runtime)), 3)
        self.assertEqual(len(controller_boundary_violations(controller)), 1)
        self.assertEqual(len(application_boundary_violations(application)), 1)

    def test_boundary_guards_allow_declared_composition_operations(self):
        controller = ast.parse(
            "def probe(self):\n"
            " self.application.registry.manifests.values()\n"
            " self.application.authoring.conversations.setdefault('x', [])\n"
        )
        application = ast.parse(
            "def probe(self, tool):\n"
            " with self.uow.transaction(): pass\n"
            " tool.execute('plugin operation')\n"
        )
        self.assertEqual(controller_boundary_violations(controller), [])
        self.assertEqual(application_boundary_violations(application), [])

    def test_dialog_policy_rejects_esc_blocking_props(self):
        source = (
            "dialog.props('persistent')\n"
            "other.props('no-backdrop-dismiss')\n"
            'dialog.props("persistent")\n'
            "third.props('no-esc-dismiss')\n"
            "fourth.props('no-backdrop-dismiss no-esc-dismiss')\n"
        )
        self.assertEqual(len(dialog_prop_violations(source)), 4)

    def test_desktop_dialogs_keep_esc_dismissal(self):
        offenders = []
        for path in (ROOT / "src/taskweave/desktop").rglob("*.py"):
            offenders.extend(
                f"{path.relative_to(ROOT)}:{item}"
                for item in dialog_prop_violations(path.read_text(encoding="utf-8"))
            )
        self.assertEqual(offenders, [])

    def test_outside_click_guard_is_timer_free_and_wired_into_the_launcher(self):
        from taskweave.desktop import dialogs

        guard = dialogs.OUTSIDE_CLICK_GUARD
        self.assertIn("__twDialogGuardInstalled", guard)
        # Floating layers must stay exempt, or ui.select inside a dialog breaks.
        self.assertIn(".q-menu", guard)
        self.assertIn(".q-dialog__backdrop", guard)
        self.assertNotIn("setTimeout", guard)
        self.assertNotIn("setInterval", guard)
        launcher = (ROOT / "src/taskweave/desktop/launcher.py").read_text(encoding="utf-8")
        self.assertIn("install_outside_click_guard()", launcher)

    def test_core_does_not_import_infrastructure_or_desktop(self):
        offenders = []
        for path in (ROOT / "src/taskweave/core").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    module = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = [node.module or ""]
                if module and any(name.startswith(("taskweave.infrastructure", "taskweave.desktop")) for name in module):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_context_sessions_receive_plan_files_root_explicitly(self):
        parameters = inspect.signature(ContextSessions.__init__).parameters
        self.assertIn("plan_files_root", parameters)
        self.assertIs(parameters["plan_files_root"].default, inspect.Parameter.empty)
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.planning.create(name="root boundary")
            reader = SimpleNamespace(get=app.repo.repositories.plans.get)
            sessions = ContextSessions(app.registry, app.repo.repositories.environments, reader, Path(home) / "explicit-plans")
            session = sessions._session(plan)
            self.assertEqual(session.root, Path(home) / "explicit-plans" / plan["plan_id"])
            session.busy.release()
            sessions.end(plan["plan_id"])

    def test_public_run_get_preserves_request_fields_without_inputs_json(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("private inputs", {"type": "object", "properties": {"secret": {"type": "string"}}})["task_id"]
            step = app.repo.save_step(task, {"input_schema": {"type": "object", "properties": {"count": {"type": "integer"}}}, "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)"})
            app.confirm_step_manual(step["step_id"], step["content_hash"])
            run = app.repo.create_run(task, {"secret": "private-value"}, app.registry.versions, step_inputs={step["step_id"]: {"count": 7}})
            request = json.loads(run["request_json"])
            request["waiting_input"] = {"scope": "task", "values": {"secret": "waiting-private"}}
            app.repo.repositories.runs.update_run_request(run["run_id"], json.dumps(request))
            public = app.dispatch("run.get", {"run_id": run["run_id"]})
            self.assertNotIn("inputs_json", public)
            returned = json.loads(public["request_json"])
            for key in ("initial_inputs", "initial_step_inputs", "step_inputs", "environment_hash", "flow_trial", "waiting_input"):
                self.assertEqual(returned[key], request[key])

    def test_desktop_queries_keep_private_inputs_outside_public_run_get(self):
        import asyncio
        import tempfile
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("private inputs", {"type": "object", "properties": {"token": {"type": "string"}}})["task_id"]
            step = app.repo.save_step(task, {"step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)"})
            app.confirm_step_manual(step["step_id"], step["content_hash"])
            run = app.repo.create_run(task, {"token": "private-value"}, app.registry.versions)
            controller = DesktopController(app)
            self.assertEqual(asyncio.run(controller.execution_inputs(run["run_id"]))["task"], {"token": "private-value"})
            self.assertEqual(asyncio.run(controller.run_request(run["run_id"]))["initial_inputs"], {"token": "private-value"})
            public_request = __import__("json").loads(app.dispatch("run.get", {"run_id": run["run_id"]})["request_json"])
            self.assertEqual(public_request["initial_inputs"], {"token": "private-value"})


if __name__ == "__main__":
    unittest.main()
