"""The dispatch split must preserve the frozen external operation policy."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from taskweave.application.operations import build_operation_routes, LOCK_EXEMPT_OPERATIONS
from taskweave.application.service import Application
from taskweave.core.validation import TaskError


POLICY = json.loads((Path(__file__).parent.parent / "fixtures" / "dispatch-policy.json").read_text())


class DispatchPolicyTests(unittest.TestCase):
    def test_routes_match_frozen_names_and_async_classification(self):
        app = Mock()
        app.repo = Mock()
        app.registry = Mock()
        app.coordinator = Mock()
        app.authoring = Mock()
        app.planning = Mock()
        sync, asynchronous = build_operation_routes(app)
        self.assertEqual(set(POLICY["methods"]), set(sync))
        self.assertEqual(set(POLICY["async_methods"]), set(asynchronous))
        self.assertEqual(set(POLICY["lock_exempt"]), LOCK_EXEMPT_OPERATIONS)

    def test_dispatch_unknown_operation_keeps_error_code(self):
        app = Mock()
        app.repo = Mock()
        app.registry = Mock()
        app.coordinator = Mock()
        app.authoring = Mock()
        app.planning = Mock()
        with self.assertRaises(TaskError) as caught:
            Application.dispatch(app, "does.not.exist")
        self.assertEqual("OPERATION_UNKNOWN", caught.exception.code)

    def test_task_routes_target_use_case_services(self):
        app = Mock()
        app.repo = Mock()
        app.registry = Mock()
        app.coordinator = Mock()
        app.authoring = Mock()
        app.planning = Mock()
        app.tasks = Mock()
        app.steps = Mock()
        sync, _ = build_operation_routes(app)
        self.assertIs(app.tasks.create, sync["task.create"])
        self.assertIs(app.steps.save, sync["step.save"])


if __name__ == "__main__":
    unittest.main()
