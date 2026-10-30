"""Pure editing operations for the structured task flow tree."""

from copy import deepcopy
from uuid import uuid4

from taskweave.core.validation import TaskError
from taskweave.core.task_flow import conditional_branches


def _walk(node, parent=None):
    yield node, parent
    if node["kind"] == "sequence":
        for child in node["children"]:
            yield from _walk(child, node)
    elif node["kind"] == "if":
        for _, body in conditional_branches(node):
            yield from _walk(body, node)
    elif node["kind"] in {"foreach", "loop"}:
        yield from _walk(node["body"], node)


def find_node(flow, node_id):
    return next(((node, parent) for node, parent in _walk(flow["root"])
                 if node["id"] == node_id), (None, None))


def sequence_targets(flow):
    result = [(flow["root"]["id"], "主流程")]
    for node, _ in _walk(flow["root"]):
        short = node["id"].replace("control-", "")[:6]
        if node["kind"] == "if":
            result.extend((body["id"], f"分支 {short} · {identity}") for identity, body in conditional_branches(node))
        elif node["kind"] in {"foreach", "loop"}:
            label = "列表遍历" if node["kind"] == "foreach" else "条件循环"
            result.append((node["body"]["id"], f"{label} {short} · 循环体"))
    return result


def insert_control(flow, kind, parent_id="root", index=None):
    result = deepcopy(flow)
    parent, _ = find_node(result, parent_id)
    if parent is None or parent["kind"] != "sequence":
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    node_id = "control-" + uuid4().hex[:12]
    body = {"id": node_id + "-body", "kind": "sequence", "children": []}
    if kind == "if":
        node = {"id": node_id, "kind": "if", "parallel": False,
                "cases": [{"id": node_id + "-case", "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
                           "body": {"id": node_id + "-then", "kind": "sequence", "children": []}}],
                "default": {"id": node_id + "-default", "body": {"id": node_id + "-else", "kind": "sequence", "children": []}}}
    elif kind == "foreach":
        node = {"id": node_id, "kind": "foreach", "items": {"literal": []},
                "max_items": 1000, "body": body}
    elif kind == "loop":
        node = {"id": node_id, "kind": "loop", "mode": "while",
                "condition": {"op": "eq", "left": {"literal": False}, "right": {"literal": True}},
                "max_iterations": 100, "state_initial": {}, "state_update": {}, "body": body}
    else:
        raise TaskError("FLOW_EDITOR_KIND_INVALID")
    children = parent["children"]
    if index is None:
        index = len(children)
    if type(index) is not int or not 0 <= index <= len(children):
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    children.insert(index, node)
    return result, node_id


def move_node(flow, node_id, parent_id, index=None):
    result = deepcopy(flow)
    node, current_parent = find_node(result, node_id)
    parent, _ = find_node(result, parent_id)
    if node is None or current_parent is None or current_parent["kind"] != "sequence":
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    if parent is None or parent["kind"] != "sequence":
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    if any(descendant["id"] == parent_id for descendant, _ in _walk(node)):
        raise TaskError("FLOW_EDITOR_CYCLE")
    current_parent["children"].remove(node)
    children = parent["children"]
    if index is None:
        index = len(children)
    if type(index) is not int or not 0 <= index <= len(children):
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    children.insert(index, node)
    return result


def update_control(flow, node_id, changes):
    result = deepcopy(flow)
    node, _ = find_node(result, node_id)
    if node is None or node["kind"] not in {"if", "foreach", "loop"}:
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    allowed = {"if": {"condition", "outputs", "cases", "default", "parallel"},
               "foreach": {"items", "max_items"},
               "loop": {"mode", "condition", "state_initial", "state_update", "max_iterations"}}[node["kind"]]
    if set(changes) - allowed:
        raise TaskError("FLOW_EDITOR_FIELD_INVALID")
    node.update(deepcopy(changes))
    return result


def remove_control(flow, node_id):
    result = deepcopy(flow)
    node, parent = find_node(result, node_id)
    if node is None or node["kind"] not in {"if", "foreach", "loop"} or parent is None:
        raise TaskError("FLOW_EDITOR_TARGET_INVALID")
    if any(descendant["kind"] == "action" for descendant, _ in _walk(node)):
        raise TaskError("FLOW_EDITOR_NOT_EMPTY", "请先移出控制块内的步骤")
    parent["children"].remove(node)
    return result
