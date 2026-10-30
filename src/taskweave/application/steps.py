"""Step editing, trial and validation application use cases."""

from taskweave.core.data_contracts import StepRecord
from taskweave.core.run_ports import StepRunStore
import asyncio
import json

from taskweave.core.validation import TaskError, normalize_step
from taskweave.core.repositories import StepRepository, TaskRepository


class StepUseCases:
    def __init__(self, steps: StepRepository, tasks: TaskRepository, runs: StepRunStore, registry, authoring, coordinator, context_sessions=None, *, uow=None):
        self.uow = uow
        self.context_sessions = context_sessions
        self.steps, self.tasks, self.runs = steps, tasks, runs
        self.registry, self.authoring, self.coordinator = registry, authoring, coordinator

    def save(self, task_id, document, step_id=None, expected_hash=None):
        return self.steps.save_step(task_id, document, step_id, expected_hash)
    def insert(self, task_id, document, parent_id, index, expected_hash):
        """Create and place an action as one definition change."""
        from taskweave.core.task_flow import conditional_branches
        with self.uow.transaction():
            if self.tasks.definition_hash(task_id) != expected_hash:
                raise TaskError("EDIT_CONFLICT")
            flow = self.tasks.flow(task_id)
            def sequences(node):
                if node['kind'] == 'sequence':
                    yield node
                    for child in node['children']:
                        yield from sequences(child)
                elif node['kind'] == 'if':
                    for _, body in conditional_branches(node):
                        yield from sequences(body)
                elif node['kind'] in {'loop', 'foreach'}:
                    yield from sequences(node['body'])
            parent = next((node for node in sequences(flow['root']) if node['id'] == parent_id), None)
            if parent is None or type(index) is not int or not 0 <= index <= len(parent['children']):
                raise TaskError("FLOW_EDITOR_TARGET_INVALID")
            saved = self.steps.save_step(task_id, document)
            parent['children'].insert(index, {'id': saved['step_id'], 'kind': 'action', 'step_id': saved['step_id']})
            self.tasks.save_flow(task_id, flow, self.tasks.definition_hash(task_id))
            return self.steps.step(saved['step_id'])

    def get(self, step_id) -> StepRecord: return self.steps.step(step_id)
    def list(self, task_id): return self.steps.steps(task_id)
    def reorder(self, task_id, step_ids): return self.steps.reorder(task_id, step_ids)
    def delete(self, step_id):
        if self.context_sessions:
            return self.context_sessions.change_step_owner(step_id, lambda: self.steps.delete_step(step_id))
        return self.steps.delete_step(step_id)

    def validate(self, step_id):
        step = self.steps.step(step_id)
        diagnostics = asyncio.run(self.authoring.validate_step(step))
        return {"step_id": step_id, "valid": not any(d["severity"] == "error" for d in diagnostics), "diagnostics": diagnostics}

    def trial_sessions(self, step_id, environment_id=None):
        self.steps.step(step_id)
        with self.coordinator.lock:
            return self.coordinator.trial_sessions(environment_id)

    @staticmethod
    def _scene_request(new_session, session_run_id, expected_session_id):
        if type(new_session) is not bool or any(value is not None and (
                not isinstance(value, str) or not value.strip()) for value in (session_run_id, expected_session_id)):
            raise TaskError('FORM_INVALID', '现场选项需要布尔值及有效实例标识')
        if new_session and session_run_id or bool(session_run_id) != bool(expected_session_id):
            raise TaskError('FORM_INVALID', '请选择新建现场或完整的已有现场')
        return ({'new': True} if new_session else
                {'run_id': session_run_id, 'session_id': expected_session_id} if session_run_id else None)

    def _bind_scene(self, run, scene, owner):
        if scene is not None:
            request = json.loads(run['request_json'])
            request['debug_scene'] = scene
            self.runs.update_run_request(run['run_id'], json.dumps(request))
            self.coordinator.bind_trial_scene(run['run_id'], owner)

    def trial(self, step_id, inputs, command_id, environment_id=None, continue_session=False, defer_inputs=False,
              new_session=False, session_run_id=None, expected_session_id=None):
        with self.coordinator.lock:
            scene = self._scene_request(new_session, session_run_id, expected_session_id)
            previous = self.runs.find_trial_command(command_id, step_id, inputs, environment_id)
            if previous:
                request = json.loads(self.runs.run(previous['run_id'])['request_json'])
                if request.get('debug_scene') != scene:
                    raise TaskError('COMMAND_CONFLICT')
                return previous
            validation = self.validate(step_id)
            if not validation["valid"]:
                raise TaskError("PLUGIN_LINT_FAILED")
            step = self.steps.step(step_id)
            owner = (self.coordinator.trial_scene_owner(session_run_id, expected_session_id, environment_id)
                     if session_run_id else None)
            lease = self.runs.trial_lease_for_task(step["task_id"]) if scene is None else None
            if lease:
                owner = self.runs.run(lease["run_id"])
                compatible = owner["mode"] == "TRIAL" and owner["task_id"] == step["task_id"] and owner["environment_id"] == environment_id and owner["status"] in {"FAILED", "SUCCEEDED"}
                if not compatible or (self.runs.has_unsafe_attempts(owner["run_id"]) and not continue_session):
                    raise TaskError("RUN_LEASE_BUSY", "已有运行占用执行器，请在试跑反馈或执行页结束该运行")
                if self.runs.has_unsafe_attempts(owner["run_id"]):
                    self.runs.event(owner["run_id"], "USER_RETRY_WITH_RETAINED_SESSION", {"step_id": step_id, "previous_effect_unknown": True})
                self.runs.release_lease(owner["run_id"])
            run = self.runs.create_run(step["task_id"], inputs, self.registry.versions, environment_id, step_id, defer_inputs=defer_inputs)
            self._bind_scene(run, scene, owner)
            result = self.coordinator.start(run["run_id"], command_id)
            if not continue_session:
                self.authoring.reset_conversation(step_id)
            return result

    def trial_flow(self, step_id, inputs, command_id, environment_id=None, step_inputs=None, defer_inputs=False, start_step_id=None,
                   new_session=False, session_run_id=None, expected_session_id=None):
        with self.coordinator.lock:
            scene = self._scene_request(new_session, session_run_id, expected_session_id)
            task_id = self.steps.step(step_id)["task_id"]
            step_inputs = self.runs.normalize_step_inputs(task_id, step_inputs)
            previous = self.runs.find_trial_command(command_id, step_id, inputs, environment_id)
            if previous:
                request = json.loads(self.runs.run(previous["run_id"])["request_json"])
                if not request.get("flow_trial") or request.get("initial_step_inputs", request.get("step_inputs", {})) != (step_inputs or {}):
                    raise TaskError("COMMAND_CONFLICT")
                if request.get('debug_scene') != scene:
                    raise TaskError('COMMAND_CONFLICT')
                return previous
            step = self.steps.step(step_id)
            from taskweave.core.task_flow import is_linear_flow
            flow = self.tasks.flow(step['task_id'])
            if not is_linear_flow(flow) and start_step_id is not None:
                if start_step_id != self.steps.steps(step['task_id'])[0]['step_id']:
                    raise TaskError('FLOW_INSTANCE_REQUIRED', '条件或循环流程请从流程起点调试')
                start_step_id = None
            scene_owner = (self.coordinator.trial_scene_owner(session_run_id, expected_session_id, environment_id)
                           if session_run_id else None)
            leases = self.runs.trial_leases_for_task(step["task_id"]) if scene is None else []
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
            self._bind_scene(run, scene, scene_owner)
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
