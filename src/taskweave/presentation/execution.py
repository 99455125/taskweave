"""Execution selection and query-cache policy using plain application records."""
import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Literal, Protocol, overload
from taskweave.core.data_contracts import RunSummary, TaskRecord, StepRecord
from taskweave.core.json_types import JSON


class ExecutionQuery(Protocol):
    @overload
    async def __call__(self, operation: Literal['run.list']) -> list[RunSummary]: ...
    @overload
    async def __call__(self, operation: Literal['run.get'], *, run_id: str) -> dict[str, JSON]: ...
    @overload
    async def __call__(self, operation: Literal['environment.list']) -> list[dict[str, JSON]]: ...
    @overload
    async def __call__(self, operation: Literal['task.list']) -> list[TaskRecord]: ...
    @overload
    async def __call__(self, operation: Literal['step.list'], *, task_id: str) -> list[StepRecord]: ...


@dataclass(frozen=True)
class ExecutionRows:
    details: list[dict]
    environments: dict
    tasks: dict
    active_run: dict | None
    definition_steps: list[dict] | None
    signature: str

from taskweave.presentation.polling import PollingState
from taskweave.presentation.state import ExecutionPageState


class ExecutionInteraction:
    def __init__(self, state: ExecutionPageState):
        self.state = state
        self.polling = PollingState()
        self.detail_cache = {}
        self.current_runs = {}
        self.render_sequence = 0
        self.refresh_sequence = 0

    def invalidate_render(self):
        self.render_sequence += 1

    def rows_identity(self, page):
        state = self.state
        return (self.render_sequence, page, tuple(state.task_ids), tuple(state.statuses),
                state.run_id, state.selected_step_run_id, state.selected_step_id, state.search_query)

    def begin_refresh(self, page):
        self.refresh_sequence += 1
        return self.refresh_sequence, page

    def accepts_refresh(self, token, page):
        return token == (self.refresh_sequence, page) and page[1] in {'run', 'executions'}

    def detail_token(self, refresh, page):
        return refresh, page, self.state.run_id, self.state.selected_step_run_id, self.state.selected_step_id

    def accepts_detail(self, token, page):
        return self.accepts_refresh(token[0], page) and token == self.detail_token(token[0], page)

    async def load_rows(self, call: ExecutionQuery, page: Callable[[], tuple], *, force=True):
        self.invalidate_render()
        identity = self.rows_identity(page())
        def current():
            return identity == self.rows_identity(page())
        all_runs = await call('run.list')
        if not current(): return None
        runs = self.filter_runs(all_runs)
        details = []
        for row in reversed(runs):
            detail = self.cached_detail(row, force=force)
            if detail is None:
                detail = await call('run.get', run_id=row['run_id'])
                if not current(): return None
                self.remember(row, detail)
            details.append(detail)
            if not current(): return None
        self.retain(runs, details)
        if self.state.run_id is None and self.state.signature is None and details:
            self.state.run_id = details[0]['run_id']
            identity = self.rows_identity(page())
        signature = self.summary([details, self.state.run_id, self.state.selected_step_run_id, self.state.selected_step_id])
        if signature == self.state.signature: return None
        environments = {item['environment_id']: item['name'] for item in await call('environment.list')}
        if not current(): return None
        tasks = {item['task_id']: item for item in await call('task.list')}
        if not current(): return None
        details = self.search(details, tasks)
        active_run = next((run for run in details if run['run_id'] == self.state.run_id), None)
        definition_steps = None
        if active_run is not None:
            definition_steps = (json.loads(active_run['definition_json'])['steps'] if active_run['definition_json']
                                else await call('step.list', task_id=active_run['task_id']))
            if not current(): return None
        self.state.signature = signature
        return ExecutionRows(details, environments, tasks, active_run, definition_steps, signature)

    @staticmethod
    def default_step_id(run, steps):
        step_ids = {step['step_id'] for step in steps}
        latest = next((attempt['step_id'] for attempt in reversed(run.get('attempts', []))
                       if attempt.get('valid') and attempt.get('step_id') in step_ids), None)
        return latest or (steps[0]['step_id'] if steps else None)

    def selected_step(self, run, steps):
        state = self.state
        if state.selected_step_run_id == run['run_id'] and state.selected_step_id in {s['step_id'] for s in steps}:
            return state.selected_step_id
        state.selected_step_run_id = run['run_id']
        state.selected_step_id = self.default_step_id(run, steps)
        return state.selected_step_id

    def select_step(self, run_id, step_id):
        self.state.run_id = run_id
        self.state.selected_step_run_id = run_id
        self.state.selected_step_id = step_id
        self.state.run_signature = self.state.signature = None
        self.polling.invalidate()

    def select_run(self, run_id):
        if self.state.run_id != run_id:
            self.state.selected_step_run_id = self.state.selected_step_id = None
        self.state.run_id = run_id
        self.state.run_signature = self.state.signature = None
        self.polling.invalidate()

    def filter_runs(self, runs):
        return [run for run in runs if run['mode'] == 'EXECUTION'
                and (not self.state.task_ids or run['task_id'] in self.state.task_ids)
                and (not self.state.statuses or run['status'] in self.state.statuses)]

    @staticmethod
    def summary(row):
        return json.dumps(row, ensure_ascii=False, indent=2, default=str)

    def cached_detail(self, row, *, force):
        cached = self.detail_cache.get(row['run_id'])
        if cached and cached[0] == self.summary(row) and not force and ('event_revision' in row or row['status'] != 'RUNNING'):
            return cached[1]
        return None

    def remember(self, row, detail):
        self.detail_cache[row['run_id']] = (self.summary(row), detail)

    def retain(self, rows, details):
        retained = {run['run_id'] for run in rows}
        self.detail_cache = {key: value for key, value in self.detail_cache.items() if key in retained}
        self.current_runs = {run['run_id']: run for run in details}

    def search(self, details, tasks):
        query = (self.state.search_query or '').strip().casefold()
        return [run for run in details if not query or query in tasks.get(run['task_id'], {}).get('name', '').casefold()
                or query in run['run_id'].casefold()]

    def dispose(self):
        self.invalidate_render()
        self.refresh_sequence += 1
        self.detail_cache.clear()
        self.current_runs.clear()
        # Disposing view handles invalidates responses, not document visibility.
        # The same interaction is reused when Workbench paints the next view.
        self.polling.invalidate()
