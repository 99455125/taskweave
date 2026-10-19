"""Task list and task configuration page operations."""

import asyncio
import json
from datetime import datetime
from nicegui import ui
from taskweave.desktop.pages.base import Page

from taskweave.core.validation import TaskError
from taskweave.desktop.forms import SchemaEditor
from taskweave.desktop.components.organization import CategoryManager

from taskweave.presentation.catalog import CatalogFilter, filter_tasks
from taskweave.presentation.tasks import TaskOrganization, UNSET as _ORGANIZATION_UNSET
from taskweave.presentation.task_import import TaskImportSession, TASK_IMPORT_LIMIT_BYTES


def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def short_updated_at(value):
    if not value:
        return "尚未更新"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return parsed.strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(value)[:16]


def run_status_label(status):
    return {"SUCCEEDED": "成功", "FAILED": "失败", "RUNNING": "运行中", "WAITING_INPUT": "等待输入",
            "PAUSED": "已暂停", "INTERRUPTED": "已中断", "CANCELLED": "已取消", "PENDING": "等待执行"}.get(status, "未知状态")




class TasksPage(Page):
    """Own task list/config UI; all cross-page behavior is an explicit callback."""

    WORKSPACE_TABS = ("overview", "steps", "execution_history", "debug_history")

    @property
    def search_query(self): return self.catalog_filter.query
    @search_query.setter
    def search_query(self, value): self.catalog_filter.query = value

    # Legacy view hooks remain explicit adapters; production composition uses narrow panels.
    @property
    def on_runs_cleared(self): return self.lifecycle.runs_cleared
    @on_runs_cleared.setter
    def on_runs_cleared(self, value):
        from dataclasses import replace
        self.lifecycle = replace(self.lifecycle, runs_cleared=value)

    @property
    def on_task_deleted(self): return self.lifecycle.deleted
    @on_task_deleted.setter
    def on_task_deleted(self, value):
        from dataclasses import replace
        self.lifecycle = replace(self.lifecycle, deleted=value)

    @property
    def before_task_update(self): return self.lifecycle.before_update
    @before_task_update.setter
    def before_task_update(self, value):
        from dataclasses import replace
        self.lifecycle = replace(self.lifecycle, before_update=value)

    @property
    def after_task_update(self): return self.lifecycle.after_update
    @after_task_update.setter
    def after_task_update(self, value):
        from dataclasses import replace
        self.lifecycle = replace(self.lifecycle, after_update=value)

    @property
    def save_step(self): return self.editor_panel.save
    @save_step.setter
    def save_step(self, value):
        from dataclasses import replace
        self.editor_panel = replace(self.editor_panel, save=value)

    @property
    def render_step_details(self): return self.editor_panel.render
    @render_step_details.setter
    def render_step_details(self, value):
        from dataclasses import replace
        self.editor_panel = replace(self.editor_panel, render=value)

    @property
    def render_execution_history(self): return self.history_panels.execution
    @render_execution_history.setter
    def render_execution_history(self, value):
        from dataclasses import replace
        self.history_panels = replace(self.history_panels, execution=value)

    @property
    def render_debug_history(self): return self.history_panels.debug
    @render_debug_history.setter
    def render_debug_history(self, value):
        from dataclasses import replace
        self.history_panels = replace(self.history_panels, debug=value)

    @property
    def open_task_execution(self): return self.history_panels.open_execution
    @open_task_execution.setter
    def open_task_execution(self, value):
        from dataclasses import replace
        self.history_panels = replace(self.history_panels, open_execution=value)

    @property
    def prepare_step_leave(self): return self.editor_panel.prepare_leave
    @prepare_step_leave.setter
    def prepare_step_leave(self, value):
        from dataclasses import replace
        self.editor_panel = replace(self.editor_panel, prepare_leave=value)

    @property
    def discard_step_for_tab(self): return self.editor_panel.discard_for_tab
    @discard_step_for_tab.setter
    def discard_step_for_tab(self, value):
        from dataclasses import replace
        self.editor_panel = replace(self.editor_panel, discard_for_tab=value)

    @property
    def create_first_step_callback(self): return self.editor_panel.create_first
    @create_first_step_callback.setter
    def create_first_step_callback(self, value):
        from dataclasses import replace
        self.editor_panel = replace(self.editor_panel, create_first=value)

    @property
    def workspace(self):
        from taskweave.presentation.workspace import TaskWorkspace
        if not hasattr(self, '_workspace_state'):
            self._workspace_state = TaskWorkspace()
        return self._workspace_state

    @property
    def workspace_tab(self): return self.workspace.tab
    @workspace_tab.setter
    def workspace_tab(self, value): self.workspace.tab = value

    @property
    def workspace_generation(self): return self.workspace.generation
    @workspace_generation.setter
    def workspace_generation(self, value): self.workspace.generation = value

    @property
    def workspace_switch_generation(self): return self.workspace.switch_generation
    @workspace_switch_generation.setter
    def workspace_switch_generation(self, value): self.workspace.switch_generation = value

    def __init__(self, controller, button, navigate, repaint, *, on_runs_cleared=None, on_task_deleted=None, before_task_update=None, after_task_update=None,
                 task_id=None, step_id=None, page_generation=None, save_step=None, render_step_details=None,
                 render_execution_history=None, render_debug_history=None, open_task_execution=None,
                 prepare_step_leave=None, discard_step_for_tab=None, create_first_step=None, page_identity=None,
                 editor_panel=None, history_panels=None, lifecycle=None):
        from taskweave.desktop.task_panels import TaskEditorPanel, TaskHistoryPanels, TaskLifecycle
        from taskweave.presentation.tasks import TaskCommands
        self.commands = TaskCommands(controller.call)
        self.editor_panel = editor_panel or TaskEditorPanel(
            render_step_details or _noop, save_step or _noop, prepare_step_leave,
            discard_step_for_tab, create_first_step)
        self.history_panels = history_panels or TaskHistoryPanels(
            render_execution_history or _noop, render_debug_history or _noop, open_task_execution or _noop)
        self.lifecycle = lifecycle or TaskLifecycle(on_runs_cleared or _noop, on_task_deleted or _noop,
                                                   before_task_update or _noop, after_task_update or _noop)
        self.controller = controller
        self.button = button
        self.navigate = navigate
        self.repaint = repaint
        self.catalog_filter = CatalogFilter()
        self.task_id = task_id or (lambda: None)
        self.step_id = step_id or (lambda: None)
        self.page_generation = page_generation or (lambda: 0)
        self.page_identity = page_identity or (lambda: ("tasks", self.page_generation()))
        self.workspace_tab = "overview"
        self.workspace_generation = 0
        self.workspace_switch_generation = 0
        self.workspace_views = {}
        self.organization = TaskOrganization(controller.call, self.page_identity)
        self.organization_by_task_id = self.organization.records
        self.organization_locks = self.organization.locks
        self._refresh_organization_controls = None
        self.category_manager = CategoryManager(controller, button, repaint, self.refresh_organization_controls)

    def dispose(self):
        self.workspace_generation += 1
        self.workspace_views.clear()

    def _workspace_identity(self):
        return (self.task_id(), self.page_generation(), self.workspace_generation)

    def _workspace_current(self, identity):
        return identity == self._workspace_identity() and identity[0] is not None

    async def render(self):
        if self.task_id():
            self.workspace_tab = "overview"
            await self.render_task_workspace()
            return
        tasks = await self.controller.call("task.list")
        self._remember_task_organizations(tasks)
        if tasks:
            initial = next((task for task in tasks if self._task_organization(task)["is_favorite"]), tasks[0])
            await self.navigate("tasks", task_id=initial["task_id"])
            return
        await self.task_list()

    async def task_list(self):
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("任务").classes("text-xl font-medium")
            with ui.row():
                self.category_manager.render_button()
                self.button("导入任务", self.import_task_dialog)
                self.button("新建任务", lambda: self.task_dialog(), primary=True)
        tasks = await self.controller.call("task.list")
        categories = await self.controller.call("organization.category.list")
        category_options = {"": "未分类"} | {item["category_id"]: item["name"] for item in categories}
        filter_options = {"": "全部任务", "favorites": "仅收藏"} | {item["category_id"]: item["name"] for item in categories}
        self._remember_task_organizations(tasks)
        with ui.row().classes("tw-panel w-full items-center gap-4 flex-wrap"):
            search = ui.input("搜索任务", value=self.search_query, placeholder="搜索名称或说明").props(
                "clearable debounce=250 prepend-icon=search"
            ).classes("grow min-w-72")
            self.catalog_filter.reset_category()
            category_filter = ui.select(filter_options, value=self.catalog_filter.category, label="分类筛选").classes("w-48")
            result_count = ui.label().classes("text-sm text-gray-500 whitespace-nowrap")
        task_list_area = ui.column().classes("w-full gap-4")

        def render_tasks():
            visible = self.catalog_filter.tasks(tasks)
            result_count.text = (
                f"共 {len(tasks)} 个任务"
                if not self.search_query.strip()
                else f"找到 {len(visible)} 个，共 {len(tasks)} 个"
            )
            task_list_area.clear()
            with task_list_area:
                if not tasks:
                    ui.label("暂无任务").classes("tw-panel w-full")
                    return
                if not visible:
                    with ui.column().classes("tw-panel w-full items-center py-10 gap-2"):
                        ui.icon("search_off", size="2.5rem").classes("text-gray-400")
                        ui.label("没有找到匹配任务").classes("font-medium")
                    return
                for task in visible:
                    with ui.column().classes("tw-panel w-full gap-3"):
                        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                            with ui.column().classes("gap-1 grow min-w-40"):
                                ui.label(task["name"]).classes("font-medium")
                                ui.label(task["description"] or "暂无说明").classes("text-gray-500")
                            with ui.row().classes("items-center gap-2"):
                                favorite_control_ref = {"control": None}
                                def toggle_favorite(t=task, ref=favorite_control_ref):
                                    return self.set_organization(t, toggle_favorite=True, favorite_control=ref["control"])
                                favorite_control_ref["control"] = self.button(
                                    "★" if self._task_organization(task)["is_favorite"] else "☆", toggle_favorite,
                                )
                                ui.select(category_options, value=self._task_organization(task)["category_id"] or "", label="分类").on_value_change(
                                    lambda event, t=task: self.set_organization(t, category_id=event.value or None)
                                ).classes("w-36")
                        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                            self.button("打开", lambda t=task: self.open_task(t), primary=True)
                            self.button("复制", lambda t=task: self.copy_task(t))
                            self.button("导出", lambda t=task: self.export_task_dialog(t))
                            self.button("清理运行", lambda t=task: self.clear_task_runs(t))
                            self.button("", lambda t=task: self.delete_task(t), flat=True).props("icon=delete round dense text-color=red-7 aria-label=删除").classes("tw-danger").tooltip("删除任务")

        def search_changed(event):
            self.search_query = event.value or ""
            render_tasks()
        def category_changed(event):
            self.catalog_filter.category = event.value or ""
            render_tasks()
        search.on_value_change(search_changed)
        category_filter.on_value_change(category_changed)
        render_tasks()
        expected_identity = self.page_identity()

        async def refresh_task_list_organization():
            if expected_identity != self.page_identity() or any(control.is_deleted for control in (search, category_filter, task_list_area)):
                return False
            latest_categories = await self.controller.call("organization.category.list")
            if expected_identity != self.page_identity() or any(control.is_deleted for control in (search, category_filter, task_list_area)):
                return False
            latest_tasks = await self.controller.call("task.list")
            if expected_identity != self.page_identity() or any(control.is_deleted for control in (search, category_filter, task_list_area)):
                return False
            tasks[:] = latest_tasks
            self._remember_task_organizations(latest_tasks)
            category_options.clear()
            category_options.update({"": "未分类"} | {item["category_id"]: item["name"] for item in latest_categories})
            filter_options = {"": "全部任务", "favorites": "仅收藏"} | {item["category_id"]: item["name"] for item in latest_categories}
            self.catalog_filter.retain_categories(filter_options)
            category_filter.set_options(filter_options, value=self.catalog_filter.category)
            render_tasks()
            return True

        self._refresh_organization_controls = refresh_task_list_organization

    def _remember_task_organizations(self, tasks):
        self.organization.remember(tasks)

    def _task_organization(self, task):
        return self.organization.metadata(task)

    async def set_organization(self, task, *, favorite=_ORGANIZATION_UNSET, category_id=_ORGANIZATION_UNSET,
                               toggle_favorite=False, favorite_control=None):
        identity = self.page_identity()
        try:
            result = await self.organization.update(task, favorite=favorite, category_id=category_id,
                                                    toggle_favorite=toggle_favorite)
        except Exception as exc:
            if identity == self.page_identity() and (favorite_control is None or not favorite_control.is_deleted):
                ui.notify(f"收藏或分类保存失败：{exc}", type="negative")
            return False
        if not result.current:
            return result.saved
        if favorite_control is not None and not favorite_control.is_deleted:
            favorite_control.text = "★" if result.metadata['is_favorite'] else "☆"
            favorite_control.update()
        if self._refresh_organization_controls:
            await self._refresh_organization_controls()
        return result.saved

    async def refresh_organization_controls(self):
        if self._refresh_organization_controls:
            return await self._refresh_organization_controls()
        return False

    async def open_task(self, task):
        previous_tab = self.workspace_tab
        self.workspace_tab = "steps"
        navigated = await self.navigate("editor", task_id=task["task_id"])
        if not navigated:
            self.workspace_tab = previous_tab

    async def select_task(self, task):
        if task["task_id"] == self.task_id():
            tabs = getattr(self, "_workspace_tabs", None)
            if tabs is not None:
                return await self.select_workspace_tab("overview", tabs)
            return self.workspace_tab == "overview"
        return await self.navigate("tasks", task_id=task["task_id"])

    async def create_first_step(self, task_id):
        if not self.editor_panel.create_first or self.task_id() != task_id:
            return False
        previous_tab = self.workspace_tab
        self.workspace_tab = "steps"
        result = await self.editor_panel.create_first(task_id)
        if result is False and self.task_id() == task_id:
            self.workspace_tab = previous_tab
        return result

    async def select_workspace_tab(self, value, tabs):
        from taskweave.presentation.workspace import TaskTabTransition

        transition = TaskTabTransition(self.workspace, value, page=self.page_identity()[0])
        identity = self._workspace_identity()
        action = transition.begin()
        if action.kind == "route_editor":
            try:
                accepted = await self.navigate("editor", task_id=self.task_id())
            except Exception:
                action = transition.route_result(False)
                if action.kind == "restore_tab" and not tabs.is_deleted:
                    tabs.value = action.value
                    tabs.update()
                raise
            action = transition.route_result(accepted)
        elif action.kind == "leave_editor":
            try:
                decision = await self.editor_panel.prepare_leave() if self.editor_panel.prepare_leave else "save"
                if self.editor_panel.prepare_leave is None:
                    await self.editor_panel.save()
            except Exception as exc:
                if (transition.token != self.workspace_switch_generation
                        or not self._workspace_current(identity)):
                    return False
                ui.notify(f"步骤保存失败，仍停留在步骤详情：{exc}", type="negative", timeout=8000)
                decision = "stay"
            if not self._workspace_current(identity):
                return False
            action = transition.resolve(decision)
        if action.kind == "done":
            return action.value
        if action.kind == "restore_tab":
            if not tabs.is_deleted and tabs.value != action.value:
                tabs.value = action.value
                tabs.update()
            return False
        if action.kind == "discard_render" and self.editor_panel.discard_for_tab:
            await self.editor_panel.discard_for_tab(value)
            return False
        if not tabs.is_deleted and tabs.value != value:
            tabs.value = value
            tabs.update()
        area = self.workspace_views.get(value)
        if area is not None and value not in getattr(self, "workspace_loaded", set()):
            if area.is_deleted or not self._workspace_current(identity):
                return False
            area.clear()
            with area:
                await self._render_workspace_panel(value, identity)
            if (transition.token != self.workspace_switch_generation
                    or not self._workspace_current(identity)):
                return False
            self.workspace_loaded.add(value)
        return True

    async def render_task_workspace(self, initial_tab=None):
        task_id = self.task_id()
        if not task_id:
            ui.label("请先选择任务。")
            return
        if initial_tab in self.WORKSPACE_TABS:
            self.workspace_tab = initial_tab
        identity = self._workspace_identity()
        task = await self.controller.call("task.get", task_id=task_id)
        if not self._workspace_current(identity):
            return
        steps = await self.controller.call("step.list", task_id=task_id)
        if not self._workspace_current(identity):
            return
        runs = await self.controller.call("run.list", task_id=task_id)
        if not self._workspace_current(identity):
            return
        tasks = await self.controller.call("task.list")
        if not self._workspace_current(identity):
            return
        categories = await self.controller.call("organization.category.list")
        if not self._workspace_current(identity):
            return
        self._remember_task_organizations(tasks)
        task_row = next((row for row in tasks if row["task_id"] == task_id), {})
        task.update(self._task_organization(task_row))
        category_names = {item["category_id"]: item["name"] for item in categories}
        filter_options = {"": "全部任务", "favorites": "仅收藏"} | category_names
        step_counts = {task_id: len(steps)}
        for row in tasks:
            if row["task_id"] == task_id:
                continue
            row_steps = await self.controller.call("step.list", task_id=row["task_id"])
            if not self._workspace_current(identity):
                return
            step_counts[row["task_id"]] = len(row_steps)

        with ui.row().classes("tw-task-workspace w-full items-start flex-wrap lg:flex-nowrap"):
            with ui.column().classes("tw-task-sidebar tw-panel w-full lg:w-72 shrink-0 gap-3"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label("任务").classes("text-lg font-medium")
                    self.button("分类管理", self.category_manager.open, flat=True)
                    self.button("+", lambda: self.task_dialog(), flat=True).props("round dense aria-label=新建任务")
                search = ui.input("搜索任务", value=self.search_query, placeholder="搜索名称或说明").props(
                    "clearable debounce=250 prepend-icon=search"
                ).classes("w-full")
                self.catalog_filter.reset_category()
                category_filter = ui.select(filter_options, value=self.catalog_filter.category, label="任务范围").classes("w-full")
                task_rows = ui.column().classes("w-full gap-2")

                def render_task_rows():
                    task_rows.clear()
                    visible = self.catalog_filter.tasks(tasks)
                    with task_rows:
                        if not visible:
                            ui.label("没有匹配的任务").classes("text-sm text-gray-500")
                        for row in visible:
                            selected = row["task_id"] == task_id
                            card = ui.element("div").classes("tw-task-nav-card w-full gap-1" + (" tw-selected" if selected else "")).props("role=button tabindex=0")
                            card.on("click", lambda _event, t=row: self.select_task(t))
                            card.on("keydown.enter", lambda _event, t=row: self.select_task(t))
                            card.on("keydown.space", lambda _event, t=row: self.select_task(t))
                            with card:
                                ui.label(row["name"]).classes("tw-task-nav-name").tooltip(row["name"])
                                with ui.row().classes("tw-task-nav-meta w-full items-center gap-2"):
                                    category = category_names.get(row.get("category_id"), "未分类")
                                    ui.label(category).classes("tw-home-tag")
                                    ui.label(short_updated_at(row.get("updated_at") or row.get("created_at"))).classes("tw-home-task-meta")
                                    ui.label(f"{step_counts.get(row['task_id'], 0)} 个步骤").classes("tw-home-task-meta")
                def search_changed(event):
                    self.search_query = event.value or ""
                    render_task_rows()
                def category_changed(event):
                    self.catalog_filter.category = event.value or ""
                    render_task_rows()
                search.on_value_change(search_changed)
                category_filter.on_value_change(category_changed)
                render_task_rows()

                expected_page_identity = self.page_identity()

                async def refresh_workspace_organization():
                    def current():
                        return (expected_page_identity == self.page_identity()
                                and self._workspace_identity() == identity
                                and not category_filter.is_deleted and not search.is_deleted and not task_rows.is_deleted)
                    if not current():
                        return False
                    latest_categories = await self.controller.call("organization.category.list")
                    if not current():
                        return False
                    latest_tasks = await self.controller.call("task.list")
                    if not current():
                        return False
                    tasks[:] = latest_tasks
                    self._remember_task_organizations(latest_tasks)
                    category_names.clear()
                    category_names.update({item["category_id"]: item["name"] for item in latest_categories})
                    options = {"": "全部任务", "favorites": "仅收藏"} | category_names
                    self.catalog_filter.retain_categories(options)
                    category_filter.set_options(options, value=self.catalog_filter.category)
                    render_task_rows()
                    return True

                self._refresh_organization_controls = refresh_workspace_organization

            with ui.column().classes("tw-task-detail min-w-0 grow gap-4"):
                with ui.row().classes("tw-task-workspace-header w-full justify-between items-center flex-nowrap gap-3"):
                    with ui.column().classes("tw-task-heading gap-1 min-w-0 grow"):
                        ui.label(task["name"]).classes("text-2xl font-semibold")
                        task_description = task.get("description") or "暂无说明"
                        ui.label(task_description).classes("tw-task-summary text-sm text-gray-500").tooltip(task_description)
                    with ui.row().classes("tw-task-header-actions items-center gap-2 flex-nowrap shrink-0"):
                        favorite_control_ref = {"control": None}
                        def toggle_task_favorite(ref=favorite_control_ref):
                            return self.set_organization(task, toggle_favorite=True, favorite_control=ref["control"])
                        favorite_control_ref["control"] = self.button("★" if self._task_organization(task)["is_favorite"] else "☆",
                                                                      toggle_task_favorite, flat=True)
                        self.button("编辑步骤", lambda: self.open_task(task), flat=True)
                        self.button("新建执行", lambda: self.history_panels.open_execution(task_id), primary=True)
                        with ui.button("更多", icon="more_horiz").props("flat"):
                            with ui.menu():
                                ui.menu_item("任务配置", lambda: self.task_dialog(task))
                                ui.menu_item("调试历史", lambda: self.select_workspace_tab("debug_history", tabs))
                                ui.menu_item("复制任务", lambda: self.copy_task(task))
                                ui.menu_item("导出任务", lambda: self.export_task_dialog(task))
                                ui.menu_item("清理运行", lambda: self.clear_task_runs(task))
                                ui.menu_item("删除任务", lambda: self.delete_task(task))

                with ui.tabs().classes("w-full tw-task-tabs") as tabs:
                    overview = ui.tab("overview", label="任务概览")
                    steps_tab = ui.tab("steps", label="步骤管理")
                    execution_tab = ui.tab("execution_history", label="执行历史")
                    debug_tab = ui.tab("debug_history", label="调试历史")
                tabs.value = self.workspace_tab
                with ui.tab_panels(tabs, value=self.workspace_tab).classes("w-full"):
                    panels = {}
                    for tab_name, tab in (("overview", overview), ("steps", steps_tab), ("execution_history", execution_tab), ("debug_history", debug_tab)):
                        with ui.tab_panel(tab):
                            panels[tab_name] = ui.column().classes("w-full gap-4")

        self.workspace_views = panels
        self._workspace_tabs = tabs
        self.workspace_loaded = set()
        tabs.on_value_change(lambda event: self.select_workspace_tab(event.value, tabs))
        self.workspace_views["overview"].clear()
        with self.workspace_views["overview"]:
            await self._render_workspace_panel("overview", identity, task=task, steps=steps, runs=runs)
        if not self._workspace_current(identity):
            return
        self.workspace_loaded.add("overview")
        if self.workspace_tab != "overview":
            area = self.workspace_views[self.workspace_tab]
            with area:
                await self._render_workspace_panel(self.workspace_tab, identity, task=task, steps=steps, runs=runs)
            if not self._workspace_current(identity):
                return
            self.workspace_loaded.add(self.workspace_tab)

    async def _render_workspace_panel(self, name, identity, *, task=None, steps=None, runs=None):
        if not self._workspace_current(identity):
            return
        task_id = identity[0]
        if name == "overview":
            steps = steps if steps is not None else await self.controller.call("step.list", task_id=task_id)
            if not self._workspace_current(identity):
                return
            runs = runs if runs is not None else await self.controller.call("run.list", task_id=task_id)
            if not self._workspace_current(identity):
                return
            task = task or await self.controller.call("task.get", task_id=task_id)
            if not self._workspace_current(identity):
                return
            executions = [run for run in runs if run.get("mode") == "EXECUTION"]
            debug_runs = [run for run in runs if run.get("mode") == "TRIAL"]
            validated = sum(step.get("validation_state") == "VALIDATED" for step in steps)
            schema = json.loads(task["input_schema_json"])
            properties = schema.get("properties", {})
            with ui.column().classes("w-full gap-4"):
                with ui.column().classes("tw-panel w-full gap-3"):
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.label("任务说明").classes("text-lg font-medium")
                        self.button("编辑", lambda: self.task_dialog(task), flat=True)
                    ui.label(task.get("description") or "暂无说明").classes("tw-task-overview-description text-gray-600")
                    with ui.row().classes("gap-2 flex-wrap"):
                        ui.label(f"{len(steps)} 个步骤").classes("tw-status-chip")
                        ui.label(f"{validated} 个已确认").classes("tw-status-chip")
                with ui.column().classes("tw-panel w-full gap-3"):
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.label("任务变量").classes("text-lg font-medium")
                        self.button("编辑变量", lambda: self.task_dialog(task), flat=True)
                    columns = [
                        {"name": "name", "label": "名称", "field": "name", "align": "left"},
                        {"name": "type", "label": "类型", "field": "type", "align": "left"},
                        {"name": "required", "label": "必填", "field": "required", "align": "left"},
                        {"name": "default", "label": "默认值", "field": "default", "align": "left"},
                        {"name": "description", "label": "说明", "field": "description", "align": "left"},
                    ]
                    rows = [{"name": key, "type": spec.get("type", "any"), "required": "是" if key in schema.get("required", []) else "否",
                             "default": str(spec.get("default", "—")), "description": spec.get("description", "—")}
                            for key, spec in properties.items()]
                    if rows:
                        ui.table(columns=columns, rows=rows, row_key="name").props("flat dense").classes("tw-task-variable-table w-full")
                    else:
                        ui.label("未定义任务变量").classes("text-sm text-gray-500")
                with ui.row().classes("tw-task-overview-bottom w-full items-stretch"):
                    with ui.column().classes("tw-panel gap-3"):
                        ui.label("执行统计").classes("text-lg font-medium")
                        status_counts = {status: sum(run.get("status") == status for run in executions)
                                         for status in ("SUCCEEDED", "FAILED", "RUNNING", "WAITING_INPUT")}
                        with ui.row().classes("tw-task-stat-grid w-full"):
                            for label, status in (("成功", "SUCCEEDED"), ("失败", "FAILED"), ("运行中", "RUNNING"), ("等待输入", "WAITING_INPUT")):
                                with ui.column().classes("tw-task-stat"):
                                    ui.label(str(status_counts[status])).classes("tw-task-stat-value")
                                    ui.label(label).classes("text-sm text-gray-500")
                        ui.label(f"累计 {len(executions)} 次执行 · {len(debug_runs)} 次调试").classes("text-sm text-gray-500")
                    with ui.column().classes("tw-panel gap-3"):
                        ui.label("最近调试").classes("text-lg font-medium")
                        latest_debug = max(debug_runs, key=lambda run: run.get("started_at") or run.get("created_at") or "", default=None)
                        if latest_debug:
                            ui.label(run_status_label(latest_debug.get("status"))).classes("tw-status-chip")
                            ui.label(f"{latest_debug.get('step_name') or '调试运行'} · {short_updated_at(latest_debug.get('started_at') or latest_debug.get('created_at'))}").classes("text-sm text-gray-600")
                            self.button("查看调试历史", lambda: self.select_workspace_tab("debug_history", self._workspace_tabs), flat=True)
                        else:
                            ui.label("暂无调试记录").classes("text-sm text-gray-500")
            return
        if name == "steps":
            await self.editor_panel.render()
            return
        callback = self.history_panels.execution if name == "execution_history" else self.history_panels.debug
        await callback(task_id)

    async def copy_task(self, task):
        await self.controller.call("task.copy", task_id=task["task_id"])
        await self.repaint()

    async def save_task(self, task, name, input_schema, description, *, before_update=None):
        if not name.strip():
            raise TaskError('FORM_INVALID', '请填写任务名称')
        if task and before_update:
            await before_update()
        return await self.commands.save(task, name, input_schema, description)

    async def create_and_open_task(self, name, input_schema, description):
        saved = await self.save_task(None, name, input_schema, description)
        self.workspace_tab = "overview"
        await self.navigate("editor", task_id=saved["task_id"])
        return saved

    async def export_task_dialog(self, task):
        package = await self.controller.call("task.export", task_id=task["task_id"])
        text = document_text(package)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label(task["name"] + " · 导出任务").classes("text-lg")
            ui.label("包含任务与步骤参数、步骤内容和绑定，以及采集上下文和图片预览；不包含环境和执行历史。")
            ui.textarea("任务 JSON", value=text).props("readonly").classes("w-full").style("max-height: 65vh; overflow: auto")

            async def copy():
                await self.controller.copy_text(text)
                ui.notify("任务 JSON 已复制")

            async def download():
                if self.controller.native:
                    path = await self.controller.save_task_export(text)
                    ui.notify("任务 JSON 已保存：" + str(path), timeout=8000)
                else:
                    ui.download.content(text, filename="taskweave-task.json", media_type="application/json")

            with ui.row():
                self.button("复制 JSON", copy)
                self.button("下载 JSON", download)
                ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()

    async def import_task_dialog(self):
        draft = TaskImportSession(lambda package: self.controller.call("task.import", package=package))
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("导入任务").classes("text-lg")
            ui.label("导入任务 JSON 创建独立副本，保留步骤对应的素材及预览。已有任务导出会恢复每步状态；AI 生成任务的步骤均为待确认。请先启用所需插件。")
            mode = ui.toggle({'file': '选择 JSON 文件', 'text': '粘贴 JSON'}, value='file')
            mode.on_value_change(lambda event: setattr(draft, 'mode', event.value))
            dialog.on('hide', draft.close)
            with ui.column().classes('w-full').bind_visibility_from(mode, 'value', lambda value: value == 'file'):
                status = ui.label('请选择任务 JSON 文件，最大 32 MiB。')

                def clear_file():
                    draft.clear_file()
                    status.set_text('请选择任务 JSON 文件，最大 32 MiB。')

                async def load_file(event):
                    clear_file()
                    try:
                        token = draft.begin_file(event.file.size())
                        content = await event.file.read()
                        if not draft.accept_file(token, content):
                            return
                    except (UnicodeError, ValueError):
                        if not dialog.is_deleted and dialog.value:
                            status.set_text('文件无效：请选择不超过 32 MiB 的 UTF-8 JSON 文件。')
                        return
                    if dialog.is_deleted or not dialog.value:
                        return
                    status.set_text(f'已读取：{event.file.name}（{len(content) / 1024 / 1024:.2f} MiB），点击“导入为新任务”完成导入。')

                ui.upload(label='任务 JSON 文件', auto_upload=True, max_files=1,
                          max_file_size=TASK_IMPORT_LIMIT_BYTES, on_upload=load_file,
                          on_rejected=clear_file).props('accept=".json,application/json"').classes('w-full').on('removed', clear_file)
            source = ui.textarea("任务 JSON").classes("w-full").props('placeholder="仅粘贴小型任务；包含截图的任务请选择 JSON 文件"')
            source.bind_visibility_from(mode, 'value', lambda value: value == 'text')

            source.on_value_change(lambda event: setattr(draft, 'source', event.value))

            async def import_package():
                if await draft.submit() is None:
                    return
                dialog.close()
                await self.repaint()
                ui.notify("任务已导入，步骤状态已按任务包恢复")

            with ui.row():
                self.button("导入为新任务", import_package, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()

    async def clear_task_runs(self, task):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl"):
            ui.label("清理任务“" + task["name"] + "”的全部运行数据？").classes("text-lg")
            ui.label("保留任务配置、步骤及验证状态；删除执行和调试记录、结果、截图、文件及调试对话。保留的插件资源也会关闭，删除后无法恢复。")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                ui.button("确认清理", on_click=lambda: dialog.submit(True)).props("outline color=negative")
        if await dialog:
            result = await self.controller.call("task.clear_runs", task_id=task["task_id"])
            await self.lifecycle.runs_cleared(task["task_id"])
            ui.notify("已清理 " + str(result["deleted_runs"]) + " 条运行记录", type="positive")
            await self.repaint()

    async def delete_task(self, task):
        with ui.dialog() as dialog, ui.card():
            ui.label("删除任务“" + task["name"] + "”及其全部执行记录、结果？")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                ui.button("确认删除", on_click=lambda: dialog.submit(True)).props("color=negative")
        if await dialog:
            await self.controller.call("task.delete", task_id=task["task_id"])
            await self.lifecycle.deleted(task["task_id"])
            await self.repaint()

    async def task_dialog(self, task=None):
        from taskweave.presentation.tasks import TaskDraft
        if task is not None:
            task = await self.controller.call("task.get", task_id=task["task_id"])
        draft = TaskDraft(task)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
            ui.label("任务配置" if task else "新建任务").classes("text-lg")
            name = ui.input("任务名称", value=task["name"] if task else "").classes("w-full")
            description = ui.textarea("说明", value=task["description"] if task else "").classes("w-full")
            schema = SchemaEditor(draft.schema_original)
            name.on_value_change(lambda event: setattr(draft, 'name', event.value))
            description.on_value_change(lambda event: setattr(draft, 'description', event.value))
            schema.on_change = lambda: setattr(draft, 'schema_rows', schema.raw_rows())
            schema.on_change()

            async def save():
                saved = await self.save_task(
                    task, draft.name, draft.schema(), draft.description,
                    before_update=self.lifecycle.before_update if task else None,
                )
                dialog.close()
                if task:
                    await self.lifecycle.after_update(saved)
                    if self.lifecycle.before_update is _noop:
                        await self.repaint()
                else:
                    self.workspace_tab = "overview"
                    await self.navigate("editor", task_id=saved["task_id"])

            with ui.row():
                self.button("保存", save, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()


async def _noop(*args, **kwargs):
    return None
