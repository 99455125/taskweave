"""Long-lived plugin collection resources owned by plans, outside run state."""

import asyncio
from dataclasses import asdict
from pathlib import Path
import threading

from taskweave.core.ports import Scope, StagedFile
from taskweave.core.repositories import EnvironmentRepository, PlanRepositoryPort
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from taskweave.infrastructure.worker import PluginContext, Resources, list_plugin_context_targets, record_plugin_context


class _PlanFiles:
    def __init__(self, root, collection_id):
        self.root = Path(root) / "staging" / collection_id

    async def allocate_file(self, name):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / uid()
        return StagedFile(uid(), str(path))


class _Session:
    def __init__(self, plan, registry, environments, root):
        self.plan_id = plan["plan_id"]
        self.session_id = uid()
        self.revision = plan["revision"]
        self.environment_id = plan.get("environment_id")
        self.plugin_ids = tuple(plan.get("plugin_ids", ()))
        self.capabilities = tuple(plan.get('capabilities', ()))
        self.task_id = plan.get('task_id', f'plan-{self.plan_id}')
        self.step_id = plan.get('step_id')
        self.task_parameters = plan.get('task_parameters', {})
        self.registry, self.environments, self.root = registry, environments, root
        self.busy = threading.Lock()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name=f"plan-{self.plan_id[:8]}")
        self.thread.start()
        self.resources = Resources(registry)
        self.recordings = set()
        self.recording_delivered = {}

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

    async def observe(self, provider_id, request, targets=False, include_view=True, recording=None):
        plugin = next((p for p in self.registry.plugins if p.manifest()["id"] in self.plugin_ids and provider_id in p.authoring(list(self.capabilities)).context_provider_ids), None)
        if plugin is None:
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        collection_id = uid()
        public, secrets = self.environments.environment(self.environment_id)
        pc = PluginContext(
            Scope(self.task_id, self.session_id, self.step_id or collection_id, collection_id),
            _PlanFiles(self.root, collection_id), self.resources, public, secrets,
            threading.Event(), lambda *args: None,
        )
        pc.task_parameters = self.task_parameters
        self.resources.context = pc
        if recording is not None:
            key = (provider_id, recording.recording_id)
            if recording.operation == 'ack' and recording.through > self.recording_delivered.get(key, 0):
                raise TaskError('CONTEXT_RECORDING_REQUEST_INVALID', '不能确认尚未读取的录制证据')
            result = await asyncio.wait_for(record_plugin_context(
                plugin, provider_id, pc, recording, request, self.registry.views,
                include_view=include_view), 60)
            key = (provider_id, result['recording_id'])
            if recording.operation == 'start':
                self.recordings.add(key)
                self.recording_delivered[key] = 0
                for previous in list(self.recording_delivered):
                    if len(self.recording_delivered) <= 64:
                        break
                    if previous not in self.recordings:
                        del self.recording_delivered[previous]
            elif recording.operation == 'read':
                self.recording_delivered[key] = max(self.recording_delivered.get(key, 0), result['cursor'])
            elif result['state'] == 'DISCARDED' or (
                    recording.operation == 'ack' and result['state'] == 'STOPPED'
                    and result['available_after'] == result['cursor']):
                self.recordings.discard(key)
                if result['state'] == 'DISCARDED':
                    self.recording_delivered.pop(key, None)
            return result
        if targets:
            return await asyncio.wait_for(list_plugin_context_targets(plugin, provider_id, pc, request), 30)
        capture = await asyncio.wait_for(
            plugin.collect_context(provider_id, pc, request or {}, include_view=include_view), 60
        )
        from taskweave.core.context_collection import serialize_context_collection
        return serialize_context_collection(capture, self.registry.views)

    def close(self):
        async def shutdown():
            try:
                await self.resources.release_all()
            finally:
                pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                await self.loop.shutdown_asyncgens()
        try:
            self.submit(shutdown())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            self.loop.close()


class ContextSessions:
    def __init__(
        self,
        registry,
        environments: EnvironmentRepository,
        plans: PlanRepositoryPort,
        plan_files_root: Path,
        *, steps=None, tasks=None,
    ):
        self.registry, self.environments, self.plans = registry, environments, plans
        self.plan_files_root = Path(plan_files_root)
        self.steps, self.tasks = steps, tasks
        self.sessions = {}
        self.guard = threading.Lock()

    def _owner(self, owner_id, environment_id=None, *, configure=False):
        if not owner_id.startswith('step:'):
            return self.plans.get(owner_id)
        import json
        step = self.steps.step(owner_id[5:])
        current = self.sessions.get(owner_id)
        environment = environment_id if configure else current.environment_id if current else None
        plugin_ids = [plugin.manifest()['id'] for plugin in self.registry.selected_plugins(step['capabilities'])]
        task = self.tasks.task(step['task_id'])
        parameters = {key:spec['default'] for key,spec in json.loads(task['input_schema_json']).get('properties', {}).items() if 'default' in spec}
        return {'plan_id':owner_id, 'revision':step['content_hash'], 'task_id':step['task_id'],
                'step_id':step['step_id'], 'plugin_ids':plugin_ids, 'capabilities':step['capabilities'],
                'environment_id':environment, 'task_parameters':parameters}

    def step_collect(self, step_id, provider_id, request=None, environment_id=None, expected_session_id=None, include_view=True):
        owner = self._owner('step:'+step_id, environment_id, configure=True)
        return self._collect_owner(owner, provider_id, request, expected_session_id, include_view)['capture']

    def step_targets(self, step_id, provider_id, request=None):
        return self._targets_owner(self._owner('step:'+step_id), provider_id, request)

    def step_record(self, step_id, provider_id, operation, *, environment_id=None, **options):
        owner = self._owner('step:'+step_id, environment_id, configure=operation=='start')
        current = self.sessions.get(owner['plan_id'])
        if operation != 'start' and current:
            owner.update(plugin_ids=list(current.plugin_ids), capabilities=list(current.capabilities))
        return self._record_owner(owner, provider_id, operation, **options)

    def _provider(self, owner, provider_id):
        plugin = next((p for p in self.registry.plugins if p.manifest()['id'] in owner.get('plugin_ids', [])
                       and provider_id in p.authoring(owner.get('capabilities', [])).context_provider_ids), None)
        if plugin is None:
            raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE', provider_id)
        return plugin

    def _session(self, plan, create=True, expected_session_id=None):
        with self.guard:
            if self._owner(plan["plan_id"])["revision"] != plan["revision"]:
                raise TaskError("EDIT_CONFLICT")
            current = self.sessions.get(plan["plan_id"])
            signature = (plan.get("environment_id"), tuple(plan.get("plugin_ids", ())), tuple(plan.get('capabilities', ())))
            if expected_session_id and (current is None or current.session_id != expected_session_id or (current.environment_id, current.plugin_ids, current.capabilities) != signature):
                raise TaskError("CONTEXT_SESSION_CHANGED", "采集实例已结束或变化，请刷新后重新选择")
            if current and not current.busy.acquire(blocking=False):
                raise TaskError("CONTEXT_SESSION_BUSY", "该计划正在采集上下文")
            if current and (current.environment_id, current.plugin_ids, current.capabilities) != signature:
                if current.recordings:
                    current.busy.release()
                    raise TaskError('CONTEXT_RECORDING_PENDING', '采集配置已变化，请先处理未保存录制')
                self.sessions.pop(plan["plan_id"], None)
                try:
                    current.close()
                finally:
                    current.busy.release()
                current = None
            if current is None and create:
                root = self.plan_files_root / 'step-observations' / plan['step_id'] if plan.get('step_id') else self.plan_files_root / plan['plan_id']
                current = _Session(plan, self.registry, self.environments, root)
                current.busy.acquire()
                self.sessions[plan["plan_id"]] = current
            return current

    def targets(self, plan_id, provider_id, request=None):
        plan = self.plans.get(plan_id)
        return self._targets_owner(plan, provider_id, request)

    def _targets_owner(self, plan, provider_id, request):
        self._provider(plan, provider_id)
        session = self._session(plan, create=False)
        if session is None:
            return {"session_id": None, "targets": []}
        try:
            targets = session.submit(session.observe(provider_id, request or {}, targets=True))
            return {"session_id": session.session_id, "targets": targets}
        finally:
            session.busy.release()

    def collect(self, plan_id, expected_revision=None, provider_id=None, request=None, expected_session_id=None, include_view=True):
        plan = self.plans.get(plan_id)
        if expected_revision is not None and plan["revision"] != expected_revision:
            raise TaskError("EDIT_CONFLICT")
        return self._collect_owner(plan, provider_id, request, expected_session_id, include_view)

    def _collect_owner(self, plan, provider_id, request, expected_session_id, include_view):
        self._provider(plan, provider_id)
        session = self._session(plan, expected_session_id=expected_session_id)
        try:
            capture = session.submit(session.observe(provider_id, request or {}, include_view=include_view))
            if self.sessions.get(plan['plan_id']) is not session:
                raise TaskError("CONTEXT_SESSION_CHANGED", "采集期间实例已变化")
            return {"capture": capture, "session_id": session.session_id}
        finally:
            session.busy.release()

    def record(self, plan_id, provider_id, operation, *, request=None, recording_id=None,
               after=0, through=None, limit=100, expected_revision=None,
               expected_session_id=None, include_view=True):
        plan = self.plans.get(plan_id)
        if expected_revision is not None and plan['revision'] != expected_revision:
            raise TaskError('EDIT_CONFLICT')
        return self._record_owner(plan, provider_id, operation, request=request, recording_id=recording_id,
            after=after, through=through, limit=limit, expected_session_id=expected_session_id, include_view=include_view)

    def _record_owner(self, plan, provider_id, operation, *, request=None, recording_id=None,
                      after=0, through=None, limit=100, expected_session_id=None, include_view=True):
        from taskweave.core.context_recording import recording_command
        command = recording_command(operation, recording_id=recording_id, after=after, through=through, limit=limit)
        plugin = self._provider(plan, provider_id)
        if not callable(getattr(plugin, 'record_context', None)):
            raise TaskError('CONTEXT_RECORDING_UNAVAILABLE', '该提供器不支持录制，仍可使用快照采集')
        if operation != 'start' and not expected_session_id:
            raise TaskError('CONTEXT_SESSION_CHANGED', '录制命令必须核对原采集实例')
        session = self._session(plan, create=operation == 'start', expected_session_id=expected_session_id)
        if session is None:
            raise TaskError('CONTEXT_SESSION_CHANGED')
        try:
            if operation == 'start' and len(session.recordings) >= 16:
                raise TaskError('CONTEXT_RECORDING_PENDING', '此实例有过多未处理录制，请先保存或丢弃')
            if (operation != 'start' and (provider_id, recording_id) not in session.recordings
                    and not (operation == 'ack' and (provider_id, recording_id) in session.recording_delivered)):
                raise TaskError('CONTEXT_RECORDING_UNAVAILABLE', '录制不存在或已经丢弃')
            result = session.submit(session.observe(provider_id, request or {}, include_view=include_view, recording=command))
            return {**result, 'session_id':session.session_id}
        finally:
            session.busy.release()

    def list(self):
        with self.guard:
            return [{"instance_type": 'step' if item.step_id else "plan", "owner_id": item.step_id or item.plan_id,
                     "session_id": item.session_id, "busy": item.busy.locked(), 'environment_id':item.environment_id}
                    for item in self.sessions.values()]

    def change_configuration(self, plan_id, operation):
        """Commit a plan lifecycle change before retiring its idle resources."""
        with self.guard:
            session = self.sessions.get(plan_id)
            if session and session.recordings:
                raise TaskError('CONTEXT_RECORDING_PENDING', '请先保存并确认或丢弃录制，再修改采集配置')
            if session and not session.busy.acquire(blocking=False):
                raise TaskError("CONTEXT_SESSION_BUSY", "该计划正在采集上下文")
            try:
                result = operation()
            except BaseException:
                if session:
                    session.busy.release()
                raise
            self.sessions.pop(plan_id, None)
        if session:
            try:
                session.close()
            finally:
                session.busy.release()
        return result

    def change_step_owner(self, step_id, operation):
        return self.change_configuration('step:'+step_id, operation)

    def change_task_owner(self, task_id, operation):
        """Protect every independent observation before deleting its task."""
        with self.guard:
            owned = [session for session in self.sessions.values() if session.step_id and session.task_id == task_id]
            acquired = []
            try:
                for session in owned:
                    if session.recordings:
                        raise TaskError('CONTEXT_RECORDING_PENDING', '请先保存或丢弃步骤录制')
                    if not session.busy.acquire(blocking=False):
                        raise TaskError('CONTEXT_SESSION_BUSY')
                    acquired.append(session)
                result = operation()
            except BaseException:
                for session in acquired:
                    session.busy.release()
                raise
            for session in owned:
                self.sessions.pop(session.plan_id, None)
        for session in owned:
            try:
                session.close()
            finally:
                session.busy.release()
        return result

    def end(self, plan_id, *, discard_recordings=False):
        with self.guard:
            session = self.sessions.get(plan_id)
            if session and session.recordings and not discard_recordings:
                raise TaskError('CONTEXT_RECORDING_PENDING', '请先保存并确认或丢弃录制，再结束实例')
            if session and not session.busy.acquire(blocking=False):
                raise TaskError("CONTEXT_SESSION_BUSY")
            self.sessions.pop(plan_id, None)
        if session:
            try:
                session.close()
            finally:
                session.busy.release()
        return {"ended": bool(session), "owner_id": plan_id}

    def close(self):
        for plan_id in list(self.sessions):
            self.end(plan_id, discard_recordings=True)
