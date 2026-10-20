"""Framework-independent definition checks for ordered task sequences."""

import re

from taskweave.core.validation import TaskError, check_schema, dumps


def _pointer(value):
    if not isinstance(value, str) or (value and not value.startswith("/")) or re.search(r"~(?![01])", value):
        raise TaskError("POINTER_INVALID")


def _source(source, preceding):
    if not isinstance(source, dict):
        raise TaskError("SEQUENCE_SOURCE_INVALID")
    kind = source.get("kind")
    if kind == "literal" and set(source) == {"kind", "value"}:
        dumps(source["value"])
    elif kind == "sequence" and set(source) == {"kind", "pointer"}:
        _pointer(source["pointer"])
    elif kind == "output" and set(source) in ({"kind", "node_id", "step_id", "output", "pointer"},
                                              {"kind", "node_id", "step_id", "output", "pointer",
                                               "item_pointer", "loop_node_id"}):
        if source["node_id"] not in preceding or not isinstance(source["step_id"], str) or not source["step_id"]:
            raise TaskError("SEQUENCE_FORWARD_REFERENCE")
        if not isinstance(source["output"], str) or not source["output"]:
            raise TaskError("SEQUENCE_SOURCE_INVALID")
        _pointer(source["pointer"])
        if "item_pointer" in source:
            _pointer(source["item_pointer"])
            if (source["pointer"] or not isinstance(source["loop_node_id"], str)
                    or not source["loop_node_id"]):
                raise TaskError("SEQUENCE_SOURCE_INVALID")
    else:
        raise TaskError("SEQUENCE_SOURCE_INVALID")


def validate_definition(name, nodes, input_schema):
    if not isinstance(name, str) or not name.strip():
        raise TaskError("SEQUENCE_NAME_INVALID")
    check_schema(input_schema)
    if not isinstance(nodes, list) or not nodes:
        raise TaskError("SEQUENCE_EMPTY")
    preceding = set()
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"node_id", "task_id", "environment_id", "inputs", "step_inputs"}:
            raise TaskError("SEQUENCE_NODE_INVALID")
        node_id, task_id = node["node_id"], node["task_id"]
        if not isinstance(node_id, str) or not node_id or node_id in preceding or not isinstance(task_id, str) or not task_id:
            raise TaskError("SEQUENCE_NODE_INVALID")
        if node["environment_id"] is not None and not isinstance(node["environment_id"], str):
            raise TaskError("SEQUENCE_NODE_INVALID")
        if not isinstance(node["inputs"], dict) or not isinstance(node["step_inputs"], dict):
            raise TaskError("SEQUENCE_NODE_INVALID")
        for target, source in node["inputs"].items():
            if not isinstance(target, str) or not target:
                raise TaskError("SEQUENCE_SOURCE_INVALID")
            _source(source, preceding)
        for step_id, values in node["step_inputs"].items():
            if not isinstance(step_id, str) or not step_id or not isinstance(values, dict):
                raise TaskError("SEQUENCE_SOURCE_INVALID")
            for target, source in values.items():
                if not isinstance(target, str) or not target:
                    raise TaskError("SEQUENCE_SOURCE_INVALID")
                _source(source, preceding)
        preceding.add(node_id)
    dumps(nodes)
    return nodes
