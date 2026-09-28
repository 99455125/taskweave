"""Legacy Store methods continue to route to their owning repositories."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.storage import Store


class StoreCompatibilityTests(unittest.TestCase):
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
