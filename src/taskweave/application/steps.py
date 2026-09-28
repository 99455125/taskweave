"""Step editing, trial and validation application use cases."""

import asyncio
import json

from taskweave.core.validation import TaskError, normalize_step
from taskweave.core.repositories import RunRepository, StepRepository, TaskRepository


class StepUseCases:
    def __init__(self, steps: StepRepository, tasks: TaskRepository, runs: RunRepository, registry, authoring, coordinator):
        self.steps, self.tasks, self.runs = steps, tasks, runs
        self.registry, self.authoring, self.coordinator = registry, authoring, coordinator

    def save(self, task_id, document, step_id=None, expected_hash=None):
        return self.steps.save_step(task_id, document, step_id, expected_hash)
    def get(self, step_id): return self.steps.step(step_id)
    def list(self, task_id): return self.steps.steps(task_id)
    def reorder(self, task_id, step_ids): return self.steps.reorder(task_id, step_ids)
    def delete(self, step_id): return self.steps.delete_step(step_id)

    def validate(self, step_id):
        step = self.steps.step(step_id)
        diagnostics = asyncio.run(self.authoring.validate_step(step))
        return {"step_id": step_id, "valid": not any(d["severity"] == "error" for d in diagnostics), "diagnostics": diagnostics}

    def trial(self, step_id, inputs, command_id, environment_id=None, continue_session=False, defer_inputs=False):
        with self.coordinator.lock:
            previous = self.runs.find_trial_command(command_id, step_id, inputs, environment_id)
            if previous:
                return previous
            validation = self.validate(step_id)
            if not validation["valid"]:
                raise TaskError("PLUGIN_LINT_FAILED")
            step = self.steps.step(step_id)
            lease = self.runs.trial_lease_for_task(step["task_id"])
            if lease:
                owner = self.runs.run(lease["run_id"])
                compatible = owner["mode"] == "TRIAL" and owner["task_id"] == step["task_id"] and owner["environment_id"] == environment_id and owner["status"] in {"FAILED", "SUCCEEDED"}
                if not compatible or (self.runs.has_unsafe_attempts(owner["run_id"]) and not continue_session):
                    raise TaskError("RUN_LEASE_BUSY", "已有运行占用执行器，请在试跑反馈或执行页结束该运行")
                if self.runs.has_unsafe_attempts(owner["run_id"]):
                    self.runs.event(owner["run_id"], "USER_RETRY_WITH_RETAINED_SESSION", {"step_id": step_id, "previous_effect_unknown": True})
                self.runs.release_lease(owner["run_id"])
            run = self.runs.create_run(step["task_id"], inputs, self.registry.versions, environment_id, step_id, defer_inputs=defer_inputs)
            result = self.coordinator.start(run["run_id"], command_id)
            if not continue_session:
                self.authoring.reset_conversation(step_id)
            return result

    def trial_flow(self, step_id, inputs, command_id, environment_id=None, step_inputs=None, defer_inputs=False, start_step_id=None):
        with self.coordinator.lock:
            task_id = self.steps.step(step_id)["task_id"]
            step_inputs = self.runs.normalize_step_inputs(task_id, step_inputs)
            previous = self.runs.find_trial_command(command_id, step_id, inputs, environment_id)
            if previous:
                request = json.loads(self.runs.run(previous["run_id"])["request_json"])
                if not request.get("flow_trial") or request.get("initial_step_inputs", request.get("step_inputs", {})) != (step_inputs or {}):
                    raise TaskError("COMMAND_CONFLICT")
                return previous
            step = self.steps.step(step_id)
            leases = self.runs.trial_leases_for_task(step["task_id"])
            for lease in leases:
                owner = self.runs.run(lease["run_id"])
                if owner["mode"] != "TRIAL" or owner["task_id"] != step["task_id"]:
                    raise TaskError("RUN_LEASE_BUSY")
            for candidate in self.steps.steps(step["task_id"]):
                if not self.validate(candidate["step_id"])["valid"]:
                    raise TaskError("PLUGIN_LINT_FAILED")
                if candidate["step_id"] == step_id:
                    break
            for lease in leases:
                self.runs.release_lease(lease["run_id"])
            run = self.runs.create_run(step["task_id"], inputs, self.registry.versions, environment_id, step_id, flow_trial=True, step_inputs=step_inputs, defer_inputs=defer_inputs)
            return self.coordinator.start(run["run_id"], command_id, start_step_id=start_step_id)

    def confirm(self, step_id, attempt_id, expected_hash):
        self.registry.check(self.steps.step(step_id))
        if self.runs.attempt_versions(attempt_id) != self.registry.versions:
            raise TaskError("PLUGIN_VERSION_MISMATCH")
        return self.steps.confirm(step_id, attempt_id, expected_hash)

    def confirm_manual(self, step_id, expected_hash, environment_id=None):
        if not self.validate(step_id)["valid"]:
            raise TaskError("PLUGIN_LINT_FAILED")
        return self.steps.confirm_manual(step_id, expected_hash, environment_id)

    def export_draft(self, step_id):
        return {"format": "taskweave-draft-1", "document": normalize_step(self.steps.step(step_id))}

    def import_draft(self, task_id, package):
        if package.get("format") != "taskweave-draft-1":
            raise TaskError("DRAFT_FORMAT_INVALID")
        return self.steps.save_step(task_id, package["document"])

    def export_feedback(self, attempt_id): return self.runs.feedback(attempt_id)
