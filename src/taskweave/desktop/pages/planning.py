"""Plan page: collect plugin evidence and turn a validated candidate into a task."""

import asyncio
import logging
from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.desktop.state import PlanningPageState
from taskweave.desktop.components.organization import CategoryManager
from taskweave.desktop.contexts import ContextCards

from taskweave.presentation.catalog import CategoryFilter, filter_plans
from taskweave.presentation.planning import PlanningInteraction, PlanEditorSession, next_plan_id, ORGANIZATION_UNSET
from taskweave.desktop.components.planning_collection import PlanningCollectionView
from taskweave.desktop.components.planning_generations import (
    PlanningGenerationView, generation_summary, short_updated_at, candidate_step_rows,
)

logger = logging.getLogger("taskweave.desktop.planning")
_ORGANIZATION_UNSET = ORGANIZATION_UNSET


async def _refresh_organization_controls_for_view(controller, expected_identity, current_identity,
                                                  category_filter, search, plan_list, plans, render, *, filter_state=None):
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
    # Legacy callers may omit state; the actual page supplies its plain selection.
    selection = filter_state if filter_state is not None else CategoryFilter(category_filter.value)
    selection.retain_categories(new_filter_options)
    plans[:] = latest_plans
    category_filter.set_options(new_filter_options, value=selection.category)
    render(new_category_options, new_filter_options)
    return True


async def mutate_planning_capture(controller, plan, context, capture, operation, lock,
                                  is_current, cards, *, editor=None, **params):
    """Persist a capture edit and refresh only its active group card."""
    editor = editor or PlanEditorSession(controller, plan)
    async with lock:
        if not is_current():
            return False
        updated = await editor.prepare_capture_change(operation, context["context_id"], capture["capture_id"], **params)
        if not is_current():
            return False
        latest_group = await editor.capture_group(updated, context["context_id"])
        if not is_current() or not cards.is_active():
            return False
        editor.accept(updated)
        if latest_group is not None:
            cards.sync_group(latest_group)
        return True


class PlanningPage(PlanningCollectionView, PlanningGenerationView, Page):
    def __init__(self, controller, state: PlanningPageState, button, repaint, navigate, render_result, *, page_identity=None):
        self.controller = controller
        self.state = state
        self.interaction = PlanningInteraction(controller, state.interaction)
        self.button = button
        self.repaint = repaint
        self.navigate = navigate
        self.render_result = render_result
        self.page_identity = page_identity or (lambda: ("planning", 0))
        self._render_plan_list = None
        self._refresh_organization_controls = None
        self._refresh_generation_history = None
        self._refresh_candidate_summary = None
        self._organization = self.interaction.organization
        self._organization_refresh_lock = self.interaction.organization_refresh_lock
        self._header_category_select = None
        self.category_manager = CategoryManager(controller, button, repaint, self.refresh_organization_controls)

    def _planning_identity(self):
        self.interaction.set_view(*self.page_identity())
        return self.interaction.identity()

    def _identity_is_current(self, identity):
        self._planning_identity()
        return self.interaction.is_current(identity)

    async def end_collection_instance(self, plan_id, identity):
        """End only the captured planning session while its planning view remains current."""
        if not self._identity_is_current(identity):
            return False
        return await self.interaction.end_collection(plan_id)

    async def latest_generation_for_view(self, plan_id, identity):
        """Load only the actual newest candidate and reject stale detail responses."""
        if not self._identity_is_current(identity):
            return False, None
        accepted, generation = await self.interaction.latest_generation(plan_id)
        return accepted and self._identity_is_current(identity), generation

    async def render(self):
        plans = await self.controller.call("plan.list")
        self.interaction.sync_organizations(plans)
        categories = await self.controller.call("organization.category.list")
        category_options = {"": "未分类"} | {item["category_id"]: item["name"] for item in categories}
        filter_options = {"": "全部规划", "favorites": "仅收藏"} | {item["category_id"]: item["name"] for item in categories}
        self.interaction.initialize_selection(plans)
        with ui.row().classes("tw-master-layout"):
            with ui.column().classes("tw-panel tw-list-sidebar gap-3"):
                with ui.row().classes("tw-plan-sidebar-heading w-full items-center justify-between flex-nowrap"):
                    ui.label("规划").classes("text-lg font-semibold shrink-0")
                    with ui.row().classes("tw-plan-sidebar-actions items-center flex-nowrap"):
                        self.button("管理分类", self.category_manager.open, flat=True).classes("tw-plan-manage-categories")
                        self.button("新建", self.create, primary=True, icon="add")
                search = ui.input(
                    "搜索规划",
                    value=self.state.search,
                    placeholder="搜索名称或描述",
                ).props("clearable debounce=250 prepend-icon=search").classes("w-full")
                filter_state = CategoryFilter()
                category_filter = ui.select(filter_options, value=filter_state.category, label="分类筛选").classes("w-full")
                plan_list = ui.column().classes("w-full gap-2")

                def render_plan_list():
                    visible = filter_plans(plans, self.state.search, favorite=filter_state.favorite,
                                           category_id=filter_state.category_id)
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
                                ui.label(f"{category_options.get(plan.get('category_id') or '', '未分类')} · r{plan['revision']} · {short_updated_at(plan.get('updated_at') or plan.get('created_at'))}").classes("tw-home-task-meta")

                def search_changed(event):
                    self.state.search = event.value or ""
                    render_plan_list()
                def category_changed(event):
                    filter_state.category = event.value or ""
                    render_plan_list()
                search.on_value_change(search_changed)
                category_filter.on_value_change(category_changed)
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
                            category_filter, search, plan_list, plans, render_with_options, filter_state=filter_state,
                        )

                self._refresh_organization_controls = refresh_organization_controls
            with ui.column().classes("tw-content grow min-w-0"):
                if not self.state.plan_id:
                    ui.label("选择或新建规划").classes("text-gray-500")
                else:
                    selected_plan = await self.controller.call("plan.get", plan_id=self.state.plan_id)
                    selected_identity = self._planning_identity()
                    with ui.row().classes("tw-detail-header w-full justify-between items-start gap-4 flex-wrap"):
                        with ui.column().classes("min-w-0 grow gap-1"):
                            with ui.row().classes("items-center gap-2"):
                                header_title = ui.label(selected_plan.get("name", "规划")).classes("tw-detail-title")
                                header_revision = ui.label(f"r{selected_plan['revision']}").classes("tw-badge tw-plan-revision")
                            header_summary = ui.label(selected_plan.get("plan_description", "")).classes("tw-page-subtitle tw-plan-header-summary")
                            header_summary.set_visibility(bool(selected_plan.get("plan_description")))
                            with header_summary:
                                summary_tooltip = ui.tooltip(selected_plan.get("plan_description", ""))
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
                            async def save_selected_plan():
                                if self.state.save_callback:
                                    await self.state.save_callback()
                            self.button("保存", save_selected_plan)
                            self.button("生成任务", lambda: self.save_then(self.choose_generation_mode, selected_plan),
                                        primary=True, icon="auto_awesome")
                            with ui.button("更多", icon="more_horiz").props("flat aria-label=规划更多操作"):
                                with ui.menu().props("auto-close"):
                                    with ui.column().classes("gap-0 p-1 min-w-40"):
                                        self.button("复制规划", lambda: self.save_then(self.copy_plan, selected_plan), flat=True).classes("w-full justify-start")
                                        self.button("删除规划", lambda: self.save_then(self.delete_plan, plans, selected_plan), flat=True).classes("tw-danger w-full justify-start")

                    def reflect_saved_plan(saved):
                        if (not self._identity_is_current(selected_identity)
                                or saved['plan_id'] != selected_plan['plan_id']
                                or header_title.is_deleted or plan_list.is_deleted):
                            return
                        header_title.text = saved['name']
                        header_revision.text = f"r{saved['revision']}"
                        header_summary.text = saved.get('plan_description', '')
                        header_summary.set_visibility(bool(header_summary.text))
                        summary_tooltip.text = header_summary.text
                        for listed_plan in plans:
                            if listed_plan['plan_id'] == saved['plan_id']:
                                listed_plan.update({field: saved[field] for field in
                                                    ('name', 'plan_description', 'revision', 'updated_at') if field in saved})
                                break
                        render_plan_list()

                    await self.editor(selected_plan, on_saved=reflect_saved_plan)

    async def _save_legacy_callback(self):
        """Retain the externally supplied save hook before an editor is mounted."""
        identity = self._planning_identity()
        if self.interaction.editor_session is None and self.state.save_callback:
            await self.state.save_callback()
        return self._identity_is_current(identity)

    async def save_then(self, callback, *args, **kwargs):
        identity = self._planning_identity()
        if self.state.save_callback:
            await self.state.save_callback()
        if not self._identity_is_current(identity) or not await self.interaction.save_current():
            return None
        return await callback(*args, **kwargs)

    async def set_organization(self, plan, favorite=None, category_id=_ORGANIZATION_UNSET):
        plan_id = plan["plan_id"]
        identity = self._planning_identity()
        try:
            metadata = await self.interaction.set_organization(plan, favorite, category_id)
        except Exception as exc:
            if self._identity_is_current(identity):
                if self._render_plan_list:
                    self._render_plan_list()
                ui.notify(f"收藏或分类保存失败：{exc}", type="negative")
            return False
        if not self._identity_is_current(identity):
            return True
        if self._render_plan_list:
            self._render_plan_list()
        select = getattr(self, "_header_category_select", None)
        if select is not None and not select.is_deleted:
            select.value = metadata['category_id'] or ""
        favorite_button = getattr(self, "_header_favorite_button", None)
        if favorite_button is not None and not favorite_button.is_deleted:
            favorite_button.text = "★" if metadata['is_favorite'] else "☆"
            favorite_button.props(f"title={'取消收藏' if metadata['is_favorite'] else '加入收藏'}")
        return True

    async def toggle_favorite(self, plan):
        current = self._organization.get(plan["plan_id"], plan)
        return await self.set_organization(plan, favorite=not bool(current.get("is_favorite")))

    def _sync_plan_organizations(self, plans):
        self.interaction.sync_organizations(plans)

    async def refresh_organization_controls(self):
        if self._refresh_organization_controls:
            await self._refresh_organization_controls()

    async def copy_plan(self, plan):
        if self.state.plan_id == plan['plan_id'] and not await self._save_legacy_callback():
            return
        copied = await self.interaction.copy_plan(plan)
        if copied and self.state.plan_id == copied['plan_id']:
            await self.repaint()

    async def delete_plan(self, plans, plan):
        if self.state.plan_id == plan['plan_id'] and not await self._save_legacy_callback():
            return
        deletion = await self.interaction.prepare_delete(plans, plan)
        if deletion is None:
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label(f'删除规划“{plan["name"]}”？').classes("text-lg font-medium")
            ui.label("将删除该规划、已采集上下文和未导入的 AI 生成记录；已经导入的任务不会受到影响。")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                ui.button("确认删除", on_click=lambda: dialog.submit(True)).props("outline text-color=red-7")
        approved = bool(await dialog)
        self._planning_identity()
        if await self.interaction.delete_plan(deletion, approved=approved):
            self.state.save_callback = None
            await self.repaint()

    async def create(self):
        if not await self._save_legacy_callback():
            return
        plan = await self.interaction.create()
        if plan and self.state.plan_id == plan['plan_id']:
            await self.repaint()

    async def open(self, plan_id):
        if not await self._save_legacy_callback() or not await self.interaction.open(plan_id):
            return False
        await self.repaint()
        return True

    async def editor(self, plan, *, on_saved=None):
        identity = self._planning_identity()
        if plan["plan_id"] != identity[0]:
            return
        editor = self.interaction.edit(plan)
        view = self.interaction.view_session()
        mutation_lock = editor.lock
        def reflect_current_plan():
            if on_saved and self._identity_is_current(identity):
                on_saved(plan)

        with ui.column().classes("tw-planning-workspace w-full min-w-0 gap-3"):
            with ui.tabs(value="基础配置").classes("w-full tw-task-tabs") as planning_tabs:
                ui.tab("基础配置", label="目标与要求")
                ui.tab("能力与素材", label="上下文材料")
                ui.tab("生成记录")
            with ui.row().classes("tw-planning-columns w-full min-w-0 items-start"):
                with ui.column().classes("tw-planning-main min-w-0 grow"):
                    with ui.column().classes("tw-plan-layout w-full min-w-0") as basic_panel:
                        with ui.column().classes("tw-panel tw-plan-form min-w-0 gap-3") as basic_form:
                            ui.label("规划内容").classes("tw-section-title")
                            name = ui.input("规划名称", value=plan["name"]).props("outlined dense").classes("w-full")
                            description = ui.textarea("任务目标", value=plan["plan_description"], placeholder="说明采集材料用于完成什么任务、最终要达到什么效果").props("outlined autogrow").classes("w-full")
                            notes = ui.textarea("操作说明（可选）", value=plan.get("plan_notes", ""), placeholder="说明全局操作顺序、变量抽取和特殊规则").props("outlined autogrow").classes("w-full")
                            capability_area = ui.element('div').classes('tw-plan-capabilities w-full')
                            with capability_area:
                                capability_error = ui.column().classes('w-full gap-2 col-span-full')
                                capability_error.set_visibility(False)
                            save_state = ui.label("已保存").classes("text-sm text-gray-500")
                    materials_panel = ui.column().classes("tw-plan-materials tw-panel w-full min-w-0")
                    materials_panel.set_visibility(False)
                    history_panel = ui.column().classes("tw-plan-history w-full min-w-0")
                    history_panel.set_visibility(False)
                assistant_panel = ui.column().classes("tw-panel tw-plan-assist gap-3")
                assistant_panel.set_visibility(False)
        environment = plugins = cards = None
        materials_loaded = False
        materials_lock = asyncio.Lock()
        def bind_draft(control, field):
            def changed(event):
                editor.change(field, event.value)
                save_state.text = "未保存"
            control.on_value_change(changed)

        for control, field in ((name, "name"), (description, "plan_description"), (notes, "plan_notes")):
            bind_draft(control, field)

        async def save_if_changed():
            def current():
                return self._identity_is_current(identity) and not save_state.is_deleted

            if not editor.dirty:
                if current() and on_saved:
                    on_saved(plan)
                return plan
            if current():
                save_state.text = "正在保存…"
            try:
                result = await editor.save()
            except Exception:
                if current():
                    save_state.text = "未保存"
                raise
            if current():
                save_state.text = "已保存" if not editor.dirty else "未保存"
                if on_saved:
                    on_saved(result)
            return result

        self.state.save_callback = save_if_changed

        with assistant_panel:
            candidate_area = ui.column().classes("tw-plan-current-candidate w-full gap-2")

            async def refresh_candidate_summary(expected_identity=identity):
                def current():
                    return (self._identity_is_current(expected_identity)
                            and not candidate_area.is_deleted)

                if not current():
                    return False
                is_current, generation = await self.latest_generation_for_view(plan["plan_id"], expected_identity)
                if not is_current or not current():
                    return False
                latest = generation
                candidate_area.clear()
                with candidate_area:
                    ui.label("最新候选").classes("font-medium")
                    if generation is None:
                        ui.label('暂无候选').classes('text-sm text-gray-500')
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

        async def collect_after_save():
            await self.save_then(self.collect_dialog, plan, on_saved=sync_group)

        async def sync_group(group):
            editor.sync_group(group)
            reflect_current_plan()
            if cards is not None:
                cards.sync_group(group)


        async def load_materials():
            nonlocal environment, plugins, cards, materials_loaded
            async with materials_lock:
                if materials_loaded or not self._identity_is_current(identity) or materials_panel.is_deleted:
                    return
                self._planning_identity()
                try:
                    materials = await view.load_materials()
                except Exception:
                    logger.warning("Could not load planning capabilities and environments", exc_info=True)
                    if self._identity_is_current(identity) and not capability_error.is_deleted:
                        capability_error.set_visibility(True)
                    return
                if materials is None or not self._identity_is_current(identity) or materials_panel.is_deleted:
                    return
                catalog, environments = materials
                capability_error.set_visibility(False)
                with capability_area:
                    environment = ui.select(
                        {item["environment_id"]: item["name"] for item in environments},
                        value=plan.get("environment_id"), label="采集环境（可选）", clearable=True,
                    ).props("outlined dense").classes("w-full")
                    with ui.column().classes('tw-plan-plugin-options w-full gap-2').props('role=group aria-label=可用插件') as plugins:
                        ui.label('可用插件').classes('text-xs text-gray-500')
                        selected = set(editor.values()['plugin_ids'])
                        installed = set(catalog['manifests'])
                        def select_plugin(event, plugin_id):
                            if not self._identity_is_current(identity):
                                return
                            if event.value:
                                selected.add(plugin_id)
                            else:
                                selected.discard(plugin_id)
                            editor.change('plugin_ids', sorted(selected))
                            save_state.text = '未保存'
                        with ui.row().classes('w-full gap-x-4 gap-y-1'):
                            for plugin_id in sorted(installed | selected):
                                title = plugin_id if plugin_id in installed else plugin_id + '（未安装）'
                                ui.checkbox(title, value=plugin_id in selected,
                                    on_change=lambda event, pid=plugin_id: select_plugin(event, pid)).props('dense')
                            if not installed and not selected:
                                ui.label('暂无可用插件').classes('text-xs text-gray-500')
                    bind_draft(environment, "environment_id")
                with materials_panel:
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label("上下文材料").classes("tw-section-title")
                        async def end_candidate_collection(expected_identity=identity, owner_id=plan["plan_id"]):
                            await self.end_collection_instance(owner_id, expected_identity)
                        self.button("结束采集实例", end_candidate_collection, flat=True)
                    contexts = plan.get("contexts", [])

                    async def save_context(context, name, notes):
                        await editor.mutate_context("plan.context.update", context["context_id"], name=name, context_notes=notes)
                        reflect_current_plan()

                    async def delete_context(context):
                        await editor.mutate_context("plan.context.delete", context["context_id"])
                        reflect_current_plan()

                    async def move_context(context, direction):
                        await editor.mutate_context("plan.context.reorder", context["context_id"], direction=direction)
                        reflect_current_plan()

                    async def recollect_context(context):
                        await save_if_changed()
                        await self.collect_dialog(plan, context, sync_group)

                    async def preview_context(context):
                        await self.context_preview(context)

                    async def mutate_capture(operation, context, capture, **params):
                        changed = await mutate_planning_capture(
                            self.controller, plan, context, capture, operation, mutation_lock,
                            lambda: self._identity_is_current(identity), cards, editor=editor, **params,
                        )
                        if changed:
                            reflect_current_plan()

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

                materials_loaded = True

        with capability_error:
            ui.label('环境与插件加载失败，请重试。').classes('text-sm text-red-700')
            self.button('重新加载', load_materials, flat=True, icon='refresh')

        async def refresh_generation_history(expected_identity=identity):
            if not self._identity_is_current(expected_identity):
                return False
            if not view.invalidate_history():
                return view.current
            return await load_history(expected_identity)

        import_counts = {}

        async def load_history(expected_identity):
            if not self._identity_is_current(expected_identity):
                return False
            accepted, generations = await view.load_history()
            if not accepted or not self._identity_is_current(expected_identity) or history_panel.is_deleted:
                return False
            if generations is None:
                return True
            counts = {}
            try:
                for generation in generations:
                    generation_id = generation['generation_id']
                    if generation.get('status') == 'IMPORTED' or generation.get('imported_task_id'):
                        key = (generation_id, generation.get('updated_at'))
                        if key not in import_counts:
                            receipts = await self.interaction.imports(generation_id)
                            if not self._identity_is_current(expected_identity) or history_panel.is_deleted:
                                return False
                            import_counts[key] = len(receipts)
                        counts[generation_id] = import_counts[key]
                    else:
                        counts[generation_id] = 0
            except Exception:
                view.invalidate_history()
                raise
            history_panel.clear()
            with history_panel:
                with ui.column().classes("tw-plan-history-content w-full gap-1"):
                    ui.label("生成记录").classes("text-lg font-semibold")
                    with ui.row().classes("tw-plan-history-table-head w-full"):
                        ui.label("生成时间 / 材料版本")
                        ui.label("调用渠道")
                        ui.label("状态 / 导入次数")
                    if not generations:
                        ui.label("暂无生成记录").classes("text-sm text-gray-500 px-2 py-3")
                    for item in generations:
                        summary = generation_summary(item)
                        with ui.row().classes("tw-plan-history-row w-full"):
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(summary["created_at"])
                                if summary["plan_revision"] is not None:
                                    ui.label(f'基于 r{summary["plan_revision"]}').classes("text-xs text-gray-500")
                            ui.label(summary["channel"])
                            with ui.row().classes("items-center justify-between gap-2"):
                                with ui.column().classes('gap-0 min-w-0'):
                                    ui.label(summary["status"])
                                    ui.label(f"导入 {counts[item['generation_id']]} 次").classes('text-xs text-gray-500')
                                self.button("查看", lambda record=item: self.open_generation(record["generation_id"], identity), flat=True)
            return True

        self._refresh_generation_history = refresh_generation_history

        async def select_planning_tab(event):
            if not self._identity_is_current(identity) or basic_panel.is_deleted:
                return
            if not view.select_tab(event.value):
                return
            basic_panel.set_visibility(view.selected_tab == "基础配置")
            materials_panel.set_visibility(view.selected_tab == "能力与素材")
            history_panel.set_visibility(view.selected_tab == "生成记录")
            assistant_panel.set_visibility(view.selected_tab == "生成记录")
            try:
                if view.selected_tab == "能力与素材":
                    await load_materials()
                elif view.selected_tab == "生成记录":
                    await load_history(identity)
            except Exception:
                if self._identity_is_current(identity):
                    ui.notify("加载失败，请重新打开此页签重试", type="negative")
                logger.warning("Could not load planning tab", exc_info=True)

        planning_tabs.on_value_change(select_planning_tab)
        await load_materials()
        await refresh_candidate_summary(identity)
