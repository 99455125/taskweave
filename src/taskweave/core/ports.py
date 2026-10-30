"""Shared contracts for task execution, authoring and plugin contributions."""

from dataclasses import dataclass, field
from typing import Any, AsyncContextManager, Mapping, Protocol, Sequence

from taskweave.core.json_types import JSON
from taskweave.core.dataset_contracts import DatasetStore
from taskweave.core.codegen_contracts import CodeGeneratorSpec, CodeGeneratorProvider
from taskweave.core.capability_contracts import Diagnostic, CapabilitySpec, AuthoringContribution
from taskweave.core.context_contracts import ContextItem, ContextView, ContextCollection, ContextRecordingCommand, ContextRecordingBatch, ContextTarget
from taskweave.core.model_ports import ToolCall, ModelReply, ModelPort


@dataclass(frozen=True)
class Scope:
    task_id: str
    run_id: str
    step_id: str
    attempt_id: str
    execution_path: str | None = None


@dataclass(frozen=True)
class ResultRequest:
    handler_id: str
    name: str
    payload: JSON


@dataclass(frozen=True)
class StepResult:
    data: JSON = None
    outputs: Sequence[ResultRequest] = field(default_factory=tuple)
    views: Sequence[Mapping[str, JSON]] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResultRef:
    result_id: str
    handler_id: str
    kind: str  # json, table, file
    locator: str  # scoped relative URI, never an arbitrary filesystem path
    media_type: str
    checksum: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    phase: str
    effect_state: str  # NOT_STARTED, SUCCEEDED, FAILED, UNKNOWN


@dataclass(frozen=True)
class StagedFile:
    token: str
    local_path: str  # plugin-only, never sent to a model or returned by ctx.call


class TaskTransaction(Protocol):
    async def execute(
        self, sql: str, parameters: Sequence[JSON] = ()
    ) -> Sequence[Mapping[str, JSON]]: ...


class TaskStore(Protocol):
    # Host-owned persistence port; returned step data is saved by default.
    async def put_json(self, name: str, data: JSON) -> ResultRef: ...
    async def allocate_file(self, name: str) -> StagedFile: ...
    async def commit_file(self, token: str, media_type: str) -> ResultRef: ...
    def table_transaction(
        self, plugin_id: str
    ) -> AsyncContextManager[TaskTransaction]: ...
    async def read(self, ref: ResultRef) -> JSON: ...


class ResourceRegistry(Protocol):
    async def acquire(self, provider_id: str, role: str) -> Any: ...
    def active(self, provider_id: str) -> Sequence[tuple[str, Any]]: ...
    async def release_all(self) -> None: ...


class PluginContext(Protocol):
    scope: Scope
    datasets: DatasetStore

    async def allocate_file(self, name: str) -> StagedFile: ...

    resources: ResourceRegistry
    environment: Mapping[str, JSON]
    task_parameters: Mapping[str, JSON]

    def log(self, level: str, message: str) -> None: ...
    def cancelled(self) -> bool: ...
    def resolve_secret(self, reference: str) -> str: ...


class StepContext(Protocol):
    scope: Scope

    async def call(self, action_id: str, inputs: Mapping[str, JSON]) -> JSON: ...
    def result(
        self, data: JSON = None, outputs: Sequence[ResultRequest] = (), views: Sequence[Mapping[str, JSON]] = ()
    ) -> StepResult: ...
    def output(self, handler_id: str, name: str, payload: JSON) -> ResultRequest: ...
    def log(self, message: str) -> None: ...
    def cancelled(self) -> bool: ...


class Action(Protocol):
    spec: CapabilitySpec

    async def preflight(
        self, ctx: PluginContext, inputs: Mapping[str, JSON]
    ) -> Sequence[Diagnostic]: ...
    async def execute(self, ctx: PluginContext, inputs: Mapping[str, JSON]) -> JSON: ...
    async def verify(
        self, ctx: PluginContext, inputs: Mapping[str, JSON], output: JSON
    ) -> Sequence[Diagnostic]: ...


@dataclass(frozen=True)
class PreparedResult:
    kind: str  # json, table, file
    payload: JSON = None
    table_name: str | None = None
    rows: Sequence[Mapping[str, JSON]] = ()
    staged_token: str | None = None
    media_type: str = "application/json"


class ResultHandler(Protocol):
    # Declarative current schemas; host validates and performs all storage IO.
    def schema(self) -> Mapping[str, JSON]: ...
    def prepare(self, request: ResultRequest) -> PreparedResult: ...
    def parse(self, stored: JSON) -> JSON: ...
    def preview(self, parsed: JSON) -> Mapping[str, JSON]: ...


class ResourceProvider(Protocol):
    async def open(self, ctx: PluginContext, role: str) -> Any: ...
    async def close(self, resource: Any) -> None: ...


class ContextTargetProvider(Protocol):
    """Optional plugin extension; enumerate retained resources without opening any."""

    async def list_context_targets(
        self, provider_id: str, ctx: PluginContext, request: JSON
    ) -> Sequence[ContextTarget]: ...


class ContextRecordingProvider(Protocol):
    """Optional extension, independent of the mandatory Plugin protocol.

    read must not consume events. ack consumes only explicitly acknowledged,
    previously delivered evidence; failed persistence must not call ack.
    """

    async def record_context(
        self, provider_id: str, ctx: PluginContext, command: ContextRecordingCommand,
        request: JSON, *, include_view: bool = True,
    ) -> ContextRecordingBatch: ...


class Plugin(Protocol):
    def manifest(self) -> Mapping[str, JSON]: ...
    def actions(self) -> Mapping[str, Action]: ...
    def tools(self) -> Mapping[str, Action]: ...
    def result_handlers(self) -> Mapping[str, ResultHandler]: ...
    def resource_providers(self) -> Mapping[str, ResourceProvider]: ...
    def authoring(self, selected_ids: Sequence[str]) -> AuthoringContribution: ...
    async def collect_context(
        self, provider_id: str, ctx: PluginContext, request: JSON, *, include_view: bool = True
    ) -> ContextCollection: ...
    async def lint(self, step_document: Mapping[str, JSON]) -> Sequence[Diagnostic]: ...
    async def diagnose(
        self, error: ErrorInfo, refs: Sequence[ResultRef]
    ) -> Sequence[Diagnostic]: ...
