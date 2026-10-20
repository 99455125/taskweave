"""Instance selection and capacity; execution policy remains in Coordinator."""
from pathlib import Path
import threading
from typing import Callable
from taskweave.core.run_ports import PoolRunStore
from taskweave.core.validation import TaskError
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, StepRepository, TaskRepository
from taskweave.infrastructure.run_coordinator import Coordinator


class CoordinatorPool:
    """Route each task trial and each formal execution to an isolated coordinator.

    Core owns lifecycle only; plugin resources remain inside each coordinator's
    worker and are still opened/closed exclusively by ResourceProvider hooks.
    """
    def __init__(self, runs: PoolRunStore, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, results: ResultRepository, registry, factory, home, max_concurrency=8, *, coordinator_factory: Callable[[], Coordinator] | None = None):
        self.runs, self.tasks, self.steps, self.environments, self.results = runs, tasks, steps, environments, results
        self._registry, self.factory = registry, factory
        self.home = Path(home).resolve()
        self.task_data_root = self.home / "tasks"
        self.lock = threading.RLock()
        self.max_concurrency = max_concurrency
        self.instances = {}
        self.last = None
        self._coordinator_factory = coordinator_factory or (lambda: Coordinator(
            runs, tasks, steps, environments, results, self.registry, factory, self.home, recover=False,
        ))
        self.runs.recover()

    @property
    def registry(self): return self._registry

    @registry.setter
    def registry(self, value):
        self._registry = value
        for coordinator in self.instances.values():
            coordinator.registry = value

    def _key(self, run):
        return ('trial', run['task_id']) if run['mode'] == 'TRIAL' else ('execution', run['run_id'])

    def _for_run(self, run_id, create=True):
        run = self.runs.run(run_id)
        key = self._key(run)
        coordinator = self.instances.get(key)
        if coordinator is None and create:
            coordinator = self._coordinator_factory()
            self.instances[key] = coordinator
        if coordinator is not None:
            self.last = coordinator
        return coordinator

    @property
    def process(self): return self.last.process if self.last else None
    @property
    def thread(self): return self.last.thread if self.last else None
    @property
    def session_run_id(self): return self.last.session_run_id if self.last else None
    @session_run_id.setter
    def session_run_id(self, value):
        if self.last is None:
            run = self.runs.run(value)
            self.last = self._for_run(run['run_id'])
        self.last.session_run_id = value

    def start(self, run_id, *args, **kwargs):
        with self.lock:
            coordinator = self._for_run(run_id)
            active = sum(bool(item.thread and item.thread.is_alive()) for item in self.instances.values())
            if not (coordinator.thread and coordinator.thread.is_alive()) and active >= self.max_concurrency:
                raise TaskError('EXECUTOR_CAPACITY', f'执行器已达并发上限 {self.max_concurrency}')
            return coordinator.start(run_id, *args, **kwargs)

    def set_max_concurrency(self, value):
        value = int(value)
        if not 1 <= value <= 8:
            raise TaskError('FORM_INVALID', '执行器并发线程数必须在 1 到 8 之间')
        self.max_concurrency = value
        return value
    def control(self, run_id, *args, **kwargs): return self._for_run(run_id).control(run_id, *args, **kwargs)
    def restart(self, run_id, *args, **kwargs): return self._for_run(run_id).restart(run_id, *args, **kwargs)
    def reconcile(self, attempt_id, *args, **kwargs):
        run_id = self.runs.attempt_run_id(attempt_id)
        return self._for_run(run_id).reconcile(attempt_id, *args, **kwargs)
    def provide_inputs(self, run_id, *args, **kwargs): return self._for_run(run_id).provide_inputs(run_id, *args, **kwargs)
    def wait(self, run_id, *args, **kwargs): return self._for_run(run_id).wait(run_id, *args, **kwargs)
    def describe_run(self, run_id):
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            run = self.runs.run_details(run_id)
            run['can_end'] = bool(self.runs.runtime_lease(run_id))
            return run
        return coordinator.describe_run(run_id)
    def collect_context(self, run_id, *args, **kwargs):
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            code = "CONTEXT_SESSION_CHANGED" if kwargs.get("expected_session_id") else "SESSION_NOT_AVAILABLE"
            raise TaskError(code, "采集实例已结束或变化，请刷新后重新选择")
        return coordinator.collect_context(run_id, *args, **kwargs)
    def record_context(self, run_id, *args, **kwargs):
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            raise TaskError('CONTEXT_SESSION_CHANGED', '原运行实例已结束')
        return coordinator.record_context(run_id, *args, **kwargs)
    def context_targets(self, run_id, step_id, provider_id, request=None):
        step = self.steps.step(step_id)
        if step["task_id"] != self.runs.run(run_id)["task_id"]:
            raise TaskError("CONTEXT_RUN_STATE_INVALID")
        if not any(provider_id in p.authoring(step["capabilities"]).context_provider_ids for p in self.registry.selected_plugins(step["capabilities"])):
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            return {"session_id": None, "targets": []}
        return coordinator.context_targets(run_id, step_id, provider_id, request)
    def context_sessions(self, task_id):
        result = []
        for (kind, owner), coordinator in list(self.instances.items()):
            if (kind == 'trial' and owner == task_id) or kind == 'execution':
                result.extend(coordinator.context_sessions(task_id))
        return result
    def active_instances(self):
        rows = []
        for key, coordinator in list(self.instances.items()):
            if coordinator.process and coordinator.process.is_alive() and coordinator.session_run_id:
                run = coordinator.describe_run(coordinator.session_run_id)
                rows.append({**run, 'instance_type': key[0]})
        return rows
    def delete_run(self, run_id):
        run = self.runs.run(run_id)
        key = self._key(run)
        coordinator = self._for_run(run_id)
        if coordinator.context_recordings:
            raise TaskError('CONTEXT_RECORDING_PENDING', '此实例有未保存录制，请先处理再删除运行')
        result = coordinator.delete_run(run_id)
        coordinator.close()
        self.instances.pop(key, None)
        return result
    def release_completed_run(self, run_id):
        """Release a sequence child's resources without changing its saved result."""
        with self.lock:
            run = self.runs.run(run_id)
            if run['status'] != 'SUCCEEDED':
                return False
            key = self._key(run)
            coordinator = self.instances.get(key)
            if coordinator is None:
                return True
            if coordinator.thread and coordinator.thread.is_alive():
                return False
            coordinator.close()
            self.instances.pop(key, None)
            if self.last is coordinator:
                self.last = None
            return True
    def clear_task_runs(self, task_id):
        with self.lock:
            selected = []
            for key, coordinator in list(self.instances.items()):
                belongs = key == ('trial', task_id)
                if not belongs and coordinator.session_run_id:
                    try:
                        belongs = self.runs.run(coordinator.session_run_id)['task_id'] == task_id
                    except TaskError as exc:
                        if exc.code != 'NOT_FOUND':
                            raise
                        belongs = True
                if belongs:
                    with coordinator.lock:
                        if coordinator.context_recordings:
                            raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理未保存录制，再清理运行')
                        if coordinator.thread and coordinator.thread.is_alive():
                            raise TaskError('RUN_BUSY', '请先结束正在执行的步骤')
                    selected.append((key, coordinator))
            if any(run['status'] == 'RUNNING' for run in self.runs.runs_for_task(task_id)):
                raise TaskError('RUN_BUSY', '请先结束正在执行的步骤')
            for key, coordinator in selected:
                coordinator.close()
                self.instances.pop(key, None)
            helper = self._coordinator_factory()
            return helper.clear_task_runs(task_id)
    def _stop_worker(self, force=False):
        if self.last: self.last._stop_worker(force)
    def close(self):
        for coordinator in list(self.instances.values()): coordinator.close()
        self.instances.clear()
