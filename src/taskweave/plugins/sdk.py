"""Public plugin API. Plugins import this module rather than internal core modules."""

from taskweave.core.ports import (
    Action,
    AuthoringContribution,
    CapabilitySpec,
    ContextItem,
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

__all__ = [
    "Action",
    "AuthoringContribution",
    "CapabilitySpec",
    "ContextItem",
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
