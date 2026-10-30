"""Context collection and persistence application use cases."""

from taskweave.core.validation import TaskError
from taskweave.core.repositories import StepContextRepository, StepRepository


class ContextUseCases:
    def __init__(self, contexts: StepContextRepository, steps: StepRepository, registry, authoring, coordinator, sessions):
        self.contexts, self.steps, self.registry, self.authoring = contexts, steps, registry, authoring
        self.coordinator, self.sessions = coordinator, sessions

    def collect(self, step_id, provider_id, request=None, environment_id=None, run_id=None, expected_session_id=None, include_view=True, execution_path=None):
        if run_id is not None:
            return self.coordinator.collect_context(run_id, step_id, provider_id, request, expected_session_id=expected_session_id,
                                                    include_view=include_view, execution_path=execution_path)
        if execution_path is not None:
            raise TaskError("FLOW_INSTANCE_REQUIRED")
        return self.sessions.step_collect(step_id, provider_id, request, environment_id,
            expected_session_id=expected_session_id, include_view=include_view)

    def record(self, step_id, provider_id, operation, *, run_id=None, execution_path=None, **options):
        if run_id is None:
            if execution_path is not None:
                raise TaskError("FLOW_INSTANCE_REQUIRED")
            return self.sessions.step_record(step_id, provider_id, operation, **options)
        return self.coordinator.record_context(run_id, step_id, provider_id, operation,
                                               execution_path=execution_path, **options)

    def targets(self, step_id, provider_id, run_id=None, request=None, execution_path=None, expected_session_id=None):
        if run_id is not None:
            return self.coordinator.context_targets(run_id, step_id, provider_id, request,
                                                    execution_path=execution_path, expected_session_id=expected_session_id)
        if execution_path is not None:
            raise TaskError("FLOW_INSTANCE_REQUIRED")
        return self.sessions.step_targets(step_id, provider_id, request)

    def save_batch(self, step_id, context_id, expected_revision, provider_id, name, context_notes, captures):
        step = self.steps.step(step_id)
        allowed = {provider for contribution in self.registry.contributions(step.get("capabilities", [])) for provider in contribution.context_provider_ids}
        if provider_id not in allowed:
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", provider_id)
        return self.contexts.save_step_context_batch(step_id, context_id, expected_revision, provider_id, name, context_notes, captures)

    def list(self, step_id): return self.contexts.list_step_contexts(step_id)
    def ai_records(self, step_id): return self.contexts.step_context_records(step_id)
    def get_capture(self, context_id, capture_id, step_id=None): return self.contexts.get_step_context_capture(context_id, capture_id, step_id)
    def save(self, step_id, provider_id, name, source_page, item, context_id=None, context_notes="", request=None, views=None, include_view=True, replace_capture=False, captured_at=None, capture_id=None, append=False, expected_revision=None, source_session_id=None):
        return self.contexts.save_step_context(step_id, provider_id, name, source_page, item, context_id, context_notes, request, views, include_view, replace_capture, captured_at, capture_id, append, expected_revision, source_session_id)
    def update_group(self, step_id, context_id, name, context_notes="", expected_revision=None):
        return self.contexts.update_step_context_group(step_id, context_id, name, context_notes, expected_revision)
    def append_capture(self, context_id, capture, *, request=None, include_view=True, source_page="draft", source_session_id=None, label="", captured_at=None, expected_revision=None, step_id=None):
        return self.contexts.append_step_context_capture(context_id, capture, request=request, include_view=include_view, source_page=source_page, source_session_id=source_session_id, label=label, captured_at=captured_at, expected_revision=expected_revision, step_id=step_id)
    def replace_capture(self, context_id, capture_id, capture, *, request=None, include_view=True, source_page="draft", source_session_id=None, label=None, captured_at=None, expected_revision=None, step_id=None):
        return self.contexts.replace_step_context_capture(context_id, capture_id, capture, request=request, include_view=include_view, source_page=source_page, source_session_id=source_session_id, label=label, captured_at=captured_at, expected_revision=expected_revision, step_id=step_id)
    def delete_capture(self, context_id, capture_id, expected_revision=None, step_id=None):
        return self.contexts.delete_step_context_capture(context_id, capture_id, expected_revision, step_id)
    def reorder_capture(self, context_id, capture_id, direction, expected_revision=None, step_id=None):
        return self.contexts.reorder_step_context_capture(context_id, capture_id, direction, expected_revision, step_id)
    def label_capture(self, context_id, capture_id, label, expected_revision=None, step_id=None, operation_notes=None, send_preview=None):
        return self.contexts.update_step_context_capture_label(context_id, capture_id, label, expected_revision, step_id, operation_notes, send_preview)
    def reorder_group(self, context_id, direction, expected_revision=None, step_id=None):
        return self.contexts.reorder_step_context(context_id, direction, expected_revision, step_id)
    def delete_group(self, context_id, expected_revision=None, step_id=None):
        return self.contexts.delete_step_context(context_id, expected_revision, step_id)

    def transfer(self, step_id, context_id, capture_ids, target_step_id, *, mode,
                 expected_revision, target_context_id=None, target_expected_revision=None, target_name=None):
        with self.contexts.transaction():
            source = next((g for g in self.contexts.list_step_contexts(step_id) if g['context_id'] == context_id), None)
            if source is None:
                raise TaskError('CONTEXT_MISMATCH', '上下文不属于来源步骤')
            target = self.steps.step(target_step_id)
            allowed = {provider for contribution in self.registry.contributions(target.get('capabilities', []))
                       for provider in contribution.context_provider_ids}
            if source['provider_id'] not in allowed:
                raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE', '目标步骤未启用此上下文的插件能力')
            return self.contexts.transfer_step_context_captures(
                step_id, context_id, capture_ids, target_step_id, mode=mode, expected_revision=expected_revision,
                target_context_id=target_context_id, target_expected_revision=target_expected_revision, target_name=target_name)
