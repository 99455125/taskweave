"""Execution filters page."""

from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.presentation.run_creation import RunCreation

STATUS = {
    "READY": "就绪", "RUNNING": "执行中", "PAUSED": "已暂停", "FAILED": "失败",
    "INTERRUPTED": "中断 / 待核对", "SUCCEEDED": "成功", "CANCELLED": "已结束",
}


class ExecutionsPage(Page):
    def __init__(self, controller, state, button, render_runs):
        self.controller, self.state = controller, state
        self.button, self.render_runs = button, render_runs

    async def render(self):
        tasks = await self.controller.call("task.list")
        if not tasks:
            ui.label("执行").classes("text-xl font-medium")
            return
        valid_ids = {task["task_id"] for task in tasks}
        self.state.task_ids = [value for value in self.state.task_ids if value in valid_ids]
        with ui.row().classes("tw-executions-master w-full min-w-0"):
            with ui.column().classes("tw-panel tw-execution-filters gap-3"):
                ui.label("执行").classes("text-lg font-semibold")
                search = ui.input("搜索任务或运行", value=self.state.search_query, placeholder="名称或运行 ID").props("clearable debounce=250 prepend-icon=search").classes("w-full")
                task_filter = ui.select(
                    {task["task_id"]: task["name"] for task in tasks},
                    value=self.state.task_ids,
                    label="任务筛选（可多选）",
                    multiple=True,
                    clearable=True,
                ).props("use-chips use-input input-debounce=0").classes("w-full")
                status_filter = ui.select(
                    {key: value for key, value in STATUS.items() if key in {"READY", "RUNNING", "PAUSED", "FAILED", "INTERRUPTED", "SUCCEEDED", "CANCELLED"}},
                    value=self.state.statuses,
                    label="状态筛选",
                    multiple=True,
                    clearable=True,
                ).props("use-chips").classes("w-full")

                async def apply_filters():
                    self.state.signature = None
                    await self.render_runs()

                async def search_changed(event):
                    self.state.search_query = event.value or ""
                    await apply_filters()

                async def tasks_changed(event):
                    self.state.task_ids = list(event.value or [])
                    await apply_filters()

                async def statuses_changed(event):
                    self.state.statuses = list(event.value or [])
                    await apply_filters()

                async def clear_filters():
                    self.state.task_ids = []
                    self.state.statuses = []
                    self.state.search_query = ""
                    task_filter.value = self.state.task_ids
                    status_filter.value = self.state.statuses
                    search.value = self.state.search_query
                    task_filter.update(); status_filter.update(); search.update()
                    await apply_filters()

                search.on_value_change(search_changed)
                task_filter.on_value_change(tasks_changed)
                status_filter.on_value_change(statuses_changed)
                with ui.row().classes("w-full justify-between items-center"):
                    self.button("清除筛选", clear_filters, flat=True)
                    ui.label("任务与状态").classes("text-xs text-gray-500")
                ui.label("执行实例").classes("tw-execution-list-title text-sm font-medium text-gray-500")
                self.state.execution_list_area = ui.column().classes("tw-run-list w-full gap-3")
            with ui.column().classes("tw-content tw-executions-main w-full min-w-0"):
                await self.render_runs()


class RunPage(Page):
    """Create executions and own the run-page render/timer boundary."""

    def __init__(self, controller, state, button, paint, environment_select,
                 trial_variables, execution_details, page, page_generation):
        self.controller, self.state, self.button = controller, state, button
        self.paint, self.environment_select, self.trial_variables = paint, environment_select, trial_variables
        self.execution_details, self.page, self.page_generation = execution_details, page, page_generation
        self.creation = RunCreation(controller, state)

    @property
    def pending_task_id(self): return self.creation.pending_task_id
    @pending_task_id.setter
    def pending_task_id(self, value): self.creation.pending_task_id = value
    @property
    def pending_open_create(self): return self.creation.pending_open_create
    @pending_open_create.setter
    def pending_open_create(self, value): self.creation.pending_open_create = value

    def dispose(self):
        self.execution_details.dispose()

    @property
    def run_id(self): return self.state.run_id
    @run_id.setter
    def run_id(self, value): self.state.run_id = value
    @property
    def execution_task_ids(self): return self.state.task_ids
    @property
    def execution_signature(self): return self.state.signature
    @execution_signature.setter
    def execution_signature(self, value): self.state.signature = value
    @property
    def execution_rows(self): return self.state.execution_rows
    @execution_rows.setter
    def execution_rows(self, value): self.state.execution_rows = value
    @property
    def run_area(self): return self.state.run_area
    @run_area.setter
    def run_area(self, value): self.state.run_area = value

    async def open_create(self, initial_task_id=None, *, on_created=None):
        flow = self.creation
        await flow.load()
        warning = flow.open(initial_task_id)
        if warning:
            ui.notify(warning, type="warning")
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("新建执行").classes("text-lg")
            task_select = ui.select(
                {task["task_id"]: task["name"] for task in flow.eligible},
                value=flow.task_id,
                label="选择任务",
            ).props("use-input input-debounce=0").classes("w-full")
            environment = await self.environment_select()
            steps = flow.steps
            start = ui.select({step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(steps)}, value=flow.start_step_id, label='开始步骤').classes('w-full')
            input_area = ui.column().classes('w-full')
            async def render_inputs():
                input_area.clear()
                start.options = {step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(flow.steps)}
                start.value = flow.start_step_id
                start.update()
                with input_area:
                    form = await self.trial_variables(flow.selected_step, environment, task_id=flow.task_id)
                    flow.input_draft = form.input_draft

            async def select_start(event):
                flow.select_start(event.value)
                await render_inputs()

            async def select_task(event):
                flow.select_task(event.value)
                await render_inputs()

            start.on_value_change(select_start)
            task_select.on_value_change(select_task)
            await render_inputs()
            async def save():
                await flow.submit()
                dialog.close()
                await (on_created or self.paint)()
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("创建并执行", save, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()

    async def render(self):
        flow = self.creation
        await flow.load()
        with ui.row().classes("tw-executions-toolbar w-full justify-between items-center"):
            ui.label("执行列表").classes("text-xl font-medium")
            self.button("新建执行", self.open_create, primary=True)
        self.execution_rows = ui.column().classes("tw-execution-rows tw-run-detail-area w-full gap-3")
        self.execution_signature = None
        self.run_area = None
        page_generation = self.page_generation()
        async def refresh_current_runs():
            if self.page_generation() == page_generation and self.page() in {'run', 'executions'}:
                await self.execution_details.poll()
        self.execution_details.own_timer(ui.timer(1, refresh_current_runs))
        await self.execution_details.refresh()
        requested, task_id = flow.consume_pending()
        if requested:
            await self.open_create(task_id)
