"""Host resource sessions shared by authoring and fixed execution."""
import os
import threading
from taskweave.core.validation import TaskError
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.storage import Results


class Resources:
    def __init__(self, registry):
        self.registry, self.items = registry, {}
        self.context = None

    async def acquire(self, provider_id, role):
        key = (provider_id, role)
        if key not in self.items:
            self.items[key] = await self.registry.providers[provider_id].open(
                self.context, role
            )
        return self.items[key]

    def active(self, provider_id):
        return [
            (role, resource)
            for (provider, role), resource in self.items.items()
            if provider == provider_id
        ]

    async def release_all(self):
        for (provider_id, role), resource in list(self.items.items()):
            await self.registry.providers[provider_id].close(resource)
        self.items.clear()


class PluginContext:
    def __init__(
        self, scope, results, resources, environment, secret_refs, cancel, emit
    ):
        self.scope, self.results, self.resources = scope, results, resources
        self.task_parameters = {}
        self.environment, self.secret_refs, self.cancel, self.emit = (
            environment,
            secret_refs,
            cancel,
            emit,
        )

    async def allocate_file(self, name):
        return await self.results.allocate_file(name)

    def resolve_secret(self, reference):
        env_name = self.secret_refs.get(reference)
        if not isinstance(env_name, str) or not env_name.startswith("env:"):
            raise TaskError("SECRET_UNAVAILABLE")
        value = os.getenv(env_name[4:])
        if value is None:
            raise TaskError("SECRET_UNAVAILABLE")
        return value

    def log(self, level, message):
        self.emit("Log", {"level": level, "message": redact(message)})

    def cancelled(self):
        return self.cancel.is_set()


class ResourceSession:
    def __init__(self, context):
        self.context = context

    async def close(self):
        await self.context.resources.release_all()


class ResourceSessionFactory:
    def __init__(self, home):
        self.home = home

    def __call__(self, *, scope, registry, environment, secret_refs, task_parameters):
        resources = Resources(registry)
        context = PluginContext(scope, Results(self.home, scope, registry), resources,
                                environment, secret_refs, threading.Event(), lambda *args: None)
        context.task_parameters = task_parameters
        resources.context = context
        return ResourceSession(context)
