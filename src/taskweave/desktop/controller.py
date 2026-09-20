"""UI operations use the public application API, including durable authoring evidence."""

import asyncio
import ast
from difflib import unified_diff
import json
import logging
import os
from pathlib import Path
import subprocess
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

    async def call(self, api_operation, **params):
        logger = logging.getLogger(__name__)
        if api_operation not in {'run.get', 'run.events', 'task.list', 'step.list'}:
            logger.info('服务操作：%s', api_operation)
        try:
            return await asyncio.to_thread(self.application.dispatch, api_operation, params)
        except Exception as exc:
            logger.error('服务操作失败：%s [%s]', api_operation, getattr(exc, 'code', type(exc).__name__))
            raise

    async def execution_inputs(self, run_id):
        stored = await asyncio.to_thread(self.application.repo.run, run_id)
        return {'task': json.loads(stored['inputs_json']),
                'steps': json.loads(stored['request_json']).get('step_inputs', {})}

    async def trial_feedback(self, run_id, step_id):
        from taskweave.infrastructure.privacy import redact
        trial = await self.call('run.get', run_id=run_id)
        attempts = [a for a in trial['attempts'] if a['step_id'] == step_id]
        if not attempts:
            raise TaskError('VALIDATION_EVIDENCE_INVALID', '尚无试跑记录')
        attempt_id = attempts[-1]['attempt_id']
        feedback = await self.call('feedback.export', attempt_id=attempt_id)
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
                items = await self.call('context.read', step_id=step['step_id'], provider_id=provider, run_id=session['run_id'], request=request)
                contexts.extend(items)
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

    async def trial(self, step, inputs, environment_id=None, continue_session=False):
        from taskweave.core.validation import pointer
        inputs = dict(inputs)
        configured = await self.configured_inputs(step['task_id'], environment_id) if step.get('bindings') else {}
        environment = (self.application.repo.environment(environment_id)[0] if step.get('bindings') else {})
        for key, binding in step.get('bindings', {}).items():
            if key in inputs:
                continue
            if 'literal' in binding:
                inputs[key] = binding['literal']
            else:
                ref = binding['ref']
                if ref['source'] == 'step':
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
        )

    async def repeat_trial(self, step, run_id, overrides=None):
        previous = await asyncio.to_thread(self.application.repo.run, run_id)
        if previous['mode'] != 'TRIAL' or previous['trial_step_id'] != step['step_id']:
            raise TaskError('VALIDATION_EVIDENCE_INVALID')
        inputs = json.loads(previous['inputs_json'])
        if json.loads(previous['request_json']).get('flow_trial'):
            from taskweave.core.validation import resolve
            environment, _ = self.application.repo.environment(previous['environment_id'])
            inputs = resolve(step['bindings'], inputs, environment, lambda sid, output: self.application.repo.read_output(run_id, sid, output, self.application.registry))
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

    async def default_environment(self):
        path = self.application.home / 'workbench.json'
        return json.loads(path.read_text()).get('default_environment_id') if path.exists() else None

    async def set_default_environment(self, environment_id):
        environments = await self.call('environment.list')
        if environment_id is not None and environment_id not in {e['environment_id'] for e in environments}:
            raise TaskError('FORM_INVALID', '请选择已有环境')
        path = self.application.home / 'workbench.json'
        settings = json.loads(path.read_text()) if path.exists() else {}
        settings['default_environment_id'] = environment_id
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(settings, ensure_ascii=False))
        temporary.replace(path)

    async def model_settings(self):
        path = self.application.home / "model.json"
        return (
            json.loads(path.read_text())
            if path.exists()
            else {
                "url": os.getenv("TASKWEAVE_MODEL_URL", ""),
                "model": os.getenv("TASKWEAVE_MODEL_NAME", ""),
                "key_env": "TASKWEAVE_MODEL_API_KEY",
            }
        )

    async def save_model(self, url, model, key_env, api_key=None):
        if key_env and not key_env.replace("_", "a").isalnum():
            raise TaskError("MODEL_KEY_REFERENCE_INVALID")
        previous = self.application.authoring.model
        key = api_key or (os.getenv(key_env) if key_env else None)
        if not key and getattr(previous, "url", None) == url:
            key = getattr(previous, "api_key", None)
        if not key:
            stored = await self.model_settings()
            if stored.get("url") == url:
                key = stored.get("api_key")
        adapter = HttpModel(url, model, key) if url and model else None
        if hasattr(self, 'server_logs'):
            self.server_logs.protect(key)
        settings = {"url": url, "model": model, "key_env": key_env, "api_key": key}
        path = self.application.home / "model.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        self.application.authoring.model = adapter
        return settings

    async def test_model(self):
        adapter = self.application.authoring.model
        if adapter is None:
            raise TaskError("MODEL_NOT_CONFIGURED")
        reply = await adapter.complete(
            [
                {
                    "role": "system",
                    "content": "Return only valid JSON with step_content and explanation. Escape newlines in strings. Example: " + json.dumps({"step_content": 'async def run(ctx, inputs):\n    return ctx.result(data={"connected": True})', "explanation": "connected"}),
                },
                {
                    "role": "user",
                    "content": 'Write async def run(ctx, inputs) returning ctx.result(data={"connected": True}).',
                },
            ],
            [],
            {"type": "object"},
        )
        try:
            tree = ast.parse(reply.proposed_content or "")
            if not any(isinstance(node, ast.AsyncFunctionDef) and node.name == "run" for node in tree.body):
                raise ValueError("missing run")
        except (SyntaxError, ValueError) as exc:
            raise TaskError("MODEL_CONTENT_INVALID", "连接已建立，但模型未生成有效的 async run 步骤内容") from exc
        return {
            "connected": bool(reply.proposed_content),
            "explanation": reply.explanation,
        }

    async def copy_text(self, text):
        if self.native and sys.platform == 'darwin':
            try:
                await asyncio.to_thread(subprocess.run, ['pbcopy'], input=text.encode('utf-8'), check=True, timeout=10)
            except (OSError, subprocess.SubprocessError) as exc:
                raise TaskError('CLIPBOARD_FAILED', '复制失败，请在文本框中全选复制') from exc
            return
        from nicegui import ui
        success = await ui.run_javascript("""return await (async () => {
            const text = TEXT;
            try { await navigator.clipboard.writeText(text); return true; } catch (_) {}
            const input = document.createElement('textarea');
            input.value = text; input.style.position = 'fixed'; input.style.opacity = '0';
            document.body.appendChild(input); input.focus(); input.select();
            try { return document.execCommand('copy'); } finally { input.remove(); }
        })();""".replace('TEXT', json.dumps(text)), timeout=10)
        if not success:
            raise TaskError('CLIPBOARD_FAILED', '复制失败，请在文本框中全选复制')

    async def save_task_export(self, text):
        # Unique files prevent silently overwriting an earlier task export.
        directory = self.application.home / 'exports'
        def save():
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ('taskweave-task-' + uuid4().hex[:12] + '.json')
            with path.open('x', encoding='utf-8') as output:
                output.write(text)
            return path
        path = await asyncio.to_thread(save)
        await self.open_path(directory)
        return path

    async def open_path(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.application.home) or not path.exists():
            raise TaskError("LOCAL_PATH_INVALID")

        def launch():
            if sys.platform == "win32":
                os.startfile(str(path))
            else:
                subprocess.Popen(
                    ["open" if sys.platform == "darwin" else "xdg-open", str(path)]
                )

        await asyncio.to_thread(launch)
