"""Optional, resource-free code generation from persisted context evidence."""
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence
from taskweave.core.json_types import JSON
import hashlib
import json

MAX_RECORDING_BYTES = 2 * 1024 * 1024
MAX_ACTIONS = 1000
MAX_DIAGNOSTICS = 100


def codegen_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class CodeGeneratorSpec:
    id: str
    name: str
    provider_ids: Sequence[str]
    sources: Sequence[str]
    recording_versions: Sequence[int]
    options_schema: Mapping[str, JSON]
    result_version: int = 1


class CodeGeneratorProvider(Protocol):
    def code_generators(self) -> Sequence[CodeGeneratorSpec]: ...
    def generate_code(self, generator_id: str, recording: Mapping[str, JSON],
                      bindings: Mapping[str, JSON], options: Mapping[str, JSON]) -> Mapping[str, JSON]: ...
