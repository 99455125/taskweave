"""Async desktop adapter over local application settings use cases."""
import asyncio
from taskweave.application.settings import ApplicationSettings


class DesktopSettings:
    def __init__(self, service: ApplicationSettings):
        self.service = service

    async def default_environment(self):
        return self.service.default_environment()

    async def workbench_settings(self):
        return self.service.workbench_settings()

    def privacy_settings(self):
        return self.service.privacy_settings()

    async def save_privacy_settings(self, *, redact_on_display, redact_for_ai):
        return self.service.save_privacy_settings(redact_on_display=redact_on_display, redact_for_ai=redact_for_ai)

    async def save_executor_max_threads(self, value):
        return self.service.save_executor_max_threads(value)

    async def migrate_workspace(self, destination):
        return await asyncio.to_thread(self.service.migrate_workspace, destination)

    async def set_default_environment(self, environment_id):
        return self.service.set_default_environment(environment_id)

    async def model_settings(self):
        return self.service.model_settings()

    async def save_model(self, url, model, key_env, api_key=None):
        return self.service.save_model(url, model, key_env, api_key)

    async def test_model(self):
        return await self.service.test_model()

    async def save_task_export(self, text):
        return await asyncio.to_thread(self.service.save_task_export, text)
