"""Task definitions, authoring evidence and durable command state."""

import json
from taskweave.core.validation import (
    TaskError,
    normalize_step,
    fingerprint,
    check_schema,
    check_bindings,
    dumps,
    validate,
)
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.storage import Store, uid, now
from taskweave.infrastructure.repositories import build_sqlite_repositories


class Repository(Store):
    def __init__(self, home):
        super().__init__(home)
        self._repository_set = build_sqlite_repositories(self)
        self.tasks = self._repository_set.tasks
        self.step_repository = self._repository_set.steps
        self.environment_repository = self._repository_set.environments
        self.run_repository = self._repository_set.runs
        self.result_repository = self._repository_set.results
        self.context_repository = self._repository_set.step_contexts

    @property
    def repositories(self):
        return self._repository_set


    def create_task(self, name, input_schema=None, description=""):
        return self.tasks.create_task(name, input_schema, description)

    def update_task(self, task_id, name, input_schema, description=""):
        return self.tasks.update_task(task_id, name, input_schema, description)

    def save_step(self, task_id, document, step_id=None, expected_hash=None):
        return self.step_repository.save_step(task_id, document, step_id, expected_hash)

    def reorder(self, task_id, step_ids):
        return self.step_repository.reorder(task_id, step_ids)

    def delete_step(self, step_id):
        return self.step_repository.delete_step(step_id)

    def save_environment(self, name, public_config, secret_refs=None, environment_id=None, descriptions=None):
        return self.environment_repository.save_environment(name, public_config, secret_refs, environment_id, descriptions)

    def normalize_step_inputs(self, task_id, step_inputs):
        return self.run_repository.normalize_step_inputs(task_id, step_inputs)

    def create_run(self, task_id, inputs, versions, environment_id=None, trial_step_id=None, flow_trial=False, defer_inputs=False, step_inputs=None):
        return self.run_repository.create_run(task_id, inputs, versions, environment_id, trial_step_id, flow_trial, defer_inputs, step_inputs)

    def confirm(self, step_id, attempt_id, expected_hash):
        return self.step_repository.confirm(step_id, attempt_id, expected_hash)

    def confirm_manual(self, step_id, expected_hash, environment_id=None):
        return self.step_repository.confirm_manual(step_id, expected_hash, environment_id)

    def confirm_imported(self, step_id, expected_hash):
        return self.step_repository.confirm_imported(step_id, expected_hash)

    def run_details(self, run_id):
        return self.run_repository.run_details(run_id)

    def copy_task(self, task_id, name=None):
        return self.tasks.copy_task(task_id, name)

    def delete_environment(self, environment_id):
        return self.environment_repository.delete_environment(environment_id)

    def list_environments(self):
        return self.environment_repository.list_environments()

    def list_tasks(self):
        return self.tasks.list_tasks()

    def list_runs(self, task_id=None):
        return self.run_repository.list_runs(task_id)

    def list_step_contexts(self, step_id):
        return self.context_repository.list_step_contexts(step_id)

    def get_step_context_capture(self, context_id, capture_id, step_id=None):
        return self.context_repository.get_step_context_capture(context_id, capture_id, step_id)

    def step_context_records(self, step_id):
        return self.context_repository.step_context_records(step_id)

    def create_step_context_group(self, step_id, provider_id, name, context_notes=''):
        return self.context_repository.create_step_context_group(step_id, provider_id, name, context_notes)

    def save_step_context_batch(self, step_id, context_id, expected_revision, provider_id, name, context_notes, captures):
        return self.context_repository.save_step_context_batch(step_id, context_id, expected_revision, provider_id, name, context_notes, captures)

    def update_step_context_group(self, step_id, context_id, name, context_notes='', expected_revision=None):
        return self.context_repository.update_step_context_group(step_id, context_id, name, context_notes, expected_revision)

    def append_step_context_capture(self, context_id, capture, *, request=None, include_view=True, source_page='draft', source_session_id=None, label='', captured_at=None, expected_revision=None, step_id=None):
        return self.context_repository.append_step_context_capture(context_id, capture, request=request, include_view=include_view, source_page=source_page, source_session_id=source_session_id, label=label, captured_at=captured_at, expected_revision=expected_revision, step_id=step_id)

    def replace_step_context_capture(self, context_id, capture_id, capture, **metadata):
        return self.context_repository.replace_step_context_capture(context_id, capture_id, capture, **metadata)

    def delete_step_context_capture(self, context_id, capture_id, expected_revision=None, step_id=None):
        return self.context_repository.delete_step_context_capture(context_id, capture_id, expected_revision, step_id)

    def reorder_step_context_capture(self, context_id, capture_id, direction, expected_revision=None, step_id=None):
        return self.context_repository.reorder_step_context_capture(context_id, capture_id, direction, expected_revision, step_id)

    def update_step_context_capture_label(self, context_id, capture_id, label, expected_revision=None, step_id=None, operation_notes=None, send_preview=None):
        return self.context_repository.update_step_context_capture_label(context_id, capture_id, label, expected_revision, step_id, operation_notes, send_preview)

    def save_step_context(self, step_id, provider_id, name, source_page, item, context_id=None, context_notes='', request=None, views=None, include_view=True, replace_capture=False, captured_at=None, capture_id=None, append=False, expected_revision=None, source_session_id=None):
        return self.context_repository.save_step_context(step_id, provider_id, name, source_page, item, context_id, context_notes, request, views, include_view, replace_capture, captured_at, capture_id, append, expected_revision, source_session_id)

    def reorder_step_context(self, context_id, direction, expected_revision=None, step_id=None):
        return self.context_repository.reorder_step_context(context_id, direction, expected_revision, step_id)

    def delete_step_context(self, context_id, expected_revision=None, step_id=None):
        return self.context_repository.delete_step_context(context_id, expected_revision, step_id)

    def events(self, run_id):
        return self.run_repository.events(run_id)

    def event_page(self, run_id, after=0, limit=100):
        return self.run_repository.event_page(run_id, after, limit)

    def feedback(self, attempt_id):
        return self.run_repository.feedback(attempt_id)

    def find_trial_command(self, command_id, step_id, inputs, environment_id):
        return self.run_repository.find_trial_command(command_id, step_id, inputs, environment_id)

    def read_result(self, result_id, registry):
        return self.result_repository.read_result(result_id, registry)

    def delete_result(self, result_id):
        return self.result_repository.delete_result(result_id)

    def delete_task(self, task_id):
        return self.tasks.delete_task(task_id)

    def reset_run_results(self, run_id, from_step_id=None):
        return self.run_repository.reset_run_results(run_id, from_step_id)

    def finish_pending_deletions(self):
        return self.run_repository.finish_pending_deletions()

    def attempt_versions(self, attempt_id):
        return self.run_repository.attempt_versions(attempt_id)
