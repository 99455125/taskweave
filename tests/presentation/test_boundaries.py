"""Executable UI replacement boundary, without installing a second frontend."""
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PresentationBoundaryTests(unittest.TestCase):
    def test_guard_rejects_framework_and_backwards_imports(self):
        import scripts.check_project as checks
        self.assertTrue(hasattr(checks, 'presentation_boundary_violations'))
        self.assertTrue(checks.presentation_boundary_violations(ast.parse('from nicegui import ui')))
        self.assertTrue(checks.presentation_boundary_violations(ast.parse('from taskweave.desktop.state import DebugState')))
        self.assertFalse(checks.presentation_boundary_violations(ast.parse('from taskweave.core.validation import TaskError')))

    def test_interactions_run_with_gui_imports_blocked(self):
        script = '''
import importlib.abc, sys, unittest
class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'nicegui', 'webview'} or fullname.startswith('taskweave.desktop'):
            raise AssertionError('GUI dependency: ' + fullname)
sys.meta_path.insert(0, NoGui())
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'tests.presentation.test_interactions', 'tests.presentation.test_planning',
    'tests.presentation.test_authoring_flow', 'tests.presentation.test_settings_boundary',
    'tests.presentation.test_debug_inputs', 'tests.test_execution_interactions', 'tests.presentation.test_settings_flow',
    'tests.presentation.test_task_organization', 'tests.presentation.test_environment',
    'tests.presentation.test_task_import', 'tests.presentation.test_plugin_selection',
    'tests.presentation.test_step_actions', 'tests.presentation.test_run_creation',
    'tests.presentation.test_execution_queries', 'tests.presentation.test_history',
    'tests.presentation.test_ai_state', 'tests.presentation.test_collection_form',
    'tests.presentation.test_input_dialog', 'tests.presentation.test_catalog',
])
result = unittest.TextTestRunner().run(suite)
sys.exit(not result.wasSuccessful())
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
