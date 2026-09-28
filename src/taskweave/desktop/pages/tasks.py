"""Task list and task configuration page operations."""

import asyncio
import json
from datetime import datetime
from nicegui import ui
from taskweave.desktop.pages.base import Page

from taskweave.core.validation import TaskError
from taskweave.desktop.forms import SchemaEditor
from taskweave.desktop.components.organization import CategoryManager

_ORGANIZATION_UNSET = object()


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


def filter_tasks(tasks, query, favorite=None, category_id=None):
    query = (query or "").strip().casefold()
    if not query:
        visible = list(tasks)
    else:
        visible = [
        task for task in tasks
        if query in (task.get("name") or "").casefold()
        or query in (task.get("description") or "").casefold()
        ]
    if favorite is True:
        visible = [task for task in visible if task.get("is_favorite")]
    if category_id:
        visible = [task for task in visible if task.get("category_id") == category_id]
    return visible


class TasksPage(Page):
    """Own task list/config UI; all cross-page behavior is an explicit callback."""

    WORKSPACE_TABS = ("overview", "steps", "execution_history", "debug_history")

    def __init__(self, controller, button, navigate, repaint, *, on_runs_cleared=None, on_task_deleted=None, before_task_update=None, after_task_update=None,
                 task_id=None, step_id=None, page_generation=None, save_step=None, render_step_details=None,
                 render_execution_history=None, render_debug_history=None, open_task_execution=None,
                 prepare_step_leave=None, discard_step_for_tab=None, create_first_step=None, page_identity=None):
        self.controller = controller
        self.button = button
        self.navigate = navigate
        self.repaint = repaint
        self.on_runs_cleared = on_runs_cleared or _noop
        self.on_task_deleted = on_task_deleted or _noop
        self.before_task_update = before_task_update or _noop
        self.after_task_update = after_task_update or _noop
        self.search_query = ""
        self.task_id = task_id or (lambda: None)
        self.step_id = step_id or (lambda: None)
        self.page_generation = page_generation or (lambda: 0)
        self.page_identity = page_identity or (lambda: ("tasks", self.page_generation()))
        self.save_step = save_step or _noop
        self.render_step_details = render_step_details or _noop
        self.render_execution_history = render_execution_history or _noop
        self.render_debug_history = render_debug_history or _noop
        self.open_task_execution = open_task_execution or _noop
        self.prepare_step_leave = prepare_step_leave
        self.discard_step_for_tab = discard_step_for_tab
        self.create_first_step_callback = create_first_step
        self.workspace_tab = "overview"
        self.workspace_generation = 0
        self.workspace_switch_generation = 0
        self.workspace_views = {}
        self.organization_by_task_id = {}
        self.organization_locks = {}
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
            category_filter = ui.select(filter_options, value="", label="分类筛选").classes("w-48")
            result_count = ui.label().classes("text-sm text-gray-500 whitespace-nowrap")
        task_list_area = ui.column().classes("w-full gap-4")

        def render_tasks():
            self.search_query = search.value or ""
            visible = filter_tasks(
                tasks, self.search_query,
                favorite=True if category_filter.value == "favorites" else None,
                category_id=category_filter.value if category_filter.value not in {"", "favorites"} else None,
            )
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

        search.on_value_change(lambda _: render_tasks())
        category_filter.on_value_change(lambda _: render_tasks())
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
            selected = category_filter.value
            category_filter.set_options(filter_options, value=selected if selected in filter_options else "")
            render_tasks()
            return True

        self._refresh_organization_controls = refresh_task_list_organization

    def _remember_task_organizations(self, tasks):
        for task in tasks:
            self.organization_by_task_id[task["task_id"]] = {
                "is_favorite": bool(task.get("is_favorite")),
                "category_id": task.get("category_id"),
            }

    def _task_organization(self, task):
        return self.organization_by_task_id.setdefault(task["task_id"], {
            "is_favorite": bool(task.get("is_favorite")), "category_id": task.get("category_id"),
        })

    async def set_organization(self, task, *, favorite=_ORGANIZATION_UNSET, category_id=_ORGANIZATION_UNSET,
                               toggle_favorite=False, favorite_control=None):
        task_id = task["task_id"]
        identity = self.page_identity()
        lock = self.organization_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            if identity != self.page_identity():
                return False
            current = self._task_organization(task).copy()
            if toggle_favorite:
                current["is_favorite"] = not current["is_favorite"]
            elif favorite is not _ORGANIZATION_UNSET:
                current["is_favorite"] = bool(favorite)
            if category_id is not _ORGANIZATION_UNSET:
                current["category_id"] = category_id
            try:
                await self.controller.call(
                    "organization.metadata.set", entity="task", entity_id=task_id,
                    is_favorite=current["is_favorite"], category_id=current["category_id"],
                )
            except Exception as exc:
                if identity == self.page_identity() and (favorite_control is None or not favorite_control.is_deleted):
                    ui.notify(f"收藏或分类保存失败：{exc}", type="negative")
                return False
            self.organization_by_task_id[task_id] = current
            task.update(current)
            if identity != self.page_identity():
                return True
            if favorite_control is not None and not favorite_control.is_deleted:
                favorite_control.text = "★" if current["is_favorite"] else "☆"
                favorite_control.update()
            if self._refresh_organization_controls:
                await self._refresh_organization_controls()
            return True

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
        if not self.create_first_step_callback or self.task_id() != task_id:
            return False
        previous_tab = self.workspace_tab
        self.workspace_tab = "steps"
        result = await self.create_first_step_callback(task_id)
        if result is False and self.task_id() == task_id:
            self.workspace_tab = previous_tab
        return result

    async def select_workspace_tab(self, value, tabs):
        if value not in self.WORKSPACE_TABS:
            return False
        # The step editor owns its own guarded route lifecycle. Route into it
        # before rendering the steps panel so async callbacks retain the same
        # identity checks as explicit “编辑步骤” navigation.
        if value == "steps" and self.page_identity()[0] != "editor":
            previous = self.workspace_tab
            self.workspace_tab = value
            try:
                navigated = await self.navigate("editor", task_id=self.task_id())
            except Exception:
                self.workspace_tab = previous
                if not tabs.is_deleted:
                    tabs.value = previous
                    tabs.update()
                raise
            if navigated is False:
                self.workspace_tab = previous
                if not tabs.is_deleted:
                    tabs.value = previous
                    tabs.update()
            return navigated
        self.workspace_switch_generation += 1
        switch_generation = self.workspace_switch_generation
        previous = self.workspace_tab
        identity = self._workspace_identity()
        if previous == "steps" and value != "steps":
            try:
                decision = await self.prepare_step_leave() if self.prepare_step_leave else "save"
                if self.prepare_step_leave is None:
                    await self.save_step()
            except Exception as exc:
                if (switch_generation != self.workspace_switch_generation
                        or not self._workspace_current(identity)):
                    return False
                ui.notify(f"步骤保存失败，仍停留在步骤详情：{exc}", type="negative", timeout=8000)
                decision = "stay"
            if (switch_generation != self.workspace_switch_generation
                    or not self._workspace_current(identity)):
                return False
            if decision == "stay":
                if not tabs.is_deleted and tabs.value != previous:
                    tabs.value = previous
                    tabs.update()
                return False
            if decision == "discard":
                self.workspace_tab = value
                if self.discard_step_for_tab:
                    await self.discard_step_for_tab(value)
                    return False
        self.workspace_tab = value
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
            if (switch_generation != self.workspace_switch_generation
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
                category_filter = ui.select(filter_options, value="", label="任务范围").classes("w-full")
                task_rows = ui.column().classes("w-full gap-2")

                def render_task_rows():
                    self.search_query = search.value or ""
                    task_rows.clear()
                    selected_filter = category_filter.value
                    visible = filter_tasks(tasks, self.search_query,
                                           favorite=True if selected_filter == "favorites" else None,
                                           category_id=selected_filter if selected_filter not in {"", "favorites"} else None)
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
                search.on_value_change(lambda _: render_task_rows())
                category_filter.on_value_change(lambda _: render_task_rows())
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
                    selected = category_filter.value
                    category_filter.set_options(options, value=selected if selected in options else "")
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
                        self.button("新建执行", lambda: self.open_task_execution(task_id), primary=True)
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
            await self.render_step_details()
            return
        callback = self.render_execution_history if name == "execution_history" else self.render_debug_history
        await callback(task_id)

    async def copy_task(self, task):
        await self.controller.call("task.copy", task_id=task["task_id"])
        await self.repaint()

    async def save_task(self, task, name, input_schema, description, *, before_update=None):
        if not name.strip():
            raise TaskError("FORM_INVALID", "请填写任务名称")
        if task:
            if before_update:
                await before_update()
            await self.controller.call(
                "task.update", task_id=task["task_id"], name=name.strip(),
                input_schema=input_schema, description=description,
            )
            return task
        return await self.controller.call(
            "task.create", name=name.strip(), input_schema=input_schema, description=description,
        )

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
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("导入任务").classes("text-lg")
            ui.label("粘贴任务 JSON 创建独立副本。已有任务导出会恢复每步状态；AI 生成任务的步骤均为待确认。请先启用所需插件。")
            source = ui.textarea("任务 JSON").classes("w-full").props('placeholder="粘贴导出的任务 JSON"')

            async def import_package():
                if len(source.value or "") > 2 * 1024 * 1024:
                    raise TaskError("TASK_PACKAGE_INVALID", "任务 JSON 超过 2MB")
                try:
                    package = json.loads(source.value or "")
                except ValueError as exc:
                    raise TaskError("TASK_PACKAGE_INVALID", "请粘贴有效 JSON") from exc
                await self.controller.call("task.import", package=package)
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
            await self.on_runs_cleared(task["task_id"])
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
            await self.on_task_deleted(task["task_id"])
            await self.repaint()

    async def task_dialog(self, task=None):
        if task is not None:
            task = await self.controller.call("task.get", task_id=task["task_id"])
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
            ui.label("任务配置" if task else "新建任务").classes("text-lg")
            name = ui.input("任务名称", value=task["name"] if task else "").classes("w-full")
            description = ui.textarea("说明", value=task["description"] if task else "").classes("w-full")
            schema = SchemaEditor(json.loads(task["input_schema_json"]) if task else None)

            async def save():
                saved = await self.save_task(
                    task, name.value, schema.schema(), description.value,
                    before_update=self.before_task_update if task else None,
                )
                dialog.close()
                if task:
                    await self.after_task_update(saved)
                    if self.before_task_update is _noop:
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
