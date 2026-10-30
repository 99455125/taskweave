"""Execution filters page."""

from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.presentation.run_creation import RunCreation

STATUS = {
    "READY": "就绪", "RUNNING": "执行中", "PAUSED": "已暂停", "FAILED": "失败",
    "WAITING_INPUT": "等待输入", "BLOCKED": "需要处理", "DELETING": "清理中",
    "INTERRUPTED": "中断 / 待核对", "SUCCEEDED": "成功", "CANCELLED": "已结束",
}


class ExecutionsPage(Page):
    def __init__(self, controller, state, button, render_runs):
        self.controller, self.state = controller, state
        self.button, self.render_runs = button, render_runs

    async def render(self):
        tasks = await self.controller.call("task.list")
        sequences = await self.controller.call("sequence.list")
        objects = {task["task_id"]: task["name"] for task in tasks}
        objects.update({'sequence:' + item['sequence_id']: '任务组合 · ' + item['name'] for item in sequences})
        valid_ids = set(objects)
        self.state.task_ids = [value for value in self.state.task_ids if value in valid_ids]
        with ui.row().classes("tw-executions-master w-full min-w-0"):
            with ui.column().classes("tw-panel tw-execution-filters gap-3"):
                ui.label("执行").classes("text-lg font-semibold")
                search = ui.input("搜索任务、组合或运行", value=self.state.search_query, placeholder="名称或运行 ID").props("clearable debounce=250 prepend-icon=search").classes("w-full")
                task_filter = ui.select(
                    objects,
                    value=self.state.task_ids,
                    label="任务或任务组合（可多选）",
                    multiple=True,
                    clearable=True,
                ).props("use-chips use-input input-debounce=0").classes("w-full")
                status_filter = ui.select(
                    STATUS,
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
                    ui.label("执行对象与状态").classes("text-xs text-gray-500")
                ui.label("执行实例").classes("tw-execution-list-title text-sm font-medium text-gray-500")
                self.state.execution_list_area = ui.column().classes("tw-run-list w-full gap-3")
            with ui.column().classes("tw-content tw-executions-main w-full min-w-0"):
                await self.render_runs()


class RunPage(Page):
    """Create executions and own the run-page render/timer boundary."""

    def __init__(self, controller, state, button, paint, environment_select,
                 trial_variables, execution_details, page, page_generation, *, open_sequence=None):
        self.controller, self.state, self.button = controller, state, button
        self.paint, self.environment_select, self.trial_variables = paint, environment_select, trial_variables
        self.execution_details, self.page, self.page_generation = execution_details, page, page_generation
        self.creation = RunCreation(controller, state)
        self.open_sequence = open_sequence

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
        sequences = await self.controller.call('sequence.list') if self.open_sequence is not None else []
        combinations = {'sequence:' + item['sequence_id']: item for item in sequences}
        warning = flow.open(initial_task_id)
        if warning and (not combinations or initial_task_id is not None):
            ui.notify(warning, type="warning")
            return
        with ui.dialog() as dialog, ui.card().classes("tw-confirm-dialog").style("width:640px; max-height:calc(100dvh - 32px); overflow:auto"):
            ui.label("新建执行").classes("tw-confirm-title")
            task_select = ui.select(
                {**{task["task_id"]: task["name"] for task in flow.eligible},
                 **{key: "任务组合 · " + item["name"] for key, item in combinations.items()}},
                value=None if warning else flow.task_id,
                label="选择任务",
            ).props("use-input input-debounce=0").classes("w-full")
            async def select_combination(event):
                if event.value not in combinations:
                    return
                dialog.close()
                await self.open_sequence(combinations[event.value]['sequence_id'])

            if warning:
                task_select.on_value_change(select_combination)
                ui.button('取消', on_click=dialog.close).props('outline').classes('tw-confirm-cancel')
                dialog.open()
                return
            environment = await self.environment_select()
            steps = flow.steps
            start = ui.select({step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(steps)}, value=flow.start_step_id, label='开始步骤').classes('w-full')
            input_area = ui.column().classes('w-full')
            controlled = False
            input_generation = 0
            async def render_inputs():
                nonlocal controlled, input_generation
                input_generation += 1
                generation = input_generation
                from taskweave.core.task_flow import is_linear_flow
                selected_task_id = flow.task_id
                task_flow = await self.controller.call('task.flow.get', task_id=selected_task_id)
                if generation != input_generation or selected_task_id != flow.task_id or input_area.is_deleted:
                    return
                controlled = not is_linear_flow(task_flow)
                input_area.clear()
                start.options = ({flow.start_step_id: '完整流程'} if controlled else
                    {step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(flow.steps)})
                start.value = flow.start_step_id
                start.set_label('启动范围' if controlled else '开始步骤')
                start.set_enabled(not controlled)
                start.update()
                with input_area:
                    from taskweave.desktop.components.startup_inputs import StartupInputs
                    view = await StartupInputs(self.controller).render(flow.steps, environment,
                        task_id=flow.task_id, draft=flow.input_draft)
                    if generation != input_generation or selected_task_id != flow.task_id or input_area.is_deleted:
                        view.area.delete()

            async def select_start(event):
                # Task selection already updates the start step. Its programmatic
                # control update must not start a second asynchronous input render.
                if event.value == flow.start_step_id:
                    return
                flow.select_start(event.value)

            async def select_task(event):
                nonlocal input_generation
                if event.value in combinations:
                    input_generation += 1
                    await select_combination(event)
                    return
                flow.select_task(event.value)
                await render_inputs()

            start.on_value_change(select_start)
            task_select.on_value_change(select_task)
            await render_inputs()
            async def save():
                await flow.submit(from_flow_start=controlled)
                dialog.close()
                await (on_created or self.paint)()
            with ui.row().classes("tw-confirm-actions"):
                ui.button("取消", on_click=dialog.close).props("outline").classes("tw-confirm-cancel")
                self.button("创建并执行", save, primary=True)
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
