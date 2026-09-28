import tempfile
import time
import unittest

from taskweave.core.validation import TaskError
from taskweave.infrastructure.plan_repository import PlanRepository
from taskweave.infrastructure.repository import Repository


SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data={})\n"
ITEM = {"kind": "text", "source": "playwright.page", "content": "page snapshot"}
VIEW = {"title": "页面截图", "renderer": "playwright.screenshot", "data": {"image_base64": "aW1hZ2U=", "mime_type": "image/png"}}


class ContextMetadataTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.repo = Repository(self.home.name)
        self.task = self.repo.create_task("上下文说明")
        self.step = self.repo.save_step(
            self.task["task_id"], {"name": "登录", "step_content": SOURCE}
        )

    def save_context(self, **overrides):
        values = {
            "step_id": self.step["step_id"], "provider_id": "playwright.page",
            "name": "登录页面", "source_page": "draft", "item": ITEM,
        }
        return self.repo.save_step_context(**(values | overrides))

    def test_step_metadata_survives_reopen_and_edit_invalidates_confirmation(self):
        context = self.save_context(context_notes="输入用户名后，等待验证码出现")
        self.repo.confirm_manual(self.step["step_id"], self.step["content_hash"])
        updated = self.save_context(
            context_id=context["context_id"], name="登录页面 · 已输入账号",
            context_notes="下一步只识别验证码，不提交登录",
        )
        reopened = Repository(self.home.name)
        summary = reopened.list_step_contexts(self.step["step_id"])[0]
        self.assertEqual(summary["context_id"], updated["context_id"])
        self.assertEqual(summary["name"], updated["name"])
        self.assertEqual(updated["context_notes"], "下一步只识别验证码，不提交登录")
        self.assertEqual(reopened.get_step_context_capture(updated["context_id"],updated["captures"][0]["capture_id"])["items"], [ITEM])
        self.assertEqual(updated["created_at"], context["created_at"])
        self.assertEqual(reopened.step(self.step["step_id"])["validation_state"], "DRAFT")
        cleared = self.save_context(context_id=context["context_id"], context_notes="")
        self.assertEqual(cleared["context_notes"], "")

    def test_context_cannot_be_updated_through_another_step(self):
        context = self.save_context(context_notes="原说明")
        another = self.repo.save_step(
            self.task["task_id"], {"name": "其他步骤", "step_content": SOURCE}
        )
        with self.assertRaises(TaskError):
            self.save_context(
                step_id=another["step_id"], context_id=context["context_id"],
                name="错误覆盖", context_notes="错误说明",
            )
        self.assertEqual(self.repo.list_step_contexts(self.step["step_id"])[0]["context_id"], context["context_id"])
        self.assertEqual(self.repo.list_step_contexts(another["step_id"]), [])

    def test_context_parent_contains_only_group_metadata(self):
        context = self.save_context()
        columns={row['name'] for row in self.repo.query('PRAGMA table_info(step_contexts)')}
        self.assertNotIn('item_json',columns)
        self.assertNotIn('views_json',columns)
        stored=self.repo.get_step_context_capture(context['context_id'],context['captures'][0]['capture_id'])
        self.assertEqual(stored['items'],[ITEM])
        self.assertEqual(self.repo.query('PRAGMA user_version')[0]['user_version'],17)

    def test_plan_name_and_notes_edit_preserves_capture_and_survives_reopen(self):
        plans = PlanRepository(self.repo)
        plan = plans.create("登录规划")
        capture = plans.add_context(
            plan["plan_id"], 1, "playwright.page", "采集登录页", "打开页面",
            "session-1", [ITEM],
        )
        context = capture["context"]
        updated_plan = plans.update_context(
            plan["plan_id"], capture["plan"]["revision"], context["context_id"],
            "登录前页面", "输入账号和密码，稍后再处理验证码",
        )
        reopened = PlanRepository(Repository(self.home.name))
        updated = reopened.contexts(plan["plan_id"])[0]
        self.assertEqual(updated_plan["revision"], capture["plan"]["revision"] + 1)
        self.assertEqual(updated["name"], "登录前页面")
        self.assertEqual(updated["context_notes"], "输入账号和密码，稍后再处理验证码")
        capture = reopened.get_capture(updated["context_id"],updated["captures"][0]["capture_id"])
        self.assertEqual(capture["items"], [ITEM])
        self.assertEqual(capture["source_session_id"], "session-1")
        with self.assertRaises(TaskError) as stale:
            reopened.update_context(plan["plan_id"], 1, context["context_id"], "旧输入", "旧说明")
        self.assertEqual(stale.exception.code, "EDIT_CONFLICT")

    def test_metadata_rejects_empty_name_and_non_text_notes(self):
        with self.assertRaises(TaskError):
            self.save_context(name="  ", context_notes="说明")
        with self.assertRaises(TaskError):
            self.save_context(context_notes={"wrong": "type"})
        plans = PlanRepository(self.repo)
        plan = plans.create("P")
        context = plans.add_context(plan["plan_id"], 1, "playwright.page", "C", "", "S", [ITEM])["context"]
        for name, notes in ((" ", "说明"), ("C", {"wrong": "type"})):
            with self.subTest(name=name, notes=notes), self.assertRaises(TaskError):
                plans.update_context(plan["plan_id"], 2, context["context_id"], name, notes)
        self.assertEqual(plans.get(plan["plan_id"])["revision"], 2)

    def test_step_contexts_have_stable_order_and_can_move(self):
        first = self.save_context(name="第一页", request={"scope": "viewport"}, views=[VIEW], include_view=True)
        second = self.save_context(name="第二页", request={"scope": "full_page"}, views=[], include_view=False)
        self.assertEqual([row["name"] for row in self.repo.list_step_contexts(self.step["step_id"])], ["第一页", "第二页"])
        self.repo.reorder_step_context(second["context_id"], "up")
        rows = self.repo.list_step_contexts(self.step["step_id"])
        self.assertEqual([row["context_id"] for row in rows], [second["context_id"], first["context_id"]])
        capture = self.repo.get_step_context_capture(rows[1]["context_id"],rows[1]["captures"][0]["capture_id"])
        self.assertEqual(capture["request"], {"scope": "viewport"})
        self.assertEqual(capture["views"], [VIEW])

    def test_step_recollection_replaces_capture_in_place(self):
        context = self.save_context(name="旧名称", request={"scope": "viewport"}, views=[VIEW])
        replaced = self.save_context(
            context_id=context["context_id"], name="新名称", context_notes="新说明",
            item=[{"kind": "text", "source": "playwright.page", "content": "new"}],
            request={"scope": "full_page"}, views=[], include_view=False,
        )
        self.assertEqual(replaced["context_id"], context["context_id"])
        self.assertEqual(replaced["order_index"], context["order_index"])
        capture = self.repo.get_step_context_capture(replaced["context_id"],context["captures"][0]["capture_id"])
        self.assertNotEqual(capture["captured_at"], context["captured_at"])
        self.assertEqual(capture["request"], {"scope": "full_page"})

    def test_step_recollection_refreshes_timestamp_even_when_payload_is_identical(self):
        context = self.save_context(request={"scope": "full_page"}, views=[VIEW])
        time.sleep(0.002)
        replaced = self.save_context(
            context_id=context["context_id"], request=context["request"],
            views=context["views"], include_view=True, replace_capture=True,
        )
        self.assertNotEqual(replaced["capture"]["captured_at"], context["captured_at"])

    def test_plan_notes_order_and_recollection_are_persistent(self):
        plans = PlanRepository(self.repo)
        plan = plans.create("合约规划")
        plan = plans.update(plan["plan_id"], 1, "合约规划", "完成合约", "按采集顺序执行", None, ["playwright"])
        first = plans.add_context(plan["plan_id"], plan["revision"], "playwright.page", "A", "先做", "s", [ITEM], {"scope": "viewport"}, [VIEW], True)
        second = plans.add_context(plan["plan_id"], first["plan"]["revision"], "playwright.page", "B", "后做", "s", [ITEM], {}, [], False)
        moved = plans.reorder_context(plan["plan_id"], second["plan"]["revision"], second["context"]["context_id"], "up")
        self.assertEqual([row["name"] for row in plans.contexts(plan["plan_id"])], ["B", "A"])
        refreshed = plans.replace_context(
            plan["plan_id"], moved["revision"], first["context"]["context_id"],
            "playwright.page", "A2", "更新", "s2", [ITEM], {"scope": "full_page"}, [], False,
        )
        self.assertEqual(refreshed["plan_notes"], "按采集顺序执行")
        updated = next(row for row in plans.contexts(plan["plan_id"]) if row["context_id"] == first["context"]["context_id"])
        self.assertEqual(updated["name"], "A2")
        self.assertEqual(updated["order_index"], 1)


if __name__ == "__main__":
    unittest.main()

    def test_capture_opt_in_and_notes_survive_reopen(self):
        context = self.save_context()
        item = context["captures"][0]
        self.assertFalse(item["send_preview"])
        self.repo.update_step_context_capture_label(context["context_id"], item["capture_id"], "新标题",
            operation_notes="长操作说明", send_preview=True)
        capture = Repository(self.home.name).get_step_context_capture(context["context_id"], item["capture_id"])
        self.assertEqual(capture["operation_notes"], "长操作说明")
        self.assertTrue(capture["send_preview"])

    def test_plan_capture_metadata_survives_copy(self):
        plans = PlanRepository(self.repo)
        plan = plans.create("采集规划")
        result = plans.add_context(plan["plan_id"], plan["revision"], "playwright.page", "页面", "组说明", "s", [ITEM], {}, [VIEW], True)
        context = result["context"]
        capture = context["captures"][0]
        changed = plans.update_capture_label(plan["plan_id"], result["plan"]["revision"], context["context_id"], capture["capture_id"], "标题", "操作说明", True)
        copied = plans.copy(plan["plan_id"], changed["revision"])
        group = plans.contexts(copied["plan_id"])[0]
        entry = group["captures"][0]
        self.assertTrue(entry["send_preview"])
        self.assertEqual(entry["operation_notes"], "操作说明")
