"""Explicit local dependency assembly; public compatibility methods live in service."""

import json
import time
from taskweave.application.tasks import TaskUseCases
from taskweave.application.settings import ApplicationSettings
from taskweave.infrastructure.model import HttpModel
from taskweave.infrastructure import sqlite_storage as storage_core
from taskweave.application.steps import StepUseCases
from taskweave.application.environments import EnvironmentUseCases
from taskweave.application.runs import RunUseCases
from taskweave.application.sequences import SequenceUseCases
from taskweave.application.sequence_driver import SequenceDriver
from taskweave.application.contexts import ContextUseCases
from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.coordinator_pool import CoordinatorPool
from taskweave.infrastructure.run_coordinator import Coordinator
from taskweave.core.run_ports import RunLeases
from taskweave.infrastructure.worker import load_registry
from taskweave.infrastructure.sqlite_storage import SQLiteStorage
from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.application.organization import OrganizationUseCases
from taskweave.infrastructure.privacy import PrivacySettings
from taskweave.application.authoring import Authoring
from taskweave.infrastructure.resource_sessions import ResourceSessionFactory
from taskweave.application.ai_requests import AISettings
from taskweave.application.planning import PlanningService
from taskweave.infrastructure.context_sessions import ContextSessions
from taskweave.infrastructure.plan_repository import PlanRepository


def compose_application(self, model, registry_factory):
    # An orphan worker watches the old parent every 200 ms.
    time.sleep(0.25)
    self.storage = SQLiteStorage(self.home)
    stores = build_sqlite_repositories(self.storage)
    self.repo = Repository.from_storage(self.storage, stores)
    self.registry = load_registry(registry_factory, self.home)
    self.registry_factory = registry_factory
    workbench_path = self.home / 'workbench.json'
    workbench_settings = json.loads(workbench_path.read_text()) if workbench_path.exists() else {}
    max_concurrency = int(workbench_settings.get('executor_max_threads', 8))
    if not 1 <= max_concurrency <= 8:
        max_concurrency = 8
    self.runtime_leases: RunLeases = stores.runs
    self.coordinator = CoordinatorPool(
        stores.runs, stores.tasks, stores.steps, stores.environments,
        stores.results, self.registry, registry_factory, self.home,
        max_concurrency=max_concurrency,
        coordinator_factory=lambda: Coordinator(
            None, stores.tasks, stores.steps, stores.environments, stores.results,
            self.registry, registry_factory, self.home, recover=False,
            queries=stores.runs, events=stores.runs, leases=stores.runs, writes=stores.runs,
        ),
    )
    stores.runs.finish_pending_deletions()
    self.ai_settings = AISettings(self.home)
    self.privacy_settings = PrivacySettings(self.home)
    self.authoring = Authoring(stores.tasks, stores.steps, stores.environments, stores.runs, stores.results, self.home, self.registry, model, lambda: self.ai_settings.get()["request_limit_bytes"], lambda: self.privacy_settings.get()["redact_for_ai"], resource_sessions=ResourceSessionFactory(self.home))
    self.plan_repo = PlanRepository(self.storage, repositories=stores)
    self.organization = OrganizationUseCases(stores.organization)
    self.context_sessions = ContextSessions(self.registry, stores.environments, stores.plans, self.home / "plans",
        steps=stores.steps, tasks=stores.tasks)
    self.tasks = TaskUseCases(stores.tasks, stores.steps, stores.step_contexts, self.storage.unit_of_work, self.registry, self.authoring, self.coordinator, self.context_sessions)
    self.steps = StepUseCases(stores.steps, stores.tasks, stores.runs, self.registry, self.authoring, self.coordinator, self.context_sessions)
    self.environments = EnvironmentUseCases(stores.environments, stores.runs, self.coordinator, self.context_sessions, stores.plans)
    self.runs = RunUseCases(stores.runs, stores.tasks, stores.steps, stores.environments, stores.results, self.registry, self.authoring, self.coordinator, self.context_sessions)
    self.runs.sequence_repository = stores.sequences
    self.tasks.sequence_repository = stores.sequences
    self.environments.sequence_repository = stores.sequences
    self.sequences = SequenceUseCases(stores.sequences, self.runs, stores.tasks, stores.steps, stores.environments, self.registry)
    self.sequence_driver = SequenceDriver(self.sequences, self.storage)
    self.sequences.driver = self.sequence_driver
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
        uow=self.storage.unit_of_work,
        plan_files_root=self.home / "plans",
    )
    self.settings = ApplicationSettings(
        self.home, privacy=self.privacy_settings,
        set_max_concurrency=self.coordinator.set_max_concurrency,
        list_environments=self.environments.list, list_instances=self.runs.instances,
        authoring=self.authoring, model_factory=HttpModel,
        workspace_location=lambda: storage_core.workspace_location_file(),
    )
    from taskweave.application.authoring_sessions import bind_application_requests
    self.authoring_requests = bind_application_requests(self)
    self.sequence_driver.recover()
