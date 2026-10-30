"""Local settings and workspace use cases, independent of desktop rendering."""
import ast
import json
import os
from pathlib import Path
import shutil
from typing import Callable, Protocol
from uuid import uuid4

from taskweave.core.model_ports import ModelPort
from taskweave.core.validation import TaskError


class PrivacySettingsPort(Protocol):
    def get(self) -> dict: ...
    def update(self, *, redact_on_display: bool, redact_for_ai: bool) -> dict: ...


class AuthoringModelOwner(Protocol):
    model: ModelPort | None


class ApplicationSettings:
    def __init__(self, home: Path, *, privacy: PrivacySettingsPort,
                 set_max_concurrency: Callable[[int], int],
                 list_environments: Callable[[], list[dict]],
                 list_instances: Callable[[], list[dict]],
                 authoring: AuthoringModelOwner,
                 model_factory: Callable[[str, str, str | None], ModelPort],
                 workspace_location: Callable[[], Path]):
        self.home = Path(home)
        self.privacy = privacy
        self.set_max_concurrency = set_max_concurrency
        self.list_environments = list_environments
        self.list_instances = list_instances
        self.authoring = authoring
        self.model_factory = model_factory
        self.workspace_location = workspace_location

    def default_environment(self):
        return (self.workbench_settings()).get('default_environment_id')


    def workbench_settings(self):
        path = self.home / 'workbench.json'
        settings = json.loads(path.read_text()) if path.exists() else {}
        settings.setdefault('executor_max_threads', 8)
        settings.update(self.privacy.get())
        return settings


    def privacy_settings(self):
        return self.privacy.get()


    def save_privacy_settings(self, *, redact_on_display, redact_for_ai):
        return self.privacy.update(
            redact_on_display=redact_on_display, redact_for_ai=redact_for_ai,
        )


    def save_executor_max_threads(self, value):
        value = self.set_max_concurrency(value)
        path = self.home / 'workbench.json'
        settings = self.workbench_settings()
        settings['executor_max_threads'] = value
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
        return value


    def migrate_workspace(self, destination):
        destination = Path(destination).expanduser().resolve()
        source = self.home.resolve()
        if destination == source or source in destination.parents:
            raise TaskError('WORKSPACE_INVALID', '新目录不能是当前工作空间或其子目录')
        if self.list_instances():
            raise TaskError('WORKSPACE_BUSY', '请先结束全部执行实例')
        if destination.exists() and any(destination.iterdir()):
            raise TaskError('WORKSPACE_INVALID', '目标目录必须为空')

        def migrate():
            destination.mkdir(parents=True, exist_ok=True)
            for item in source.iterdir():
                if item.name in {'coordinator.lock'}:
                    continue
                target = destination / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
            marker = self.workspace_location()
            marker.parent.mkdir(parents=True, exist_ok=True)
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(json.dumps({'workspace_home': str(destination), 'remove_after_restart': str(source)}, ensure_ascii=False), encoding='utf-8')
            temporary.replace(marker)
        migrate()
        return {'workspace_home': str(destination), 'restart_required': True}


    def set_default_environment(self, environment_id):
        environments = self.list_environments()
        if environment_id is not None and environment_id not in {e['environment_id'] for e in environments}:
            raise TaskError('FORM_INVALID', '请选择已有环境')
        path = self.home / 'workbench.json'
        settings = self.workbench_settings()
        settings['default_environment_id'] = environment_id
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(settings, ensure_ascii=False))
        temporary.replace(path)


    def model_settings(self):
        path = self.home / "model.json"
        return (
            json.loads(path.read_text())
            if path.exists()
            else {
                "url": os.getenv("TASKWEAVE_MODEL_URL", ""),
                "model": os.getenv("TASKWEAVE_MODEL_NAME", ""),
                "key_env": "TASKWEAVE_MODEL_API_KEY",
            }
        )


    def save_model(self, url, model, key_env, api_key=None):
        if key_env and not key_env.replace("_", "a").isalnum():
            raise TaskError("MODEL_KEY_REFERENCE_INVALID")
        previous = self.authoring.model
        key = api_key or (os.getenv(key_env) if key_env else None)
        if not key and getattr(previous, "url", None) == url:
            key = getattr(previous, "api_key", None)
        if not key:
            stored = self.model_settings()
            if stored.get("url") == url:
                key = stored.get("api_key")
        adapter = self.model_factory(url, model, key) if url and model else None
        settings = {"url": url, "model": model, "key_env": key_env, "api_key": key}
        path = self.home / "model.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        self.authoring.model = adapter
        return settings


    async def test_model(self):
        adapter = self.authoring.model
        if adapter is None:
            raise TaskError("MODEL_NOT_CONFIGURED")
        reply = await adapter.complete(
            [
                {
                    "role": "system",
                    "content": "只返回 JSON 对象，包含完整的 step_content 和简短 explanation，不要 Markdown。",
                },
                {
                    "role": "user",
                    "content": 'Write async def run(ctx, inputs) returning ctx.result(data={"connected": True}).',
                },
            ],
            [],
            {
                "type": "object",
                "properties": {
                    "step_content": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["step_content"],
            },
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


    def save_task_export(self, text):
        return WorkspaceExports(self.home).save_task_export(text)

    def save_plan_prompt(self, text):
        return WorkspaceExports(self.home).save_plan_prompt(text)

    def save_chat_bundle(self, content):
        return WorkspaceExports(self.home).save_chat_bundle(content)


class WorkspaceExports:
    """File-only use case also available to minimal local export clients."""
    def __init__(self, home):
        self.home = Path(home)

    def _save(self, text, prefix, suffix):
        directory = self.home / 'exports'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (prefix + uuid4().hex[:12] + suffix)
        with path.open('x', encoding='utf-8') as output:
            output.write(text)
        return path

    def save_task_export(self, text):
        return self._save(text, 'taskweave-task-', '.json')

    def save_plan_prompt(self, text):
        return self._save(text, 'taskweave-plan-', '.txt')

    def save_chat_bundle(self, content):
        directory = self.home / 'exports'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ('taskweave-chat-' + uuid4().hex[:12] + '.zip')
        with path.open('xb') as output:
            output.write(content)
        return path
