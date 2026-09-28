"""Long-lived plugin collection resources owned by plans, outside run state."""

import asyncio
from dataclasses import asdict
from pathlib import Path
import threading

from taskweave.core.ports import Scope, StagedFile
from taskweave.core.repositories import EnvironmentRepository, PlanRepositoryPort
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from taskweave.infrastructure.worker import PluginContext, Resources, list_plugin_context_targets


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
        self.registry, self.environments, self.root = registry, environments, root
        self.busy = threading.Lock()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name=f"plan-{self.plan_id[:8]}")
        self.thread.start()
        self.resources = Resources(registry)

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

    async def observe(self, provider_id, request, targets=False, include_view=True):
        plugin = next((p for p in self.registry.plugins if p.manifest()["id"] in self.plugin_ids and provider_id in p.authoring([]).context_provider_ids), None)
        if plugin is None:
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        collection_id = uid()
        public, secrets = self.environments.environment(self.environment_id)
        pc = PluginContext(
            Scope(f"plan-{self.plan_id}", self.session_id, collection_id, collection_id),
            _PlanFiles(self.root, collection_id), self.resources, public, secrets,
            threading.Event(), lambda *args: None,
        )
        self.resources.context = pc
        if targets:
            return await asyncio.wait_for(list_plugin_context_targets(plugin, provider_id, pc, request), 30)
        capture = await asyncio.wait_for(
            plugin.collect_context(provider_id, pc, request or {}, include_view=include_view), 60
        )
        from taskweave.core.context_collection import serialize_context_collection
        return serialize_context_collection(capture, self.registry.views)

    def close(self):
        try:
            self.submit(self.resources.release_all())
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
    ):
        self.registry, self.environments, self.plans = registry, environments, plans
        self.plan_files_root = Path(plan_files_root)
        self.sessions = {}
        self.guard = threading.Lock()

    def _session(self, plan, create=True, expected_session_id=None):
        with self.guard:
            if self.plans.get(plan["plan_id"])["revision"] != plan["revision"]:
                raise TaskError("EDIT_CONFLICT")
            current = self.sessions.get(plan["plan_id"])
            signature = (plan.get("environment_id"), tuple(plan.get("plugin_ids", ())))
            if expected_session_id and (current is None or current.session_id != expected_session_id or (current.environment_id, current.plugin_ids) != signature):
                raise TaskError("CONTEXT_SESSION_CHANGED", "采集实例已结束或变化，请刷新后重新选择")
            if current and not current.busy.acquire(blocking=False):
                raise TaskError("CONTEXT_SESSION_BUSY", "该计划正在采集上下文")
            if current and (current.environment_id, current.plugin_ids) != signature:
                self.sessions.pop(plan["plan_id"], None)
                try:
                    current.close()
                finally:
                    current.busy.release()
                current = None
            if current is None and create:
                current = _Session(plan, self.registry, self.environments, self.plan_files_root / plan["plan_id"])
                current.busy.acquire()
                self.sessions[plan["plan_id"]] = current
            return current

    def targets(self, plan_id, provider_id, request=None):
        plan = self.plans.get(plan_id)
        if not any(p.manifest()["id"] in plan.get("plugin_ids", []) and provider_id in p.authoring([]).context_provider_ids for p in self.registry.plugins):
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
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
        if not any(p.manifest()["id"] in plan.get("plugin_ids", []) and provider_id in p.authoring([]).context_provider_ids for p in self.registry.plugins):
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        session = self._session(plan, expected_session_id=expected_session_id)
        try:
            capture = session.submit(session.observe(provider_id, request or {}, include_view=include_view))
            if self.sessions.get(plan_id) is not session:
                raise TaskError("CONTEXT_SESSION_CHANGED", "采集期间实例已变化")
            return {"capture": capture, "session_id": session.session_id}
        finally:
            session.busy.release()

    def list(self):
        with self.guard:
            return [{"instance_type": "plan", "owner_id": item.plan_id, "session_id": item.session_id, "busy": item.busy.locked()} for item in self.sessions.values()]

    def change_configuration(self, plan_id, operation):
        """Commit a plan lifecycle change before retiring its idle resources."""
        with self.guard:
            session = self.sessions.get(plan_id)
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

    def end(self, plan_id):
        with self.guard:
            session = self.sessions.get(plan_id)
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
            self.end(plan_id)
