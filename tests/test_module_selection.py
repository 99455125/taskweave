"""Exact module test selection stays explicit and conservative."""

import tempfile
import unittest
import importlib
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path

from scripts.test_modules import (
    UnmappedSourceError,
    load_map,
    select_changed,
    select_modules,
    source_coverage_errors,
)

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "tests" / "module-map.json"


class ModuleSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module_map = load_map(MAP, ROOT)

    def test_ui_tasks_change_does_not_select_settings(self):
        result = select_changed(["src/taskweave/desktop/pages/tasks.py"], self.module_map, ROOT)
        self.assertIn("ui.tasks", result["modules"])
        self.assertNotIn("ui.settings", result["modules"])

    def test_shared_contract_change_selects_reverse_dependents(self):
        result = select_changed(["src/taskweave/core/repositories.py"], self.module_map, ROOT)
        self.assertIn("shared.contracts", result["modules"])
        self.assertIn("application.steps", result["modules"])
        self.assertIn("ui.editor", result["modules"])

    def test_step_port_change_selects_repository_application_and_ui_consumers(self):
        result = select_changed(["src/taskweave/core/repositories.py"], self.module_map, ROOT)
        self.assertIn("repository.steps", result["modules"])
        self.assertIn("application.steps", result["modules"])
        self.assertIn("ui.editor", result["modules"])

    def test_repository_consumer_changes_select_the_actual_dependents(self):
        step_contexts = select_changed(["src/taskweave/infrastructure/repositories/step_contexts.py"], self.module_map, ROOT)
        self.assertIn("repository.tasks", step_contexts["modules"])
        self.assertIn("tests.repositories.test_task_repository", step_contexts["targets"])
        results = select_changed(["src/taskweave/infrastructure/repositories/results.py"], self.module_map, ROOT)
        self.assertIn("repository.runs", results["modules"])
        self.assertIn("tests.repositories.test_run_repository", results["targets"])

    def test_run_repository_change_selects_application_and_ui_consumers(self):
        result = select_changed(["src/taskweave/infrastructure/repositories/runs.py"], self.module_map, ROOT)
        for module in (
            "repository.runs", "application.runs", "application.steps",
            "application.authoring", "ui.debug", "ui.editor", "ui.executions",
        ):
            self.assertIn(module, result["modules"])
        for target in (
            "tests.test_execution_control", "tests.test_step_authoring",
            "tests.test_ai_authoring", "tests.ui.test_step_debug_session",
            "tests.ui.test_step_ai_editor", "tests.ui.test_executions_page",
        ):
            self.assertIn(target, result["targets"])

    def test_result_repository_change_selects_authoring_and_ai_ui(self):
        result = select_changed(["src/taskweave/infrastructure/repositories/results.py"], self.module_map, ROOT)
        for module in ("repository.results", "application.authoring", "ui.editor"):
            self.assertIn(module, result["modules"])
        self.assertIn("tests.test_ai_authoring", result["targets"])
        self.assertIn("tests.ui.test_step_ai_editor", result["targets"])

    def test_shared_context_sessions_source_maps_to_real_application_consumers(self):
        direct = {
            name for name, record in self.module_map.items()
            if "src/taskweave/infrastructure/context_sessions.py" in record["source_globs"]
        }
        self.assertEqual(direct, {"application.runs", "application.planning", "application.environments"})
        selected = select_changed(["src/taskweave/infrastructure/context_sessions.py"], self.module_map, ROOT)
        self.assertTrue(direct.issubset(set(selected["modules"])))

    def test_application_dependencies_match_explicit_consumer_ports(self):
        expected = {
            "application.authoring": {
                "repository.tasks", "repository.steps", "repository.environments",
                "repository.runs", "repository.results", "shared.contracts",
            },
            "application.runs": {
                "repository.runs", "repository.tasks", "repository.steps",
                "repository.environments", "repository.results", "application.authoring",
                "shared.contracts",
            },
            "application.steps": {
                "repository.steps", "repository.tasks", "repository.runs",
                "application.authoring", "application.runs", "domain.steps", "shared.contracts",
            },
            "application.tasks": {
                "repository.tasks", "repository.steps", "repository.contexts",
                "application.authoring", "application.runs", "domain.tasks",
                "shared.storage", "shared.contracts",
            },
            "application.environments": {
                "repository.environments", "repository.runs", "repository.planning",
                "application.runs", "shared.contracts",
            },
            "application.planning": {
                "repository.planning", "repository.contexts", "repository.steps",
                "application.tasks", "application.authoring", "shared.contracts",
            },
        }
        for module, dependencies in expected.items():
            with self.subTest(module=module):
                self.assertEqual(set(self.module_map[module]["depends_on"]), dependencies)

    def test_environment_application_change_selects_environment_ui(self):
        result = select_changed(["src/taskweave/application/environments.py"], self.module_map, ROOT)
        self.assertIn("application.environments", result["modules"])
        self.assertIn("ui.environments", result["modules"])

    def test_operations_routes_select_all_application_consumers(self):
        result = select_changed(["src/taskweave/application/operations.py"], self.module_map, ROOT)
        for module in ("application.tasks", "application.steps", "application.planning", "application.authoring", "application.environments", "application.runs"):
            self.assertIn(module, result["modules"])
        self.assertIn("tests.test_http_task_api", result["targets"])

    def test_sql_package_resource_selects_shared_storage(self):
        result = select_changed(["src/taskweave/infrastructure/sql/control.sql"], self.module_map, ROOT)
        self.assertIn("shared.storage", result["modules"])
        self.assertIn("tests.test_control_db_migration", result["targets"])

    def test_playwright_browser_launch_tests_are_opt_in(self):
        quick = select_modules(["plugins.playwright"], self.module_map)
        with_browser = select_modules(["plugins.playwright"], self.module_map, include_browser=True)
        browser_test = "tests.test_playwright_choices.PlaywrightChoiceTests.test_snapshot_includes_native_and_custom_choices"
        self.assertNotIn(browser_test, quick["targets"])
        self.assertIn(browser_test, with_browser["browser_targets"])

    def test_target_ids_have_no_module_method_overlap(self):
        targets = {
            target
            for record in self.module_map.values()
            for target in record["targets"] + record["browser_targets"]
        }
        for target in targets:
            self.assertFalse(any(other.startswith(target + ".") for other in targets if other != target), target)

    def test_existing_unittest_files_have_a_mapped_entry(self):
        target_modules = set()
        for record in self.module_map.values():
            for target in record["targets"] + record["browser_targets"]:
                parts = target.split(".")
                for length in range(2, len(parts) + 1):
                    path = ROOT.joinpath(*parts[:length]).with_suffix(".py")
                    if path.is_file():
                        target_modules.add(path.resolve())
                        break
        files = set()
        for pattern in ("tests/test_*.py", "tests/ui/test_*.py", "tests/application/test_*.py", "tests/repositories/test_*.py"):
            files.update(path.resolve() for path in ROOT.glob(pattern))
        self.assertEqual(sorted(path.relative_to(ROOT).as_posix() for path in files - target_modules), [])

    def test_all_mapped_targets_resolve_to_unique_test_ids(self):
        targets = []
        for record in self.module_map.values():
            for target in record["targets"] + record["browser_targets"]:
                if target not in targets:
                    targets.append(target)
        loader = unittest.defaultTestLoader
        test_ids = []
        for target in targets:
            suite = loader.loadTestsFromName(target)
            pending = [suite]
            while pending:
                item = pending.pop()
                if isinstance(item, unittest.TestSuite):
                    pending.extend(item)
                else:
                    self.assertIsInstance(item, unittest.TestCase, target)
                    self.assertNotIsInstance(item, unittest.FunctionTestCase, target)
                    test_ids.append(item.id())
        self.assertEqual(len(test_ids), len(set(test_ids)))

    def test_every_existing_unittest_id_is_covered_by_a_mapped_target(self):
        targets = {
            target
            for record in self.module_map.values()
            for target in record["targets"] + record["browser_targets"]
        }
        files = set()
        for pattern in ("tests/test_*.py", "tests/ui/test_*.py", "tests/application/test_*.py", "tests/repositories/test_*.py"):
            files.update(ROOT.glob(pattern))
        loader = unittest.defaultTestLoader
        unmapped = []
        for path in sorted(files):
            module_name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            module = importlib.import_module(module_name)
            pending = [loader.loadTestsFromModule(module)]
            while pending:
                item = pending.pop()
                if isinstance(item, unittest.TestSuite):
                    pending.extend(item)
                    continue
                self.assertIsInstance(item, unittest.TestCase, module_name)
                test_id = item.id()
                if not any(test_id == target or test_id.startswith(target + ".") for target in targets):
                    unmapped.append(test_id)
        self.assertEqual(unmapped, [])

    def test_unknown_product_source_is_rejected(self):
        with self.assertRaises(UnmappedSourceError) as caught:
            select_changed(["src/taskweave/new_unknown_module.py"], self.module_map, ROOT)
        self.assertIn("new_unknown_module.py", str(caught.exception))
        with self.assertRaises(UnmappedSourceError):
            select_changed(["plugins/new_vendor/src/plugin.py"], self.module_map, ROOT)

    def test_coverage_maps_every_product_python_file(self):
        self.assertEqual(source_coverage_errors(ROOT, self.module_map), [])

    def test_duplicate_targets_from_multiple_modules_are_run_once(self):
        result = select_modules(["ui.tasks", "shared.ui"], self.module_map, include_browser=False)
        self.assertEqual(len(result["targets"]), len(set(result["targets"])))

    def test_browser_targets_are_opt_in(self):
        quick = select_modules(["ui.editor"], self.module_map, include_browser=False)
        with_browser = select_modules(["ui.editor"], self.module_map, include_browser=True)
        self.assertEqual(quick["browser_targets"], [])
        self.assertTrue(with_browser["browser_targets"])
        self.assertTrue(set(quick["targets"]).isdisjoint(with_browser["browser_targets"]))

    def test_changed_reasons_identify_direct_path_and_dependency(self):
        result = select_changed(["src/taskweave/desktop/pages/tasks.py"], self.module_map, ROOT)
        self.assertTrue(any("pages/tasks.py" in reason for reason in result["reasons"]["ui.tasks"]))

    def test_cli_dry_run_does_not_execute_unittest(self):
        from scripts.test_modules import main
        from unittest.mock import patch
        with patch("scripts.test_modules.run_targets", side_effect=AssertionError("dry run executed tests")):
            status = main(["--module", "ui.tasks", "--dry-run", "--root", str(ROOT), "--map", str(MAP)])
        self.assertEqual(status, 0)

    def test_cli_list_and_changed_dry_run(self):
        from scripts.test_modules import main
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--list", "--root", str(ROOT), "--map", str(MAP)]), 0)
        self.assertIn("application.environments", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--changed", "src/taskweave/desktop/pages/tasks.py", "--dry-run", "--root", str(ROOT), "--map", str(MAP)]), 0)
        self.assertIn("ui.tasks", output.getvalue())
        self.assertNotIn("ui.settings", output.getvalue())

    def test_cli_rejects_unknown_empty_and_unmapped_requests(self):
        from scripts.test_modules import main
        errors = StringIO()
        with redirect_stderr(errors):
            self.assertEqual(main(["--module", "ui.missing", "--root", str(ROOT), "--map", str(MAP)]), 2)
            self.assertEqual(main(["--changed", "src/taskweave/new_unknown.py", "--dry-run", "--root", str(ROOT), "--map", str(MAP)]), 2)
            self.assertEqual(main(["--root", str(ROOT), "--map", str(MAP)]), 2)
        self.assertIn("unknown module", errors.getvalue())
        self.assertIn("unmapped product source", errors.getvalue())
        self.assertIn("choose either --module or --changed", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
