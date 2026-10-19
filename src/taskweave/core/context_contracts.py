"""Collected evidence, preview and recording data contracts."""
from dataclasses import dataclass, field
from typing import Mapping, Sequence, TypedDict
from taskweave.core.json_types import JSON


@dataclass(frozen=True)
class ContextItem:
    kind: str  # text, image
    mime_type: str
    content: str  # text or controlled image reference
    source: str
    truncated: bool = False


@dataclass(frozen=True)
class ContextView:
    """Plugin-defined preview stored beside context evidence."""

    title: str
    renderer: str
    data: JSON


@dataclass(frozen=True)
class ContextCollection:
    """One atomic authoring capture and its optional user previews."""

    items: Sequence[ContextItem]
    views: Sequence[ContextView] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContextRecordingCommand:
    """Optional capture lifecycle command; cursors never imply persistence."""

    operation: str
    recording_id: str | None = None
    after: int = 0
    through: int | None = None
    limit: int = 100


@dataclass(frozen=True)
class ContextRecordingBatch:
    """Non-consuming evidence page or lifecycle acknowledgement."""

    recording_id: str
    state: str  # RECORDING, PAUSED, STOPPED, DISCARDED
    cursor: int
    collection: ContextCollection = field(default_factory=lambda: ContextCollection(()))
    available_after: int = 0
    dropped_count: int = 0
    has_more: bool = False


class ContextTarget(TypedDict):
    target_id: str
    label: str
    request: Mapping[str, JSON]
