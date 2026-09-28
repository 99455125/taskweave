"""Compatibility facade for plan, context and generation repositories."""

from taskweave.infrastructure.repositories.plan_contexts import PlanContextRepository
from taskweave.infrastructure.repositories.plan_generations import PlanGenerationRepository
from taskweave.infrastructure.repositories.plans import PlanMetadataRepository


class PlanRepository:
    def __init__(self, store):
        self.store = store
        repositories = getattr(store, "_repository_set", None)
        if repositories is None:
            self.plan_contexts = PlanContextRepository(store)
            self.plans = PlanMetadataRepository(store, self.plan_contexts)
            self.plan_generations = PlanGenerationRepository(store)
        else:
            self.plan_contexts = repositories.plan_contexts
            self.plans = repositories.plans
            self.plan_generations = repositories.plan_generations
        self.root = self.plans.root

    @staticmethod
    def _decode(plan):
        return PlanMetadataRepository._decode(plan)

    def create(self, name='新计划'):
        return self.plans.create(name)

    def copy(self, plan_id, expected_revision):
        return self.plans.copy(plan_id, expected_revision)

    def list(self):
        return self.plans.list()

    def get(self, plan_id):
        return self.plans.get(plan_id)

    @staticmethod
    def _expect(db, plan_id, revision):
        return PlanMetadataRepository._expect(db, plan_id, revision)

    def update(self, plan_id, expected_revision, name, plan_description='', plan_notes='', environment_id=None, plugin_ids=None):
        return self.plans.update(plan_id, expected_revision, name, plan_description, plan_notes, environment_id, plugin_ids)

    def delete(self, plan_id, expected_revision):
        return self.plans.delete(plan_id, expected_revision)

    def contexts(self, plan_id):
        return self.plan_contexts.contexts(plan_id)

    def get_capture(self, context_id, capture_id, plan_id=None):
        return self.plan_contexts.get_capture(context_id, capture_id, plan_id)

    def context_records(self, plan_id):
        return self.plan_contexts.context_records(plan_id)

    def save_context_batch(self, plan_id, expected_revision, context_id, provider_id, name, context_notes, captures):
        return self.plan_contexts.save_context_batch(plan_id, expected_revision, context_id, provider_id, name, context_notes, captures)

    def append_capture(self, plan_id, expected_revision, context_id, capture, *, request=None, include_view=True, session_id=None, label=''):
        return self.plan_contexts.append_capture(plan_id, expected_revision, context_id, capture, request=request, include_view=include_view, session_id=session_id, label=label)

    def delete_capture(self, plan_id, expected_revision, context_id, capture_id):
        return self.plan_contexts.delete_capture(plan_id, expected_revision, context_id, capture_id)

    def reorder_capture(self, plan_id, expected_revision, context_id, capture_id, direction):
        return self.plan_contexts.reorder_capture(plan_id, expected_revision, context_id, capture_id, direction)

    def update_capture_label(self, plan_id, expected_revision, context_id, capture_id, label, operation_notes=None, send_preview=None):
        return self.plan_contexts.update_capture_label(plan_id, expected_revision, context_id, capture_id, label, operation_notes, send_preview)

    @staticmethod
    def _context_metadata(name, context_notes):
        return PlanContextRepository._context_metadata(name, context_notes)

    def add_context(self, plan_id, expected_revision, provider_id, name, context_notes, session_id, items, request=None, views=None, include_view=True):
        return self.plan_contexts.add_context(plan_id, expected_revision, provider_id, name, context_notes, session_id, items, request, views, include_view)

    def update_context(self, plan_id, expected_revision, context_id, name, context_notes=''):
        return self.plan_contexts.update_context(plan_id, expected_revision, context_id, name, context_notes)

    def replace_context(self, plan_id, expected_revision, context_id, provider_id, name, context_notes, session_id, items, request=None, views=None, include_view=True):
        return self.plan_contexts.replace_context(plan_id, expected_revision, context_id, provider_id, name, context_notes, session_id, items, request, views, include_view)

    def replace_capture(self, plan_id, expected_revision, context_id, capture_id, capture, *, request=None, include_view=True, session_id=None):
        return self.plan_contexts.replace_capture(plan_id, expected_revision, context_id, capture_id, capture, request=request, include_view=include_view, session_id=session_id)

    def reorder_context(self, plan_id, expected_revision, context_id, direction):
        return self.plan_contexts.reorder_context(plan_id, expected_revision, context_id, direction)

    def delete_context(self, plan_id, expected_revision, context_id):
        return self.plan_contexts.delete_context(plan_id, expected_revision, context_id)

    def create_generation(self, plan_id, revision, channel, request_path):
        return self.plan_generations.create_generation(plan_id, revision, channel, request_path)

    def generation(self, generation_id):
        return self.plan_generations.generation(generation_id)

    def finish_generation(self, generation_id, status, response_path=None, candidate=None, diagnostics=None):
        return self.plan_generations.finish_generation(generation_id, status, response_path, candidate, diagnostics)

    def mark_imported(self, generation_id, task_id):
        return self.plan_generations.mark_imported(generation_id, task_id)
