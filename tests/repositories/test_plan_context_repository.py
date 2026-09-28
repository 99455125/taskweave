import tempfile
import unittest
from pathlib import Path

from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.storage import Store


class PlanContextRepositoryTests(unittest.TestCase):
    def test_plan_context_mutations_return_plan_mappings_and_preserve_revision_at_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            repos = build_sqlite_repositories(Store(Path(directory)))
            plan = repos.plans.create("plan")

            def add_context(name):
                result = repos.plan_contexts.save_context_batch(
                    plan["plan_id"], repos.plans.get(plan["plan_id"])["revision"], None,
                    "demo.page", name, "", [{"label": "one", "capture": {"items": [{"content": name}], "views": []}, "request": {}}],
                )
                return result["group"]

            first, second = add_context("first"), add_context("second")
            revision = repos.plans.get(plan["plan_id"])["revision"]

            boundary = repos.plan_contexts.reorder_context(plan["plan_id"], revision, first["context_id"], "up")
            self.assertIsInstance(boundary, dict)
            self.assertEqual(boundary["revision"], revision)
            self.assertEqual([group["context_id"] for group in repos.plan_contexts.contexts(plan["plan_id"])], [first["context_id"], second["context_id"]])

            moved = repos.plan_contexts.reorder_context(plan["plan_id"], revision, first["context_id"], "down")
            self.assertIsInstance(moved, dict)
            self.assertEqual(moved["revision"], revision + 1)
            self.assertEqual([group["context_id"] for group in repos.plan_contexts.contexts(plan["plan_id"])], [second["context_id"], first["context_id"]])

            capture_id = first["captures"][0]["capture_id"]
            renamed = repos.plan_contexts.update_capture_label(moved["plan_id"], moved["revision"], first["context_id"], capture_id, "renamed")
            self.assertIsInstance(renamed, dict)
            self.assertEqual(renamed["revision"], moved["revision"] + 1)
            self.assertEqual(repos.plan_contexts.get_capture(first["context_id"], capture_id)["label"], "renamed")

    def test_contexts_store_ordered_captures_and_summaries(self):
        with tempfile.TemporaryDirectory() as directory:
            repos = build_sqlite_repositories(Store(Path(directory)))
            plan = repos.plans.create("plan")
            saved = repos.plan_contexts.save_context_batch(
                plan["plan_id"], plan["revision"], None, "demo.page", "page", "",
                [{"label": "capture", "capture": {"items": [{"kind": "text", "content": "x"}], "views": []}, "request": {}}],
            )
            group = repos.plan_contexts.contexts(plan["plan_id"])[0]
            self.assertNotIn("items", group["captures"][0])
            self.assertEqual("x", repos.plan_contexts.get_capture(group["context_id"], group["captures"][0]["capture_id"])["items"][0]["content"])
