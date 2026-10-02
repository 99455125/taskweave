"""Planning page dependencies and stale-save callbacks are explicit."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.state import PlanningPageState
from taskweave.desktop.planning import PlanningPage, _refresh_organization_controls_for_view, generation_summary, mutate_planning_capture


class PlanningPageTests(unittest.TestCase):
    def test_materials_and_history_load_only_on_first_open_and_keep_drafts(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch('plan.create', {'name': 'lazy planning'})
            client = Client(page('/planning-lazy'))
            async def scenario():
                with client:
                    controller = DesktopController(app)
                    controller.call = AsyncMock(wraps=controller.call)
                    planning = PlanningPage(controller, PlanningPageState(plan_id=plan['plan_id']),
                        lambda title, callback, **kw: ui.button(title, on_click=callback), AsyncMock(), AsyncMock(), AsyncMock())
                    await planning.editor(plan)
                    operations = [call.args[0] for call in controller.call.await_args_list]
                    self.assertNotIn('environment.list', operations)
                    self.assertNotIn('capabilities', operations)
                    materials = next(e for e in client.elements.values() if 'tw-plan-materials' in e.classes)
                    history = next(e for e in client.elements.values() if 'tw-plan-history' in e.classes)
                    self.assertFalse(materials.visible)
                    self.assertFalse(history.visible)
                    self.assertFalse(materials.default_slot.children)
                    self.assertFalse(history.default_slot.children)
                    name = next(e for e in client.elements.values() if getattr(e, 'label', '') == '规划名称')
                    name.value = '尚未保存的名称'
                    await planning.state.save_callback()
                    self.assertEqual(app.planning.get(plan['plan_id'])['name'], name.value)
                    tabs = next(e for e in client.elements.values() if 'tw-task-tabs' in e.classes)
                    select = tabs._change_handlers[-1]
                    controller.call.reset_mock()
                    await select(SimpleNamespace(value='能力与素材'))
                    controls = list(materials.default_slot.children)
                    self.assertTrue(controls)
                    self.assertEqual(name.value, '尚未保存的名称')
                    self.assertEqual([c.args[0] for c in controller.call.await_args_list].count('environment.list'), 1)
                    await select(SimpleNamespace(value='基础配置'))
                    await select(SimpleNamespace(value='能力与素材'))
                    self.assertEqual(materials.default_slot.children, controls)
                    self.assertEqual([c.args[0] for c in controller.call.await_args_list].count('environment.list'), 1)
                    controller.call.reset_mock()
                    await select(SimpleNamespace(value='生成记录'))
                    await select(SimpleNamespace(value='基础配置'))
                    await select(SimpleNamespace(value='生成记录'))
                    self.assertEqual([c.args[0] for c in controller.call.await_args_list].count('plan.generation.list'), 1)
                    await select(SimpleNamespace(value='基础配置'))
                    controller.call.reset_mock()
                    await planning._refresh_generation_history(planning._planning_identity())
                    controller.call.assert_not_awaited()
                    await select(SimpleNamespace(value='生成记录'))
                    controller.call.assert_awaited_once_with('plan.generation.list', plan_id=plan['plan_id'])
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_late_materials_response_does_not_build_for_another_plan(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.dispatch('plan.create', {'name': 'old plan'})
            client = Client(page('/planning-late-materials'))
            async def scenario():
                with client:
                    controller = DesktopController(app)
                    original = controller.call
                    entered, release = asyncio.Event(), asyncio.Event()
                    async def call(operation, **params):
                        if operation == 'environment.list':
                            entered.set()
                            await release.wait()
                        return await original(operation, **params)
                    controller.call = call
                    state = PlanningPageState(plan_id=plan['plan_id'])
                    planning = PlanningPage(controller, state,
                        lambda title, callback, **kw: ui.button(title, on_click=callback), AsyncMock(), AsyncMock(), AsyncMock())
                    await planning.editor(plan)
                    tabs = next(e for e in client.elements.values() if 'tw-task-tabs' in e.classes)
                    materials = next(e for e in client.elements.values() if 'tw-plan-materials' in e.classes)
                    pending = asyncio.create_task(tabs._change_handlers[-1](SimpleNamespace(value='能力与素材')))
                    await asyncio.wait_for(entered.wait(), 2)
                    self.assertFalse(materials.default_slot.children)
                    state.plan_id = 'another-plan'
                    state.generation += 1
                    release.set()
                    await pending
                    self.assertFalse(materials.default_slot.children)
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_capture_label_reorder_delete_refresh_only_group_and_preserve_all_form_drafts(self):
        async def scenario():
            plan = {"plan_id": "p1", "revision": 1, "name": "saved"}
            context = {"context_id": "ctx"}
            capture = {"capture_id": "cap"}
            drafts = {
                "name": "name draft", "plan_description": "description draft",
                "plan_notes": "notes draft", "environment_id": "env-draft",
                "plugin_ids": ["plugin-draft"],
            }
            original_drafts = dict(drafts)
            lock = asyncio.Lock()
            identity = ["p1"]
            synced = []
            cards = SimpleNamespace(is_active=lambda: True, sync_group=synced.append)
            controller = AsyncMock()
            operations = [
                ("plan.context.capture.label", {"label": "新标签"}),
                ("plan.context.capture.reorder", {"direction": "up"}),
                ("plan.context.capture.delete", {}),
            ]
            for revision, (operation, params) in enumerate(operations, 2):
                group = {"context_id": "ctx", "revision": revision, "captures": [{"capture_id": "cap"}]}
                controller.call.return_value = {"plan_id": "p1", "revision": revision, "contexts": [group]}
                self.assertTrue(await mutate_planning_capture(
                    controller, plan, context, capture, operation, lock,
                    lambda: identity[0] == "p1", cards, **params,
                ))
                self.assertEqual(synced[-1], group)
                self.assertEqual(plan["revision"], revision)
                self.assertEqual(drafts, original_drafts)
            self.assertEqual([call.args[0] for call in controller.call.await_args_list],
                             [operation for operation, _ in operations])
            self.assertEqual(controller.call.await_args_list[0].kwargs["expected_revision"], 1)
            self.assertEqual(controller.call.await_args_list[1].kwargs["expected_revision"], 2)

        asyncio.run(scenario())

    def test_capture_mutation_failure_keeps_current_plan_and_draft(self):
        async def scenario():
            plan = {"plan_id": "p1", "revision": 4}
            draft = {"name": "未保存", "plan_notes": "保留这段说明"}
            cards = SimpleNamespace(is_active=lambda: True, sync_group=MagicMock())
            controller = AsyncMock()
            controller.call.side_effect = OSError("保存失败")
            with self.assertRaisesRegex(OSError, "保存失败"):
                await mutate_planning_capture(
                    controller, plan, {"context_id": "ctx"}, {"capture_id": "cap"},
                    "plan.context.capture.label", asyncio.Lock(), lambda: True, cards, label="新名",
                )
            self.assertEqual(plan, {"plan_id": "p1", "revision": 4})
            self.assertEqual(draft, {"name": "未保存", "plan_notes": "保留这段说明"})
            cards.sync_group.assert_not_called()
            controller.call.assert_awaited_once_with(
                "plan.context.capture.label", plan_id="p1", expected_revision=4,
                context_id="ctx", capture_id="cap", label="新名",
            )

        asyncio.run(scenario())

    def test_late_capture_mutation_does_not_sync_a_different_planning_page(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            plan = {"plan_id": "p1", "revision": 4}
            identity = ["p1"]
            async def mutate(*args, **kwargs):
                entered.set()
                await release.wait()
                return {"plan_id": "p1", "revision": 5, "contexts": [{"context_id": "ctx"}]}
            controller = SimpleNamespace(call=AsyncMock(side_effect=mutate))
            cards = SimpleNamespace(is_active=lambda: identity[0] == "p1", sync_group=MagicMock())
            pending = asyncio.create_task(mutate_planning_capture(
                controller, plan, {"context_id": "ctx"}, {"capture_id": "cap"},
                "plan.context.capture.delete", asyncio.Lock(), lambda: identity[0] == "p1", cards,
            ))
            await entered.wait()
            identity[0] = "p2"
            release.set()
            self.assertFalse(await pending)
            self.assertEqual(plan, {"plan_id": "p1", "revision": 4})
            cards.sync_group.assert_not_called()

        asyncio.run(scenario())

    def test_unready_latest_candidate_is_diagnostic_only_and_formatted(self):
        summary = generation_summary({
            "generation_id": "g-latest", "created_at": "2026-09-27T06:30:00+00:00",
            "channel": "web_chat", "status": "BLOCKED", "candidate": None,
            "diagnostics": [{"code": "PLAN_INFORMATION_MISSING", "message": "缺少合同编号"}],
        })
        self.assertFalse(summary["can_import"])
        self.assertEqual(summary["channel"], "网页 Chat")
        self.assertEqual(summary["status"], "信息不足")
        self.assertNotIn("web_chat", summary["channel"])
        self.assertNotIn("BLOCKED", summary["status"])
        self.assertIn("缺少合同编号", summary["diagnostics"][0])

    def test_import_generation_allows_two_independent_imports_and_refreshes_candidate(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                {"task_id": "task-a"}, {"task_id": "task-b"},
            ]
            page = PlanningPage(controller, PlanningPageState(plan_id="p1"), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            page._refresh_generation_history = AsyncMock()
            page._refresh_candidate_summary = AsyncMock()
            identity = page._planning_identity()

            first = await page.import_generation("g1", identity)
            second = await page.import_generation("g1", identity)

            self.assertEqual([first["task_id"], second["task_id"]], ["task-a", "task-b"])
            self.assertEqual([call.args for call in controller.call.await_args_list], [
                ("plan.generation.import",), ("plan.generation.import",),
            ])
            page._refresh_candidate_summary.assert_has_awaits([unittest.mock.call(identity), unittest.mock.call(identity)])

        with patch("taskweave.desktop.planning.ui.notify"):
            asyncio.run(scenario())

    def test_latest_generation_detail_response_does_not_update_another_plan(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            state = PlanningPageState(plan_id="p1")
            controller = AsyncMock()

            async def call(operation, **kwargs):
                if operation == "plan.generation.list":
                    entered.set()
                    await release.wait()
                    return [{"generation_id": "old-latest"}]
                raise AssertionError("Stale candidate detail must not be fetched")

            controller.call.side_effect = call
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            identity = page._planning_identity()
            pending = asyncio.create_task(page.latest_generation_for_view("p1", identity))
            await entered.wait()
            state.plan_id = "p2"
            release.set()
            is_current, generation = await pending
            self.assertFalse(is_current)
            self.assertIsNone(generation)
            controller.call.assert_awaited_once_with("plan.generation.list", plan_id="p1")

        asyncio.run(scenario())

    def test_deleted_category_refreshes_authoritative_cache_and_future_writes(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        async def scenario(home):
            with Application(home) as app:
                category = app.dispatch("organization.category.create", {"name": "即将删除"})
                other = app.dispatch("organization.category.create", {"name": "保留分类"})
                plan = app.dispatch("plan.create", {"name": "分类缓存回归"})
                app.dispatch("organization.metadata.set", {"entity": "plan", "entity_id": plan["plan_id"],
                    "is_favorite": True, "category_id": category["category_id"]})
                plan = app.dispatch("plan.get", {"plan_id": plan["plan_id"]})
                controller = DesktopController(app)
                page = PlanningPage(controller, PlanningPageState(plan_id=plan["plan_id"]), MagicMock(),
                    AsyncMock(), AsyncMock(), AsyncMock())
                page._organization[plan["plan_id"]] = {"is_favorite": 1, "category_id": category["category_id"]}
                app.dispatch("organization.category.delete", {"category_id": category["category_id"]})
                identity = page._planning_identity()
                category_filter, search, plan_list = (MagicMock(value="", is_deleted=False),
                    MagicMock(value="draft search", is_deleted=False), MagicMock(is_deleted=False))
                header = MagicMock(is_deleted=False)
                page._header_category_select = header
                plans = [plan]

                def render(category_options, _filter_options):
                    page._sync_plan_organizations(plans)
                    header.set_options(category_options, value=page._organization[plan["plan_id"]]["category_id"] or "")

                page._render_plan_list = MagicMock()
                result = await _refresh_organization_controls_for_view(controller, identity,
                    page._planning_identity, category_filter, search, plan_list, plans, render)
                self.assertTrue(result)
                self.assertIsNone(page._organization[plan["plan_id"]]["category_id"])
                self.assertEqual(header.set_options.call_args.kwargs["value"], "")
                self.assertNotIn(category["category_id"], header.set_options.call_args.args[0])
                await page.toggle_favorite(plan)
                await page.set_organization(plan, category_id=other["category_id"])
                saved = app.dispatch("plan.get", {"plan_id": plan["plan_id"]})
                self.assertEqual(saved["is_favorite"], 0)
                self.assertEqual(saved["category_id"], other["category_id"])

        with tempfile.TemporaryDirectory() as home:
            asyncio.run(scenario(home))

    def test_category_refresh_updates_header_options_without_touching_plan_draft(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                [{"category_id": "new", "name": "新建分类"}],
                [{"plan_id": "p1", "is_favorite": 1, "category_id": "new"}],
            ]
            identity = ("p1", 3, "planning", 8)
            category_filter = MagicMock(value="")
            search = MagicMock(value="本地未保存搜索")
            plan_list = MagicMock(is_deleted=False)
            for control in (category_filter, search):
                control.is_deleted = False
            plans = [{"plan_id": "p1", "is_favorite": 1, "category_id": None}]
            header_select = MagicMock(is_deleted=False)
            seen = []
            def render(category_options, filter_options):
                seen.append((category_options, filter_options, search.value, plans[0]["category_id"]))
                header_select.set_options(category_options, value=plans[0]["category_id"] or "")
            result = await _refresh_organization_controls_for_view(
                controller, identity, lambda: identity, category_filter, search,
                plan_list, plans, lambda categories, filters: (plans.__setitem__(0, {
                    **plans[0], "category_id": "new"}), render(categories, filters)),
            )
            self.assertTrue(result)
            self.assertIn("new", seen[0][0])
            self.assertEqual(seen[0][2], "本地未保存搜索")
            self.assertEqual(seen[0][3], "new")
            category_filter.set_options.assert_called_once()
            self.assertEqual(header_select.set_options.call_args.args[0]["new"], "新建分类")
            self.assertEqual(header_select.set_options.call_args.kwargs["value"], "new")
        asyncio.run(scenario())

    def test_sequential_favorite_and_category_updates_share_authoritative_metadata(self):
        async def scenario():
            plan = {"plan_id": "p1", "is_favorite": 0, "category_id": None}
            controller = AsyncMock()
            page = PlanningPage(controller, PlanningPageState(plan_id="p1"), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            favorite_button = MagicMock(is_deleted=False)
            page._header_favorite_button = favorite_button
            await page.set_organization(plan, favorite=True)
            self.assertEqual(favorite_button.text, "★")
            await page.set_organization(plan, category_id="work")
            self.assertEqual(favorite_button.text, "★")
            writes = [call.kwargs for call in controller.call.await_args_list if call.args[0] == "organization.metadata.set"]
            self.assertEqual([(write["is_favorite"], write["category_id"]) for write in writes], [(1, None), (1, "work")])
            self.assertEqual(page._organization["p1"], {"is_favorite": 1, "category_id": "work"})
        asyncio.run(scenario())

    def test_late_organization_refresh_does_not_touch_deleted_view_controls(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = [("planning", 4)]
            controller = AsyncMock()

            async def call(operation):
                self.assertEqual(operation, "organization.category.list")
                entered.set()
                await release.wait()
                return []

            controller.call.side_effect = call
            category_filter = MagicMock(value="")
            search = MagicMock(value="draft B")
            plan_list = MagicMock(is_deleted=False)
            category_filter.is_deleted = False
            search.is_deleted = False
            plans = [{"plan_id": "p2", "name": "B"}]
            render = MagicMock()
            pending = asyncio.create_task(_refresh_organization_controls_for_view(
                controller, identity[0], lambda: identity[0], category_filter,
                search, plan_list, plans, render,
            ))
            await entered.wait()
            identity[0] = ("planning", 5)
            category_filter.is_deleted = True
            release.set()
            result = await pending

            self.assertFalse(result)
            category_filter.set_options.assert_not_called()
            plan_list.clear.assert_not_called()
            render.assert_not_called()
            self.assertEqual(plans, [{"plan_id": "p2", "name": "B"}])

        asyncio.run(scenario())

    def test_organization_update_preserves_unsaved_plan_draft_and_selection(self):
        async def scenario():
            plan = {"plan_id": "p1", "name": "已保存名称", "plan_description": "已保存说明", "revision": 7}
            draft = {
                "name": "未保存名称",
                "plan_description": "未保存说明",
                "environment_id": "env-draft",
                "plugin_ids": ["playwright"],
            }
            controller = AsyncMock()
            controller.call.return_value = {**plan, **draft, "revision": 8}
            state = PlanningPageState(plan_id="p1")
            save_calls = []

            async def save_draft():
                save_calls.append(dict(draft))
                await controller.call("plan.update", plan_id="p1", **draft)

            state.save_callback = save_draft
            repaint = AsyncMock()
            page = PlanningPage(controller, state, MagicMock(), repaint, AsyncMock(), AsyncMock())
            page._render_plan_list = MagicMock()

            await page.set_organization(plan, favorite=True, category_id="work")

            self.assertEqual(state.plan_id, "p1")
            self.assertIs(state.save_callback, save_draft)
            repaint.assert_not_awaited()
            self.assertEqual(save_calls, [])
            self.assertEqual(plan["is_favorite"], True)
            self.assertEqual(plan["category_id"], "work")
            page._render_plan_list.assert_called_once_with()

            await state.save_callback()
            self.assertEqual(save_calls, [draft])
            controller.call.assert_any_await("plan.update", plan_id="p1", **draft)

        asyncio.run(scenario())

    def test_organization_save_failure_keeps_plan_form_and_draft_callback(self):
        async def scenario():
            plan = {"plan_id": "p1", "is_favorite": 0, "category_id": None}
            controller = AsyncMock()
            controller.call.side_effect = OSError("category store unavailable")
            state = PlanningPageState(plan_id="p1")
            draft = {"name": "UNSAVED", "plan_description": "UNSAVED DESCRIPTION"}
            async def save_draft():
                return dict(draft)
            state.save_callback = save_draft
            repaint = AsyncMock()
            page = PlanningPage(controller, state, MagicMock(), repaint, AsyncMock(), AsyncMock())
            page._render_plan_list = MagicMock()

            with patch("taskweave.desktop.planning.ui.notify") as notify:
                result = await page.set_organization(plan, True, "work")

            self.assertFalse(result)
            self.assertIs(state.save_callback, save_draft)
            self.assertEqual(await state.save_callback(), draft)
            self.assertEqual(plan["is_favorite"], 0)
            self.assertIsNone(plan["category_id"])
            page._render_plan_list.assert_called_once_with()
            repaint.assert_not_awaited()
            notify.assert_called_once()

        asyncio.run(scenario())

    def test_late_organization_response_does_not_repaint_another_selected_plan(self):
        async def scenario():
            started = asyncio.Event()
            release = asyncio.Event()
            controller = AsyncMock()

            async def call(operation, **kwargs):
                if operation == "organization.metadata.set":
                    started.set()
                    await release.wait()

            controller.call.side_effect = call
            state = PlanningPageState(plan_id="p1", save_callback=AsyncMock())
            repaint = AsyncMock()
            page = PlanningPage(controller, state, MagicMock(), repaint, AsyncMock(), AsyncMock())
            page._render_plan_list = MagicMock()
            original = {"plan_id": "p1", "is_favorite": False, "category_id": None}

            pending = asyncio.create_task(page.set_organization(original, True, "work"))
            await started.wait()
            state.plan_id = "p2"
            release.set()
            await pending

            self.assertEqual(state.plan_id, "p2")
            self.assertEqual(original["is_favorite"], True)
            repaint.assert_not_awaited()
            self.assertIsNotNone(state.save_callback)

        asyncio.run(scenario())

    def test_generate_refreshes_current_generation_history_before_preview(self):
        async def scenario():
            events = []
            plan = {"plan_id": "p1", "revision": 4}
            controller = AsyncMock()
            controller.call.return_value = {"generation_id": "g1", "status": "READY", "candidate": {}}
            state = PlanningPageState(plan_id="p1", generation=2)
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", 8))
            page._refresh_generation_history = AsyncMock(side_effect=lambda identity: events.append(("history", identity)))
            page._refresh_candidate_summary = AsyncMock(side_effect=lambda identity: events.append(("summary", identity)))
            page.preview = AsyncMock(side_effect=lambda generation, identity=None: events.append(("preview", identity)))

            await page.generate(plan, "api")

            self.assertEqual([kind for kind, _ in events], ["history", "summary", "preview"])
            self.assertEqual(events[0][1], ("p1", 2, "planning", 8))
            self.assertEqual(events[1][1], events[0][1])

        asyncio.run(scenario())

    def test_late_generation_for_previous_plan_does_not_update_current_view(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            page_context = [8]
            state = PlanningPageState(plan_id="p1", generation=2)
            controller = AsyncMock()

            async def call(operation, **kwargs):
                entered.set()
                await release.wait()
                return {"generation_id": "g1", "status": "READY", "candidate": {}}

            controller.call.side_effect = call
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", page_context[0]))
            page._refresh_generation_history = AsyncMock()
            page.preview = AsyncMock()
            pending = asyncio.create_task(page.generate({"plan_id": "p1", "revision": 4}, "api"))
            await entered.wait()
            state.plan_id, state.generation = "p2", 3
            page_context[0] = 9
            release.set()
            await pending

            page._refresh_generation_history.assert_not_awaited()
            page.preview.assert_not_awaited()

        asyncio.run(scenario())

    def test_parse_and_import_refresh_history_only_for_originating_plan(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                {"generation_id": "g1", "status": "READY", "candidate": {"steps": []}},
                {"task_id": "t1"},
            ]
            state = PlanningPageState(plan_id="p1", generation=2)
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", 8))
            identity = page._planning_identity()
            history = AsyncMock()
            page._refresh_generation_history = history
            page.preview = AsyncMock()
            dialog = MagicMock()
            await page.parse_generation("g1", "{}", identity, dialog.close)
            self.assertEqual(history.await_count, 1)
            page.preview.assert_awaited_once()
            receipts = AsyncMock()
            with patch("taskweave.desktop.planning.ui.notify") as notify:
                await page.import_generation("g1", identity, receipts)
            self.assertEqual(history.await_count, 2)
            receipts.assert_awaited_once()
            notify.assert_called_once_with("已创建新任务：t1", type="positive")

        asyncio.run(scenario())

    def test_failed_parse_refreshes_diagnostics_and_preserves_original_error(self):
        async def scenario():
            original = TaskError("MODEL_JSON_INVALID", "bad JSON")
            controller = AsyncMock()
            controller.call.side_effect = original
            state = PlanningPageState(plan_id="p1", generation=2)
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", 8))
            identity = page._planning_identity()
            page._refresh_generation_history = AsyncMock()

            with self.assertRaises(TaskError) as raised:
                await page.parse_generation("g1", "invalid JSON", identity)

            self.assertIs(raised.exception, original)
            page._refresh_generation_history.assert_awaited_once_with(identity)

            page._refresh_generation_history.side_effect = OSError("history refresh failed")
            with self.assertLogs("taskweave.desktop.planning", level="WARNING"):
                with self.assertRaises(TaskError) as raised_after_refresh_failure:
                    await page.parse_generation("g1", "invalid JSON", identity)
            self.assertIs(raised_after_refresh_failure.exception, original)

        asyncio.run(scenario())

    def test_failed_generate_refreshes_history_and_preserves_original_error(self):
        async def scenario():
            original = TaskError("MODEL_UNAVAILABLE", "model unavailable")
            controller = AsyncMock()
            controller.call.side_effect = original
            state = PlanningPageState(plan_id="p1", generation=2)
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", 8))
            page._refresh_generation_history = AsyncMock()

            with self.assertRaises(TaskError) as raised:
                await page.generate({"plan_id": "p1", "revision": 3}, "api")

            self.assertIs(raised.exception, original)
            page._refresh_generation_history.assert_awaited_once_with(page._planning_identity())

        asyncio.run(scenario())

    def test_failed_parse_for_previous_plan_does_not_refresh_current_history(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            controller = AsyncMock()

            async def call(*args, **kwargs):
                entered.set()
                await release.wait()
                raise TaskError("MODEL_JSON_INVALID", "bad JSON")

            controller.call.side_effect = call
            state = PlanningPageState(plan_id="p1", generation=2)
            view = [8]
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", view[0]))
            page._refresh_generation_history = AsyncMock()
            identity = page._planning_identity()
            pending = asyncio.create_task(page.parse_generation("g1", "invalid JSON", identity))
            await entered.wait()
            state.plan_id, state.generation = "p2", 3
            view[0] = 9
            release.set()
            with self.assertRaises(TaskError):
                await pending
            page._refresh_generation_history.assert_not_awaited()

        asyncio.run(scenario())

    def test_late_parse_and_import_do_not_refresh_another_plan(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            controller = AsyncMock()

            async def call(operation, **kwargs):
                entered.set()
                await release.wait()
                return {"generation_id": "g1", "status": "READY", "candidate": {"steps": []}}

            controller.call.side_effect = call
            state = PlanningPageState(plan_id="p1", generation=2)
            page_context = [8]
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(), page_identity=lambda: ("planning", page_context[0]))
            page._refresh_generation_history = AsyncMock()
            page.preview = AsyncMock()
            identity = page._planning_identity()
            close_dialog = MagicMock()
            parse_pending = asyncio.create_task(page.parse_generation("g1", "{}", identity, close_dialog))
            await entered.wait()
            state.plan_id, state.generation = "p2", 3
            page_context[0] = 9
            release.set()
            await parse_pending
            page._refresh_generation_history.assert_not_awaited()
            page.preview.assert_not_awaited()
            close_dialog.assert_called_once_with()

            entered.clear()
            release.clear()
            receipts = AsyncMock()
            import_pending = asyncio.create_task(page.import_generation("g1", identity, receipts))
            await entered.wait()
            release.set()
            await import_pending
            receipts.assert_not_awaited()
            page._refresh_generation_history.assert_not_awaited()

        asyncio.run(scenario())

    def test_open_generation_reads_saved_candidate_and_opens_preview(self):
        async def scenario():
            record = {"generation_id": "g1", "status": "IMPORTED", "candidate": {"steps": []}}
            controller = AsyncMock()
            controller.call.return_value = record
            page = PlanningPage(controller, PlanningPageState(plan_id="p1"), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            page.preview = AsyncMock()

            await page.open_generation("g1")

            controller.call.assert_awaited_once_with("plan.generation.get", generation_id="g1")
            page.preview.assert_awaited_once_with(record, page._planning_identity())

        asyncio.run(scenario())

    def test_render_owns_plan_selection_and_search_state(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [[{"plan_id": "p1", "name": "计划"}], [], {"plan_id": "p1"}]
            state = PlanningPageState()
            page = PlanningPage(controller, state, MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            page.editor = AsyncMock()
            with patch("taskweave.desktop.planning.ui") as fake_ui:
                fake_ui.input.return_value.props.return_value.classes.return_value.value = ""
                await page.render()
            self.assertEqual(state.plan_id, "p1")
            self.assertEqual(fake_ui.input.call_args.args[0], "搜索规划")
            controller.call.assert_any_await("plan.get", plan_id="p1")

        asyncio.run(scenario())

    def test_open_saves_existing_draft_before_changing_plan_and_repainting(self):
        async def scenario():
            events = []
            controller = AsyncMock()
            state = PlanningPageState(plan_id="old", save_callback=AsyncMock(side_effect=lambda: events.append("save")))
            navigate = AsyncMock()
            repaint = AsyncMock(side_effect=lambda: events.append("render"))
            page = PlanningPage(controller, state, MagicMock(), repaint, navigate, AsyncMock())

            await page.open("new")

            self.assertEqual(events, ["save", "render"])
            self.assertEqual(state.plan_id, "new")
            controller.call.assert_not_awaited()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
