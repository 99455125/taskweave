"""UI operations use the public application API, including durable authoring evidence."""

import asyncio
import ast
from copy import deepcopy
from difflib import unified_diff
import json
import logging
import os
from pathlib import Path
import subprocess
import shutil
import sys
from uuid import uuid4

from taskweave.core.validation import TaskError, normalize_step
from taskweave.infrastructure.model import HttpModel


def command_id():
    return str(uuid4())


class DesktopController:
    def __init__(self, application):
        self.application = application
        self.native = False
        from taskweave.application.authoring_sessions import bind_application_requests
        self.authoring_requests = getattr(application, 'authoring_requests', None)
        if self.authoring_requests is None:
            # Minimal legacy adapters may omit composition; keep their request
            # lifetime on the supplied application rather than this UI client.
            self.authoring_requests = bind_application_requests(application)
            if application is not None:
                application.authoring_requests = self.authoring_requests
        self._authoring_requests = self.authoring_requests.requests

    def authoring_request(self, step_id):
        return self.authoring_requests.get(step_id)

    async def author_step(self, operation, saved, **params):
        return await self.authoring_requests.submit(operation, saved, **params)

    async def call(self, api_operation, **params):
        logger = logging.getLogger(__name__)
        if api_operation not in {'run.get', 'run.events', 'run.events.page', 'task.list', 'step.list'}:
            logger.info('服务操作：%s', api_operation)
        try:
            return await asyncio.to_thread(self.application.dispatch, api_operation, params)
        except Exception as exc:
            logger.error('服务操作失败：%s [%s]', api_operation, getattr(exc, 'code', type(exc).__name__))
            raise

    @property
    def workspace_home(self):
        return self.application.home

    async def review_report(self, kind, identity):
        report = await asyncio.to_thread(self.application.agent.reviews.read, kind, identity)
        return self.application.agent.sanitize(self.application.agent.public_review(report))

    async def review_decide(self, kind, identity, expected_fingerprint, decision, note):
        return await asyncio.to_thread(self.application.agent.reviews.decide, kind, identity, expected_fingerprint, decision, note)

    async def open_review(self, kind, identity):
        from nicegui import ui
        from taskweave.desktop.components.agent_review import ReviewDialog
        dialog = ReviewDialog(self, lambda label, callback, **options: ui.button(label, on_click=callback))
        await dialog.open(kind, identity)
        return dialog

    def reset_debug_conversation(self, step_id):
        self.application.authoring.reset_conversation(step_id)

    async def validate_step_candidate(self, candidate):
        return await self.application.authoring.validate_step(candidate)

    def append_debug_conversation(self, step_id, messages):
        self.application.authoring.conversations.setdefault(step_id, []).extend(messages)

    def plugin_contributions(self, capabilities):
        return self.application.registry.contributions(capabilities)

    def plugin_context_requests(self):
        requests = {}
        for manifest in self.application.registry.manifests.values():
            requests.update(manifest.get('context_requests', {}))
        return requests

    @property
    def result_renderers(self):
        return self.application.registry.views

    async def execution_inputs(self, run_id):
        return await asyncio.to_thread(self.application.runs.input_values, run_id)

    async def run_request(self, run_id):
        """Read private request state for the local workbench, outside run.get."""
        return await asyncio.to_thread(self.application.runs.request, run_id)

    async def trial_feedback(self, run_id, step_id):
        from taskweave.infrastructure.privacy import redact
        trial = await self.call('run.get', run_id=run_id)
        attempts = [a for a in trial['attempts'] if a['step_id'] == step_id]
        if not attempts:
            raise TaskError('VALIDATION_EVIDENCE_INVALID', '尚无调试记录')
        attempt_id = attempts[-1]['attempt_id']
        feedback = await self.call('feedback.export', attempt_id=attempt_id)
        feedback['run_id'] = run_id
        feedback['attempt_id'] = attempt_id
        definition = json.loads(trial['definition_json'])
        executed = next((item for item in definition['steps'] if item['step_id'] == step_id), None)
        feedback['executed_step_content'] = executed.get('step_content') if executed else None
        events = await self.call('run.events', run_id=run_id)
        logs = []
        size = 0
        for event in reversed(events):
            if event.get('attempt_id') != attempt_id:
                continue
            entry = redact(event)
            length = len(json.dumps(entry, ensure_ascii=False).encode())
            if size + length > 16000 or len(logs) >= 50:
                break
            logs.append(entry)
            size += length
        feedback['trial_logs'] = list(reversed(logs))
        snapshots = [json.loads(e['payload_json']) for e in events if e.get('attempt_id') == attempt_id and e['kind'] == 'BrowserFailureSnapshot']
        feedback['failure_snapshots'] = snapshots
        failed = [json.loads(e['payload_json']) for e in events if e.get('attempt_id') == attempt_id and e['kind'] == 'ActionFailed']
        feedback['failed_action'] = failed[-1] if failed else None
        feedback['note'] = 'Latest attempt error metadata and bounded redacted trial logs'
        return feedback

    async def repair_contexts(self, step, run_id, feedback):
        sessions = await self.call('run.context.sessions', task_id=step['task_id'])
        if not sessions:
            return [], {'available': False, 'reason': '运行会话已丢失，未打开新浏览器；历史快照仅作为失败时证据。'}
        session = sessions[0]
        contributions = self.application.registry.contributions(step['capabilities'])
        providers = sorted({p for c in contributions for p in c.context_provider_ids})
        role = (feedback.get('failed_action') or {}).get('role')
        if not role and feedback.get('failure_snapshots'):
            role = feedback['failure_snapshots'][-1].get('role')
        request = {'role': role} if role else {}
        contexts, errors = [], []
        for provider in providers:
            try:
                capture = await self.call(
                    'context.read', step_id=step['step_id'], provider_id=provider,
                    run_id=session['run_id'], request=request, include_view=False,
                )
                contexts.extend(capture['items'])
            except Exception as exc:
                errors.append({'provider_id': provider, 'error_code': getattr(exc, 'code', type(exc).__name__)})
        return contexts, {'available': bool(contexts), 'run_id': session['run_id'], 'errors': errors}

    async def save_draft(self, task_id, document, old=None):
        normalized = normalize_step(document)
        if old and normalized == normalize_step(old):
            return await self.call("step.get", step_id=old["step_id"])
        return await self.call(
            "step.save",
            task_id=task_id,
            document=normalized,
            step_id=old["step_id"] if old else None,
            expected_hash=old["content_hash"] if old else None,
        )

    async def previous_result(self, task_id, step_id, environment_id=None, output="data"):
        runs = await self.call('run.list', task_id=task_id)
        for row in reversed(runs[-30:]):
            run = await self.call('run.get', run_id=row['run_id'])
            if run['environment_id'] != environment_id:
                continue
            try:
                result = await self.call('run.output', run_id=run['run_id'], step_id=step_id, output=output)
            except TaskError as exc:
                if exc.code == 'OUTPUT_NOT_AVAILABLE':
                    continue
                raise
            return result
        raise TaskError('OUTPUT_NOT_AVAILABLE')

    async def configured_inputs(self, task_id, environment_id=None):
        task, environments = await asyncio.gather(self.call('task.get', task_id=task_id), self.call('environment.list'))
        environment = next((json.loads(row['public_config_json']) for row in environments if row['environment_id'] == environment_id), {})
        defaults = {key: spec['default'] for key, spec in json.loads(task['input_schema_json']).get('properties', {}).items() if 'default' in spec}
        return {**environment, **defaults}

    async def trial(self, step, inputs, environment_id=None, continue_session=False, *, scene=None,
                    source_run_id=None, source_paths=None, explicit_sources=False):
        from taskweave.core.validation import pointer
        inputs = dict(inputs)
        configured = await self.configured_inputs(step['task_id'], environment_id) if step.get('bindings') else {}
        environment = (self.application.runs.environment(environment_id)[0] if step.get('bindings') else {})
        for key, binding in step.get('bindings', {}).items():
            if key in inputs:
                continue
            if 'literal' in binding:
                inputs[key] = binding['literal']
            else:
                ref = binding['ref']
                if ref['source'] == 'step':
                    if source_run_id is not None:
                        source = await self.call('run.get', run_id=source_run_id)
                        if source['task_id'] != step['task_id'] or source['environment_id'] != environment_id:
                            raise TaskError('VALIDATION_EVIDENCE_INVALID', '结果来源的任务或环境不匹配')
                        paths = {a['execution_path'] for a in source.get('attempts', [])
                                 if a['step_id'] == ref['step_id'] and a['valid'] and a['status'] == 'SUCCEEDED'
                                 and a.get('execution_path')}
                        if len(paths) > 1 and not (source_paths or {}).get(ref['step_id']):
                            raise TaskError('FLOW_INSTANCE_REQUIRED', '请选择前序结果的具体执行实例')
                        value = await self.call('run.output', run_id=source_run_id, step_id=ref['step_id'],
                                                output=ref.get('output', 'data'),
                                                **({'execution_path': source_paths[ref['step_id']]}
                                                   if source_paths and ref['step_id'] in source_paths else {}))
                    else:
                        if explicit_sources:
                            raise TaskError('INPUT_MISSING', '请填写依赖值或选择前序结果来源')
                        value = await self.previous_result(step['task_id'], ref['step_id'], environment_id, output=ref.get('output', 'data'))
                else:
                    value = {**configured, **inputs} if ref['source'] == 'task' else environment
                inputs[key] = pointer(value, ref['pointer'])
        return await self.call(
            "step.trial",
            continue_session=continue_session,
            defer_inputs=True,
            step_id=step["step_id"],
            inputs=inputs,
            command_id=command_id(),
            environment_id=environment_id,
            **({'new_session': True} if scene == {} else
               {'session_run_id': scene['run_id'], 'expected_session_id': scene['session_id']} if scene else {}),
        )

    async def repeat_trial(self, step, run_id, overrides=None):
        previous = await asyncio.to_thread(self.application.runs.stored, run_id)
        if previous['mode'] != 'TRIAL' or previous['trial_step_id'] != step['step_id']:
            raise TaskError('VALIDATION_EVIDENCE_INVALID')
        inputs = json.loads(previous['inputs_json'])
        if json.loads(previous['request_json']).get('flow_trial'):
            from taskweave.core.validation import resolve
            environment, _ = self.application.runs.environment(previous['environment_id'])
            inputs = resolve(step['bindings'], inputs, environment, lambda sid, output: self.application.runs.output(run_id, sid, output))
        inputs.update(json.loads(previous['request_json']).get('step_inputs', {}).get(step['step_id'], {}))
        inputs.update(overrides or {})
        return await self.trial(step, inputs, previous['environment_id'], continue_session=True)

    async def confirm(self, step, run_id):
        run = await self.call("run.get", run_id=run_id)
        attempts = [
            a
            for a in run["attempts"]
            if a["step_id"] == step["step_id"]
            and a["valid"]
            and a["status"] == "SUCCEEDED"
        ]
        if run["mode"] != "TRIAL" or not attempts:
            raise TaskError("VALIDATION_EVIDENCE_INVALID")
        return await self.call(
            "step.confirm",
            step_id=step["step_id"],
            attempt_id=attempts[-1]["attempt_id"],
            expected_hash=step["content_hash"],
        )

    async def start(self, task_id, inputs, environment_id, mode="ALL", target=None):
        # A single UI operation owns creation/start; a busy button cannot double-dispatch.
        run = await self.call(
            "run.create", task_id=task_id, inputs=inputs, environment_id=environment_id
        )
        return await self.call(
            "run.start",
            run_id=run["run_id"],
            command_id=command_id(),
            mode=mode,
            target_step_id=target,
        )

    @staticmethod
    def diff(before, after):
        return "".join(
            unified_diff(
                before.splitlines(True),
                after.splitlines(True),
                fromfile="当前内容",
                tofile="AI 建议",
            )
        )

    @property
    def settings_adapter(self):
        from taskweave.desktop.settings import DesktopSettings
        return DesktopSettings(self.application.settings)

    async def default_environment(self):
        return await self.settings_adapter.default_environment()

    async def workbench_settings(self):
        return await self.settings_adapter.workbench_settings()

    def privacy_settings(self):
        return self.settings_adapter.privacy_settings()

    async def save_privacy_settings(self, *, redact_on_display, redact_for_ai):
        return await self.settings_adapter.save_privacy_settings(redact_on_display=redact_on_display, redact_for_ai=redact_for_ai)

    async def save_executor_max_threads(self, value):
        return await self.settings_adapter.save_executor_max_threads(value)

    async def migrate_workspace(self, destination):
        return await self.settings_adapter.migrate_workspace(destination)

    async def set_default_environment(self, environment_id):
        return await self.settings_adapter.set_default_environment(environment_id)

    async def model_settings(self):
        return await self.settings_adapter.model_settings()

    async def save_model(self, url, model, key_env, api_key=None):
        settings = await self.settings_adapter.save_model(url, model, key_env, api_key)
        if hasattr(self, 'server_logs'):
            self.server_logs.protect(settings['api_key'])
        return settings

    async def test_model(self):
        return await self.settings_adapter.test_model()

    async def save_task_export(self, text):
        return await self._save_export(text, 'save_task_export')

    async def save_plan_prompt(self, text):
        return await self._save_export(text, 'save_plan_prompt')

    async def save_chat_bundle(self, content):
        return await self._save_export(content, 'save_chat_bundle')

    async def _save_export(self, text, operation):
        from taskweave.application.settings import WorkspaceExports
        service = getattr(self.application, 'settings', None)
        if service is None:
            service = WorkspaceExports(self.application.home)
        path = await asyncio.to_thread(getattr(service, operation), text)
        await self.open_path(path.parent)
        return path

    async def copy_text(self, text):
        from taskweave.desktop.platform import copy_text
        return await copy_text(text, native=self.native)

    async def open_path(self, path):
        from taskweave.desktop.platform import open_path
        return await open_path(path, workspace_home=self.application.home)
