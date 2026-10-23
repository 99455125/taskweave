"""Public application API shared by CLI, HTTP and future desktop UI."""

from pathlib import Path
from taskweave.core.validation import TaskError
from taskweave.application.operations import dispatch_operation
from taskweave.application.composition import compose_application
from taskweave.infrastructure.locking import InstanceLock
from taskweave.infrastructure.sqlite_storage import default_home


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
            compose_application(self, model, registry_factory)
        except Exception:
            self.instance.close()
            raise

    def close(self):
        try:
            if hasattr(self, "sequence_driver"):
                self.sequence_driver.close()
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
        if self.runtime_leases.has_runtime_lease() or (
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
        self.sequences.registry = registry
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

    def end_instance(self, instance_type, owner_id, command_id=None):
        return self.runs.end_instance(instance_type, owner_id, command_id)

    def dispatch(self, operation, params=None):
        return dispatch_operation(self, operation, params)
