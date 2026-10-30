"""Explicit purpose policies; argument defaults come from real use cases."""

import inspect
from copy import deepcopy
import jsonschema

from taskweave.application.operations import build_operation_contracts
from taskweave.core.validation import TaskError


PURPOSE_OPERATIONS = {
    "inspect": frozenset("""task.get task.list task.export task.flow.get task.flow.describe
        step.get step.list draft.export feedback.export plan.get plan.list
        plan.generation.get plan.generation.list plan.generation.imports
        run.get run.list run.output run.events.page result.read
        sequence.get sequence.list sequence.run.get sequence.run.list
        instance.list run.instances run.context.sessions step.trial.sessions""".split()),
    "author": frozenset("""task.create task.update task.copy task.import
        task.flow.save step.save step.reorder step.validate step.delete
        draft.import plan.create plan.copy plan.update plan.generation.parse
        plan.generation.import sequence.save organization.category.create
        organization.metadata.set""".split()),
    "context": frozenset("""context.read context.record context.targets context.list
        context.ai context.save context.save_batch context.group.update
        context.capture.get context.capture.append context.capture.replace
        context.capture.delete context.capture.reorder context.capture.label
        context.reorder context.delete plan.context.collect plan.context.read
        plan.context.targets plan.context.record plan.context.list
        plan.context.capture.get plan.context.capture.append plan.context.capture.replace
        plan.context.capture.delete plan.context.capture.reorder plan.context.capture.label
        plan.context.save_batch plan.context.update plan.context.reorder
        plan.context.delete""".split()),
    "execute": frozenset("""step.trial step.trial.flow step.confirm step.confirm.manual
        task.flow.confirm run.create run.start run.inputs run.restart run.control
        run.reconcile instance.end sequence.start sequence.run.inputs
        sequence.run.retry sequence.run.reconcile sequence.pause sequence.cancel
        sequence.continue""".split()),
}

_OBJECTS = frozenset("document package flow input_schema output_schema inputs step_inputs node_inputs node_step_inputs request capture item public_config secret_refs descriptions".split())
_ARRAYS = frozenset("nodes step_ids plugin_ids captures views contexts selected_ids".split())
_BOOLEANS = frozenset("continue_session defer_inputs include_view replace_capture append send_preview enabled is_favorite".split())
_NUMBERS = frozenset("expected_revision revision timeout limit after".split())
_RECORD_OPTIONS = {
    "recording_id": {"type": "string"},
    "expected_session_id": {"type": "string"}, "request": {"type": "object"},
    "after": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1},
    "through": {"type": ["integer", "null"], "minimum": 0},
    "include_view": {"type": "boolean"},
}

VIRTUAL_OPERATIONS = {
    "task.run": ("execute", {"type": "object", "properties": {
        "task_id": {"type": "string"}, "expected_hash": {"type": "string"},
        "inputs": {"type": "object"}, "step_inputs": {"type": "object"},
        "environment_id": {"type": ["string", "null"]}, "defer_inputs": {"type": "boolean"},
        "review_spec_id": {"type": "string"},
    }, "required": ["task_id", "expected_hash"], "additionalProperties": False}),
    "materials": ("author", {"type": "object", "properties": {
        "task_id": {"type": "string"}, "step_id": {"type": "string"}, "plan_id": {"type": "string"},
        "capability_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 40},
        "context_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "environment_id": {"type": ["string", "null"]},
    }, "oneOf": [{"required": [key]} for key in ("task_id", "step_id", "plan_id")], "additionalProperties": False}),
    "candidate.validate": ("author", {"type": "object", "properties": {"package": {"type": "object"}},
                                      "required": ["package"], "additionalProperties": False}),
}


def parameter_schema(parameter):
    name, default = parameter.name, parameter.default
    if name in _OBJECTS:
        schema = {"type": "object"}
    elif name in _ARRAYS:
        schema = {"type": "array"}
    elif name in _BOOLEANS or type(default) is bool:
        schema = {"type": "boolean"}
    elif name in _NUMBERS or type(default) is int:
        schema = {"type": "integer"}
    elif type(default) is float:
        schema = {"type": "number"}
    elif name.endswith("_id") or name.endswith("_hash") or name in {
        "name", "description", "plan_description", "plan_notes", "context_notes",
        "provider_id", "operation", "decision", "evidence", "mode", "channel",
        "response_text", "direction", "label", "operation_notes", "source_page",
        "captured_at", "retry_execution_path", "category_id",
        "instance_type", "entity", "execution_path", "item_pointer",
    } or isinstance(default, str):
        schema = {"type": "string"}
    else:
        raise TaskError("AGENT_CONTRACT_UNDECLARED", "外部参数需要显式声明类型: " + name)
    if default is not inspect.Parameter.empty:
        schema["default"] = default
        if default is None and "type" in schema:
            schema["type"] = [schema["type"], "null"]
    return schema


def operation_detail(app, operation):
    if operation in VIRTUAL_OPERATIONS:
        purpose, schema = VIRTUAL_OPERATIONS[operation]
        return {"operation": operation, "purposes": [purpose], "parameters": deepcopy(schema), "asynchronous": False}
    purposes = [key for key, names in PURPOSE_OPERATIONS.items() if operation in names]
    contract = build_operation_contracts(app).get(operation)
    if not purposes or contract is None:
        raise TaskError("AGENT_OPERATION_DENIED", "该操作不属于外部 AI 接口")
    properties, required = {}, []
    for parameter in contract.signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            properties.update(_RECORD_OPTIONS)
            if operation == "context.record":
                properties["environment_id"] = {"type": ["string", "null"]}
            elif operation == "plan.context.record":
                properties["expected_revision"] = {"type": ["integer", "null"]}
            else:
                raise TaskError("AGENT_CONTRACT_UNDECLARED", "可变参数需声明具体策略")
            continue
        properties[parameter.name] = parameter_schema(parameter)
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    return {"operation": operation, "purposes": purposes,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False},
            "asynchronous": contract.asynchronous}


def validate_operation(app, purpose, operation, params):
    if operation not in PURPOSE_OPERATIONS.get(purpose, ()) and not (
        operation in VIRTUAL_OPERATIONS and VIRTUAL_OPERATIONS[operation][0] == purpose
    ):
        raise TaskError("AGENT_OPERATION_DENIED", "该用途不允许此操作")
    schema = operation_detail(app, operation)["parameters"]
    try:
        jsonschema.Draft202012Validator(schema).validate(params)
    except jsonschema.ValidationError as exc:
        # Do not echo the rejected value, which may contain credentials.
        path = "/".join(map(str, exc.absolute_path))
        raise TaskError("AGENT_ARGUMENT_INVALID", "参数不符合操作契约" + (": " + path if path else "")) from exc
    if operation == "context.record" and params.get("run_id") is not None and "environment_id" in params:
        raise TaskError("AGENT_ARGUMENT_INVALID", "运行录制使用运行所属环境")
    return params
