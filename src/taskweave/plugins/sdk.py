"""Public plugin API. Plugins import this module rather than internal core modules."""

from taskweave.core.ports import (
    Action,
    AuthoringContribution,
    CapabilitySpec,
    ContextItem,
    ContextCollection,
    ContextView,
    ContextTarget,
    ContextTargetProvider,
    ContextRecordingCommand,
    ContextRecordingBatch,
    ContextRecordingProvider,
    Diagnostic,
    ErrorInfo,
    PluginContext,
    PreparedResult,
    ResultHandler,
    ResultRequest,
    ResourceProvider,
    StepResult,
)
from taskweave.core.validation import TaskError as PluginError
from taskweave.core.dataset_contracts import DatasetStore
from taskweave.core.codegen_contracts import CodeGeneratorSpec, CodeGeneratorProvider, codegen_digest, MAX_RECORDING_BYTES, MAX_ACTIONS

__all__ = [
    "DatasetStore",
    "CodeGeneratorSpec", "CodeGeneratorProvider", "codegen_digest",
    "MAX_RECORDING_BYTES", "MAX_ACTIONS",
    "Action",
    "AuthoringContribution",
    "CapabilitySpec",
    "ContextItem",
    "ContextCollection",
    "ContextView",
    "ContextTarget",
    "ContextTargetProvider",
    "ContextRecordingCommand",
    "ContextRecordingBatch",
    "ContextRecordingProvider",
    "Diagnostic",
    "ErrorInfo",
    "PluginContext",
    "PreparedResult",
    "ResultHandler",
    "ResultRequest",
    "ResourceProvider",
    "StepResult",
    "PluginError",
]
