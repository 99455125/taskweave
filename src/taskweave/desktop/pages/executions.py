"""Execution filters page."""

from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import command_id

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
            ui.label("暂无任务。请先在任务菜单中创建并确认步骤。").classes("tw-panel w-full text-gray-500")
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
                    self.state.search_query = search.value or ""
                    self.state.task_ids = list(task_filter.value or [])
                    self.state.statuses = list(status_filter.value or [])
                    self.state.signature = None
                    await self.render_runs()

                async def clear_filters():
                    task_filter.value = []
                    status_filter.value = []
                    search.value = ""
                    task_filter.update(); status_filter.update(); search.update()
                    await apply_filters()

                search.on_value_change(lambda _: apply_filters())
                task_filter.on_value_change(lambda _: apply_filters())
                status_filter.on_value_change(lambda _: apply_filters())
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
        self.pending_task_id = None
        self.pending_open_create = False

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

    async def render(self):
        tasks = await self.controller.call("task.list")
        task_steps = {}
        eligible = []
        for task in tasks:
            steps = await self.controller.call("step.list", task_id=task["task_id"])
            task_steps[task["task_id"]] = steps
            if steps and all(step["validation_state"] == "VALIDATED" for step in steps):
                eligible.append(task)
        with ui.row().classes("tw-executions-toolbar w-full justify-between items-center"):
            ui.label("执行列表").classes("text-xl font-medium")
            async def create(initial_task_id=None):
                if not eligible:
                    ui.notify("尚无步骤全部确认的任务。请先创建任务并确认全部步骤。", type="warning")
                    return
                if initial_task_id is not None and initial_task_id not in {task["task_id"] for task in eligible}:
                    ui.notify("该任务的步骤尚未全部确认，不能创建执行。", type="warning")
                    return
                with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
                    ui.label("新建执行").classes("text-lg")
                    task_select = ui.select(
                        {task["task_id"]: task["name"] for task in eligible},
                        value=initial_task_id or eligible[0]["task_id"],
                        label="选择任务",
                    ).props("use-input input-debounce=0").classes("w-full")
                    environment = await self.environment_select()
                    steps = task_steps[task_select.value]
                    start = ui.select({step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(steps)}, value=steps[0]['step_id'] if steps else None, label='开始步骤').classes('w-full')
                    input_area = ui.column().classes('w-full')
                    selected_form = [None]

                    async def render_inputs():
                        input_area.clear()
                        current_steps = task_steps[task_select.value]
                        if start.value not in {step['step_id'] for step in current_steps}:
                            start.options = {step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(current_steps)}
                            start.value = current_steps[0]['step_id']
                            start.update()
                        selected = next(step for step in current_steps if step['step_id'] == start.value)
                        with input_area:
                            selected_form[0] = await self.trial_variables(selected, environment, task_id=task_select.value)

                    start.on_value_change(lambda _: render_inputs())
                    task_select.on_value_change(lambda _: render_inputs())
                    await render_inputs()
                    async def save():
                        form = selected_form[0]
                        selected_task_id = task_select.value
                        response = await self.controller.call("run.create", task_id=selected_task_id, inputs=form.task_draft_values(), step_inputs={start.value: form.step_draft_values()}, environment_id=environment.value or None, defer_inputs=True)
                        self.run_id = response["run_id"]
                        if self.execution_task_ids and selected_task_id not in self.execution_task_ids:
                            self.execution_task_ids.append(selected_task_id)
                        await self.controller.call('run.start', run_id=self.run_id, command_id=command_id(), mode='ALL', start_step_id=start.value)
                        dialog.close()
                        await self.paint()
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        self.button("创建并执行", save, primary=True)
                        ui.button("取消", on_click=dialog.close).props("outline")
                dialog.open()
            self.button("新建执行", create, primary=True)
        self.execution_rows = ui.column().classes("tw-execution-rows tw-run-detail-area w-full gap-3")
        self.execution_signature = None
        self.run_area = None
        page_generation = self.page_generation()
        async def refresh_current_runs():
            if self.page_generation() == page_generation and self.page() in {'run', 'executions'}:
                await self.execution_details.refresh()
        self.execution_details.own_timer(ui.timer(1, refresh_current_runs))
        await self.execution_details.refresh()
        if self.pending_task_id is not None:
            task_id, self.pending_task_id = self.pending_task_id, None
            await create(task_id)
        elif self.pending_open_create:
            self.pending_open_create = False
            await create()
