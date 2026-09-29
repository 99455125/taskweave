"""Plan page: collect plugin evidence and turn a validated candidate into a task."""

import asyncio
import copy
import json
import logging
from datetime import datetime
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.pages.base import Page
from taskweave.desktop.forms import ValueForm
from taskweave.desktop.state import PlanningPageState
from taskweave.desktop.components.organization import CategoryManager
from taskweave.desktop.contexts import (
    render_context_draft_rows, ContextCards, show_context_preview,
    ContextCaptureDraft,
    ContextTargetPicker,
    context_hidden_parameters,
    context_advanced_overrides,
    merge_context_request,
    context_target_options,
    context_view_default,
    context_surface_defaults,
)

logger = logging.getLogger(__name__)
_ORGANIZATION_UNSET = object()
GENERATION_CHANNEL_LABELS = {"api": "大模型 API", "web_chat": "网页 Chat"}
GENERATION_STATUS_LABELS = {
    "GENERATING": "生成中", "READY": "待导入", "IMPORTED": "已导入",
    "FAILED": "生成失败", "PARSE_FAILED": "解析失败", "BLOCKED": "信息不足",
}


def generation_summary(generation):
    """Return the latest candidate's display data without promoting an older result."""
    if not generation:
        return None
    candidate = generation.get("candidate")
    can_import = generation.get("status") in {"READY", "IMPORTED"} and bool(candidate)
    steps = candidate.get("steps", []) if can_import else []
    documents = [item.get("document", item) for item in steps]
    return {
        "generation_id": generation["generation_id"],
        "created_at": short_updated_at(generation.get("created_at")),
        "channel": GENERATION_CHANNEL_LABELS.get(generation.get("channel"), "未知渠道"),
        "status": GENERATION_STATUS_LABELS.get(generation.get("status"), "未就绪"),
        "status_code": generation.get("status"),
        "can_import": can_import,
        "name": (candidate.get("task", {}).get("name") if can_import else None),
        "step_count": len(documents),
        "steps": [{"index": index, "name": step.get("name", "未命名步骤")} for index, step in enumerate(documents[:3], 1)],
        "diagnostics": [
            " · ".join(str(item[key]) for key in ("code", "message") if item.get(key)) if isinstance(item, dict) else str(item)
            for item in generation.get("diagnostics", [])
        ],
    }


def short_updated_at(value):
    if not value:
        return "尚未更新"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return str(value)[:16]



def filter_plans(plans, query, favorite=None, category_id=None):
    query = (query or "").strip().casefold()
    if not query:
        visible = list(plans)
    else:
        visible = [
        plan for plan in plans
        if query in (plan.get("name") or "").casefold()
        or query in (plan.get("plan_description") or "").casefold()
        ]
    if favorite is True:
        visible = [plan for plan in visible if plan.get("is_favorite")]
    if category_id:
        visible = [plan for plan in visible if plan.get("category_id") == category_id]
    return visible


async def _refresh_organization_controls_for_view(controller, expected_identity, current_identity,
                                                  category_filter, search, plan_list, plans, render):
    """Refresh only live controls belonging to the view that requested the update."""
    def current():
        controls = (category_filter, search, plan_list)
        return (
            expected_identity[-2] == "planning"
            and current_identity() == expected_identity
            and all(not control.is_deleted for control in controls)
        )

    if not current():
        return False
    latest_categories = await controller.call("organization.category.list")
    if not current():
        return False
    latest_plans = await controller.call("plan.list")
    if not current():
        return False
    new_category_options = {"": "未分类"} | {item["category_id"]: item["name"] for item in latest_categories}
    new_filter_options = {"": "全部规划", "favorites": "仅收藏"} | {item["category_id"]: item["name"] for item in latest_categories}
    selected_filter = category_filter.value
    plans[:] = latest_plans
    category_filter.set_options(new_filter_options, value=selected_filter if selected_filter in new_filter_options else "")
    render(new_category_options, new_filter_options)
    return True


def next_plan_id(plans, deleted_id):
    ids = [plan["plan_id"] for plan in plans]
    if deleted_id not in ids or len(ids) <= 1:
        return None
    index = ids.index(deleted_id)
    return ids[index + 1] if index + 1 < len(ids) else ids[index - 1]


def candidate_step_rows(candidate, context_labels):
    refs = candidate.get("plan_context_refs", {})
    return [{
        "index": index,
        "document": entry["document"],
        "status": "待调试" if entry["document"]["step_content"].strip() else "待编写",
        "context_names": [context_labels.get(context_id, context_id) for context_id in refs.get(entry["key"], [])],
    } for index, entry in enumerate(candidate["steps"], 1)]


async def mutate_planning_capture(controller, plan, context, capture, operation, lock,
                                  is_current, cards, **params):
    """Persist a capture edit and refresh only its active group card."""
    async with lock:
        if not is_current():
            return False
        updated = await controller.call(
            operation, plan_id=plan["plan_id"], expected_revision=plan["revision"],
            context_id=context["context_id"], capture_id=capture["capture_id"], **params,
        )
        if not is_current():
            return False
        groups = updated.get("contexts")
        if groups is None:
            groups = await controller.call("plan.context.list", plan_id=plan["plan_id"])
        if not is_current() or not cards.is_active():
            return False
        plan.update(updated)
        latest_group = next((item for item in groups
                             if item.get("context_id") == context["context_id"]), None)
        if latest_group is not None:
            cards.sync_group(latest_group)
        return True


class PlanningPage(Page):
    def __init__(self, controller, state: PlanningPageState, button, repaint, navigate, render_result, *, page_identity=None):
        self.controller = controller
        self.state = state
        self.button = button
        self.repaint = repaint
        self.navigate = navigate
        self.render_result = render_result
        self.page_identity = page_identity or (lambda: ("planning", 0))
        self._render_plan_list = None
        self._refresh_organization_controls = None
        self._refresh_generation_history = None
        self._refresh_candidate_summary = None
        self._candidate_summary_generation = 0
        self._organization = {}
        self._organization_locks = {}
        self._organization_refresh_lock = asyncio.Lock()
        self._header_category_select = None
        self.category_manager = CategoryManager(controller, button, repaint, self.refresh_organization_controls)

    def _planning_identity(self):
        return (self.state.plan_id, self.state.generation, *self.page_identity())

    def _identity_is_current(self, identity):
        return identity == self._planning_identity() and self.page_identity()[0] == "planning"

    async def end_collection_instance(self, plan_id, identity):
        """End only the captured planning session while its planning view remains current."""
        if not self._identity_is_current(identity):
            return False
        return await self.controller.call("instance.end", instance_type="plan", owner_id=plan_id)

    async def latest_generation_for_view(self, plan_id, identity):
        """Load only the actual newest candidate and reject stale detail responses."""
        if not self._identity_is_current(identity):
            return False, None
        rows = await self.controller.call("plan.generation.list", plan_id=plan_id)
        if not self._identity_is_current(identity):
            return False, None
        if not rows:
            return True, None
        generation = await self.controller.call("plan.generation.get", generation_id=rows[0]["generation_id"])
        if not self._identity_is_current(identity):
            return False, None
        return True, generation

    async def render(self):
        plans = await self.controller.call("plan.list")
        for item in plans:
            self._organization[item["plan_id"]] = {
                "is_favorite": int(bool(item.get("is_favorite"))),
                "category_id": item.get("category_id"),
            }
        categories = await self.controller.call("organization.category.list")
        category_options = {"": "未分类"} | {item["category_id"]: item["name"] for item in categories}
        filter_options = {"": "全部规划", "favorites": "仅收藏"} | {item["category_id"]: item["name"] for item in categories}
        if not self.state.plan_id and plans:
            self.state.plan_id = plans[0]["plan_id"]
            self.state.generation += 1
        with ui.row().classes("tw-master-layout"):
            with ui.column().classes("tw-panel tw-list-sidebar gap-3"):
                with ui.row().classes("tw-plan-sidebar-heading w-full items-center justify-between flex-nowrap"):
                    ui.label("规划").classes("text-lg font-semibold")
                    self.button("新建", self.create, primary=True)
                with ui.row().classes("tw-plan-category-toolbar w-full items-center justify-end"):
                    self.category_manager.render_button()
                search = ui.input(
                    "搜索规划",
                    value=self.state.search,
                    placeholder="搜索名称或描述",
                ).props("clearable debounce=250 prepend-icon=search").classes("w-full")
                category_filter = ui.select(filter_options, value="", label="分类筛选").classes("w-full")
                plan_list = ui.column().classes("w-full gap-2")

                def render_plan_list():
                    self.state.search = search.value or ""
                    selected_category = category_filter.value
                    visible = filter_plans(plans, search.value, favorite=True if selected_category == "favorites" else None,
                                           category_id=selected_category if selected_category not in {"", "favorites"} else None)
                    plan_list.clear()
                    with plan_list:
                        if not plans:
                            ui.label("暂无规划").classes("text-gray-500 px-2 py-3")
                            return
                        if not visible:
                            with ui.column().classes("w-full items-center gap-1 py-6"):
                                ui.icon("search_off", size="2rem").classes("text-gray-400")
                                ui.label("没有找到匹配规划").classes("text-sm text-gray-500")
                            return
                        for plan in visible:
                            selected = plan["plan_id"] == self.state.plan_id
                            card = ui.element("div").classes("tw-plan-list-card w-full" + (" tw-selected" if selected else "")).props("role=button tabindex=0")
                            card.on("click", lambda _event, p=plan: self.open(p["plan_id"]))
                            card.on("keydown.enter", lambda _event, p=plan: self.open(p["plan_id"]))
                            card.on("keydown.space", lambda _event, p=plan: self.open(p["plan_id"]))
                            with card:
                                ui.label(plan["name"]).classes("tw-plan-list-name").tooltip(plan["name"])
                                ui.label(f"{category_options.get(plan.get('category_id') or '', '未分类')} · {short_updated_at(plan.get('updated_at') or plan.get('created_at'))}").classes("tw-home-task-meta")

                search.on_value_change(lambda _: render_plan_list())
                category_filter.on_value_change(lambda _: render_plan_list())
                self._render_plan_list = render_plan_list
                render_plan_list()

                async def refresh_organization_controls():
                    nonlocal category_options, filter_options
                    expected_identity = self._planning_identity()

                    def render_with_options(new_category_options, new_filter_options):
                        nonlocal category_options, filter_options
                        category_options, filter_options = new_category_options, new_filter_options
                        self._sync_plan_organizations(plans)
                        header_select = self._header_category_select
                        if header_select is not None and not header_select.is_deleted:
                            selected_plan_id = self.state.plan_id
                            selected_metadata = self._organization.get(selected_plan_id, {})
                            header_select.set_options(new_category_options, value=selected_metadata.get("category_id") or "")
                        render_plan_list()

                    async with self._organization_refresh_lock:
                        return await _refresh_organization_controls_for_view(
                            self.controller, expected_identity, self._planning_identity,
                            category_filter, search, plan_list, plans, render_with_options,
                        )

                self._refresh_organization_controls = refresh_organization_controls
            with ui.column().classes("tw-content grow min-w-0"):
                if not self.state.plan_id:
                    ui.label("选择或新建规划").classes("text-gray-500")
                else:
                    selected_plan = await self.controller.call("plan.get", plan_id=self.state.plan_id)
                    with ui.row().classes("tw-detail-header w-full justify-between items-start gap-4 flex-wrap"):
                        with ui.column().classes("min-w-0 grow gap-1"):
                            ui.label(selected_plan.get("name", "规划")).classes("tw-detail-title")
                            if selected_plan.get("plan_description"):
                                ui.label(selected_plan["plan_description"]).classes("tw-page-subtitle tw-plan-header-summary").tooltip(selected_plan["plan_description"])
                        with ui.row().classes("items-center gap-2 shrink-0"):
                            category_select = ui.select(category_options, value=selected_plan.get("category_id") or "", label="分类").props("outlined dense").classes("tw-plan-category-select").on_value_change(
                                lambda event, p=selected_plan: self.set_organization(p, category_id=event.value or None)
                            )
                            self._header_category_select = category_select
                            favorite_button = self.button(
                                "★" if self._organization.get(selected_plan["plan_id"], selected_plan).get("is_favorite") else "☆",
                                lambda p=selected_plan: self.toggle_favorite(p), flat=True,
                            ).props("aria-label=切换规划收藏")
                            favorite_button.tooltip("切换收藏")
                            self._header_favorite_button = favorite_button
                            self.button("复制", lambda: self.save_then(self.copy_plan, selected_plan), flat=True)
                            self.button("删除", lambda: self.save_then(self.delete_plan, plans, selected_plan), flat=True).classes("tw-danger")
                            async def save_selected_plan():
                                if self.state.save_callback:
                                    await self.state.save_callback()
                            self.button("保存", save_selected_plan, primary=True)
                    await self.editor(selected_plan)

    async def save_then(self, callback, *args, **kwargs):
        """Persist the current planning draft before opening a dependent workflow."""
        if self.state.save_callback:
            await self.state.save_callback()
        return await callback(*args, **kwargs)

    async def set_organization(self, plan, favorite=None, category_id=_ORGANIZATION_UNSET):
        plan_id = plan["plan_id"]
        lock = self._organization_locks.setdefault(plan_id, asyncio.Lock())
        async with self._organization_refresh_lock, lock:
            current = self._organization.setdefault(plan_id, {
                "is_favorite": int(bool(plan.get("is_favorite"))),
                "category_id": plan.get("category_id"),
            })
            next_favorite = int(bool(current["is_favorite"] if favorite is None else favorite))
            next_category = current["category_id"] if category_id is _ORGANIZATION_UNSET else category_id
            identity = self._planning_identity()
            try:
                await self.controller.call("organization.metadata.set", entity="plan", entity_id=plan_id,
                                           is_favorite=next_favorite, category_id=next_category)
            except Exception as exc:
                if self._identity_is_current(identity):
                    if self._render_plan_list:
                        self._render_plan_list()
                    ui.notify(f"收藏或分类保存失败：{exc}", type="negative")
                return False
            current.update(is_favorite=next_favorite, category_id=next_category)
            plan.update(is_favorite=next_favorite, category_id=next_category)
            if not self._identity_is_current(identity):
                return True
            if self._render_plan_list:
                self._render_plan_list()
            select = getattr(self, "_header_category_select", None)
            if select is not None and not select.is_deleted and self.state.plan_id == plan_id:
                select.value = next_category or ""
            favorite_button = getattr(self, "_header_favorite_button", None)
            if favorite_button is not None and not favorite_button.is_deleted and self.state.plan_id == plan_id:
                favorite_button.text = "★" if next_favorite else "☆"
                favorite_button.props(f"title={'取消收藏' if next_favorite else '加入收藏'}")
            return True

    async def toggle_favorite(self, plan):
        current = self._organization.get(plan["plan_id"], plan)
        return await self.set_organization(plan, favorite=not bool(current.get("is_favorite")))

    def _sync_plan_organizations(self, plans):
        latest = {item["plan_id"]: {
            "is_favorite": int(bool(item.get("is_favorite"))),
            "category_id": item.get("category_id"),
        } for item in plans}
        self._organization.clear()
        self._organization.update(latest)

    async def refresh_organization_controls(self):
        if self._refresh_organization_controls:
            await self._refresh_organization_controls()

    async def copy_plan(self, plan):
        if self.state.plan_id == plan["plan_id"]:
            callback = self.state.save_callback
            if callback:
                await callback()
        current = await self.controller.call("plan.get", plan_id=plan["plan_id"])
        copied = await self.controller.call(
            "plan.copy", plan_id=plan["plan_id"], expected_revision=current["revision"]
        )
        self.state.search = ""
        self.state.generation += 1
        self.state.plan_id = copied["plan_id"]
        await self.repaint()

    async def delete_plan(self, plans, plan):
        if self.state.plan_id == plan["plan_id"]:
            callback = self.state.save_callback
            if callback:
                await callback()
        current = await self.controller.call("plan.get", plan_id=plan["plan_id"])
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label(f'删除规划“{plan["name"]}”？').classes("text-lg font-medium")
            ui.label("将删除该规划、已采集上下文和未导入的 AI 生成记录；已经导入的任务不会受到影响。")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                ui.button("确认删除", on_click=lambda: dialog.submit(True)).props("outline text-color=red-7")
        if not await dialog:
            return
        replacement = next_plan_id(plans, plan["plan_id"])
        await self.controller.call(
            "plan.delete", plan_id=plan["plan_id"], expected_revision=current["revision"]
        )
        if self.state.plan_id == plan["plan_id"]:
            self.state.generation += 1
            self.state.plan_id = replacement
            self.state.save_callback = None
        await self.repaint()

    async def create(self):
        callback = self.state.save_callback
        if callback:
            await callback()
        plan = await self.controller.call("plan.create", name="新规划")
        self.state.generation += 1
        self.state.plan_id = plan["plan_id"]
        await self.repaint()

    async def open(self, plan_id):
        previous_plan_id = self.state.plan_id
        previous_generation = self.state.generation
        callback = self.state.save_callback
        if callback:
            await callback()
        if (self.state.plan_id, self.state.generation) != (previous_plan_id, previous_generation):
            return False
        if self.state.plan_id != plan_id:
            self.state.generation += 1
        self.state.plan_id = plan_id
        await self.repaint()
        return True

    async def editor(self, plan):
        identity = self._planning_identity()
        if plan["plan_id"] != identity[0]:
            return
        mutation_lock = asyncio.Lock()
        catalog = await self.controller.call("capabilities")
        if not self._identity_is_current(identity):
            return
        with ui.column().classes("tw-planning-workspace w-full min-w-0 gap-3"):
            with ui.tabs().classes("w-full tw-task-tabs") as planning_tabs:
                ui.tab("基础配置")
                ui.tab("能力与素材")
                ui.tab("生成记录")
            with ui.row().classes("tw-planning-columns w-full min-w-0 items-start"):
                with ui.column().classes("tw-planning-main min-w-0 grow"):
                    with ui.column().classes("tw-plan-layout w-full min-w-0") as basic_panel:
                        with ui.column().classes("tw-panel tw-plan-form min-w-0 gap-3") as basic_form:
                            ui.label("基础信息").classes("tw-section-title")
                            name = ui.input("规划名称", value=plan["name"]).props("outlined dense").classes("w-full")
                            description = ui.textarea("规划描述", value=plan["plan_description"], placeholder="说明采集材料用于完成什么任务、最终要达到什么效果").props("outlined autogrow").classes("w-full")
                            notes = ui.textarea("操作说明（可选）", value=plan.get("plan_notes", ""), placeholder="说明全局操作顺序、变量抽取和特殊规则").props("outlined autogrow").classes("w-full")
                            save_state = ui.label("已保存").classes("text-sm text-gray-500")
                    materials_panel = ui.column().classes("tw-plan-materials tw-panel w-full min-w-0")
                    history_panel = ui.column().classes("tw-plan-history w-full min-w-0")
                assistant_panel = ui.column().classes("tw-panel tw-plan-assist gap-3 shrink-0")
        with materials_panel:
            ui.label("所用插件能力与上下文素材").classes("tw-section-title")
            environments = await self.controller.call("environment.list")
            if not self._identity_is_current(identity) or materials_panel.is_deleted:
                return
            environment = ui.select(
                {item["environment_id"]: item["name"] for item in environments},
                value=plan.get("environment_id"), label="采集环境（可选）", clearable=True,
            ).props("outlined dense").classes("w-full")
            plugins = ui.select(list(catalog["manifests"]), value=plan.get("plugin_ids", []), label="所用插件", multiple=True).props("outlined dense use-chips").classes("w-full")
            ui.label("所选插件用于规划材料与能力参考；能力目录仍按已安装插件动态提供。").classes("text-xs text-gray-500")

            def mark_changed(_=None):
                save_state.text = "未保存"

            for control in (name, description, notes, environment, plugins):
                control.on_value_change(mark_changed)

            def values():
                return {
                    "name": name.value.strip() or "新规划",
                    "plan_description": description.value or "",
                    "plan_notes": notes.value or "",
                    "environment_id": environment.value,
                    "plugin_ids": plugins.value or [],
                }

            async def save_if_changed():
                async with mutation_lock:
                    current = values()
                    if all(plan.get(key) == value for key, value in current.items()):
                        return plan
                    save_state.text = "正在保存…"
                    updated = await self.controller.call("plan.update", plan_id=plan["plan_id"], expected_revision=plan["revision"], **current)
                    plan.update(updated); save_state.text = "已保存"
                    return plan

            self.state.save_callback = save_if_changed

            with assistant_panel:
                ui.label("AI 生成任务").classes("tw-section-title")
                ui.label("使用当前规划配置与已保存的上下文快照生成候选；生成不会启动执行。 ").classes("text-sm text-gray-500")
                self.button("大模型api调用", lambda: generate_after_save("api"), primary=True, icon="auto_awesome").classes("w-full")
                self.button("大模型网页chat调用", lambda: generate_after_save("web_chat"), icon="forum").classes("w-full")
                ui.separator()
                candidate_area = ui.column().classes("tw-plan-current-candidate w-full gap-2")

                async def refresh_candidate_summary(expected_identity=identity):
                    self._candidate_summary_generation += 1
                    request_generation = self._candidate_summary_generation

                    def current():
                        return (request_generation == self._candidate_summary_generation
                                and self._identity_is_current(expected_identity)
                                and not candidate_area.is_deleted)

                    if not current():
                        return False
                    is_current, generation = await self.latest_generation_for_view(plan["plan_id"], expected_identity)
                    if not is_current or not current():
                        return False
                    latest = generation
                    candidate_area.clear()
                    with candidate_area:
                        ui.label("候选预览").classes("font-medium")
                        if generation is None:
                            ui.label("暂无生成候选。完成一次实际生成后，可在这里查看候选与诊断。").classes("text-sm text-gray-500")
                            return True
                        summary = generation_summary(generation)
                        ui.label(f'{summary["created_at"]} · {summary["channel"]} · {summary["status"]}').classes("text-sm text-gray-500")
                        if summary["can_import"]:
                            ui.label(summary["name"] or "未命名任务").classes("font-medium")
                            ui.label(f'共 {summary["step_count"]} 个步骤').classes("text-sm text-gray-600")
                            for row in summary["steps"]:
                                ui.label(f'{row["index"]:02d} · {row["name"]}').classes("text-sm text-gray-600")
                            async def import_latest(generation_id=summary["generation_id"], expected=expected_identity):
                                await self.import_generation(generation_id, expected)
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                self.button("查看完整预览", lambda item=latest: self.open_generation(item["generation_id"], expected_identity), flat=True, icon="visibility")
                                self.button("导入为任务", import_latest, primary=True)
                        else:
                            ui.label("当前最新候选尚未就绪，不能导入。").classes("text-sm text-amber-800")
                            if summary["diagnostics"]:
                                ui.label("诊断：" + "；".join(str(item) for item in summary["diagnostics"])).classes("text-sm text-red-700 whitespace-pre-wrap")
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                self.button("查看诊断", lambda item=latest: self.open_generation(item["generation_id"], expected_identity), flat=True, icon="visibility")
                                disabled_import = self.button("导入为任务", lambda: None, primary=True)
                                disabled_import.disable()
                    return current()

                self._refresh_candidate_summary = refresh_candidate_summary
                async def end_candidate_collection(expected_identity=identity, owner_id=plan["plan_id"]):
                    await self.end_collection_instance(owner_id, expected_identity)
                self.button("结束采集实例", end_candidate_collection, flat=True)

            async def collect_after_save():
                await self.save_then(self.collect_dialog, plan, on_saved=sync_group)

            async def generate_after_save(channel):
                await self.save_then(self.generate, plan, channel)

            candidate_loaded = await refresh_candidate_summary(identity)
            if (not candidate_loaded or not self._identity_is_current(identity)
                    or basic_panel.is_deleted or materials_panel.is_deleted
                    or assistant_panel.is_deleted):
                return

            ui.separator()
            contexts = plan.get("contexts", [])

            async def save_context(context, name, notes):
                async with mutation_lock:
                    updated = await self.controller.call(
                        "plan.context.update", plan_id=plan["plan_id"], expected_revision=plan["revision"],
                        context_id=context["context_id"], name=name, context_notes=notes,
                    )
                    plan.update(updated)

            async def delete_context(context):
                async with mutation_lock:
                    updated = await self.controller.call(
                        "plan.context.delete", plan_id=plan["plan_id"], expected_revision=plan["revision"],
                        context_id=context["context_id"],
                    )
                    plan.update(updated)

            async def move_context(context, direction):
                async with mutation_lock:
                    updated = await self.controller.call(
                        "plan.context.reorder", plan_id=plan["plan_id"], expected_revision=plan["revision"],
                        context_id=context["context_id"], direction=direction,
                    )
                    plan.update(updated)

            async def recollect_context(context):
                await save_if_changed()
                await self.collect_dialog(plan, context, sync_group)

            async def preview_context(context):
                await self.context_preview(context)

            async def mutate_capture(operation, context, capture, **params):
                await mutate_planning_capture(
                    self.controller, plan, context, capture, operation, mutation_lock,
                    lambda: self._identity_is_current(identity), cards, **params,
                )

            async def delete_capture(context, capture):
                await mutate_capture('plan.context.capture.delete', context, capture)

            async def move_capture(context, capture, direction):
                await mutate_capture('plan.context.capture.reorder', context, capture, direction=direction)

            async def label_capture(context, capture, label, **metadata):
                await mutate_capture('plan.context.capture.label', context, capture, label=label, **metadata)

            async def preview_one_capture(context, capture):
                saved = await self.controller.call("plan.context.capture.get", plan_id=plan["plan_id"], context_id=context["context_id"], capture_id=capture["capture_id"])
                if self._identity_is_current(identity):
                    await self.show_context_preview(capture.get("label") or "采集项", saved)

            cards = ContextCards(
                contexts, save_context, delete_context, move=move_context,
                recollect=recollect_context, preview=preview_context,
                append=collect_after_save, delete_capture=delete_capture,
                move_capture=move_capture, update_capture=label_capture,
                preview_capture=preview_one_capture,
                redact_on_display=self.controller.privacy_settings()["redact_on_display"],
                is_active=lambda: self._identity_is_current(identity),
            )

            async def sync_group(group):
                contexts = plan.setdefault('contexts', [])
                current = next((item for item in contexts if item['context_id'] == group['context_id']), None)
                if current: current.update(group)
                else: contexts.append(group)
                cards.sync_group(group)


        with history_panel:
            async def refresh_generation_history(expected_identity=identity):
                if not self._identity_is_current(expected_identity):
                    return False
                generations = await self.controller.call("plan.generation.list", plan_id=plan["plan_id"])
                if not self._identity_is_current(expected_identity) or history_panel.is_deleted:
                    return False
                history_panel.clear()
                with history_panel:
                    with ui.column().classes("tw-plan-history-content w-full gap-1"):
                        ui.label("生成记录").classes("text-lg font-semibold")
                        with ui.row().classes("tw-plan-history-table-head w-full"):
                            ui.label("生成时间")
                            ui.label("调用渠道")
                            ui.label("状态")
                        if not generations:
                            ui.label("暂无生成记录").classes("text-sm text-gray-500 px-2 py-3")
                        for item in generations:
                            summary = generation_summary(item)
                            with ui.row().classes("tw-plan-history-row w-full"):
                                ui.label(summary["created_at"])
                                ui.label(summary["channel"])
                                with ui.row().classes("items-center justify-between gap-2"):
                                    ui.label(summary["status"])
                                    self.button("查看", lambda record=item: self.open_generation(record["generation_id"], identity), flat=True)
                return True

            history_loaded = await refresh_generation_history(identity)
            if (not history_loaded or not self._identity_is_current(identity)
                    or basic_panel.is_deleted or materials_panel.is_deleted
                    or assistant_panel.is_deleted or history_panel.is_deleted):
                return
            self._refresh_candidate_summary = refresh_candidate_summary
            self._refresh_generation_history = refresh_generation_history
        def select_tab(selected):
            basic_panel.set_visibility(selected == "基础配置")
            materials_panel.set_visibility(selected == "能力与素材")
            history_panel.set_visibility(selected == "生成记录")
            planning_tabs.value = selected
            planning_tabs.update()

        def select_planning_tab(event):
            select_tab(event.value)
        planning_tabs.on_value_change(select_planning_tab)
        materials_panel.set_visibility(False)
        history_panel.set_visibility(False)


    async def collect_dialog(self, plan, existing=None, on_saved=None):
        if existing and existing.get('capture_id'):
            existing = {**existing, **await self.controller.call('plan.context.capture.get', context_id=existing['context_id'], capture_id=existing['capture_id'], plan_id=plan['plan_id'])}
        elif existing and existing.get('captures'):
            latest=existing['captures'][-1]
            existing={**existing,**await self.controller.call('plan.context.capture.get',context_id=existing['context_id'],capture_id=latest['capture_id'],plan_id=plan['plan_id'])}
        requests = self.controller.plugin_context_requests()
        available = {key: value for key, value in requests.items() if key.split(".", 1)[0] in set(plan.get("plugin_ids", []))}
        if not available: raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", "所选插件没有上下文采集器")
        draft = ContextCaptureDraft((existing or {}).get('captures', []))
        initial_name = (existing or {}).get('name', '新上下文')
        initial_notes = (existing or {}).get('context_notes', '')
        with ui.dialog() as dialog, ui.card().classes("tw-context-collection-dialog w-full max-w-5xl"):
            with ui.row().classes('tw-context-dialog-header w-full justify-between items-center'):
                ui.label("编辑与采集上下文 · 规划").classes("text-lg font-medium")
                ui.button(icon='close', on_click=lambda:cancel()).props('flat round dense aria-label=关闭弹窗')
            ui.label("修改先暂存，确认保存时整组一次提交；取消不会写入。").classes("tw-context-dialog-note w-full")
            initial_provider = existing.get("provider_id") if existing else next(iter(sorted(available)))
            if initial_provider not in available:
                initial_provider = next(iter(sorted(available)))
            with ui.row().classes("tw-context-dialog-fields w-full items-center gap-3"):
                name = ui.input("上下文名称", value=initial_name).classes("grow min-w-0")
                provider = ui.select(sorted(available), value=initial_provider, label="插件采集器").classes("grow min-w-0")
            if existing and existing.get('context_id'):
                provider.disable()
            notes = ui.textarea("操作说明（可选）", value=initial_notes, placeholder="说明本组页面或数据的用途，以及操作顺序").props("autogrow").classes("w-full")
            staged_title = ui.label().classes("font-medium")
            staged_area = ui.column().classes("w-full gap-2")
            deleted_area = ui.column().classes("w-full gap-1")

            async def load_targets():
                return await self.controller.call("plan.context.targets", plan_id=plan["plan_id"], provider_id=provider.value)

            target_area = ui.column().classes("w-full gap-1")
            target_state = {"picker": None, "options": None}

            request_forms = {}
            request_groups = {}
            for identifier, request_schema in available.items():
                schema = copy.deepcopy(request_schema)
                for key, value in context_surface_defaults(request_schema, "planning").items():
                    schema["properties"][key]["default"] = value
                if existing and identifier == initial_provider:
                    for key, value in existing.get("request", {}).items():
                        if key in schema.get("properties", {}):
                            schema["properties"][key]["default"] = value
                with ui.column().classes("w-full gap-1") as group:
                    request_forms[identifier] = ValueForm(schema)
                request_groups[identifier] = group

            def update_request_form(_=None):
                picker = target_state["picker"]
                for identifier, group in request_groups.items():
                    group.set_visibility(identifier == provider.value)
                    request_forms[identifier].hide_fields(context_hidden_parameters(
                        available[identifier], identifier == provider.value and picker is not None and not picker.uses_parameters
                    ))

            async def select_provider(_=None):
                target_area.clear()
                options = context_target_options(available[provider.value])
                target_state.update(picker=None, options=options)
                if options:
                    with target_area:
                        picker = ContextTargetPicker(load_targets, options)
                    target_state["picker"] = picker
                    picker.select.on_value_change(update_request_form)
                    await picker.refresh()
                    selected = (existing or {}).get("request", {}).get("target_id")
                    if selected and selected in picker.targets:
                        picker.select.value = selected
                update_request_form()

            provider.on_value_change(select_provider)
            await select_provider()
            view_default = context_view_default(available[provider.value])
            view_state = {"supported": view_default is not None}
            include_view = ui.checkbox("同时生成预览", value=(existing or {}).get("include_view", view_default is True))
            include_view.set_visibility(view_state["supported"])

            def update_view_option(_=None):
                default = context_view_default(available[provider.value])
                view_state["supported"] = default is not None
                include_view.set_visibility(view_state["supported"])
                if not existing:
                    include_view.value = default is True
            provider.on_value_change(update_view_option)
            advanced_values = context_advanced_overrides(
                available[initial_provider], (existing or {}).get("request", {})
            )
            with ui.expansion("高级参数 JSON（可选）", icon="tune").classes("w-full border rounded"):
                advanced = ui.textarea(
                    "JSON 对象", value=json.dumps(advanced_values, ensure_ascii=False, indent=2)
                ).classes("w-full")

            async def preview_item(entry):
                preview_identity = self._planning_identity()
                if entry.get('is_new'):
                    capture = entry['capture']
                else:
                    capture = await self.controller.call('plan.context.capture.get', plan_id=plan['plan_id'], context_id=existing['context_id'], capture_id=entry['capture_id'])
                if not self._identity_is_current(preview_identity):
                    return
                await self.show_context_preview(entry.get('label') or '采集项', capture)

            def render_staged():
                staged_title.text = f"保留采集项 · {len(draft.entries)}"
                staged_area.clear(); deleted_area.clear()
                with staged_area:
                    render_context_draft_rows(draft, preview_item, render_staged)
                if draft.deleted:
                    with deleted_area:
                        ui.label('待删除（可撤销）').classes('text-xs text-gray-500')
                        for entry in draft.deleted:
                            with ui.row().classes('items-center gap-2'):
                                ui.label(entry.get('label') or '采集项')
                                ui.button('撤销删除', on_click=lambda item=entry: (draft.undo_delete(item), render_staged())).props('flat dense')
            render_staged()

            async def collect():
                try:
                    picker = target_state["picker"]
                    hidden = context_hidden_parameters(
                        available[provider.value], picker is not None and not picker.uses_parameters
                    )
                    form_values = request_forms[provider.value].values(exclude=hidden)
                    overrides = json.loads(advanced.value or "{}")
                    target_request, session_id = picker.selection() if picker else ({}, None)
                    request = merge_context_request(form_values, overrides, target_request)
                    result = await self.controller.call(
                        "plan.context.read", plan_id=plan["plan_id"], expected_revision=plan["revision"],
                        provider_id=provider.value, request=request, expected_session_id=session_id,
                        include_view=bool(include_view.value) if view_state["supported"] else False,
                    )
                    collected = result['capture']
                    label = (collected.get('items') or [{}])[0].get('source') or f'采集 {len(draft.entries) + 1}'
                    draft.append(collected, request, bool(include_view.value) if view_state["supported"] else False, result.get('session_id'), 'planning', label)
                    render_staged()
                    ui.notify(f'已暂存采集项：{label}，可继续采集', type='positive')
                except ValueError as exc:
                    ui.notify(f'采集失败，暂存内容仍保留：高级参数需要有效 JSON 对象（{exc}）', type='negative')
                except Exception as exc:
                    ui.notify(f'采集失败，暂存内容仍保留：{exc}', type='negative')

            async def cancel():
                if draft.dirty or (name.value or '') != initial_name or (notes.value or '') != initial_notes:
                    with ui.dialog() as confirm, ui.card():
                        ui.label('关闭将丢弃本次未保存的编辑和采集项。')
                        with ui.row():
                            ui.button('继续编辑', on_click=lambda: confirm.submit(False)).props('outline')
                            ui.button('丢弃并关闭', on_click=lambda: confirm.submit(True)).props('text-color=red-7')
                    if not await confirm: return
                dialog.close()

            async def save_batch():
                if existing and not draft.dirty and (name.value or '') == initial_name and (notes.value or '') == initial_notes:
                    dialog.close()
                    return
                try:
                    result = await self.controller.call(
                        'plan.context.save_batch', plan_id=plan['plan_id'], expected_revision=plan['revision'],
                        context_id=(existing or {}).get('context_id'), provider_id=provider.value,
                        name=name.value or '', context_notes=notes.value or '', captures=draft.payload(),
                    )
                except Exception as exc:
                    ui.notify(f'保存失败，暂存内容仍保留：{exc}', type='negative')
                    return
                plan.update(result['plan'])
                if on_saved: await on_saved(result['group'])
                dialog.close()

            self.button('采集一项', collect, primary=True)
            ui.label('每次采集只暂存在此弹窗；确认保存后才会进入规划材料。浏览器等外部操作不会因取消自动回滚。').classes('text-xs text-gray-500')
            with ui.row().classes('tw-context-dialog-actions w-full justify-end gap-2'):
                ui.button('取消', on_click=cancel).props('outline')
                ui.button('确认保存', on_click=save_batch).props('unelevated color=primary')
        dialog.open()

    async def show_context_preview(self, title, capture):
        identity = self._planning_identity()
        await show_context_preview(title, capture, self.controller.result_renderers,
            self.render_result, redact_on_display=self.controller.privacy_settings()['redact_on_display'],
            is_active=lambda: self._identity_is_current(identity))

    async def context_preview(self, context):
        identity = self._planning_identity()
        capture = await self.controller.call('plan.context.capture.get', context_id=context['context_id'], capture_id=context['capture_id'], plan_id=self.state.plan_id)
        if not self._identity_is_current(identity):
            return
        await self.show_context_preview(context["name"] + " · " + (context.get('label') or '采集项'), capture)

    async def generate(self, plan, channel):
        identity = self._planning_identity()
        if plan["plan_id"] != identity[0] or not self._identity_is_current(identity):
            return None
        try:
            result = await self.controller.call("plan.generate", plan_id=plan["plan_id"], expected_revision=plan["revision"], channel=channel)
        except Exception:
            await self._refresh_failed_generation(identity)
            raise
        if not self._identity_is_current(identity):
            return result
        if self._refresh_generation_history:
            await self._refresh_generation_history(identity)
        if not self._identity_is_current(identity):
            return result
        if self._refresh_candidate_summary:
            await self._refresh_candidate_summary(identity)
        if not self._identity_is_current(identity):
            return result
        if channel == "web_chat":
            with ui.dialog() as dialog, ui.card().classes("tw-plan-web-dialog w-full max-w-5xl"):
                ui.label("大模型网页chat调用").classes("text-lg font-medium")
                ui.label(f'请求大小：{result["request_size_bytes"] / 1024:.1f} KB / {result["request_limit_bytes"] / 1024:.0f} KB').classes("text-gray-500")
                from taskweave.desktop.contexts import render_preview_attachments
                render_preview_attachments(result)
                prompt = ui.textarea("完整提示词", value=result["prompt"]).props("readonly").classes("tw-plan-prompt w-full")
                response = ui.textarea("粘贴网页回复 JSON").classes("tw-plan-response w-full")
                async def parse():
                    await self.parse_generation(result["generation_id"], response.value or "", identity, dialog.close)
                async def copy_prompt():
                    await self.controller.copy_text(result["prompt"])
                    ui.notify("完整提示词已复制")
                async def download_prompt():
                    if self.controller.native:
                        path = await self.controller.save_plan_prompt(result["prompt"])
                        ui.notify("提示词已保存：" + str(path), timeout=8000)
                    else:
                        ui.download.content(result["prompt"], filename=f'taskweave-plan-{result["generation_id"]}.txt', media_type="application/octet-stream")
                with ui.row().classes("gap-2 flex-wrap"):
                    self.button("复制提示词", copy_prompt)
                    self.button("下载提示词", download_prompt)
                    self.button("解析并预览", parse, primary=True)
                    ui.button("关闭", on_click=dialog.close).props("outline")
            dialog.open()
        else:
            await self.preview(result, identity)

    async def parse_generation(self, generation_id, response_text, identity, close_dialog=None):
        try:
            candidate = await self.controller.call(
                "plan.generation.parse", generation_id=generation_id, response_text=response_text
            )
        except Exception:
            await self._refresh_failed_generation(identity)
            raise
        if not self._identity_is_current(identity):
            if close_dialog:
                close_dialog()
            return None
        if self._refresh_generation_history:
            await self._refresh_generation_history(identity)
        if not self._identity_is_current(identity):
            if close_dialog:
                close_dialog()
            return None
        if self._refresh_candidate_summary:
            await self._refresh_candidate_summary(identity)
        if not self._identity_is_current(identity):
            if close_dialog:
                close_dialog()
            return None
        if close_dialog:
            close_dialog()
        await self.preview(candidate, identity)
        return candidate

    async def _refresh_failed_generation(self, identity):
        """Refresh diagnostics after failure without hiding the original error."""
        if not self._identity_is_current(identity) or not self._refresh_generation_history:
            return
        try:
            await self._refresh_generation_history(identity)
            if self._identity_is_current(identity) and self._refresh_candidate_summary:
                await self._refresh_candidate_summary(identity)
        except Exception:
            logger.warning("Could not refresh plan generation history after a failed operation", exc_info=True)

    async def preview(self, generation, identity=None):
        identity = identity or self._planning_identity()
        if not self._identity_is_current(identity):
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-5xl"):
            ui.label("任务候选预览").classes("text-lg font-medium")
            if generation["status"] not in {"READY", "IMPORTED"} or not generation.get("candidate"):
                ui.label("尚不能导入：" + json.dumps(generation.get("diagnostics", []), ensure_ascii=False)).classes("text-red-700")
            else:
                receipt_rows = ui.column().classes("w-full gap-1")

                async def refresh_receipts():
                    receipt_rows.clear()
                    rows = await self.controller.call("plan.generation.imports", generation_id=generation["generation_id"])
                    with receipt_rows:
                        ui.label("已导入任务").classes("font-medium")
                        for receipt in rows:
                            ui.label(f'{receipt["imported_at"]} · {receipt["task_id"]}').classes("text-sm text-gray-600")

                await refresh_receipts()
                package = generation["candidate"]
                ui.label(package["task"]["name"])
                if generation.get("context_labels") and not package.get("plan_context_refs"):
                    ui.label("尚未关联规划上下文；导入后可在步骤中重新采集").classes("text-amber-800")
                rows = candidate_step_rows(package, generation.get("context_labels", {}))
                unwritten = sum(row["status"] == "待编写" for row in rows)
                if unwritten:
                    ui.label(f"{unwritten} 个步骤待编写，可导入后补充上下文并调试").classes("text-amber-800")
                for row in rows:
                    step = row["document"]
                    with ui.expansion(f'{row["index"]}. {step["name"]} · {row["status"]}').classes("w-full"):
                        ui.label(step["step_description"])
                        if step["step_notes"]:
                            ui.label(step["step_notes"]).classes("whitespace-pre-wrap text-gray-700")
                        if row["context_names"]:
                            ui.label("关联上下文：" + "、".join(row["context_names"])).classes("text-sm text-gray-600")
                        if step["step_content"].strip():
                            ui.code(step["step_content"], language="python").classes("w-full")
                async def import_task():
                    await self.import_generation(generation["generation_id"], identity, refresh_receipts)
                self.button("导入为任务", import_task, primary=True)
            ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()

    async def import_generation(self, generation_id, identity, refresh_receipts=None):
        value = await self.controller.call("plan.generation.import", generation_id=generation_id)
        if not self._identity_is_current(identity):
            return value
        if refresh_receipts:
            await refresh_receipts()
        if self._refresh_generation_history:
            await self._refresh_generation_history(identity)
        if self._identity_is_current(identity) and self._refresh_candidate_summary:
            await self._refresh_candidate_summary(identity)
        if self._identity_is_current(identity):
            ui.notify("已创建新任务：" + value["task_id"], type="positive")
        return value

    async def open_generation(self, generation_id, identity=None):
        identity = identity or self._planning_identity()
        if not self._identity_is_current(identity):
            return
        generation = await self.controller.call("plan.generation.get", generation_id=generation_id)
        if self._identity_is_current(identity):
            await self.preview(generation, identity)
