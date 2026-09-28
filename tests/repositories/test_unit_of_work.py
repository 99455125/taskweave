"""SQLite transaction guarantees shared by business repositories and Store."""

import threading
import tempfile
import unittest
import asyncio
from pathlib import Path

from taskweave.infrastructure.storage import Store
from taskweave.infrastructure.unit_of_work import SQLiteUnitOfWork


class SQLiteUnitOfWorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.uow = self.store.unit_of_work
        self.store.execute("CREATE TABLE uow_probe (value TEXT PRIMARY KEY)")

    def tearDown(self):
        self.temp.cleanup()

    def test_outer_failure_rolls_back_repository_and_store_writes(self):
        with self.assertRaisesRegex(RuntimeError, "outer"):
            with self.uow.transaction() as db:
                db.execute("INSERT INTO uow_probe VALUES ('repo')")
                self.store.execute("INSERT INTO uow_probe VALUES ('store')")
                self.assertEqual(["repo", "store"], [r["value"] for r in self.store.query("SELECT value FROM uow_probe ORDER BY value")])
                raise RuntimeError("outer")
        self.assertEqual([], self.store.query("SELECT value FROM uow_probe"))

    def test_caught_inner_failure_rolls_back_savepoint_only(self):
        with self.uow.transaction():
            self.store.execute("INSERT INTO uow_probe VALUES ('outer-before')")
            with self.assertRaisesRegex(RuntimeError, "inner"):
                with self.uow.transaction():
                    self.store.execute("INSERT INTO uow_probe VALUES ('inner')")
                    raise RuntimeError("inner")
            self.store.execute("INSERT INTO uow_probe VALUES ('outer-after')")
        self.assertEqual(["outer-after", "outer-before"], [r["value"] for r in self.store.query("SELECT value FROM uow_probe ORDER BY value")])

    def test_inner_success_does_not_commit_outer_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "outer"):
            with self.uow.transaction():
                with self.uow.transaction():
                    self.store.execute("INSERT INTO uow_probe VALUES ('inner-success')")
                raise RuntimeError("outer")
        self.assertEqual([], self.store.query("SELECT value FROM uow_probe"))

    def test_propagated_inner_failure_rolls_back_outer_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "inner-propagated"):
            with self.uow.transaction():
                self.store.execute("INSERT INTO uow_probe VALUES ('outer')")
                with self.uow.transaction():
                    self.store.execute("INSERT INTO uow_probe VALUES ('inner')")
                    raise RuntimeError("inner-propagated")
        self.assertEqual([], self.store.query("SELECT value FROM uow_probe"))

    def test_asyncio_child_task_does_not_inherit_active_connection(self):
        async def check():
            with self.uow.transaction():
                parent = self.uow.current_connection()

                async def child():
                    return self.uow.current_connection()

                child_connection = await asyncio.create_task(child())
                self.assertIsNotNone(parent)
                self.assertIsNone(child_connection)

        asyncio.run(check())

    def test_other_thread_cannot_read_uncommitted_write(self):
        inserted = threading.Event()
        release = threading.Event()
        observed = []

        def writer():
            with self.uow.transaction():
                self.store.execute("INSERT INTO uow_probe VALUES ('pending')")
                inserted.set()
                release.wait(5)

        thread = threading.Thread(target=writer)
        thread.start()
        self.assertTrue(inserted.wait(5))
        try:
            observed.extend(self.store.query("SELECT value FROM uow_probe"))
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], observed)
        self.assertEqual([{"value": "pending"}], self.store.query("SELECT value FROM uow_probe"))

    def test_foreign_keys_are_enabled_on_uow_connection(self):
        with self.uow.transaction() as db:
            self.assertEqual(1, db.execute("PRAGMA foreign_keys").fetchone()[0])
            db.execute("CREATE TABLE uow_parent (id TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE uow_child (parent_id TEXT REFERENCES uow_parent(id))")
            with self.assertRaises(Exception):
                db.execute("INSERT INTO uow_child VALUES ('missing')")


if __name__ == "__main__":
    unittest.main()
