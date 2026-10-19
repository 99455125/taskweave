"""Legacy Store methods continue to route to their owning repositories."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from taskweave.infrastructure.plan_repository import PlanRepository
from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.storage import Store
from taskweave.infrastructure.sqlite_storage import SQLiteStorage
from taskweave.infrastructure.repositories import build_sqlite_repositories


class StoreCompatibilityTests(unittest.TestCase):
    def test_facades_bind_existing_composition_and_share_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = SQLiteStorage(directory)
            repositories = build_sqlite_repositories(storage)
            facade = Repository.from_storage(storage, repositories)
            plans = PlanRepository(storage, repositories=repositories)
            self.assertIs(storage.unit_of_work, facade.unit_of_work)
            self.assertIs(repositories, facade.repositories)
            self.assertIs(repositories.plans, plans.plans)
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with storage.transaction():
                    facade.create_task("rollback")
                    plans.create("rollback")
                    raise RuntimeError("rollback")
            self.assertEqual([], repositories.tasks.list_tasks())
            self.assertEqual([], repositories.plans.list())

    def test_legacy_facades_read_shared_data_and_preserve_outer_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory))
            store = Store(Path(directory))
            plans = PlanRepository(repository)
            task = repository.create_task("shared")
            self.assertEqual(task, store.task(task["task_id"]))
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with repository.transaction():
                    repository.create_task("rollback")
                    plans.create("rollback")
                    raise RuntimeError("rollback")
            self.assertEqual([task], repository.list_tasks())
            self.assertEqual([], plans.list())

    def test_store_receipt_delegates_to_result_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            result_repository = store._repository_adapter("results")
            receipt = [{"result_id": "r1"}]
            result_repository.receipt = Mock(return_value=receipt)

            self.assertEqual(receipt, store.receipt({"attempt_id": "a1"}))
            result_repository.receipt.assert_called_once_with({"attempt_id": "a1"})

    def test_repository_receipt_delegates_to_result_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory))
            receipt = [{"result_id": "r2"}]
            repository.result_repository.receipt = Mock(return_value=receipt)

            self.assertEqual(receipt, repository.receipt({"attempt_id": "a2"}))
            repository.result_repository.receipt.assert_called_once_with({"attempt_id": "a2"})


if __name__ == "__main__":
    unittest.main()
