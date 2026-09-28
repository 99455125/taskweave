"""Plan repository copy and context persistence rollback checks."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskweave.infrastructure.plan_repository import PlanRepository
from taskweave.infrastructure.storage import Store


class PlanRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.repo = PlanRepository(self.store)
        self.plan = self.repo.create("source")

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_failure_rolls_back_new_plan_and_context_rows(self):
        saved = self.repo.save_context_batch(
            self.plan["plan_id"], self.plan["revision"], None,
            "demo.page", "page", "notes",
            [{"label": "one", "capture": {"items": [{"kind": "text", "content": "page"}], "views": []}, "request": {}}],
        )
        with patch.object(self.repo.plan_contexts, "copy_contexts", side_effect=RuntimeError("injected context copy failure")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.repo.copy(self.plan["plan_id"], saved["plan"]["revision"])

        self.assertEqual([self.plan["plan_id"]], [item["plan_id"] for item in self.repo.list()])
        self.assertEqual(1, len(self.repo.contexts(self.plan["plan_id"])))
        self.assertEqual(1, len(self.repo.context_records(self.plan["plan_id"])[0]["captures"]))


if __name__ == "__main__":
    unittest.main()
