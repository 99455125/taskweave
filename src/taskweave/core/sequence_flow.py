"""Translate task-call operands to the shared pure control-flow language.

Action step_id values in a combination identify task references, not steps
inside the referenced task. Child output names carry both the child step
and its JSON output so the shared aggregator can preserve both loop levels.
"""

from copy import deepcopy

from taskweave.core.task_flow import validate_flow
from taskweave.core.validation import TaskError


def source_operand(source):
    kind = source.get("kind")
    if kind == "literal":
        return {"literal": source["value"]}
    if kind == "sequence":
        return {"ref": {"source": "task", "pointer": source["pointer"]}}
    if kind == "output":
        ref = {"source": "step", "step_id": source["node_id"],
               "output": source["step_id"] + "/" + source["output"], "pointer": source["pointer"]}
        for key in ("item_pointer", "loop_node_id"):
            if key in source:
                ref[key] = source[key]
        return {"ref": ref}
    if kind in {"loop", "branch"}:
        return {"ref": {"source": kind, **{key: value for key, value in source.items() if key != "kind"}}}
    raise TaskError("SEQUENCE_SOURCE_INVALID")


def flow_operands(flow):
    """Visit only syntax-owned operand positions, never literal business JSON.

    Mapping keys (including an output or state named 'literal' or 'ref') are
    business names, not operand tags. A standalone operand is also accepted.
    Structural validation remains validate_flow's responsibility.
    """
    def condition(value):
        if not isinstance(value, dict):
            return
        op = value.get("op")
        if op in {"all", "any"} and isinstance(value.get("conditions"), list):
            for child in value["conditions"]:
                yield from condition(child)
        elif op == "not":
            yield from condition(value.get("condition"))
        elif op in {"exists", "empty"}:
            yield value.get("value")
        elif op in {"eq", "ne", "gt", "gte", "lt", "lte", "contains"}:
            yield value.get("left")
            yield value.get("right")

    def node(value):
        if not isinstance(value, dict):
            return
        kind = value.get("kind")
        if kind == "sequence" and isinstance(value.get("children"), list):
            for child in value["children"]:
                yield from node(child)
        elif kind == "if":
            if isinstance(value.get("cases"), list):
                for case in value["cases"]:
                    if isinstance(case, dict):
                        yield from condition(case.get("condition"))
                        yield from node(case.get("body"))
                default = value.get("default")
                if isinstance(default, dict):
                    yield from node(default.get("body"))
            outputs = value.get("outputs")
            if isinstance(outputs, dict):
                for mapping in outputs.values():
                    if isinstance(mapping, dict):
                        yield from mapping.values()
        elif kind == "foreach":
            yield value.get("items")
            yield from node(value.get("body"))
        elif kind == "loop":
            yield from condition(value.get("condition"))
            for name in ("state_initial", "state_update"):
                if isinstance(value.get(name), dict):
                    yield from value[name].values()
            yield from node(value.get("body"))

    if isinstance(flow, dict) and "root" in flow:
        yield from node(flow["root"])
    else:
        yield flow


def machine_flow(flow):
    result = deepcopy(flow)
    for value in flow_operands(result):
        if isinstance(value, dict):
            ref = value.get("ref")
            if isinstance(ref, dict) and ref.get("source") == "node":
                if not {"source", "node_id", "step_id", "output"} <= set(ref):
                    raise TaskError("SEQUENCE_SOURCE_INVALID")
                if set(ref) - {"source", "node_id", "step_id", "output", "pointer", "item_pointer", "loop_node_id"}:
                    raise TaskError("SEQUENCE_SOURCE_INVALID")
                if any(not isinstance(ref.get(key), str) or not ref[key] for key in ('node_id', 'step_id', 'output')):
                    raise TaskError("SEQUENCE_SOURCE_INVALID")
                value["ref"] = source_operand({"kind": "output", **{key: item for key, item in ref.items() if key != "source"},
                                                "pointer": ref.get("pointer", "")})["ref"]
    return result


def linear_flow(nodes):
    return {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
        {"id": node["node_id"], "kind": "action", "step_id": node["node_id"]} for node in nodes]}}


def validate_sequence_flow(flow, nodes):
    if not isinstance(flow, dict) or not isinstance(flow.get('root'), dict) or flow['root'].get('kind') != 'sequence':
        raise TaskError('FLOW_INVALID')
    for value in flow_operands(flow):
        if isinstance(value, dict):
            if 'ref' in value and isinstance(value['ref'], dict) and value['ref'].get('source') not in {'task', 'node', 'loop', 'branch'}:
                raise TaskError('SEQUENCE_SOURCE_INVALID')
    effective = machine_flow(flow)
    bindings = []
    for node in nodes:
        sources = [*node["inputs"].values(), *(source for values in node["step_inputs"].values() for source in values.values())]
        bindings.append({"step_id": node["node_id"], "bindings": {
            str(index): source_operand(source) for index, source in enumerate(sources)}})
    validate_flow(effective, bindings)
    return effective
