"""Model request/reply contracts, independent of plugin runtime protocols."""
from dataclasses import dataclass, field
from typing import Mapping, Sequence, Protocol
from taskweave.core.json_types import JSON
from taskweave.core.capability_contracts import CapabilitySpec


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool_id: str
    arguments: Mapping[str, JSON]


@dataclass(frozen=True)
class ModelReply:
    proposed_content: str | None = None
    explanation: str = ""
    tool_calls: Sequence[ToolCall] = ()
    structured_content: Mapping[str, JSON] = field(default_factory=dict)


class ModelPort(Protocol):
    def capabilities(
        self,
    ) -> Mapping[str, JSON]: ...  # tools, images, json_object, json_schema
    async def complete(
        self,
        messages: Sequence[JSON],
        tool_specs: Sequence[CapabilitySpec],
        response_contract: JSON,
        *,
        request_limit_bytes: int | None = None,
    ) -> ModelReply: ...
