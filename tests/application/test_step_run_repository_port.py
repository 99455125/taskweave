"""Step confirmation uses only the declared run repository port."""

import tempfile
import unittest
from pathlib import Path

from taskweave.application.service import Application
from taskweave.application.steps import StepUseCases
from taskweave.core.repositories import RunRepository
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import now, uid


class _DeclaredRunPort:
    """Expose only methods declared by RunRepository, forwarding to SQLite."""

    def __init__(self, repository, versions=None):
        self.repository = repository
        self.versions = versions

    def __getattr__(self, name):
        if name not in RunRepository.__dict__:
            raise AttributeError(f"outside RunRepository port: {name}")
        if name == "attempt_versions" and self.versions is not None:
            return lambda attempt_id: self.versions
        return getattr(self.repository, name)


class StepRunRepositoryPortTests(unittest.TestCase):
    def _confirmed_attempt(self, app):
        stores = app.repo.repositories
        task = stores.tasks.create_task("port confirmation")["task_id"]
        step = stores.steps.save_step(task, {"step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)"})
        run = stores.runs.create_run(task, {}, app.registry.versions, trial_step_id=step["step_id"])
        attempt_id = uid()
        stores.runs.create_attempt(attempt_id, task, run["run_id"], step["step_id"], step["content_hash"], now())
        stores.runs.finish_attempt(attempt_id, [])
        return stores, step, attempt_id

    def _service(self, app, stores, run_port):
        return StepUseCases(stores.steps, stores.tasks, run_port, app.registry, app.authoring, app.coordinator)

    def test_confirm_succeeds_through_declared_replaceable_attempt_versions_port(self):
        with tempfile.TemporaryDirectory() as home, Application(Path(home)) as app:
            stores, step, attempt_id = self._confirmed_attempt(app)
            port = _DeclaredRunPort(stores.runs)
            self.assertIn("attempt_versions", RunRepository.__dict__)
            service = self._service(app, stores, port)

            result = service.confirm(step["step_id"], attempt_id, step["content_hash"])

            self.assertEqual(result["validation_state"], "VALIDATED")

    def test_confirm_rejects_plugin_version_mismatch_through_replacement(self):
        with tempfile.TemporaryDirectory() as home, Application(Path(home)) as app:
            stores, step, attempt_id = self._confirmed_attempt(app)
            port = _DeclaredRunPort(stores.runs, versions={"stale-plugin": "0"})
            service = self._service(app, stores, port)

            with self.assertRaises(TaskError) as raised:
                service.confirm(step["step_id"], attempt_id, step["content_hash"])

            self.assertEqual(raised.exception.code, "PLUGIN_VERSION_MISMATCH")
            self.assertEqual(stores.steps.step(step["step_id"])["validation_state"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
