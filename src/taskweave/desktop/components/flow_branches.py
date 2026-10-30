"""Edit the current cases/default conditional branch structure."""

from copy import deepcopy
from uuid import uuid4

from taskweave.core.validation import TaskError


def split_branches(node):
    """Return independent editable case records and the default sequence."""
    return deepcopy([{"id": case["id"], "condition": case["condition"], "then": case["body"],
                      "values": {name: mapping[case["id"]] for name, mapping in node.get("outputs", {}).items()}}
                     for case in node["cases"]]), deepcopy(node["default"]["body"])


def branch_output_values(node):
    """Return output names in display order and the default bindings."""
    return list(node.get("outputs", {})), deepcopy({name: mapping[node["default"]["id"]] for name, mapping in node.get("outputs", {}).items()})


def new_branch(*, values=None):
    """Create an empty, initially nonmatching case with explicit output bindings.

    Existing public outputs must be supplied by the caller before saving. This
    function does not infer an output value or silently substitute null.
    """
    return {"id": str(uuid4()),
            "condition": {"op": "eq", "left": {"literal": False}, "right": {"literal": True}},
            "then": {"id": str(uuid4()), "kind": "sequence", "children": []},
            "values": deepcopy(values) if values is not None else {}}


def _check_index(cases, index):
    if type(index) is not int or not 0 <= index < len(cases):
        raise TaskError("FORM_INVALID", "分支位置无效")


def _reorder(cases, contents):
    return [{**deepcopy(case), **deepcopy(content)} for case, content in zip(cases, contents)]


def _content(case):
    return {name: case[name] for name in ("condition", "then", "values")}


def move_branch(cases, index, target):
    """Move a condition and its path/output values, retaining the slot IDs."""
    _check_index(cases, index)
    _check_index(cases, target)
    contents = [_content(case) for case in cases]
    contents.insert(target, contents.pop(index))
    return _reorder(cases, contents)


def remove_branch(cases, index):
    """Remove an empty case while keeping at least one condition and every path."""
    _check_index(cases, index)
    if len(cases) < 2:
        raise TaskError("FORM_INVALID", "至少保留一条条件分支")
    if cases[index]["then"]["children"]:
        raise TaskError("FORM_INVALID", "请先移走此分支中的步骤或控制块")
    contents = [_content(case) for case in cases]
    contents.pop(index)
    return _reorder(cases[:-1], contents)


def build_branches(original_node, cases, fallback, output_names, *, fallback_values=None):
    """Build a version 2 if node without mutating any input.

    The caller still validates the complete flow, including reference scope and
    the existing nesting limit. Branch identities remain stable while editing their bodies.
    """
    if not cases:
        raise TaskError("FORM_INVALID", "至少保留一条条件分支")
    names = list(output_names)
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise TaskError("FORM_INVALID", "输出名称不能为空或重复")
    expected = set(names)
    for case in cases:
        if set(case.get("values", {})) != expected:
            raise TaskError("FORM_INVALID", "请为每条分支明确配置全部公共输出")
    if fallback_values is None:
        _, fallback_values = branch_output_values(original_node)
        fallback_values = {name: value for name, value in fallback_values.items() if name in expected}
    if set(fallback_values) != expected:
        raise TaskError("FORM_INVALID", "请为默认分支明确配置全部公共输出")
    if fallback.get("kind") != "sequence":
        raise TaskError("FORM_INVALID", "默认分支必须是步骤分组")

    fallback_id = original_node.get("default", {}).get("id", original_node["id"] + "-default")
    result = {"id": original_node["id"], "kind": "if", "parallel": original_node.get("parallel", False),
              "cases": [{"id": case["id"], "condition": deepcopy(case["condition"]), "body": deepcopy(case["then"])} for case in cases],
              "default": {"id": fallback_id, "body": deepcopy(fallback)}}
    if names or "outputs" in original_node:
        result["outputs"] = {name: {**{case["id"]: deepcopy(case["values"][name]) for case in cases},
                                   fallback_id: deepcopy(fallback_values[name])} for name in names}
    return result
