import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from taskweave.application.service import Application
from taskweave.core.validation import TaskError


SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data={})\n"


def package():
    return {
        "format": "taskweave-task-2", "origin": "ai_generated",
        "task": {"name": "生成任务", "description": "", "input_schema": {"type": "object"}},
        "steps": [{"key": "step-1", "validation_state": "DRAFT", "document": {
            "name": "步骤", "step_description": "返回空结果", "step_notes": "",
            "step_content": SOURCE, "input_schema": {"type": "object"},
            "output_schema": {"type": "object"}, "bindings": {}, "capabilities": [],
            "plugin_requirements": {}, "timeout_ms": 60000,
            "delay_after_previous_seconds": 0, "content_format": "python-async-v1",
        }}],
    }


class PlanningTests(unittest.TestCase):
    def test_context_mapping_cannot_silently_omit_steps(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.planning.create("对应材料")
            added = app.planning.contexts.add_context(
                plan["plan_id"], 1, "playwright.page", "登录", "", "session",
                [{"kind": "text", "content": "登录表单"}],
            )
            generated = app.dispatch("plan.generate", {
                "plan_id": plan["plan_id"], "expected_revision": added["plan"]["revision"],
                "channel": "web_chat",
            })
            candidate = package()
            candidate["steps"].append(json.loads(json.dumps(candidate["steps"][0])))
            candidate["steps"][1]["key"] = "step-2"
            for refs in (None, {}, {"step-1": [added["context"]["context_id"]]}):
                with self.subTest(refs=refs):
                    if refs is not None:
                        candidate["plan_context_refs"] = refs
                    with self.assertRaisesRegex(TaskError, "上下文对应关系"):
                        app.planning.parse(generated["generation_id"], json.dumps(candidate))
                    self.assertEqual(app.repo.list_tasks(), [])
            candidate["plan_context_refs"] = {
                "step-1": [added["context"]["context_id"]], "step-2": [],
            }
            self.assertEqual(app.planning.parse(
                generated["generation_id"], json.dumps(candidate))["status"], "READY")
            # Recheck persisted candidates at import too, before creating any task.
            app.planning.generations.finish_generation(
                generated["generation_id"], "READY", candidate=package())
            with self.assertRaisesRegex(TaskError, "上下文对应关系"):
                app.planning.import_generation(generated["generation_id"])
            self.assertEqual(app.repo.list_tasks(), [])

    def test_prompt_schema_requires_explicit_step_context_mapping(self):
        from jsonschema import Draft202012Validator
        from taskweave.application.planning import PLAN_CANDIDATE_SCHEMA
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.planning.get(app.planning.create("提示词")["plan_id"])
            materials = app.planning._materials(plan)
            self.assertEqual(materials["task_package_schema"], PLAN_CANDIDATE_SCHEMA)
            self.assertTrue(list(Draft202012Validator(
                materials["task_package_schema"]).iter_errors(package())))
            candidate = package()
            candidate["plan_context_refs"] = {"step-1": []}
            Draft202012Validator(materials["task_package_schema"]).validate(candidate)

    def test_planning_to_task_package_preserves_scope_and_per_step_evidence(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.planning.create("完整往返")
            contexts = []
            for index in range(2):
                added = app.planning.contexts.add_context(
                    plan["plan_id"], plan["revision"], "playwright.page",
                    f"页面{index}", f"操作说明{index}", "live-session",
                    [{"kind": "text", "content": f"页面内容{index}"}],
                    {"scope": "full_page"},
                    [{"title": "完整截图", "renderer": "playwright.screenshot",
                      "data": {"image_base64": f"image-{index}"}}], True,
                )
                plan = added["plan"]
                contexts.append(added["context"]["context_id"])
                appended = app.planning.contexts.append_capture(
                    plan["plan_id"], plan["revision"], contexts[-1],
                    {"items": [{"kind": "text", "content": f"补采{index}"}], "views": []},
                    request={"scope": "viewport"}, include_view=False, label="第二次采集",
                )
                plan = appended["plan"]
            generated = app.dispatch("plan.generate", {
                "plan_id": plan["plan_id"], "expected_revision": plan["revision"],
                "channel": "web_chat",
            })
            candidate = package()
            candidate["task"]["input_schema"] = {
                "type": "object", "properties": {"contract_no": {"type": "string"}},
                "required": ["contract_no"],
            }
            first = candidate["steps"][0]["document"]
            first["input_schema"] = {
                "type": "object", "properties": {"login_name": {"type": "string"}},
                "required": ["login_name"],
            }
            first["output_schema"] = {
                "type": "object", "properties": {"record_id": {"type": "string"}},
            }
            first["step_content"] = ""
            second = json.loads(json.dumps(candidate["steps"][0]))
            second["key"] = "step-2"
            second["document"]["input_schema"] = {
                "type": "object", "properties": {"record_id": {"type": "string"}},
            }
            second["document"]["bindings"] = {"record_id": {"ref": {
                "source": "step", "step_id": "step-1", "output": "data",
                "pointer": "/record_id",
            }}}
            candidate["steps"].append(second)
            candidate["plan_context_refs"] = {
                "step-1": contexts, "step-2": [contexts[1]],
            }
            app.planning.parse(generated["generation_id"], json.dumps(candidate))
            task = app.planning.import_generation(generated["generation_id"])
            exported = app.export_task(task["task_id"])
            self.assertEqual(exported["task"]["input_schema"], candidate["task"]["input_schema"])
            self.assertEqual(exported["steps"][0]["document"]["input_schema"], first["input_schema"])
            self.assertEqual([c["step_key"] for c in exported["contexts"]],
                             ["step-1", "step-1", "step-2"])
            self.assertEqual([c["captures"][0]["views"][0]["data"]["image_base64"]
                              for c in exported["contexts"]], ["image-0", "image-1", "image-1"])
            self.assertEqual([len(c["captures"]) for c in exported["contexts"]], [2, 2, 2])
            self.assertEqual(exported["contexts"][0]["captures"][1]["label"], "第二次采集")
            self.assertEqual(exported["contexts"][0]["captures"][1]["items"][0]["content"], "补采0")
            self.assertFalse(exported["contexts"][0]["captures"][1]["include_view"])
            # Cross workspace: no dependency on source plan, session or database IDs.
            with tempfile.TemporaryDirectory() as other_home, Application(other_home) as other:
                imported = other.import_task(json.loads(json.dumps(exported)))
                self.assertEqual(other.export_task(imported["task_id"]), exported)
                steps = other.repo.steps(imported["task_id"])
                self.assertEqual(steps[1]["bindings"]["record_id"]["ref"]["step_id"],
                                 steps[0]["step_id"])

    def test_generation_snapshot_uses_configured_files_root_without_repository_root_attribute(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.planning.create("snapshot")
            plan = app.planning.get(plan["plan_id"])
            plans = app.planning.plans
            app.planning.plans = SimpleNamespace(get=plans.get)
            try:
                _, _, root, _ = app.planning._snapshot(plan, "web_chat")
            finally:
                app.planning.plans = plans

            expected = app.home / "plans" / plan["plan_id"] / "generations"
            self.assertEqual(root, expected)
            self.assertTrue(root.is_dir())

    def test_copy_plan_preserves_contexts_but_not_ids_sessions_or_generations(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            original = app.dispatch("plan.create", {"name": "P"})
            original = app.dispatch("plan.update", {
                "plan_id": original["plan_id"], "expected_revision": 1,
                "name": "P", "plan_description": "目标", "plan_notes": "先登录",
                "environment_id": None, "plugin_ids": ["playwright"],
            })
            for index in range(2):
                added = app.planning.contexts.add_context(
                    original["plan_id"], original["revision"], "playwright.page",
                    f"页面{index}", f"操作{index}", "live-session",
                    [{"kind": "text", "content": str(index)}], {"scope": "viewport"},
                    [{"title": f"预览{index}", "renderer": "playwright.screenshot", "data": {"image_base64": "a"}}], True,
                )
                original = added["plan"]
            app.dispatch("plan.generate", {"plan_id": original["plan_id"], "expected_revision": original["revision"], "channel": "web_chat"})
            copied = app.dispatch("plan.copy", {"plan_id": original["plan_id"], "expected_revision": original["revision"]})
            self.assertEqual(copied["name"], "P 副本")
            self.assertEqual(copied["plan_description"], "目标")
            self.assertEqual(copied["plan_notes"], "先登录")
            self.assertEqual(copied["plugin_ids"], ["playwright"])
            source_contexts = app.planning.contexts.contexts(original["plan_id"])
            copied_contexts = app.planning.contexts.contexts(copied["plan_id"])
            self.assertEqual([x["name"] for x in copied_contexts], ["页面0", "页面1"])
            self.assertEqual([x["context_notes"] for x in copied_contexts], ["操作0", "操作1"])
            self.assertEqual([x["captures"][0]["captured_at"] for x in copied_contexts], [x["captures"][0]["captured_at"] for x in source_contexts])
            self.assertEqual([app.planning.contexts.get_capture(x["context_id"],x["captures"][0]["capture_id"])["views"] for x in copied_contexts], [app.planning.contexts.get_capture(x["context_id"],x["captures"][0]["capture_id"])["views"] for x in source_contexts])
            self.assertTrue(set(x["context_id"] for x in copied_contexts).isdisjoint(x["context_id"] for x in source_contexts))
            self.assertTrue(all(app.planning.contexts.get_capture(x["context_id"],x["captures"][0]["capture_id"]).get("source_session_id") != "live-session" for x in copied_contexts))
            self.assertEqual(app.repo.query("SELECT * FROM plan_generations WHERE plan_id=?", (copied["plan_id"],)), [])
            app.planning.contexts.update_context(copied["plan_id"], copied["revision"], copied_contexts[0]["context_id"], "新页面", "")
            self.assertEqual(app.planning.contexts.contexts(original["plan_id"])[0]["name"], "页面0")

    def test_generation_imports_frozen_referenced_context(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            captured = app.planning.contexts.add_context(
                plan["plan_id"], plan["revision"], "playwright.page", "旧页面",
                "第一步页面", "session-old", [{"kind": "text", "content": "before"}],
                {"scope": "viewport"}, [], False,
            )
            plan, context = captured["plan"], captured["context"]
            second=app.planning.contexts.append_capture(plan['plan_id'],plan['revision'],context['context_id'],{'items':[{'kind':'text','content':'second'}],'views':[{'title':'second preview'}]},request={'scope':'full_page'},include_view=True,session_id='session-second',label='第二项')
            plan=second['plan']
            generated = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": plan["revision"], "channel": "web_chat"})
            app.planning.contexts.delete_capture(plan['plan_id'],plan['revision'],context['context_id'],second['capture']['capture_id'])
            candidate = package()
            candidate["steps"][0]["document"]["step_content"] = ""
            candidate["plan_context_refs"] = {"step-1": [context["context_id"]]}
            delegate = app.tasks
            class PublicTaskOperations:
                __slots__ = ()
                def validate_package(self, package, *, expected_origin=None):
                    return delegate.validate_package(package, expected_origin=expected_origin)
                def import_package(self, package):
                    return delegate.import_package(package)
                def delete(self, task_id):
                    return delegate.delete(task_id)
            app.planning.tasks = PublicTaskOperations()
            ready = app.dispatch("plan.generation.parse", {"generation_id": generated["generation_id"], "response_text": json.dumps(candidate)})
            self.assertEqual(ready["status"], "READY")
            imported = app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            step = app.repo.steps(imported["task_id"])[0]
            copied = app.repo.list_step_contexts(step["step_id"])
            self.assertEqual(len(copied), 1)
            self.assertNotEqual(copied[0]["context_id"], context["context_id"])
            self.assertEqual(copied[0]["name"], "旧页面")
            imported_capture = app.repo.get_step_context_capture(copied[0]["context_id"],copied[0]["captures"][0]["capture_id"])
            imported_second = app.repo.get_step_context_capture(copied[0]["context_id"],copied[0]["captures"][1]["capture_id"])
            self.assertEqual(imported_capture["items"][0]["content"], "before")
            self.assertEqual(imported_second['items'][0]['content'],'second')
            self.assertEqual(imported_second['views'][0]['title'],'second preview')
            self.assertEqual(imported_capture["source_page"], "planning_import")
            repeated = app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            repeated_step = app.repo.steps(repeated["task_id"])[0]
            self.assertNotEqual(step["step_id"], repeated_step["step_id"])
            repeated_groups = app.repo.list_step_contexts(repeated_step["step_id"])
            self.assertNotEqual(copied[0]["context_id"], repeated_groups[0]["context_id"])
            app.tasks.delete(imported["task_id"])
            self.assertEqual(app.repo.steps(repeated["task_id"])[0]["step_id"], repeated_step["step_id"])
            self.assertEqual([row["task_id"] for row in app.planning.generation_imports(generated["generation_id"])], [imported["task_id"], repeated["task_id"]])

    def test_generation_rejects_foreign_context_reference(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            generated = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": 1, "channel": "web_chat"})
            candidate = package()
            candidate["plan_context_refs"] = {"step-1": ["unknown-context"]}
            with self.assertRaises(TaskError) as error:
                app.dispatch("plan.generation.parse", {"generation_id": generated["generation_id"], "response_text": json.dumps(candidate)})
            self.assertIn("unknown-context", str(error.exception))

    def test_generation_context_import_failure_removes_partial_task(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            captured = app.planning.contexts.add_context(plan["plan_id"], 1, "playwright.page", "页面", "", "session", [{"kind": "text", "content": "x"}])
            generated = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": captured["plan"]["revision"], "channel": "web_chat"})
            candidate = package()
            candidate["plan_context_refs"] = {"step-1": [captured["context"]["context_id"]]}
            app.dispatch("plan.generation.parse", {"generation_id": generated["generation_id"], "response_text": json.dumps(candidate)})
            with patch.object(app.repo.repositories.step_contexts, "create_step_context_group", side_effect=TaskError("SAVE_FAILED")):
                with self.assertRaises(TaskError):
                    app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            self.assertEqual(app.repo.list_tasks(), [])

    def test_generation_receipt_failure_removes_imported_task(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            generated = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": 1, "channel": "web_chat"})
            app.dispatch("plan.generation.parse", {"generation_id": generated["generation_id"], "response_text": json.dumps(package())})
            with patch.object(app.planning.generations, "mark_imported", side_effect=TaskError("SAVE_FAILED")):
                with self.assertRaises(TaskError):
                    app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            self.assertEqual(app.repo.list_tasks(), [])

    def test_repeat_import_failure_preserves_previous_task_and_receipt(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            generated = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": 1, "channel": "web_chat"})
            app.dispatch("plan.generation.parse", {"generation_id": generated["generation_id"], "response_text": json.dumps(package())})
            first = app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            original_mark = app.planning.generations.mark_imported
            def persist_then_fail(generation_id, task_id):
                original_mark(generation_id, task_id)
                raise TaskError("SAVE_FAILED")
            with patch.object(app.planning.generations, "mark_imported", side_effect=persist_then_fail):
                with self.assertRaises(TaskError):
                    app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            self.assertEqual([task["task_id"] for task in app.repo.list_tasks()], [first["task_id"]])
            self.assertEqual([row["task_id"] for row in app.planning.generation_imports(generated["generation_id"])], [first["task_id"]])
            self.assertEqual(app.planning.generation_get(generated["generation_id"])["imported_task_id"], first["task_id"])

    def test_repeat_context_copy_failure_rolls_back_only_new_import(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            captured = app.planning.contexts.add_context(plan["plan_id"], 1, "playwright.page", "Page", "frozen", "s", [{"kind": "text", "content": "one"}])
            plan = captured["plan"]
            appended = app.planning.contexts.append_capture(plan["plan_id"], plan["revision"], captured["context"]["context_id"], {"items": [{"kind": "text", "content": "two"}], "views": []}, request={}, include_view=False)
            generated = app.dispatch("plan.generate", {"plan_id": appended["plan"]["plan_id"], "expected_revision": appended["plan"]["revision"], "channel": "web_chat"})
            candidate = package()
            candidate["steps"][0]["document"]["step_content"] = ""
            candidate["plan_context_refs"] = {"step-1": [captured["context"]["context_id"]]}
            app.dispatch("plan.generation.parse", {"generation_id": generated["generation_id"], "response_text": json.dumps(candidate)})
            first = app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            real_append = app.repo.repositories.step_contexts.append_step_context_capture
            calls = 0
            def fail_second_capture(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise TaskError("SAVE_FAILED", "midway through frozen captures")
                return real_append(*args, **kwargs)
            with patch.object(app.repo.repositories.step_contexts, "append_step_context_capture", side_effect=fail_second_capture):
                with self.assertRaises(TaskError):
                    app.dispatch("plan.generation.import", {"generation_id": generated["generation_id"]})
            self.assertEqual([item["task_id"] for item in app.repo.list_tasks()], [first["task_id"]])
            self.assertEqual(app.planning.generation_imports(generated["generation_id"])[0]["task_id"], first["task_id"])
            self.assertEqual(app.repo.query("SELECT COUNT(*) AS count FROM step_contexts")[0]["count"], 1)
            self.assertEqual(app.repo.query("SELECT COUNT(*) AS count FROM steps")[0]["count"], 1)

    def test_ai_draft_allows_empty_code_but_rejects_invalid_nonempty_code(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            draft = package()
            draft["steps"][0]["document"]["step_content"] = ""
            self.assertEqual(app.tasks.validate_package(draft)["steps"][0]["document"]["step_content"], "")
            draft["steps"][0]["document"]["step_content"] = "return True"
            with self.assertRaises(TaskError):
                app.tasks.validate_package(draft)

    def test_empty_draft_cannot_be_manually_confirmed(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            draft = package()
            draft["steps"][0]["document"]["step_content"] = ""
            task = app.import_task(draft)
            step = app.repo.steps(task["task_id"])[0]
            with self.assertRaises(TaskError):
                app.confirm_step_manual(step["step_id"], step["content_hash"])
            with self.assertRaises(TaskError):
                app.create_run(task["task_id"])
            with self.assertRaises(TaskError):
                app.trial_step(step["step_id"], {}, "empty-draft-trial")

    def test_plan_search_and_adjacent_selection(self):
        from taskweave.desktop.planning import filter_plans, next_plan_id

        plans = [
            {"plan_id": "a", "name": "登录", "plan_description": "打开门户"},
            {"plan_id": "b", "name": "账单", "plan_description": "TiDB 核对"},
            {"plan_id": "c", "name": "导出", "plan_description": "下载文件"},
        ]
        self.assertEqual([p["plan_id"] for p in filter_plans(plans, "tidb")], ["b"])
        self.assertEqual(next_plan_id(plans, "b"), "c")
        self.assertEqual(next_plan_id(plans, "c"), "b")
        self.assertEqual(next_plan_id(plans, "a"), "b")

    def test_planning_prompt_prefers_importable_drafts_for_local_gaps(self):
        from taskweave.application.prompts import PLAN_RULES

        self.assertIn("step_content 为空", PLAN_RULES)
        self.assertIn("待补充：", PLAN_RULES)
        self.assertIn("plan_context_refs", PLAN_RULES)
        self.assertIn("只有整个规划", PLAN_RULES)

    def test_preview_rows_distinguish_unwritten_and_written_steps(self):
        from taskweave.desktop.planning import candidate_step_rows

        candidate = package()
        candidate["steps"].append(json.loads(json.dumps(candidate["steps"][0])))
        candidate["steps"][1]["key"] = "step-2"
        candidate["steps"][1]["document"]["step_content"] = ""
        candidate["plan_context_refs"] = {"step-2": ["ctx-1"]}
        rows = candidate_step_rows(candidate, {"ctx-1": "合约页"})
        self.assertEqual([row["status"] for row in rows], ["待调试", "待编写"])
        self.assertEqual(rows[1]["context_names"], ["合约页"])

    def test_plan_list_has_search_and_delete_without_result_count(self):
        from taskweave.desktop.planning import PlanningPage

        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [[{"plan_id": "p1", "name": "合同", "revision": 1} ], [], {"plan_id": "p1"}]
            button = MagicMock()
            page = PlanningPage(controller, PlanningPageState(plan_id="p1"), button, AsyncMock(), AsyncMock(), AsyncMock())
            page.editor = AsyncMock()
            with patch("taskweave.desktop.planning.ui") as fake_ui:
                fake_ui.input.return_value.props.return_value.classes.return_value.value = ""
                fake_ui.select.return_value.value = ""
                fake_ui.select.return_value.classes.return_value.value = ""
                await page.render()
            labels = [call.args[0] for call in fake_ui.label.call_args_list]
            self.assertIn("规划", labels)
            self.assertIn("搜索规划", [call.args[0] for call in fake_ui.input.call_args_list])
            titles = [call.args[0] for call in button.call_args_list]
            self.assertIn("新建规划", titles)
            self.assertIn("合同", titles)
            props = [entry.args[0] for entry in button.return_value.props.call_args_list]
            self.assertTrue(any("icon=delete" in value for value in props))

        from taskweave.desktop.state import PlanningPageState
        from unittest.mock import AsyncMock, MagicMock, patch
        asyncio.run(scenario())

    def test_plan_context_dialog_is_plugin_schema_driven(self):
        from taskweave.desktop.contexts import context_hidden_parameters, context_surface_defaults

        schema = {
            "type": "object", "properties": {"url": {}, "scope": {}, "token": {}},
            "x-taskweave-context-targets": {
                "hide_parameters_when_selected": True,
                "keep_parameters_when_selected": ["token"],
            },
            "x-taskweave-context-surface-defaults": {"planning": {"scope": "viewport", "unknown": "ignored"}},
        }
        self.assertEqual(context_hidden_parameters(schema, True), {"url", "scope"})
        self.assertEqual(context_hidden_parameters(schema, False), set())
        self.assertEqual(context_surface_defaults(schema, "planning"), {"scope": "viewport"})

    def test_plan_materials_include_notes_and_context_order(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch('plan.create', {'name': 'P'})
            plan = app.dispatch('plan.update', {
                'plan_id': plan['plan_id'], 'expected_revision': 1, 'name': 'P',
                'plan_description': '目标', 'plan_notes': '按上下文顺序执行',
                'plugin_ids': [], 'environment_id': None,
            })
            materials = app.planning._materials(plan)
            self.assertEqual(materials['plan']['plan_notes'], '按上下文顺序执行')
            self.assertTrue(all('views' not in item for item in materials['contexts']))

    def test_crud_revision_and_web_generation_import_creates_independent_tasks(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "核对计划"})
            updated = app.dispatch("plan.update", {"plan_id": plan["plan_id"], "expected_revision": 1, "name": "核对计划", "plan_description": "生成一步任务", "plugin_ids": [], "environment_id": None})
            self.assertEqual(updated["revision"], 2)
            with self.assertRaises(TaskError) as conflict:
                app.dispatch("plan.update", {"plan_id": plan["plan_id"], "expected_revision": 1, "name": "旧编辑"})
            self.assertEqual(conflict.exception.code, "EDIT_CONFLICT")
            generation = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": 2, "channel": "web_chat"})
            self.assertIn("taskweave-task-2", generation["prompt"])
            reply = json.dumps(package(), ensure_ascii=False)
            ready = app.dispatch("plan.generation.parse", {"generation_id": generation["generation_id"], "response_text": reply})
            self.assertEqual(ready["status"], "READY")
            first = app.dispatch("plan.generation.import", {"generation_id": generation["generation_id"]})
            second = app.dispatch("plan.generation.import", {"generation_id": generation["generation_id"]})
            self.assertNotEqual(first["task_id"], second["task_id"])
            self.assertEqual([item["task_id"] for item in app.planning.generation_imports(generation["generation_id"])], [first["task_id"], second["task_id"]])
            self.assertEqual(app.planning.generations.generation(generation["generation_id"])["imported_task_id"], first["task_id"])
            self.assertEqual(app.repo.steps(first["task_id"])[0]["validation_state"], "DRAFT")

    def test_invalid_web_reply_never_creates_task(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            generation = app.dispatch("plan.generate", {"plan_id": plan["plan_id"], "expected_revision": 1, "channel": "web_chat"})
            before = len(app.repo.list_tasks())
            with self.assertRaises(TaskError):
                app.dispatch("plan.generation.parse", {"generation_id": generation["generation_id"], "response_text": "{bad"})
            self.assertEqual(len(app.repo.list_tasks()), before)

    def test_web_plan_recovers_unescaped_python_quotes_inside_step_content(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch("plan.create", {"name": "P"})
            generation = app.dispatch("plan.generate", {
                "plan_id": plan["plan_id"], "expected_revision": 1, "channel": "web_chat",
            })
            candidate = package()
            candidate["steps"][0]["document"]["step_content"] = (
                'async def run(ctx, inputs):\n'
                '    role = "operator"\n'
                '    return ctx.result(data={"role": role})\n'
            )
            reply = json.dumps(candidate, ensure_ascii=False)
            reply = reply.replace(r'\"operator\"', '"operator"').replace(r'\"role\"', '"role"')
            reply = reply.replace('    role', r'\u0020\u0020\u0020\u0020role')
            ready = app.dispatch("plan.generation.parse", {
                "generation_id": generation["generation_id"], "response_text": reply,
            })
            self.assertEqual(ready["status"], "READY")
            self.assertEqual(
                ready["candidate"]["steps"][0]["document"]["step_content"],
                candidate["steps"][0]["document"]["step_content"],
            )
