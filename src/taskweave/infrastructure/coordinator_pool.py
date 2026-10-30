"""Instance selection and capacity; execution policy remains in Coordinator."""
from pathlib import Path
import json
import threading
from typing import Callable
from taskweave.core.run_ports import PoolRunStore
from taskweave.core.validation import TaskError, fingerprint
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, StepRepository, TaskRepository
from taskweave.infrastructure.run_coordinator import Coordinator
from taskweave.infrastructure.execution_capacity import ExecutionCapacity


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
        self.execution_capacity = ExecutionCapacity(max_concurrency)
        self.instances = {}
        self.run_coordinators = {}
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
        if run['mode'] == 'TRIAL':
            if json.loads(run['request_json']).get('full_flow_trial'):
                return ('sequence_trial', run['run_id'])
            return ('trial', run['task_id'])
        return ('execution', run['run_id'])

    def _for_run(self, run_id, create=True):
        if run_id in self.run_coordinators:
            return self.run_coordinators[run_id]
        run = self.runs.run(run_id)
        key = self._key(run)
        coordinator = self.instances.get(key)
        if coordinator is None and create:
            coordinator = self._coordinator_factory()
            self.instances[key] = coordinator
        if coordinator is not None:
            coordinator.execution_capacity = self.execution_capacity
            self.last = coordinator
            self.run_coordinators[run_id] = coordinator
        return coordinator

    def trial_sessions(self, environment_id=None):
        scenes = {}
        for coordinator in list(self.instances.values()):
            if not coordinator.session_run_id:
                continue
            run = self.runs.run(coordinator.session_run_id)
            if run['environment_id'] != environment_id or run['status'] not in {'PAUSED', 'FAILED', 'INTERRUPTED', 'SUCCEEDED', 'RUNNING'}:
                continue
            workers = ([worker for worker, _ in coordinator._retained_branch_contexts(run['run_id']).values()]
                       if coordinator.branch_workers else [coordinator])
            for worker in workers:
                if (not worker.process or not worker.process.is_alive() or not worker.context_session_id
                        or worker.context_session_id != worker.transport.session_id):
                    continue
                step = self.steps.step(worker.context_step_id) if worker.context_step_id else None
                scenes[worker.context_session_id] = {'run_id': run['run_id'], 'session_id': worker.context_session_id,
                    'task_id': run['task_id'], 'task_name': self.tasks.task(run['task_id'])['name'],
                    'step_name': step['name'] if step else '', 'status': run['status'],
                    'busy': worker.transport.operation_lock.locked()}
        return list(scenes.values())

    def trial_scene_owner(self, run_id, expected_session_id, environment_id):
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            raise TaskError('CONTEXT_SESSION_CHANGED', '原现场已结束，请重新选择')
        run = self.runs.run(run_id)
        if run['environment_id'] != environment_id:
            raise TaskError('ENVIRONMENT_CHANGED', '所选现场属于其他环境')
        if json.loads(run['request_json']).get('environment_hash') != fingerprint(self.environments.environment(environment_id)):
            raise TaskError('ENVIRONMENT_CHANGED', '所选现场的环境配置已变化')
        if json.loads(run['plugin_versions_json']) != self.registry.versions:
            raise TaskError('PLUGIN_VERSION_MISMATCH')
        if run['status'] == 'RUNNING' or (coordinator.thread and coordinator.thread.is_alive()):
            raise TaskError('RUN_BUSY', '该现场正在执行步骤')
        workers = ([worker for worker, _ in coordinator._retained_branch_contexts(run_id).values()]
                   if coordinator.branch_workers else [coordinator])
        owner = next((worker for worker in workers if worker.context_session_id == expected_session_id
                      and worker.transport.session_id == expected_session_id
                      and worker.process and worker.process.is_alive()), None)
        if owner is None:
            raise TaskError('CONTEXT_SESSION_CHANGED', '原现场已结束或变化，请重新选择')
        owner.assert_scene_idle()
        if coordinator.has_context_recordings() or owner.has_context_recordings():
            raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理该现场的录制')
        return owner

    def bind_trial_scene(self, run_id, owner=None):
        coordinator = self._coordinator_factory()
        coordinator.explicit_scene = True
        coordinator.execution_capacity = self.execution_capacity
        if owner is not None:
            coordinator.transport = owner.transport
            coordinator.cancel = owner.cancel
            coordinator.context_session_id = owner.context_session_id
            coordinator.context_recordings = owner.context_recordings
            coordinator.context_recording_delivered = owner.context_recording_delivered
            coordinator.context_recording_capabilities = owner.context_recording_capabilities
        self.instances[('trial-scene', run_id)] = coordinator
        self.run_coordinators[run_id] = coordinator
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
            coordinator.max_parallel_actions = self.max_concurrency
            active = sum(bool(item.thread and item.thread.is_alive()) for item in self.instances.values())
            if not (coordinator.thread and coordinator.thread.is_alive()) and active >= self.max_concurrency:
                raise TaskError('EXECUTOR_CAPACITY', f'执行器已达并发上限 {self.max_concurrency}')
            return coordinator.start(run_id, *args, **kwargs)

    def set_max_concurrency(self, value):
        value = int(value)
        if not 1 <= value <= 8:
            raise TaskError('FORM_INVALID', '执行器并发线程数必须在 1 到 8 之间')
        self.max_concurrency = value
        self.execution_capacity.resize(value)
        return value
    def control(self, run_id, *args, **kwargs): return self._for_run(run_id).control(run_id, *args, **kwargs)
    def restart(self, run_id, *args, **kwargs):
        with self.lock:
            return self._for_run(run_id).restart(run_id, *args, **kwargs)
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
    def context_targets(self, run_id, step_id, provider_id, request=None, execution_path=None, expected_session_id=None):
        step = self.steps.step(step_id)
        if step["task_id"] != self.runs.run(run_id)["task_id"]:
            raise TaskError("CONTEXT_RUN_STATE_INVALID")
        if not any(provider_id in p.authoring(step["capabilities"]).context_provider_ids for p in self.registry.selected_plugins(step["capabilities"])):
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        coordinator = self._for_run(run_id, create=False)
        if coordinator is None:
            if expected_session_id or execution_path is not None:
                raise TaskError("CONTEXT_SESSION_CHANGED", "原路径的资源实例已结束，请刷新后重新选择")
            return {"session_id": None, "targets": []}
        return coordinator.context_targets(run_id, step_id, provider_id, request,
                                           execution_path=execution_path, expected_session_id=expected_session_id)
    def context_sessions(self, task_id):
        result = {}
        for (kind, owner), coordinator in list(self.instances.items()):
            if (kind == 'trial' and owner == task_id) or kind in {'execution', 'trial-scene'}:
                for row in coordinator.context_sessions(task_id):
                    result[row.get('session_id') or row['run_id']] = row
        return list(result.values())
    def active_instances(self):
        rows = {}
        for key, coordinator in list(self.instances.items()):
            live = bool(coordinator.process and coordinator.process.is_alive()) or any(
                worker.process and worker.process.is_alive() for worker in list(coordinator.branch_workers.values()))
            if live and coordinator.session_run_id:
                run = coordinator.describe_run(coordinator.session_run_id)
                identity = coordinator.transport.session_id or coordinator.session_run_id
                rows[identity] = {**run, 'instance_type': 'trial' if key[0] == 'trial-scene' else key[0]}
        return list(rows.values())
    def delete_run(self, run_id):
        with self.lock:
            return self._delete_run(run_id)

    def _delete_run(self, run_id):
        run = self.runs.run(run_id)
        key = self._key(run)
        coordinator = self._for_run(run_id)
        if coordinator.has_context_recordings():
            raise TaskError('CONTEXT_RECORDING_PENDING', '此实例有未保存录制，请先处理再删除运行')
        result = coordinator.delete_run(run_id)
        coordinator.close()
        self._forget(coordinator)
        return result

    def _forget(self, coordinator):
        self.instances = {key: item for key, item in self.instances.items() if item is not coordinator}
        self.run_coordinators = {key: item for key, item in self.run_coordinators.items() if item is not coordinator}
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
            try:
                with coordinator.scene_guard():
                    coordinator.close()
            except TaskError as exc:
                if exc.code == 'RUN_BUSY':
                    return False
                raise
            self._forget(coordinator)
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
                        if coordinator.has_context_recordings():
                            raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理未保存录制，再清理运行')
                        if coordinator.thread and coordinator.thread.is_alive():
                            raise TaskError('RUN_BUSY', '请先结束正在执行的步骤')
                        coordinator.assert_scene_idle()
                    selected.append((key, coordinator))
            if any(run['status'] == 'RUNNING' for run in self.runs.runs_for_task(task_id)):
                raise TaskError('RUN_BUSY', '请先结束正在执行的步骤')
            for key, coordinator in selected:
                with coordinator.scene_guard():
                    coordinator.close()
                self._forget(coordinator)
            helper = self._coordinator_factory()
            return helper.clear_task_runs(task_id)
    def _stop_worker(self, force=False):
        if self.last: self.last._stop_worker(force)
    def close(self):
        for coordinator in list(self.instances.values()): coordinator.close()
        self.instances.clear()
        self.run_coordinators.clear()
