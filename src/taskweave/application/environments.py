"""Environment configuration and lock-aware lifecycle use cases."""

from taskweave.core.validation import TaskError
from taskweave.core.repositories import EnvironmentRepository, PlanRepositoryPort, RunRepository


class EnvironmentUseCases:
    def __init__(self, environments: EnvironmentRepository, runs: RunRepository, coordinator, context_sessions, plans: PlanRepositoryPort):
        self.environments, self.runs = environments, runs
        self.coordinator, self.context_sessions, self.plans = coordinator, context_sessions, plans

    def save(self, name, public_config, secret_refs=None, environment_id=None, descriptions=None):
        return self.environments.save_environment(name, public_config, secret_refs, environment_id, descriptions)
    def list(self): return self.environments.list_environments()
    def get(self, environment_id): return self.environments.environment(environment_id)

    def delete(self, environment_id):
        for instance in self.context_sessions.list():
            if self.plans.get(instance["owner_id"]).get("environment_id") == environment_id:
                raise TaskError("ENVIRONMENT_LOCKED", "该环境仍被计划采集实例使用，请先结束实例")
        for run in self.runs.runs_for_environment(environment_id):
            current = self.coordinator.describe_run(run["run_id"])
            if current["status"] in {"RUNNING", "PAUSED"} or current["can_end"]:
                raise TaskError("ENVIRONMENT_LOCKED", "该环境仍有运行或保留资源，请先结束执行")
        return self.environments.delete_environment(environment_id)
