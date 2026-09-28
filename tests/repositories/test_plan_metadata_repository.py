import tempfile
import unittest
from pathlib import Path

from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.storage import Store


class PlanMetadataRepositoryTests(unittest.TestCase):
    def test_metadata_crud_and_copy_use_composed_context_port(self):
        with tempfile.TemporaryDirectory() as directory:
            repos = build_sqlite_repositories(Store(Path(directory)))
            plan = repos.plans.create("source")
            changed = repos.plans.update(plan["plan_id"], plan["revision"], "renamed")
            copied = repos.plans.copy(plan["plan_id"], changed["revision"])
            self.assertEqual("renamed 副本", copied["name"])
