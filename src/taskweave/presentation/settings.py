"""Settings drafts and command sequencing, independent of framework controls."""
from typing import Literal, Protocol, TypedDict
from taskweave.core.validation import TaskError
from taskweave.application.ai_requests import MAX_AI_REQUEST_LIMIT_KIB


class AIRequestSettings(TypedDict):
    ai_request_limit_kib: int
    request_limit_bytes: int


class ModelSettings(TypedDict):
    url: str
    model: str
    key_env: str
    api_key: str | None


class ModelConnectionResult(TypedDict):
    connected: bool
    explanation: str


class PrivacySettingsResult(TypedDict):
    redact_on_display: bool
    redact_for_ai: bool


class WorkspaceMigrationResult(TypedDict):
    workspace_home: str
    restart_required: bool


class SettingsApplication(Protocol):
    async def save_model(self, url: str, model: str, key_env: str, api_key: str | None = None) -> ModelSettings: ...
    async def test_model(self) -> ModelConnectionResult: ...
    async def call(self, operation: Literal['ai.settings.update'], *, ai_request_limit_kib: int) -> AIRequestSettings: ...
    async def save_privacy_settings(self, *, redact_on_display: bool, redact_for_ai: bool) -> PrivacySettingsResult: ...
    async def save_executor_max_threads(self, value: int) -> int: ...
    async def migrate_workspace(self, destination: str) -> WorkspaceMigrationResult: ...


class SettingsSession:
    def __init__(self, application: SettingsApplication):
        self.application = application
        self.section = 'ai'
        self.draft = {}

    def load(self, model: dict, workbench: dict, limits: dict):
        self.draft = {
            'url': model.get('url', ''), 'model': model.get('model', ''),
            'key_env': model.get('key_env', 'TASKWEAVE_MODEL_API_KEY'), 'api_key': '',
            'request_limit': limits['ai_request_limit_kib'],
            'redact_on_display': workbench.get('redact_on_display', True),
            'redact_for_ai': workbench.get('redact_for_ai', True),
            'executor_threads': workbench.get('executor_max_threads', 8), 'destination': '',
        }

    async def save_model(self):
        d = self.draft
        return await self.application.save_model(d['url'].strip(), d['model'].strip(),
                                                d['key_env'].strip(), d['api_key'] or None)

    async def test_model(self):
        await self.save_model()
        yield None
        yield await self.application.test_model()

    @staticmethod
    def integer(value, message):
        try:
            if value is None or value != int(value):
                raise ValueError()
            return int(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise TaskError('FORM_INVALID', message) from exc

    async def save_limit(self):
        value = self.integer(self.draft['request_limit'], f'请输入 1–{MAX_AI_REQUEST_LIMIT_KIB} 的整数')
        return await self.application.call('ai.settings.update', ai_request_limit_kib=value)

    async def save_privacy(self):
        return await self.application.save_privacy_settings(
            redact_on_display=self.draft['redact_on_display'], redact_for_ai=self.draft['redact_for_ai'])

    async def save_executor(self):
        value = self.integer(self.draft['executor_threads'], '请填写 1 到 8 之间的整数')
        return await self.application.save_executor_max_threads(value)

    async def migrate(self, confirmed: bool):
        if confirmed:
            return await self.application.migrate_workspace(self.draft['destination'] or '')
        return None
