"""Receipts share definition transactions and never guess interrupted effects."""

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError


def store(app):
    try:
        from taskweave.infrastructure.agent_store import AgentStore
    except ModuleNotFoundError as exc:
        raise AssertionError("Persistent AI request receipts are not implemented") from exc
    return AgentStore(app.storage)


class AgentStoreTests(CoreFixture):
    def test_definition_and_receipt_commit_together_and_replay(self):
        receipts = store(self.app)
        first = receipts.atomic("create-contract", "fp1", lambda: self.app.tasks.create("通用示例"))
        repeated = receipts.atomic("create-contract", "fp1", lambda: self.app.tasks.create("重复"))
        self.assertEqual(repeated["task_id"], first["task_id"])
        self.assertEqual(len(self.app.tasks.list()), 1)
        with self.assertRaises(TaskError) as error:
            receipts.atomic("create-contract", "fp2", lambda: self.app.tasks.create("不同"))
        self.assertEqual(error.exception.code, "COMMAND_CONFLICT")

    def test_crash_between_definition_and_receipt_rolls_back_both(self):
        receipts = store(self.app)
        def crash():
            self.app.tasks.create("不能残留")
            raise RuntimeError("simulated crash before receipt commit")
        with self.assertRaises(RuntimeError):
            receipts.atomic("create-before-crash", "fp", crash)
        self.assertEqual(self.app.tasks.list(), [])
        self.assertIsNone(receipts.request("create-before-crash"))
        receipts.atomic("create-before-crash", "fp", lambda: self.app.tasks.create("恢复"))
        self.assertEqual(len(self.app.tasks.list()), 1)

    def test_interrupted_external_effect_remains_uncertain_after_reopen(self):
        receipts = store(self.app)
        receipts.claim("capture-1", "fp")
        reopened = store(self.app)
        self.assertEqual(reopened.request("capture-1")["state"], "PENDING")
        with self.assertRaises(TaskError) as error:
            reopened.claim("capture-1", "fp")
        self.assertEqual(error.exception.code, "AGENT_REQUEST_UNCERTAIN")
        receipts.finish("capture-1", "fp", {"session_id": "original"})
        self.assertEqual(reopened.claim("capture-1", "fp"), {"session_id": "original"})

    def test_immutable_materials_cannot_be_replaced(self):
        receipts = store(self.app)
        receipts.put("bundle", "b1", {"hash": "old"})
        self.assertEqual(receipts.get("bundle", "b1"), {"hash": "old"})
        with self.assertRaises(TaskError) as error:
            receipts.put("bundle", "b1", {"hash": "new"})
        self.assertEqual(error.exception.code, "AGENT_SNAPSHOT_IMMUTABLE")
