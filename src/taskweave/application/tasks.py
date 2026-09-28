"""Task definition and task-package application use cases."""

from taskweave.application.task_transfer import export_task, import_task, validate_task_package
from taskweave.core.repositories import StepContextRepository, StepRepository, TaskRepository, UnitOfWork


class TaskUseCases:
    def __init__(self, tasks: TaskRepository, steps: StepRepository, step_contexts: StepContextRepository, uow: UnitOfWork, registry, authoring, coordinator):
        self.tasks = tasks
        self.steps = steps
        self.step_contexts = step_contexts
        self.uow = uow
        self.registry = registry
        self.authoring = authoring
        self.coordinator = coordinator

    def create(self, name, input_schema=None, description=""):
        return self.tasks.create_task(name, input_schema, description)

    def get(self, task_id): return self.tasks.task(task_id)
    def list(self): return self.tasks.list_tasks()
    def update(self, task_id, name, input_schema, description=""):
        return self.tasks.update_task(task_id, name, input_schema, description)
    def delete(self, task_id): return self.tasks.delete_task(task_id)
    def copy(self, task_id, name=None): return self.tasks.copy_task(task_id, name)

    def export(self, task_id):
        return export_task(self.tasks, self.steps, self.step_contexts, task_id)

    def validate_package(self, package, *, expected_origin=None):
        return validate_task_package(self.registry, self.authoring, package, expected_origin=expected_origin)

    def import_package(self, package):
        return import_task(
            self.tasks, self.steps, self.step_contexts, self.uow,
            self.registry, self.authoring, package,
        )

    def clear_runs(self, task_id):
        result = self.coordinator.clear_task_runs(task_id)
        for step in self.steps.steps(task_id):
            self.authoring.reset_conversation(step["step_id"])
        return result
