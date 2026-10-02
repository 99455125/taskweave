"""Public application API shared by CLI, HTTP and future desktop UI."""

import asyncio
import json
from pathlib import Path
import time
from taskweave.core.validation import TaskError, normalize_step
from taskweave.application.operations import dispatch_operation
from taskweave.core.repositories import OrganizationRepository as OrganizationRepositoryPort
from taskweave.application.tasks import TaskUseCases
from taskweave.application.steps import StepUseCases
from taskweave.application.environments import EnvironmentUseCases
from taskweave.application.runs import RunUseCases
from taskweave.application.contexts import ContextUseCases
from taskweave.infrastructure.locking import InstanceLock
from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.runtime import CoordinatorPool
from taskweave.infrastructure.worker import load_registry
from taskweave.infrastructure.storage import default_home
from taskweave.infrastructure.privacy import PrivacySettings
from taskweave.application.authoring import Authoring
from taskweave.application.ai_requests import AISettings
from taskweave.application.planning import PlanningService
from taskweave.infrastructure.context_sessions import ContextSessions
from taskweave.infrastructure.plan_repository import PlanRepository


class Application:
    def __init__(
        self,
        home=None,
        model=None,
        registry_factory=None,
    ):
        self.home = Path(home or default_home()).resolve()
        self.instance = InstanceLock(self.home / "coordinator.lock")
        try:
            # An orphan worker watches the old parent every 200 ms.
            time.sleep(0.25)
            self.repo = Repository(self.home)
            stores = self.repo.repositories
            self.registry = load_registry(registry_factory, self.home)
            self.registry_factory = registry_factory
            workbench_path = self.home / 'workbench.json'
            workbench_settings = json.loads(workbench_path.read_text()) if workbench_path.exists() else {}
            max_concurrency = int(workbench_settings.get('executor_max_threads', 8))
            if not 1 <= max_concurrency <= 8:
                max_concurrency = 8
            self.coordinator = CoordinatorPool(
                stores.runs, stores.tasks, stores.steps, stores.environments,
                stores.results, self.registry, registry_factory, self.home,
                max_concurrency=max_concurrency,
            )
            self.repo.finish_pending_deletions()
            self.ai_settings = AISettings(self.home)
            self.privacy_settings = PrivacySettings(self.home)
            self.authoring = Authoring(stores.tasks, stores.steps, stores.environments, stores.runs, stores.results, self.home, self.registry, model, lambda: self.ai_settings.get()["request_limit_bytes"], lambda: self.privacy_settings.get()["redact_for_ai"])
            self.plan_repo = PlanRepository(self.repo)
            self.organization: OrganizationRepositoryPort = stores.organization
            self.context_sessions = ContextSessions(self.registry, stores.environments, stores.plans, self.home / "plans",
                steps=stores.steps, tasks=stores.tasks)
            self.tasks = TaskUseCases(stores.tasks, stores.steps, stores.step_contexts, self.repo.unit_of_work, self.registry, self.authoring, self.coordinator, self.context_sessions)
            self.steps = StepUseCases(stores.steps, stores.tasks, stores.runs, self.registry, self.authoring, self.coordinator, self.context_sessions)
            self.environments = EnvironmentUseCases(stores.environments, stores.runs, self.coordinator, self.context_sessions, stores.plans)
            self.runs = RunUseCases(stores.runs, stores.tasks, stores.steps, stores.environments, stores.results, self.registry, self.authoring, self.coordinator, self.context_sessions)
            self.contexts = ContextUseCases(stores.step_contexts, stores.steps, self.registry, self.authoring, self.coordinator, self.context_sessions)
            self.planning = PlanningService(
                plans=stores.plans,
                contexts=stores.plan_contexts,
                generations=stores.plan_generations,
                sessions=self.context_sessions,
                settings=self.ai_settings,
                registry=self.registry,
                authoring=self.authoring,
                privacy_settings=self.privacy_settings,
                tasks=self.tasks,
                steps=stores.steps,
                step_contexts=stores.step_contexts,
                uow=self.repo.unit_of_work,
                plan_files_root=self.home / "plans",
            )
        except Exception:
            self.instance.close()
            raise

    def close(self):
        try:
            self.context_sessions.close()
            self.coordinator.close()
        finally:
            self.instance.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def validate_step(self, step_id):
        return self.steps.validate(step_id)

    def trial_step(self, step_id, inputs, command_id, environment_id=None, continue_session=False, defer_inputs=False):
        return self.steps.trial(step_id, inputs, command_id, environment_id, continue_session, defer_inputs)

    def trial_flow(self, step_id, inputs, command_id, environment_id=None, step_inputs=None, defer_inputs=False, start_step_id=None):
        return self.steps.trial_flow(step_id, inputs, command_id, environment_id, step_inputs, defer_inputs, start_step_id)

    def confirm_step(self, step_id, attempt_id, expected_hash):
        return self.steps.confirm(step_id, attempt_id, expected_hash)

    def confirm_step_manual(self, step_id, expected_hash, environment_id=None):
        return self.steps.confirm_manual(step_id, expected_hash, environment_id)

    def create_run(self, task_id, inputs=None, environment_id=None, defer_inputs=False, step_inputs=None):
        return self.runs.create(task_id, inputs, environment_id, defer_inputs, step_inputs)

    def clear_task_runs(self, task_id):
        return self.tasks.clear_runs(task_id)

    def export_task(self, task_id):
        return self.tasks.export(task_id)

    def import_task(self, package):
        return self.tasks.import_package(package)

    def delete_environment(self, environment_id):
        return self.environments.delete(environment_id)

    def export_draft(self, step_id):
        return self.steps.export_draft(step_id)

    def import_draft(self, task_id, package):
        return self.steps.import_draft(task_id, package)

    def export_feedback(self, attempt_id):
        return self.steps.export_feedback(attempt_id)

    def configure_plugin(self, plugin_id, enabled):
        from taskweave.plugins.manager import PluginManager

        if self.registry_factory is not None:
            raise TaskError("PLUGIN_CONFIG_FIXED")
        if self.repo.repositories.runs.has_runtime_lease() or (
            self.coordinator.thread and self.coordinator.thread.is_alive()
        ) or self.context_sessions.list():
            raise TaskError("PLUGIN_CONFIG_LOCKED")
        registry = PluginManager(self.home).configure(plugin_id, enabled)
        self.coordinator._stop_worker()
        self.registry = self.coordinator.registry = self.authoring.registry = registry
        self.context_sessions.registry = registry
        self.tasks.registry = registry
        self.steps.registry = registry
        self.runs.registry = registry
        self.contexts.registry = registry
        self.planning.registry = registry
        return registry.catalog()

    def collect_context(
        self, step_id, provider_id, request=None, environment_id=None, run_id=None,
        expected_session_id=None, include_view=True,
    ):
        return self.contexts.collect(step_id, provider_id, request, environment_id, run_id, expected_session_id, include_view)

    def context_targets(self, step_id, provider_id, run_id=None, request=None):
        return self.contexts.targets(step_id, provider_id, run_id, request)

    def save_context_batch(self, step_id, context_id, expected_revision, provider_id, name, context_notes, captures):
        return self.contexts.save_batch(step_id, context_id, expected_revision, provider_id, name, context_notes, captures)

    def installed_plugins(self):
        from taskweave.plugins.manager import PluginManager

        return PluginManager(self.home).catalog()

    def instances(self):
        return self.runs.instances()

    def end_instance(self, instance_type, owner_id):
        return self.runs.end_instance(instance_type, owner_id)

    def dispatch(self, operation, params=None):
        return dispatch_operation(self, operation, params)
