"""Run lifecycle, result queries and instance application use cases."""

import asyncio
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, RunRepository, StepRepository, TaskRepository


class RunUseCases:
    def __init__(self, runs: RunRepository, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, results: ResultRepository, registry, authoring, coordinator, context_sessions):
        self.runs, self.tasks, self.steps, self.environments, self.results = runs, tasks, steps, environments, results
        self.registry, self.authoring, self.coordinator, self.context_sessions = registry, authoring, coordinator, context_sessions

    def create(self, task_id, inputs=None, environment_id=None, defer_inputs=False, step_inputs=None):
        for step in self.steps.steps(task_id):
            diagnostics = asyncio.run(self.authoring.validate_step(step))
            if any(item["severity"] == "error" for item in diagnostics):
                from taskweave.core.validation import TaskError
                raise TaskError("PLUGIN_LINT_FAILED")
        return self.runs.create_run(task_id, inputs or {}, self.registry.versions, environment_id, defer_inputs=defer_inputs, step_inputs=step_inputs)

    def start(self, run_id, command_id, mode="ALL", target_step_id=None, retry_step_id=None, start_step_id=None):
        return self.coordinator.start(run_id, command_id, mode, target_step_id, retry_step_id, start_step_id)
    def provide_inputs(self, run_id, command_id, inputs, step_inputs=None, expected_input_id=None):
        return self.coordinator.provide_inputs(run_id, command_id, inputs, step_inputs,
                                              expected_input_id=expected_input_id)
    def restart(self, run_id, command_id, target_step_id, start_step_id=None):
        return self.coordinator.restart(run_id, command_id, target_step_id, start_step_id)
    def delete(self, run_id): return self.coordinator.delete_run(run_id)
    def control(self, run_id, command_id, operation): return self.coordinator.control(run_id, command_id, operation)
    def reconcile(self, attempt_id, decision, evidence, command_id):
        return self.coordinator.reconcile(attempt_id, decision, evidence, command_id)
    def get(self, run_id):
        return self.coordinator.describe_run(run_id)
    def wait(self, run_id, timeout=30): return self.coordinator.wait(run_id, timeout)
    def instances(self): return self.coordinator.active_instances() + self.context_sessions.list()
    def end_instance(self, instance_type, owner_id):
        if instance_type == "plan":
            return self.context_sessions.end(owner_id)
        if instance_type == 'step':
            return self.context_sessions.end('step:'+owner_id)
        return self.coordinator.control(owner_id, "END")
    def context_sessions_for_task(self, task_id): return self.coordinator.context_sessions(task_id)
    def list(self, task_id=None): return self.runs.list_runs(task_id)
    def output(self, run_id, step_id, output="data"): return self.results.read_output(run_id, step_id, output, self.registry)
    def events(self, run_id): return self.runs.events(run_id)
    def event_page(self, run_id, after=0, limit=100): return self.runs.event_page(run_id, after, limit)
    def read_result(self, result_id): return self.results.read_result(result_id, self.registry)
    def delete_result(self, result_id): return self.results.delete_result(result_id)
    def stored(self, run_id): return self.runs.run(run_id)
    def request(self, run_id): return self.runs.private_run_request(run_id)
    def input_values(self, run_id): return self.runs.private_run_inputs(run_id)
    def environment(self, environment_id): return self.environments.environment(environment_id)
