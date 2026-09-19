"""Public application API shared by CLI, HTTP and future desktop UI."""

import asyncio
import json
from pathlib import Path
import time
from taskweave.core.validation import TaskError, normalize_step
from taskweave.infrastructure.locking import InstanceLock
from taskweave.infrastructure.repository import Repository
from taskweave.infrastructure.runtime import Coordinator
from taskweave.infrastructure.worker import load_registry
from taskweave.infrastructure.storage import default_home
from taskweave.application.authoring import Authoring


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
            self.registry = load_registry(registry_factory, self.home)
            self.registry_factory = registry_factory
            self.coordinator = Coordinator(self.repo, self.registry, registry_factory)
            self.repo.finish_pending_deletions()
            self.authoring = Authoring(self.repo, self.registry, model)
        except Exception:
            self.instance.close()
            raise

    def close(self):
        try:
            self.coordinator.close()
        finally:
            self.instance.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def validate_step(self, step_id):
        step = self.repo.step(step_id)
        diagnostics = asyncio.run(self.authoring.validate_step(step))
        return {
            "step_id": step_id,
            "valid": not any(d["severity"] == "error" for d in diagnostics),
            "diagnostics": diagnostics,
        }

    def trial_step(self, step_id, inputs, command_id, environment_id=None, continue_session=False, defer_inputs=False):
        # Trial creation and start share a stable command receipt (including retry).
        with self.coordinator.lock:
            previous = self.repo.find_trial_command(
                command_id, step_id, inputs, environment_id
            )
            if previous:
                return previous
            validation = self.validate_step(step_id)
            if not validation["valid"]:
                raise TaskError("PLUGIN_LINT_FAILED")
            step = self.repo.step(step_id)
            leases = self.repo.query("SELECT * FROM runtime_lease")
            lease = leases[0] if leases else None
            if lease:
                owner = self.repo.run(lease['run_id'])
                compatible = owner['mode'] == 'TRIAL' and owner['task_id'] == step['task_id'] and owner['environment_id'] == environment_id and owner['status'] in {'FAILED','SUCCEEDED'}
                unsafe = self.repo.query("SELECT 1 FROM step_attempts WHERE run_id=? AND valid=1 AND (status='UNKNOWN' OR (status='FAILED' AND effect_state IN ('UNKNOWN','SUCCEEDED')))", (owner['run_id'],))
                if not compatible or (unsafe and not continue_session):
                    raise TaskError('RUN_LEASE_BUSY', '已有运行占用执行器，请在试跑反馈或执行页结束该运行')
                if unsafe:
                    self.repo.event(owner['run_id'], 'USER_RETRY_WITH_RETAINED_SESSION', {'step_id': step_id, 'previous_effect_unknown': True})
                self.repo.execute("DELETE FROM runtime_lease WHERE run_id=?", (owner['run_id'],))
            run = self.repo.create_run(
                step["task_id"], inputs, self.registry.versions, environment_id, step_id, defer_inputs=defer_inputs
            )
            result = self.coordinator.start(run["run_id"], command_id)
            if not continue_session:
                self.authoring.reset_conversation(step_id)
            return result

    def trial_flow(self, step_id, inputs, command_id, environment_id=None, step_inputs=None, defer_inputs=False):
        with self.coordinator.lock:
            task_id = self.repo.step(step_id)['task_id']
            step_inputs = self.repo.normalize_step_inputs(task_id, step_inputs)
            previous = self.repo.find_trial_command(command_id, step_id, inputs, environment_id)
            if previous:
                request = json.loads(self.repo.run(previous['run_id'])['request_json'])
                if not request.get('flow_trial') or request.get('initial_step_inputs', request.get('step_inputs', {})) != (step_inputs or {}):
                    raise TaskError('COMMAND_CONFLICT')
                return previous
            if self.coordinator.thread and self.coordinator.thread.is_alive():
                raise TaskError('RUN_BUSY')
            step = self.repo.step(step_id)
            leases = self.repo.query('SELECT * FROM runtime_lease')
            for lease in leases:
                owner = self.repo.run(lease['run_id'])
                if owner['mode'] != 'TRIAL' or owner['task_id'] != step['task_id']:
                    raise TaskError('RUN_LEASE_BUSY')
            for candidate in self.repo.steps(step['task_id']):
                if not self.validate_step(candidate['step_id'])['valid']:
                    raise TaskError('PLUGIN_LINT_FAILED')
                if candidate['step_id'] == step_id:
                    break
            self.coordinator._stop_worker()
            for lease in leases:
                self.repo.execute('DELETE FROM runtime_lease WHERE run_id=?', (lease['run_id'],))
            run = self.repo.create_run(step['task_id'], inputs, self.registry.versions, environment_id, step_id, flow_trial=True, step_inputs=step_inputs, defer_inputs=defer_inputs)
            self.authoring.reset_conversation(step_id)
            return self.coordinator.start(run['run_id'], command_id)

    def confirm_step(self, step_id, attempt_id, expected_hash):
        self.registry.check(self.repo.step(step_id))
        if self.repo.attempt_versions(attempt_id) != self.registry.versions:
            raise TaskError("PLUGIN_VERSION_MISMATCH")
        return self.repo.confirm(step_id, attempt_id, expected_hash)

    def confirm_step_manual(self, step_id, expected_hash, environment_id=None):
        validation = self.validate_step(step_id)
        if not validation['valid']:
            raise TaskError('PLUGIN_LINT_FAILED')
        return self.repo.confirm_manual(step_id, expected_hash, environment_id)

    def create_run(self, task_id, inputs=None, environment_id=None, defer_inputs=False):
        for step in self.repo.steps(task_id):
            diagnostics = asyncio.run(self.authoring.validate_step(step))
            if any(d["severity"] == "error" for d in diagnostics):
                raise TaskError("PLUGIN_LINT_FAILED")
        return self.repo.create_run(
            task_id, inputs or {}, self.registry.versions, environment_id, defer_inputs=defer_inputs
        )

    def clear_task_runs(self, task_id):
        result = self.coordinator.clear_task_runs(task_id)
        for step in self.repo.steps(task_id):
            self.authoring.reset_conversation(step['step_id'])
        return result

    def export_task(self, task_id):
        from taskweave.application.task_transfer import export_task
        return export_task(self, task_id)

    def import_task(self, package):
        from taskweave.application.task_transfer import import_task
        return import_task(self, package)

    def delete_environment(self, environment_id):
        runs = self.repo.query('SELECT run_id FROM task_runs WHERE environment_id=?', (environment_id,))
        for run in runs:
            current = self.coordinator.describe_run(run['run_id'])
            if current['status'] in {'RUNNING', 'PAUSED'} or current['can_end']:
                raise TaskError('ENVIRONMENT_LOCKED', '该环境仍有运行或保留资源，请先结束执行')
        return self.repo.delete_environment(environment_id)

    def export_draft(self, step_id):
        return {
            "format": "taskweave-draft-1",
            "document": normalize_step(self.repo.step(step_id)),
        }

    def import_draft(self, task_id, package):
        if package.get("format") != "taskweave-draft-1":
            raise TaskError("DRAFT_FORMAT_INVALID")
        return self.repo.save_step(task_id, package["document"])

    def export_feedback(self, attempt_id):
        return self.repo.feedback(attempt_id)

    def configure_plugin(self, plugin_id, enabled):
        from taskweave.plugins.manager import PluginManager

        if self.registry_factory is not None:
            raise TaskError("PLUGIN_CONFIG_FIXED")
        if self.repo.query("SELECT 1 FROM runtime_lease") or (
            self.coordinator.thread and self.coordinator.thread.is_alive()
        ):
            raise TaskError("PLUGIN_CONFIG_LOCKED")
        registry = PluginManager(self.home).configure(plugin_id, enabled)
        self.coordinator._stop_worker()
        self.registry = self.coordinator.registry = self.authoring.registry = registry
        return registry.catalog()

    def collect_context(
        self, step_id, provider_id, request=None, environment_id=None, run_id=None
    ):
        if run_id is not None:
            return self.coordinator.collect_context(
                run_id, step_id, provider_id, request
            )
        return asyncio.run(
            self.authoring.collect_context(
                step_id, provider_id, request, environment_id
            )
        )

    def installed_plugins(self):
        from taskweave.plugins.manager import PluginManager

        return PluginManager(self.home).catalog()

    def dispatch(self, operation, params=None):
        methods = {
            "plugin.configure": self.configure_plugin,
            "plugin.list": self.installed_plugins,
            "context.read": self.collect_context,
            "task.copy": self.repo.copy_task,
            "task.clear_runs": self.clear_task_runs,
            "task.export": self.export_task,
            "task.import": self.import_task,
            "task.reorder": self.repo.reorder_tasks,
            "environment.list": self.repo.list_environments,
            "task.create": self.repo.create_task,
            "task.update": self.repo.update_task,
            "task.list": self.repo.list_tasks,
            "task.get": self.repo.task,
            "task.delete": self.repo.delete_task,
            "step.save": self.repo.save_step,
            "step.get": self.repo.step,
            "step.list": self.repo.steps,
            "step.reorder": self.repo.reorder,
            "step.delete": self.repo.delete_step,
            "step.validate": self.validate_step,
            "step.trial": self.trial_step,
            "step.trial.flow": self.trial_flow,
            "step.confirm": self.confirm_step,
            "step.confirm.manual": self.confirm_step_manual,
            "draft.export": self.export_draft,
            "draft.import": self.import_draft,
            "feedback.export": self.export_feedback,
            "environment.save": self.repo.save_environment,
            "environment.delete": self.delete_environment,
            "capabilities": self.registry.catalog,
            "run.create": self.create_run,
            "run.start": self.coordinator.start,
            "run.inputs": self.coordinator.provide_inputs,
            "run.restart": self.coordinator.restart,
            "run.delete": self.coordinator.delete_run,
            "run.control": self.coordinator.control,
            "run.reconcile": self.coordinator.reconcile,
            "run.get": self.coordinator.describe_run,
            "run.context.sessions": self.coordinator.context_sessions,
            "run.list": self.repo.list_runs,
            "run.wait": self.coordinator.wait,
            "run.output": lambda run_id, step_id, output="data": self.repo.read_output(
                run_id, step_id, output, self.registry
            ),
            "run.events": self.repo.events,
            "result.read": lambda result_id: self.repo.read_result(
                result_id, self.registry
            ),
            "result.delete": self.repo.delete_result,
        }
        async_methods = {
            "step.generate": self.authoring.generate,
            "step.diagnose": self.authoring.diagnose,
        }
        if operation in async_methods:
            return asyncio.run(async_methods[operation](**(params or {})))
        if operation not in methods:
            raise TaskError("OPERATION_UNKNOWN", operation)
        if operation in {
            "run.wait",
            "run.get",
            "run.list",
            "run.events",
            "run.output",
            "result.read",
            "task.list",
            "task.get",
            "step.get",
            "step.list",
            "capabilities",
            "draft.export",
            "task.export",
            "feedback.export",
        }:
            return methods[operation](**(params or {}))
        with self.coordinator.lock:
            return methods[operation](**(params or {}))
