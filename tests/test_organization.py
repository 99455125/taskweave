"""Local favorites and category semantics across task and planning records."""

from tests._runtime_fixture import RuntimeFixture
from unittest.mock import patch


class OrganizationTests(RuntimeFixture):
    def test_category_storage_errors_are_not_reported_as_duplicate_names(self):
        with patch.object(self.app.organization.store, "execute", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                self.app.dispatch("organization.category.create", {"name": "分类"})

    def test_category_delete_uncategorizes_both_objects_without_definition_changes(self):
        plan = self.app.dispatch("plan.create", {"name": "P"})
        category = self.app.dispatch("organization.category.create", {"name": "常用"})
        before = self.app.repo.definition_hash(self.task)
        self.app.dispatch("organization.metadata.set", {"entity": "task", "entity_id": self.task, "is_favorite": True, "category_id": category["category_id"]})
        self.app.dispatch("organization.metadata.set", {"entity": "plan", "entity_id": plan["plan_id"], "is_favorite": True, "category_id": category["category_id"]})
        self.assertEqual(self.app.repo.definition_hash(self.task), before)
        self.app.dispatch("organization.category.delete", {"category_id": category["category_id"]})
        self.assertEqual(self.app.repo.task(self.task)["category_id"], None)
        self.assertEqual(self.app.planning.get(plan["plan_id"])["category_id"], None)
        self.assertEqual(self.app.repo.task(self.task)["is_favorite"], 1)
        self.assertEqual(self.app.planning.get(plan["plan_id"])["is_favorite"], 1)

    def test_copy_keeps_category_but_new_object_is_not_favorite(self):
        plan = self.app.dispatch("plan.create", {"name": "P"})
        category = self.app.dispatch("organization.category.create", {"name": "工作"})
        self.app.dispatch("organization.metadata.set", {"entity": "task", "entity_id": self.task, "is_favorite": True, "category_id": category["category_id"]})
        self.app.dispatch("organization.metadata.set", {"entity": "plan", "entity_id": plan["plan_id"], "is_favorite": True, "category_id": category["category_id"]})
        task_copy = self.app.dispatch("task.copy", {"task_id": self.task})
        plan_copy = self.app.dispatch("plan.copy", {"plan_id": plan["plan_id"], "expected_revision": plan["revision"]})
        self.assertEqual(self.app.repo.task(task_copy["task_id"])["category_id"], category["category_id"])
        self.assertEqual(self.app.repo.task(task_copy["task_id"])["is_favorite"], 0)
        self.assertEqual(self.app.planning.get(plan_copy["plan_id"])["category_id"], category["category_id"])
        self.assertEqual(self.app.planning.get(plan_copy["plan_id"])["is_favorite"], 0)

    def test_task_package_omits_local_organization_metadata(self):
        category = self.app.dispatch("organization.category.create", {"name": "本地"})
        self.app.dispatch("organization.metadata.set", {"entity": "task", "entity_id": self.task, "is_favorite": True, "category_id": category["category_id"]})
        package = self.app.dispatch("task.export", {"task_id": self.task})
        self.assertNotIn("is_favorite", package["task"])
        self.assertNotIn("category_id", package["task"])
        imported = self.app.dispatch("task.import", {"package": package})
        task = self.app.repo.task(imported["task_id"])
        self.assertEqual(task["is_favorite"], 0)
        self.assertIsNone(task["category_id"])
