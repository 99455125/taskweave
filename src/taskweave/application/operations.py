"""Stable public operation routing, separated from use-case composition."""

import asyncio

from taskweave.core.validation import TaskError


LOCK_EXEMPT_OPERATIONS = frozenset({
    "ai.settings.get", "ai.settings.update", "capabilities", "context.ai",
    "context.capture.get", "context.list", "context.read", "context.targets", "context.record",
    "draft.export", "feedback.export", "instance.end", "instance.list",
    "plan.context.capture.get", "plan.context.collect", "plan.context.delete",
    "plan.context.list", "plan.context.read", "plan.context.targets", "plan.context.record",
    "plan.context.update", "plan.create", "plan.delete", "plan.generation.get", "plan.generation.import", "plan.generation.imports", "plan.generation.list",
    "plan.generation.parse", "plan.get", "plan.list", "plan.update", "result.read",
    "run.events", "run.events.page", "run.get", "run.instances", "run.list", "run.output", "run.wait",
    "step.get", "step.list", "task.export", "task.get", "task.list", "organization.category.list",
})


def build_operation_routes(app):
    sync = {
        "plugin.configure": app.configure_plugin,
        "plugin.list": app.installed_plugins,
        "organization.category.list": app.organization.categories,
        "organization.category.create": app.organization.create_category,
        "organization.category.rename": app.organization.rename_category,
        "organization.category.delete": app.organization.delete_category,
        "organization.metadata.set": app.organization.set_metadata,
        "context.read": app.contexts.collect,
        "context.record": app.contexts.record,
        "context.targets": app.contexts.targets,
        "context.list": app.contexts.list,
        "context.ai": app.contexts.ai_records,
        "context.save": app.contexts.save,
        "context.save_batch": app.contexts.save_batch,
        "context.group.update": app.contexts.update_group,
        "context.capture.get": app.contexts.get_capture,
        "context.capture.append": app.contexts.append_capture,
        "context.capture.replace": app.contexts.replace_capture,
        "context.capture.delete": app.contexts.delete_capture,
        "context.capture.reorder": app.contexts.reorder_capture,
        "context.capture.label": app.contexts.label_capture,
        "context.reorder": app.contexts.reorder_group,
        "context.delete": app.contexts.delete_group,
        "task.copy": app.tasks.copy,
        "task.clear_runs": app.tasks.clear_runs,
        "task.export": app.tasks.export,
        "task.import": app.tasks.import_package,
        "plan.create": app.planning.create,
        "plan.copy": app.planning.copy,
        "plan.list": app.planning.list,
        "plan.get": app.planning.get,
        "plan.update": app.planning.update,
        "plan.delete": app.planning.delete,
        "plan.context.collect": app.planning.context_collect,
        "plan.context.read": app.planning.context_collect,
        "plan.context.save_batch": app.planning.context_save_batch,
        "plan.context.targets": app.planning.context_targets,
        "plan.context.record": app.planning.context_record,
        "plan.context.list": app.planning.context_list,
        "plan.context.capture.get": app.planning.context_capture_get,
        "plan.context.capture.append": app.planning.context_capture_append,
        "plan.context.capture.replace": app.planning.context_capture_replace,
        "plan.context.capture.delete": app.planning.context_capture_delete,
        "plan.context.capture.reorder": app.planning.context_capture_reorder,
        "plan.context.capture.label": app.planning.context_capture_label,
        "plan.context.update": app.planning.context_update,
        "plan.context.reorder": app.planning.context_reorder,
        "plan.context.delete": app.planning.context_delete,
        "plan.generation.parse": app.planning.parse,
        "plan.generation.import": app.planning.import_generation,
        "plan.generation.list": app.planning.generation_list,
        "plan.generation.get": app.planning.generation_get,
        "plan.generation.imports": app.planning.generation_imports,
        "instance.list": app.instances,
        "instance.end": app.end_instance,
        "ai.settings.get": app.ai_settings.get,
        "ai.settings.update": app.ai_settings.update,
        "environment.list": app.environments.list,
        "task.create": app.tasks.create,
        "task.update": app.tasks.update,
        "task.list": app.tasks.list,
        "task.get": app.tasks.get,
        "task.delete": app.tasks.delete,
        "step.save": app.steps.save,
        "step.get": app.steps.get,
        "step.list": app.steps.list,
        "step.reorder": app.steps.reorder,
        "step.delete": app.steps.delete,
        "step.validate": app.steps.validate,
        "step.trial": app.steps.trial,
        "step.trial.flow": app.steps.trial_flow,
        "step.confirm": app.steps.confirm,
        "step.confirm.manual": app.steps.confirm_manual,
        "draft.export": app.steps.export_draft,
        "draft.import": app.steps.import_draft,
        "feedback.export": app.steps.export_feedback,
        "environment.save": app.environments.save,
        "environment.delete": app.environments.delete,
        "capabilities": app.registry.catalog,
        "run.create": app.runs.create,
        "run.start": app.runs.start,
        "run.inputs": app.runs.provide_inputs,
        "run.restart": app.runs.restart,
        "run.delete": app.runs.delete,
        "run.control": app.runs.control,
        "run.instances": app.runs.instances,
        "run.reconcile": app.runs.reconcile,
        "run.get": app.runs.get,
        "run.context.sessions": app.runs.context_sessions_for_task,
        "run.list": app.runs.list,
        "run.wait": app.runs.wait,
        "run.output": app.runs.output,
        "run.events": app.runs.events,
        "run.events.page": app.runs.event_page,
        "result.read": app.runs.read_result,
        "result.delete": app.runs.delete_result,
    }
    asynchronous = {
        "step.generate": app.authoring.generate,
        "step.generate_goal": app.authoring.generate_goal,
        "step.diagnose": app.authoring.diagnose,
        "plan.generate": app.planning.generate,
    }
    return sync, asynchronous


def dispatch_operation(app, operation, params=None):
    sync, asynchronous = build_operation_routes(app)
    arguments = params or {}
    if operation in asynchronous:
        return asyncio.run(asynchronous[operation](**arguments))
    if operation not in sync:
        raise TaskError("OPERATION_UNKNOWN", operation)
    if operation in LOCK_EXEMPT_OPERATIONS:
        return sync[operation](**arguments)
    with app.coordinator.lock:
        return sync[operation](**arguments)
