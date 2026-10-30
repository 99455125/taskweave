"""Pure structured task-flow definitions and condition evaluation."""

from copy import deepcopy
import re

from taskweave.core.validation import TaskError, dumps


FLOW_VERSION = 2
MAX_DEPTH = 8
MAX_ITERATIONS = 10_000
DEFAULT_LOOP_ITERATIONS = 100
DEFAULT_FOREACH_ITEMS = 1_000
_POINTER = re.compile(r"~(?![01])")


def conditional_branches(node):
    """Ordered stable branch identities and bodies for a conditional group."""
    return [(case["id"], case["body"]) for case in [*node["cases"], node["default"]]]


def _valid_pointer(value):
    return isinstance(value, str) and (not value or value.startswith("/")) and not _POINTER.search(value)


def normalize_flow(graph: dict, steps: list[dict]) -> dict:
    """Validate and copy the current structured flow without converting old data."""
    validate_flow(graph, steps)
    return deepcopy(graph)


def _check_operand(operand, step_ids, loop_ids, available_steps=None, branch_outputs=None):
    if not isinstance(operand, dict):
        raise TaskError("FLOW_OPERAND_INVALID")
    if set(operand) == {"literal"}:
        dumps(operand["literal"])
        return
    if set(operand) != {"ref"} or not isinstance(operand["ref"], dict):
        raise TaskError("FLOW_OPERAND_INVALID")
    ref = operand["ref"]
    source = ref.get("source")
    if source not in {"task", "environment", "step", "loop", "branch"} or not _valid_pointer(ref.get("pointer", "")):
        raise TaskError("FLOW_OPERAND_INVALID")
    if source == "step" and ref.get("step_id") not in step_ids:
        raise TaskError("FLOW_REFERENCE_INVALID")
    if source == "step" and available_steps is not None and ref["step_id"] not in available_steps:
        raise TaskError("FLOW_REFERENCE_INVALID")
    if source == "loop":
        if ref.get("node_id") not in loop_ids or ref.get("field") not in {"item", "index", "state"}:
            raise TaskError("FLOW_REFERENCE_INVALID")
    if source == "branch":
        node_id = ref.get("node_id")
        if (not isinstance(node_id, str) or not isinstance(ref.get("output"), str)
                or available_steps is not None and "branch:" + node_id not in available_steps
                or branch_outputs is not None and ref["output"] not in branch_outputs.get(node_id, ())):
            raise TaskError("FLOW_REFERENCE_INVALID")
    allowed = {"source", "pointer"}
    if source == "step":
        allowed |= {"step_id", "output", "item_pointer", "loop_node_id"}
        if "item_pointer" in ref and not _valid_pointer(ref["item_pointer"]):
            raise TaskError("FLOW_OPERAND_INVALID")
    if source == "loop":
        allowed |= {"node_id", "field"}
    if source == "branch":
        allowed |= {"node_id", "output"}
    if set(ref) - allowed:
        raise TaskError("FLOW_OPERAND_INVALID")


def _check_condition(condition, step_ids, loop_ids, available_steps=None, branch_outputs=None):
    if not isinstance(condition, dict):
        raise TaskError("FLOW_CONDITION_INVALID")
    op = condition.get("op")
    if op in {"all", "any"}:
        children = condition.get("conditions")
        if set(condition) != {"op", "conditions"} or not isinstance(children, list) or not children:
            raise TaskError("FLOW_CONDITION_INVALID")
        for child in children:
            _check_condition(child, step_ids, loop_ids, available_steps, branch_outputs)
    elif op == "not":
        if set(condition) != {"op", "condition"}:
            raise TaskError("FLOW_CONDITION_INVALID")
        _check_condition(condition["condition"], step_ids, loop_ids, available_steps, branch_outputs)
    elif op in {"exists", "empty"}:
        if set(condition) != {"op", "value"}:
            raise TaskError("FLOW_CONDITION_INVALID")
        _check_operand(condition["value"], step_ids, loop_ids, available_steps, branch_outputs)
    elif op in {"eq", "ne", "gt", "gte", "lt", "lte", "contains"}:
        if set(condition) != {"op", "left", "right"}:
            raise TaskError("FLOW_CONDITION_INVALID")
        _check_operand(condition["left"], step_ids, loop_ids, available_steps, branch_outputs)
        _check_operand(condition["right"], step_ids, loop_ids, available_steps, branch_outputs)
    else:
        raise TaskError("FLOW_CONDITION_INVALID")


def validate_flow(flow: dict, steps: list[dict]) -> None:
    if not isinstance(flow, dict) or set(flow) != {"version", "root"} or flow["version"] != FLOW_VERSION:
        raise TaskError("FLOW_INVALID")
    step_ids = {step["step_id"] for step in steps}
    by_step = {step["step_id"]: step for step in steps}
    node_ids = set()
    action_ids = set()
    branch_outputs = {}

    def walk(node, depth, loops, available):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise TaskError("FLOW_INVALID")
        if node.get("kind") in {"if", "foreach", "loop"}:
            depth += 1
        if depth > MAX_DEPTH:
            raise TaskError("FLOW_DEPTH_EXCEEDED")
        if node["id"] in node_ids:
            if node.get("kind") == "action":
                raise TaskError("FLOW_ACTION_DUPLICATE")
            raise TaskError("FLOW_NODE_DUPLICATE")
        node_ids.add(node["id"])
        kind = node.get("kind")
        if kind == "sequence":
            if set(node) != {"id", "kind", "children"} or not isinstance(node["children"], list):
                raise TaskError("FLOW_INVALID")
            for child in node["children"]:
                available = walk(child, depth, loops, available)
            return available
        elif kind == "action":
            if set(node) != {"id", "kind", "step_id"} or node["step_id"] not in step_ids:
                raise TaskError("FLOW_REFERENCE_INVALID")
            if node["step_id"] in action_ids:
                raise TaskError("FLOW_ACTION_DUPLICATE")
            for binding in by_step[node["step_id"]].get("bindings", {}).values():
                _check_operand(binding, step_ids, loops, available, branch_outputs)
            action_ids.add(node["step_id"])
            return available | {node["step_id"]}
        elif kind == "if":
            if (not {"id", "kind", "cases", "default"} <= set(node)
                    or set(node) - {"id", "kind", "cases", "default", "parallel", "outputs"}
                    or type(node.get("parallel", False)) is not bool
                    or not isinstance(node["cases"], list) or not node["cases"]):
                raise TaskError("FLOW_INVALID")
            identities = set()
            branch_available = {}
            for branch in [*node["cases"], node["default"]]:
                expected = {"id", "body"} if branch is node["default"] else {"id", "condition", "body"}
                if (not isinstance(branch, dict) or set(branch) != expected
                        or not isinstance(branch.get("id"), str) or not branch["id"]
                        or branch["id"] in identities
                        or not isinstance(branch.get("body"), dict) or branch["body"].get("kind") != "sequence"):
                    raise TaskError("FLOW_INVALID")
                identities.add(branch["id"])
                if "condition" in branch:
                    _check_condition(branch["condition"], step_ids, loops, available, branch_outputs)
                branch_available[branch["id"]] = walk(branch["body"], depth, loops, available)
            outputs = node.get("outputs", {})
            if not isinstance(outputs, dict) or any(not isinstance(name, str) or not name for name in outputs):
                raise TaskError("FLOW_INVALID")
            for mapping in outputs.values():
                if not isinstance(mapping, dict) or set(mapping) != identities:
                    raise TaskError("FLOW_INVALID")
                for identity, operand in mapping.items():
                    _check_operand(operand, step_ids, loops, branch_available[identity], branch_outputs)
            branch_outputs[node["id"]] = set(outputs)
            return available | {"branch:" + node["id"]}
        elif kind == "foreach":
            if not {"id", "kind", "items", "body"} <= set(node) or set(node) - {"id", "kind", "items", "body", "max_items"}:
                raise TaskError("FLOW_INVALID")
            limit = node.get("max_items", DEFAULT_FOREACH_ITEMS)
            if type(limit) is not int or not 1 <= limit <= MAX_ITERATIONS:
                raise TaskError("LOOP_LIMIT_INVALID")
            _check_operand(node["items"], step_ids, loops, available, branch_outputs)
            if not isinstance(node["body"], dict) or node["body"].get("kind") != "sequence":
                raise TaskError("FLOW_INVALID")
            body_available = walk(node["body"], depth, (*loops, node["id"]), available)
            return body_available
        elif kind == "loop":
            if not {"id", "kind", "mode", "condition", "body"} <= set(node) or set(node) - {"id", "kind", "mode", "condition", "body", "max_iterations", "state_initial", "state_update"}:
                raise TaskError("FLOW_INVALID")
            if node["mode"] not in {"while", "until"}:
                raise TaskError("FLOW_INVALID")
            for field in ("state_initial", "state_update"):
                if not isinstance(node.get(field, {}), dict) or any(
                    not isinstance(name, str) or not name for name in node.get(field, {})
                ):
                    raise TaskError("FLOW_INVALID")
            limit = node.get("max_iterations", DEFAULT_LOOP_ITERATIONS)
            if type(limit) is not int or not 1 <= limit <= MAX_ITERATIONS:
                raise TaskError("LOOP_LIMIT_INVALID")
            for initial in (node.get("state_initial") or {}).values():
                _check_operand(initial, step_ids, loops, available, branch_outputs)
            inner_loops = (*loops, node["id"])
            if not isinstance(node["body"], dict) or node["body"].get("kind") != "sequence":
                raise TaskError("FLOW_INVALID")
            if node["mode"] == "while":
                _check_condition(node["condition"], step_ids, inner_loops, available, branch_outputs)
            body_available = walk(node["body"], depth, inner_loops, available)
            for update in (node.get("state_update") or {}).values():
                _check_operand(update, step_ids, inner_loops, body_available, branch_outputs)
            if node["mode"] == "until":
                _check_condition(node["condition"], step_ids, inner_loops, body_available, branch_outputs)
            return body_available
        else:
            raise TaskError("FLOW_INVALID")

    walk(flow["root"], 0, (), set())
    if action_ids != step_ids:
        raise TaskError("FLOW_STEP_UNPLACED")


def is_linear_flow(flow: dict) -> bool:
    def linear(node):
        return node["kind"] == "action" or node["kind"] == "sequence" and all(linear(child) for child in node["children"])
    return linear(flow["root"])


def remap_step_ids(flow: dict, mapping: dict[str, str]) -> dict:
    """Translate action identities and step refs across package/copy boundaries."""
    result = deepcopy(flow)

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if value.get("kind") == "action" and "step_id" in value:
                old = value["step_id"]
                value["step_id"] = mapping[old]
                if value.get("id") == old:
                    value["id"] = mapping[old]
            if isinstance(value.get("ref"), dict) and value["ref"].get("source") == "step":
                value["ref"]["step_id"] = mapping[value["ref"]["step_id"]]
            for child in value.values():
                visit(child)

    visit(result)
    return result


def _same_json_kind(left, right):
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    if type(left) in {int, float} or type(right) in {int, float}:
        return type(left) in {int, float} and type(right) in {int, float}
    return type(left) is type(right)


def evaluate_condition(condition: dict, read) -> bool:
    op = condition["op"]
    if op == "all":
        return all(evaluate_condition(item, read) for item in condition["conditions"])
    if op == "any":
        return any(evaluate_condition(item, read) for item in condition["conditions"])
    if op == "not":
        return not evaluate_condition(condition["condition"], read)
    if op == "exists":
        try:
            read(condition["value"])
        except TaskError as exc:
            if exc.code == "INPUT_MISSING":
                return False
            raise
        return True
    if op == "empty":
        value = read(condition["value"])
        if not isinstance(value, (str, list, dict)):
            raise TaskError("FLOW_TYPE_INVALID")
        return len(value) == 0
    left, right = read(condition["left"]), read(condition["right"])
    if op in {"eq", "ne"}:
        equal = _same_json_kind(left, right) and left == right
        return equal if op == "eq" else not equal
    if op in {"gt", "gte", "lt", "lte"}:
        comparable = (type(left) in {int, float} and type(right) in {int, float}) or (type(left) is str and type(right) is str)
        if not comparable:
            raise TaskError("FLOW_TYPE_INVALID")
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[op]
    if op == "contains":
        if isinstance(left, str) and isinstance(right, str):
            return right in left
        if isinstance(left, list):
            return right in left
        if isinstance(left, dict) and isinstance(right, str):
            return right in left
        raise TaskError("FLOW_TYPE_INVALID")
    raise TaskError("FLOW_CONDITION_INVALID")
