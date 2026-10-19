"""Capability declarations and authoring contribution values."""
from dataclasses import dataclass, field
from typing import Mapping, Sequence
from taskweave.core.json_types import JSON


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    description: str
    input_schema: Mapping[str, JSON]
    output_schema: Mapping[str, JSON]
    effect: str  # READ, WRITE
    timeout_ms: int = 30000
    retry_safe: bool = False
    resource_ids: Sequence[str] = ()


@dataclass(frozen=True)
class AuthoringContribution:
    instructions: str
    examples: Sequence[str] = ()
    context_provider_ids: Sequence[str] = ()
    tool_ids: Sequence[str] = ()
    constraints: Mapping[str, JSON] = field(default_factory=dict)
    channel_overrides: Mapping[str, JSON] = field(default_factory=dict)
