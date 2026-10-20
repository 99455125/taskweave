"""Assemble action results using the control tree's iteration boundaries."""

from taskweave.core.validation import TaskError, pointer


def _segment(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _contains(node, step_id):
    kind = node["kind"]
    if kind == "action":
        return node["step_id"] == step_id
    if kind == "sequence":
        return any(_contains(child, step_id) for child in node["children"])
    if kind == "if":
        return _contains(node["then"], step_id) or _contains(node["else"], step_id)
    return _contains(node["body"], step_id)


def _contains_node(node, node_id):
    if node["id"] == node_id:
        return True
    if node["kind"] == "sequence":
        return any(_contains_node(child, node_id) for child in node["children"])
    if node["kind"] == "if":
        return _contains_node(node["then"], node_id) or _contains_node(node["else"], node_id)
    if node["kind"] in {"foreach", "loop"}:
        return _contains_node(node["body"], node_id)
    return False


def aggregate_output(flow, visits, step_id, output, read_attempt, *, item_pointer=None, loop_node_id=None,
                     active_frames=()):
    """Read one action's effective attempts, preserving nested loop shape.

    ``read_attempt`` receives an exact attempt id and output name. A skipped
    branch occupies one null slot in an enclosing iteration.
    """
    if not _contains(flow["root"], step_id):
        raise TaskError("FLOW_REFERENCE_INVALID")
    if item_pointer is not None and loop_node_id is None:
        raise TaskError("FLOW_REFERENCE_INVALID")
    records = {visit["execution_path"]: visit for visit in visits}
    active = {frame["path"]: frame for frame in active_frames if frame["kind"] in {"foreach", "loop"}}
    projected = False

    def descend(node, path):
        nonlocal projected
        kind = node["kind"]
        if kind == "action":
            record = records.get(path)
            if record is None or record["status"] != "SUCCEEDED" or not record.get("attempt_id"):
                raise TaskError("RESULT_NOT_FOUND")
            return read_attempt(record["attempt_id"], output)
        if kind == "sequence":
            child = next(child for child in node["children"] if _contains(child, step_id))
            return descend(child, path + "/" + _segment(child["id"]))
        record = records.get(path)
        if record is None or record["status"] not in {"SUCCEEDED", "RUNNING"}:
            raise TaskError("RESULT_NOT_FOUND")
        if kind == "if":
            branch = record["payload"]["selected"]
            selected = node[branch]
            if not _contains(selected, step_id):
                return None
            return descend(selected, path + "/" + branch + "/" + _segment(selected["id"]))
        if path in active:
            frame = active[path]
            body = node["body"]
            return descend(body, path + "/" + str(frame["index"]) + "/" + _segment(body["id"]))
        if kind == "foreach":
            count = (len(record["payload"]["items"]) if record["status"] == "SUCCEEDED" else
                     sum(1 for visit in visits if visit["kind"] == "iteration"
                         and visit.get("parent_path") == path and visit["status"] == "SUCCEEDED"))
        else:
            count = record["payload"].get("completed", 0)
        body = node["body"]
        values = []
        for index in range(count):
            value = descend(body, path + "/" + str(index) + "/" + _segment(body["id"]))
            if node["id"] == loop_node_id:
                projected = True
                if value is not None and item_pointer is not None:
                    value = pointer(value, item_pointer)
            values.append(value)
        if node["id"] == loop_node_id:
            projected = True
        return values

    result = descend(flow["root"], "/" + _segment(flow["root"]["id"]))
    if loop_node_id is not None and not projected:
        raise TaskError("FLOW_REFERENCE_INVALID")
    return result


def aggregate_branch_output(flow, visits, node_id, output, read_mapping, *, active_frames=()):
    """Resolve a public branch output in its own selected iteration path."""
    if not _contains_node(flow["root"], node_id):
        raise TaskError("FLOW_REFERENCE_INVALID")
    records = {visit["execution_path"]: visit for visit in visits}
    active = {frame["path"]: frame for frame in active_frames if frame["kind"] in {"foreach", "loop"}}

    def descend(node, path):
        kind = node["kind"]
        if kind == "sequence":
            child = next(child for child in node["children"] if _contains_node(child, node_id))
            return descend(child, path + "/" + _segment(child["id"]))
        record = records.get(path)
        if record is None or record["status"] not in {"SUCCEEDED", "RUNNING"}:
            raise TaskError("RESULT_NOT_FOUND")
        if kind == "if":
            selected = record["payload"]["selected"]
            if node["id"] == node_id:
                try:
                    mapping = node["outputs"][output][selected]
                except KeyError as exc:
                    raise TaskError("FLOW_REFERENCE_INVALID") from exc
                return read_mapping(mapping, path, selected)
            branch = node[selected]
            if not _contains_node(branch, node_id):
                return None
            return descend(branch, path + "/" + selected + "/" + _segment(branch["id"]))
        body = node["body"]
        if path in active:
            index = active[path]["index"]
            return descend(body, path + "/" + str(index) + "/" + _segment(body["id"]))
        if record["status"] != "SUCCEEDED":
            raise TaskError("RESULT_NOT_FOUND")
        count = len(record["payload"]["items"]) if kind == "foreach" else record["payload"]["completed"]
        return [descend(body, path + "/" + str(index) + "/" + _segment(body["id"]))
                for index in range(count)]

    return descend(flow["root"], "/" + _segment(flow["root"]["id"]))
