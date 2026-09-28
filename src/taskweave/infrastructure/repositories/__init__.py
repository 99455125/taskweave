"""Domain-oriented SQLite repository adapters."""

from taskweave.infrastructure.repositories.environments import EnvironmentRepository
from taskweave.infrastructure.repositories.plan_contexts import PlanContextRepository
from taskweave.infrastructure.repositories.plan_generations import PlanGenerationRepository
from taskweave.infrastructure.repositories.plans import PlanMetadataRepository
from taskweave.infrastructure.repositories.organization import OrganizationRepository
from taskweave.infrastructure.repositories.runs import RunRepository
from taskweave.infrastructure.repositories.results import ResultRepository
from taskweave.infrastructure.repositories.steps import StepRepository
from taskweave.infrastructure.repositories.step_contexts import StepContextRepository
from taskweave.infrastructure.repositories.tasks import TaskRepository

__all__ = ["EnvironmentRepository", "PlanContextRepository", "PlanGenerationRepository", "PlanMetadataRepository", "RepositorySet", "ResultRepository", "RunRepository", "StepContextRepository", "StepRepository", "TaskRepository"]


def build_sqlite_repositories(store):
    """Build the complete domain repository set over one existing storage/UoW."""
    environments = EnvironmentRepository(store)
    steps = StepRepository(store, environments)
    step_contexts = StepContextRepository(store, steps)
    tasks = TaskRepository(store, steps, step_contexts)
    results = ResultRepository(store, tasks)
    runs = RunRepository(store, tasks, steps, environments, results)
    plan_contexts = PlanContextRepository(store)
    plans = PlanMetadataRepository(store, plan_contexts)
    plan_generations = PlanGenerationRepository(store)
    organization = OrganizationRepository(store)
    return RepositorySet(
        tasks=tasks,
        steps=steps,
        environments=environments,
        runs=runs,
        results=results,
        step_contexts=step_contexts,
        plans=plans,
        plan_contexts=plan_contexts,
        plan_generations=plan_generations,
        organization=organization,
    )


class RepositorySet:
    """Explicit collection shared by use cases that span repository boundaries."""

    def __init__(self, *, tasks, steps, environments, runs, results, step_contexts, plans, plan_contexts, plan_generations, organization):
        self.tasks = tasks
        self.steps = steps
        self.environments = environments
        self.runs = runs
        self.results = results
        self.step_contexts = step_contexts
        self.plans = plans
        self.plan_contexts = plan_contexts
        self.plan_generations = plan_generations
        self.organization = organization
