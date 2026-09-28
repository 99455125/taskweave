"""Application composition refreshes dynamic capability dependencies."""

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from taskweave.application.service import Application


class ApplicationCompositionTests(unittest.TestCase):
    def test_planning_receives_context_ports_and_configured_plan_file_root(self):
        with tempfile.TemporaryDirectory() as directory, Application(Path(directory)) as app:
            self.assertIs(app.planning.steps, app.repo.repositories.steps)
            self.assertIs(app.planning.step_contexts, app.repo.repositories.step_contexts)
            self.assertEqual(app.planning.plan_files_root, app.home / "plans")
            self.assertEqual(app.context_sessions.plan_files_root, app.home / "plans")
            self.assertIs(app.coordinator.runs, app.repo.repositories.runs)
            self.assertIs(app.coordinator.tasks, app.repo.repositories.tasks)
            self.assertIs(app.coordinator.steps, app.repo.repositories.steps)
            self.assertIs(app.coordinator.environments, app.repo.repositories.environments)
            self.assertIs(app.coordinator.results, app.repo.repositories.results)
            self.assertEqual(app.coordinator.home, app.home)
            self.assertEqual(app.coordinator.task_data_root, app.home / "tasks")

    def test_plugin_reconfiguration_refreshes_run_and_context_use_cases(self):
        with tempfile.TemporaryDirectory() as directory, Application(Path(directory)) as app:
            provider = SimpleNamespace(context_provider_ids=("demo.page",))
            replacement = SimpleNamespace(
                versions={"replacement": "2"},
                plugins=[],
                catalog=lambda: {"plugins": ["replacement"]},
                contributions=lambda capabilities: [provider],
            )
            app.coordinator._stop_worker = Mock()
            app.runs.runs.create_run = Mock(return_value={"run_id": "run-new"})
            app.contexts.steps.step = Mock(return_value={"capabilities": ["replacement.action"]})
            app.contexts.contexts.save_step_context_batch = Mock(return_value={"context_id": "ctx"})

            with patch("taskweave.plugins.manager.PluginManager.configure", return_value=replacement):
                app.configure_plugin("replacement", True)

            created = app.runs.create("task-new")
            self.assertEqual(created["run_id"], "run-new")
            app.runs.runs.create_run.assert_called_once()
            self.assertEqual(app.runs.runs.create_run.call_args.args[2], replacement.versions)
            self.assertIs(app.tasks.registry, replacement)
            self.assertIs(app.steps.registry, replacement)
            self.assertIs(app.runs.registry, replacement)
            self.assertIs(app.contexts.registry, replacement)
            self.assertIs(app.planning.registry, replacement)
            app.contexts.save_batch("step", None, None, "demo.page", "page", "", [])
            app.contexts.contexts.save_step_context_batch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
