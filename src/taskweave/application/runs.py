"""Run lifecycle, result queries and instance application use cases."""

from taskweave.core.data_contracts import RunSummary, CommandResult, ExecutionRequest
from taskweave.core.run_ports import RunApplicationStore
import asyncio
from uuid import uuid4
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, StepRepository, TaskRepository


class RunUseCases:
    def __init__(self, runs: RunApplicationStore, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, results: ResultRepository, registry, authoring, coordinator, context_sessions, flow_runs=None):
        self.runs, self.tasks, self.steps, self.environments, self.results = runs, tasks, steps, environments, results
        self.registry, self.authoring, self.coordinator, self.context_sessions = registry, authoring, coordinator, context_sessions
        self.flow_runs = flow_runs
        self.sequence_repository = None

    def _assert_independent(self, run_id):
        if self.sequence_repository and self.sequence_repository.owner_of_child(run_id):
            from taskweave.core.validation import TaskError
            raise TaskError("SEQUENCE_CHILD_MANAGED", "请在任务组合中操作此执行")

    def create(self, task_id, inputs=None, environment_id=None, defer_inputs=False, step_inputs=None) -> RunSummary:
        for step in self.steps.steps(task_id):
            diagnostics = asyncio.run(self.authoring.validate_step(step))
            if any(item["severity"] == "error" for item in diagnostics):
                from taskweave.core.validation import TaskError
                raise TaskError("PLUGIN_LINT_FAILED")
        return self.runs.create_run(task_id, inputs or {}, self.registry.versions, environment_id, defer_inputs=defer_inputs, step_inputs=step_inputs)

    def start(self, run_id, command_id, mode="ALL", target_step_id=None, retry_step_id=None, start_step_id=None, retry_execution_path=None) -> CommandResult:
        self._assert_independent(run_id)
        return self._managed_start(run_id, command_id, mode, target_step_id, retry_step_id, start_step_id, retry_execution_path)

    def _managed_start(self, run_id, command_id, mode="ALL", target_step_id=None, retry_step_id=None, start_step_id=None, retry_execution_path=None):
        return self.coordinator.start(run_id, command_id, mode, target_step_id, retry_step_id, start_step_id, retry_execution_path)
    def provide_inputs(self, run_id, command_id, inputs, step_inputs=None, expected_input_id=None):
        self._assert_independent(run_id)
        return self._managed_provide_inputs(run_id, command_id, inputs, step_inputs, expected_input_id)

    def _managed_provide_inputs(self, run_id, command_id, inputs, step_inputs=None, expected_input_id=None):
        return self.coordinator.provide_inputs(run_id, command_id, inputs, step_inputs,
                                              expected_input_id=expected_input_id)
    def restart(self, run_id, command_id, target_step_id, start_step_id=None):
        self._assert_independent(run_id)
        return self.coordinator.restart(run_id, command_id, target_step_id, start_step_id)
    def delete(self, run_id):
        self._assert_independent(run_id)
        return self.coordinator.delete_run(run_id)
    def control(self, run_id, command_id, operation):
        self._assert_independent(run_id)
        return self._managed_control(run_id, command_id, operation)
    def _managed_control(self, run_id, command_id, operation):
        return self.coordinator.control(run_id, command_id, operation)
    def reconcile(self, attempt_id, decision, evidence, command_id):
        self._assert_independent(self.runs.attempt_run_id(attempt_id))
        return self._managed_reconcile(attempt_id, decision, evidence, command_id)
    def _managed_reconcile(self, attempt_id, decision, evidence, command_id):
        return self.coordinator.reconcile(attempt_id, decision, evidence, command_id)
    def get(self, run_id) -> RunSummary:
        return self.coordinator.describe_run(run_id)
    def wait(self, run_id, timeout=30): return self.coordinator.wait(run_id, timeout)
    def instances(self): return self.coordinator.active_instances() + self.context_sessions.list()
    def end_instance(self, instance_type, owner_id, command_id=None):
        if instance_type == "plan":
            return self.context_sessions.end(owner_id)
        if instance_type == 'step':
            return self.context_sessions.end('step:'+owner_id)
        self._assert_independent(owner_id)
        return self.coordinator.control(owner_id, command_id or str(uuid4()), "abandon")
    def context_sessions_for_task(self, task_id): return self.coordinator.context_sessions(task_id)
    def list(self, task_id=None): return self.runs.list_runs(task_id)
    def output(self, run_id, step_id, output="data", *, execution_path=None, item_pointer=None, loop_node_id=None):
        return self.project_output(run_id, step_id, output, execution_path=execution_path,
                                   item_pointer=item_pointer, loop_node_id=loop_node_id)

    def project_output(self, run_id, step_id, output='data', *, execution_path=None, item_pointer=None, loop_node_id=None, transform=lambda value: value):
        """Apply an outbound projection before aggregate/item selection loses field context."""
        from taskweave.core.flow_values import aggregate_output
        from taskweave.core.task_flow import is_linear_flow
        import json
        if execution_path is not None:
            attempt = self.runs.latest_attempt_for_instance(run_id, execution_path)
            if attempt is None or attempt["step_id"] != step_id:
                from taskweave.core.validation import TaskError
                raise TaskError("OUTPUT_NOT_AVAILABLE")
            return transform(self.results.read_attempt_output(attempt["attempt_id"], output, self.registry))
        run = self.runs.run(run_id)
        definition = json.loads(run["definition_json"] or "{}")
        flow = definition.get("flow")
        if flow is None or is_linear_flow(flow):
            return transform(self.results.read_output(run_id, step_id, output, self.registry))
        instances = self.flow_runs.instances(run_id)
        return aggregate_output(flow, instances, step_id, output,
                                lambda aid, name: transform(self.results.read_attempt_output(aid, name, self.registry)),
                                item_pointer=item_pointer, loop_node_id=loop_node_id)
    def events(self, run_id): return self.runs.events(run_id)
    def event_page(self, run_id, after=0, limit=100): return self.runs.event_page(run_id, after, limit)
    def read_result(self, result_id): return self.results.read_result(result_id, self.registry)
    def delete_result(self, result_id):
        run_id = self.results.run_id_for_result(result_id)
        if run_id:
            self._assert_independent(run_id)
        return self.results.delete_result(result_id)
    def stored(self, run_id): return self.runs.run(run_id)
    def request(self, run_id) -> ExecutionRequest: return self.runs.private_run_request(run_id)
    def input_values(self, run_id): return self.runs.private_run_inputs(run_id)
    def environment(self, environment_id): return self.environments.environment(environment_id)
