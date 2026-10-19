"""Stable JSON-facing business records; optional fields reflect enriched queries.

Types document the existing wire shape, not validation or serialized wrappers.
Plugin schemas and payloads deliberately retain JSON extension fields.
"""
from typing import TypedDict
from taskweave.core.json_types import JSON


class _TaskRecordOptional(TypedDict, total=False):
    definition_hash: str
    is_favorite: bool
    category_id: str | None


class TaskRecord(_TaskRecordOptional):
    task_id: str
    name: str
    input_schema_json: str
    description: str
    created_at: str
    updated_at: str


class _StepRecordOptional(TypedDict, total=False):
    step_notes: str


class StepRecord(_StepRecordOptional):
    step_id: str
    task_id: str
    name: str
    content_hash: str
    step_content: str
    step_description: str
    input_schema: dict[str, JSON]
    output_schema: dict[str, JSON]
    bindings: dict[str, JSON]
    capabilities: list[str]
    timeout_ms: int
    validation_state: str


class ExecutionRequest(TypedDict, total=False):
    initial_inputs: dict[str, JSON]
    initial_step_inputs: dict[str, JSON]
    step_inputs: dict[str, JSON]
    flow_trial: bool
    environment_hash: str
    waiting_input: dict[str, JSON] | None
    mode: str
    target: str | None
    retry: str | None


class _RunSummaryOptional(TypedDict, total=False):
    can_end: bool
    attempts: list[dict[str, JSON]]
    inputs_json: str


class RunSummary(_RunSummaryOptional):
    run_id: str
    task_id: str
    status: str
    mode: str
    environment_id: str | None
    request_json: str


class CommandResult(TypedDict, total=False):
    run_id: str
    status: str
    attempt_id: str
    deleted: str
    decision: str
    command_id: str
    requested: str
    task_id: str
    deleted_runs: int


class _ExecutionCommandOptional(TypedDict, total=False):
    mode: str
    target: str | None
    retry: str | None


class ExecutionCommand(_ExecutionCommandOptional):
    operation: str
