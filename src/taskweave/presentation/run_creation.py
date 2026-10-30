"""Framework-independent execution creation selection and submission."""
from uuid import uuid4
from typing import Literal, Protocol, overload
from taskweave.core.data_contracts import TaskRecord, StepRecord, RunSummary, CommandResult
from taskweave.core.json_types import JSON
from taskweave.presentation.state import ExecutionPageState
from taskweave.presentation.startup_inputs import StartupInputDraft


class RunCreationApplication(Protocol):
    @overload
    async def call(self, operation: Literal['task.list']) -> list[TaskRecord]: ...
    @overload
    async def call(self, operation: Literal['step.list'], *, task_id: str) -> list[StepRecord]: ...
    @overload
    async def call(self, operation: Literal['run.create'], *, task_id: str, inputs: dict[str, JSON],
                   step_inputs: dict[str, dict[str, JSON]], environment_id: str | None,
                   defer_inputs: bool) -> RunSummary: ...
    @overload
    async def call(self, operation: Literal['run.start'], *, run_id: str, command_id: str,
                   mode: str, start_step_id: str | None) -> CommandResult: ...


class RunCreation:
    def __init__(self, application: RunCreationApplication, execution_state: ExecutionPageState):
        self.application = application
        self.execution_state = execution_state
        self.eligible = []
        self.task_steps = {}
        self.task_id = None
        self.start_step_id = None
        self.input_draft = StartupInputDraft()
        self.input_drafts = {}
        self.pending_task_id = None
        self.pending_open_create = False

    async def load(self):
        tasks = await self.application.call('task.list')
        task_steps, eligible = {}, []
        for task in tasks:
            steps = await self.application.call('step.list', task_id=task['task_id'])
            task_steps[task['task_id']] = steps
            if steps and all(step['validation_state'] == 'VALIDATED' for step in steps):
                eligible.append(task)
        self.task_steps, self.eligible = task_steps, eligible

    def open(self, initial_task_id=None):
        if not self.eligible:
            return '尚无步骤全部确认的任务。请先创建任务并确认全部步骤。'
        if initial_task_id is not None and initial_task_id not in {task['task_id'] for task in self.eligible}:
            return '该任务的步骤尚未全部确认，不能创建执行。'
        self.start_step_id = None
        self.input_drafts = {}
        self.task_id = None
        self.select_task(initial_task_id or self.eligible[0]['task_id'])
        return None

    @property
    def steps(self):
        return self.task_steps[self.task_id]

    @property
    def selected_step(self):
        return next(step for step in self.steps if step['step_id'] == self.start_step_id)

    def select_task(self, task_id):
        if self.task_id is not None:
            self.input_drafts[self.task_id] = self.input_draft
        self.task_id = task_id
        self.input_draft = self.input_drafts.setdefault(task_id, StartupInputDraft())
        if self.start_step_id not in {step['step_id'] for step in self.steps}:
            self.start_step_id = self.steps[0]['step_id']

    def select_start(self, step_id):
        self.start_step_id = step_id

    def consume_pending(self):
        if self.pending_task_id is not None:
            task_id, self.pending_task_id = self.pending_task_id, None
            return True, task_id
        if self.pending_open_create:
            self.pending_open_create = False
            return True, None
        return False, None

    async def submit(self, *, from_flow_start=False):
        # Snapshot selection before awaiting: accepted creation always starts the
        # same run, even if another event changes the visible selection meanwhile.
        task_id, step_id = self.task_id, self.start_step_id
        draft = self.input_draft
        response = await self.application.call(
            'run.create', task_id=task_id, inputs=draft.task_values(),
            step_inputs=draft.step_values([step['step_id'] for step in self.steps]
                if from_flow_start else [step['step_id'] for step in self.steps[self.steps.index(self.selected_step):]]),
            environment_id=draft.environment_id or None, defer_inputs=True,
        )
        run_id = response['run_id']
        self.execution_state.run_id = run_id
        if self.execution_state.task_ids and task_id not in self.execution_state.task_ids:
            self.execution_state.task_ids.append(task_id)
        await self.application.call('run.start', run_id=run_id,
                                    command_id=str(uuid4()), mode='ALL',
                                    start_step_id=None if from_flow_start else step_id)
        return run_id
