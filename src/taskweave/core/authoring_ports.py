"""Resource ownership boundary for AI authoring; no host implementation imports."""
from typing import Mapping, Protocol
from taskweave.core.json_types import JSON
from taskweave.core.ports import PluginContext, Scope


class AuthoringResourceSession(Protocol):
    context: PluginContext
    async def close(self) -> None: ...


class AuthoringResourceFactory(Protocol):
    def __call__(self, *, scope: Scope, registry: object,
                 environment: Mapping[str, JSON], secret_refs: Mapping[str, str],
                 task_parameters: Mapping[str, JSON]) -> AuthoringResourceSession: ...
