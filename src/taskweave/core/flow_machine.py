"""Pure cursor transitions for structured task execution."""

from copy import deepcopy

from taskweave.core.task_flow import DEFAULT_FOREACH_ITEMS, DEFAULT_LOOP_ITERATIONS, evaluate_condition, conditional_branches
from taskweave.core.validation import TaskError, dumps

CONTROL_BATCH_SIZE = 128
MAX_CONTROL_VISITS = 1_000_000


class FlowDecisionError(TaskError):
    def __init__(self, code, node_id, execution_path, cursor, instances):
        super().__init__(code)
        self.node_id = node_id
        self.execution_path = execution_path
        self.cursor = cursor
        self.instances = instances


def _nodes(flow):
    found = {}

    def visit(node):
        found[node["id"]] = node
        if node["kind"] == "sequence":
            for child in node["children"]:
                visit(child)
        elif node["kind"] == "if":
            for _, branch in conditional_branches(node):
                visit(branch)
        elif node["kind"] in {"foreach", "loop"}:
            visit(node["body"])

    visit(flow["root"])
    return found


def _part(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _read(binding, cursor, read_value):
    if "literal" in binding:
        return binding["literal"]
    return read_value(binding, cursor)


def _condition(condition, cursor, read_value):
    return evaluate_condition(condition, lambda binding: _read(binding, cursor, read_value))


def _visit(frame, status, payload=None, **extra):
    return {
        "execution_path": frame["path"], "node_id": frame["node_id"],
        "kind": frame["kind"], "status": status,
        "payload": payload if payload is not None else {}, **extra,
    }


def _finish(cursor, visits):
    frames = cursor["frames"]
    finished = frames.pop()
    if finished["kind"] != "sequence":
        visits.append(_visit(finished, "SUCCEEDED", {
            key: finished[key] for key in ("selected", "facts", "outputs", "index", "state", "items", "completed") if key in finished
        }))
    if not frames:
        return
    parent = frames[-1]
    if parent["kind"] == "sequence":
        parent["index"] += 1
    elif parent["kind"] == "if":
        _finish(cursor, visits)
    elif parent["kind"] == "foreach":
        visits.append({"execution_path": parent["path"] + "/" + str(parent["index"]),
                       "node_id": parent["node_id"], "kind": "iteration", "status": "SUCCEEDED",
                       "parent_path": parent["path"],
                       "payload": {"index": parent["index"], "item": parent["items"][parent["index"]]}})
        parent["index"] += 1
        parent["active"] = False
    elif parent["kind"] == "loop":
        parent["phase"] = "after"
        parent["active"] = False
        parent["completed"] += 1
    else:
        raise TaskError("FLOW_CURSOR_INVALID")


def next_action(flow, cursor, read_value, *, read_with_pending=None, _batch_size=CONTROL_BATCH_SIZE):
    """Advance control nodes until one action is ready or the flow ends."""
    nodes = _nodes(flow)
    cursor = deepcopy(cursor) if cursor is not None else {
        "frames": [{"node_id": flow["root"]["id"], "kind": "sequence",
                    "path": "/" + _part(flow["root"]["id"]), "index": 0}],
        "pending": None, "actions": 0, "control_visits": 0,
    }
    visits = []
    def transition(action, done, actions=None):
        cursor["control_visits"] = cursor.get("control_visits", 0) + sum(
            item["kind"] != "action" for item in visits)
        if cursor["control_visits"] > MAX_CONTROL_VISITS:
            frame = cursor["frames"][-1] if cursor["frames"] else {"node_id": flow["root"]["id"],
                                                                   "path": "/" + _part(flow["root"]["id"])}
            raise FlowDecisionError("FLOW_CONTROL_LIMIT_EXCEEDED", frame["node_id"], frame["path"], cursor, visits)
        return {"cursor": cursor, "instances": visits, "action": action, "done": done,
                "errors": cursor_errors(cursor),
                "actions": actions if actions is not None else ([action] if action is not None else [])}

    def read(binding, current):
        current = {**current, "frames": [*current.get("context", []), *current["frames"]]}
        return (read_with_pending(binding, current, visits) if read_with_pending is not None
                else read_value(binding, current))
    if cursor["pending"] is not None:
        return transition(cursor["pending"], False)
    while cursor["frames"]:
        if len(visits) >= _batch_size:
            return transition(None, False)
        frame = cursor["frames"][-1]
        node = nodes[frame["node_id"]]
        kind = frame["kind"]
        try:
            if kind == "sequence":
                if frame["index"] >= len(node["children"]):
                    _finish(cursor, visits)
                    continue
                child = node["children"][frame["index"]]
                path = frame["path"] + "/" + _part(child["id"])
                if child["kind"] == "action":
                    pending = {"node_id": child["id"], "step_id": child["step_id"], "execution_path": path}
                    cursor["pending"] = pending
                    visits.append({"execution_path": path, "node_id": child["id"], "kind": "action",
                                   "status": "READY", "parent_path": frame["path"], "payload": {}})
                    return transition(pending, False)
                cursor["frames"].append({"node_id": child["id"], "kind": child["kind"], "path": path})
                continue
            if kind == "if":
                if "selected" not in frame:
                    selected = []
                    facts = {}
                    def frozen_read(binding, current):
                        key = dumps(binding)
                        if key not in facts:
                            facts[key] = {"binding": deepcopy(binding), "value": deepcopy(read(binding, current))}
                        return deepcopy(facts[key]["value"])
                    for case in node["cases"]:
                        if _condition(case["condition"], cursor, frozen_read):
                            selected.append(case["id"])
                            if not node.get("parallel", False):
                                break
                    frame["selected"] = selected or [node["default"]["id"]]
                    frame["facts"] = list(facts.values())
                    branches = dict(conditional_branches(node))
                    frame["lanes"] = []
                    for identity in frame["selected"]:
                        body = branches[identity]
                        frame["lanes"].append({"frames": [{"node_id": body["id"], "kind": "sequence",
                            "path": frame["path"] + "/" + _part(identity) + "/" + _part(body["id"]), "index": 0}],
                            "resource_path": (frame["path"] + "/" + _part(identity)
                                              if node.get("parallel", False) else cursor.get("resource_path", "/")),
                            "pending": None, "actions": 0, "control_visits": 0})
                    visits.append(_visit(frame, "RUNNING", {"selected": frame["selected"], "facts": frame["facts"]}))
                actions = []
                all_done = True
                for index, lane in enumerate(frame["lanes"]):
                    if len(visits) >= _batch_size:
                        all_done = False
                        break
                    if lane.get("error"):
                        all_done = False
                        continue
                    context = [*cursor.get("context", []), *[{key: value for key, value in item.items()
                        if key != "lanes"} for item in cursor["frames"]]]
                    try:
                        child = next_action(flow, {**lane, "context": context}, read_value,
                            _batch_size=_batch_size - len(visits),
                            read_with_pending=lambda binding, current, pending:
                                read_with_pending(binding, current, [*visits, *pending])
                                if read_with_pending is not None else read_value(binding, current))
                    except FlowDecisionError as exc:
                        failed = {"execution_path": exc.execution_path + "/$error", "node_id": exc.node_id,
                                  "kind": "control", "status": "FAILED", "error_code": exc.code, "payload": {}}
                        child = {"cursor": {**exc.cursor, "error": failed},
                                 "instances": [*exc.instances, failed], "actions": [], "done": False}
                    child["cursor"].pop("context", None)
                    frame["lanes"][index] = child["cursor"]
                    visits.extend(child["instances"])
                    actions.extend(child["actions"])
                    all_done = all_done and child["done"]
                if not all_done:
                    return transition(actions[0] if actions else None, False, actions)
                frame["outputs"] = {}
                for name, mapping in node.get("outputs", {}).items():
                    values = {identity: _read(mapping[identity], cursor, read) for identity in frame["selected"]}
                    frame["outputs"][name] = values if node.get("parallel", False) else values[frame["selected"][0]]
                _finish(cursor, visits)
                continue
            if kind == "foreach":
                if "items" not in frame:
                    items = _read(node["items"], cursor, read)
                    if not isinstance(items, list):
                        raise TaskError("FLOW_TYPE_INVALID")
                    if len(items) > node.get("max_items", DEFAULT_FOREACH_ITEMS):
                        raise TaskError("LOOP_LIMIT_EXCEEDED")
                    frame.update(items=deepcopy(items), index=0, active=False)
                    visits.append(_visit(frame, "RUNNING", {"items": frame["items"], "index": 0}))
                if frame["index"] >= len(frame["items"]):
                    _finish(cursor, visits)
                    continue
                if not frame["active"]:
                    frame["active"] = True
                    body = node["body"]
                    cursor["frames"].append({"node_id": body["id"], "kind": "sequence",
                                             "path": frame["path"] + "/" + str(frame["index"]) + "/" + _part(body["id"]),
                                             "index": 0})
                continue
            if kind == "loop":
                if "state" not in frame:
                    frame["state"] = {name: _read(binding, cursor, read)
                                      for name, binding in node.get("state_initial", {}).items()}
                    frame.update(index=0, completed=0, phase="initial" if node["mode"] == "while" else "run", active=False)
                    visits.append(_visit(frame, "RUNNING", {"index": 0, "completed": 0, "state": frame["state"]}))
                if frame["phase"] == "initial":
                    if not _condition(node["condition"], cursor, read):
                        _finish(cursor, visits)
                        continue
                    frame["phase"] = "run"
                if frame["phase"] == "after":
                    state_before = deepcopy(frame["state"])
                    updated = {name: _read(binding, cursor, read)
                               for name, binding in node.get("state_update", {}).items()}
                    frame["state"] = {**frame["state"], **updated}
                    visits.append({"execution_path": frame["path"] + "/" + str(frame["index"]),
                                   "node_id": frame["node_id"], "kind": "iteration", "status": "SUCCEEDED",
                                   "parent_path": frame["path"],
                                   "payload": {"index": frame["index"], "state_before": state_before,
                                               "state": deepcopy(frame["state"])}})
                    condition_true = _condition(node["condition"], cursor, read)
                    should_continue = condition_true if node["mode"] == "while" else not condition_true
                    visits.append(_visit(frame, "RUNNING", {"index": frame["index"], "completed": frame["completed"], "state": frame["state"]}))
                    if not should_continue:
                        _finish(cursor, visits)
                        continue
                    frame["index"] += 1
                    frame["phase"] = "run"
                if frame["index"] >= node.get("max_iterations", DEFAULT_LOOP_ITERATIONS):
                    raise TaskError("LOOP_LIMIT_EXCEEDED")
                if not frame["active"]:
                    frame["active"] = True
                    body = node["body"]
                    cursor["frames"].append({"node_id": body["id"], "kind": "sequence",
                                             "path": frame["path"] + "/" + str(frame["index"]) + "/" + _part(body["id"]),
                                             "index": 0})
                continue
            raise TaskError("FLOW_CURSOR_INVALID")
        except TaskError as exc:
            raise FlowDecisionError(exc.code, frame["node_id"], frame["path"], cursor, visits) from exc
    return transition(None, True)


def cursor_errors(cursor):
    """Frozen failures block only their lane until the group has drained."""
    errors = [cursor["error"]] if cursor.get("error") else []
    for frame in cursor["frames"]:
        for lane in frame.get("lanes", []):
            errors.extend(cursor_errors(lane))
    return errors


def live_resource_paths(cursor):
    """Include suspended ancestor lanes until their own sequence has finished."""
    owners = {cursor.get("resource_path", "/")} if cursor.get("frames") else set()
    for frame in cursor.get("frames", []):
        for lane in frame.get("lanes", []):
            owners.update(live_resource_paths(lane))
    return owners


def pending_actions(cursor):
    """List current leaf occurrences without advancing control decisions."""
    actions = [cursor["pending"]] if cursor.get("pending") else []
    for frame in cursor.get("frames", []):
        for lane in frame.get("lanes", []):
            actions.extend(pending_actions(lane))
    return actions


def action_cursor(cursor, execution_path):
    """A pending path's read context, including all enclosing loop frames."""
    pending = cursor.get("pending")
    if pending and pending["execution_path"] == execution_path:
        return {**cursor, "frames": [*cursor.get("context", []), *cursor["frames"]]}
    context = [*cursor.get("context", []), *[{key: value for key, value in frame.items()
               if key != "lanes"} for frame in cursor["frames"]]]
    for frame in cursor["frames"]:
        for lane in frame.get("lanes", []):
            found = action_cursor({**lane, "context": context}, execution_path)
            if found is not None:
                return found
    return None


def advance_after_action(flow, cursor, attempt_id=None, *, execution_path=None):
    """Advance exactly one successful action occurrence."""
    cursor = deepcopy(cursor)
    if execution_path is not None and (cursor.get("pending") or {}).get("execution_path") != execution_path:
        for frame in cursor["frames"]:
            for index, lane in enumerate(frame.get("lanes", [])):
                if action_cursor(lane, execution_path) is not None:
                    advanced = advance_after_action(flow, lane, attempt_id, execution_path=execution_path)
                    frame["lanes"][index] = advanced["cursor"]
                    cursor["actions"] += 1
                    return {**advanced, "cursor": cursor}
        raise TaskError("FLOW_INSTANCE_REQUIRED")
    pending = cursor.get("pending")
    if pending is None or not cursor["frames"] or cursor["frames"][-1]["kind"] != "sequence":
        raise TaskError("FLOW_CURSOR_INVALID")
    cursor["frames"][-1]["index"] += 1
    cursor["pending"] = None
    cursor["actions"] += 1
    return {"cursor": cursor, "instances": [{
        "execution_path": pending["execution_path"], "node_id": pending["node_id"],
        "kind": "action", "status": "SUCCEEDED", "attempt_id": attempt_id,
        "payload": {},
    }], "action": None, "done": False}
