"""Declarative acceptance comparisons over JSON, without evaluating scripts."""

import json

from taskweave.core.validation import fingerprint


def equal(left, right):
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    return left == right


def preview(value, limit=800):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(text) <= limit:
        return value
    return {"preview": text[:limit], "truncated": True, "fingerprint": fingerprint(value), "characters": len(text)}


def evaluate(value, rule, witness=True, on_skip="not_applicable"):
    if witness is None:
        return {"status": "NOT_APPLICABLE" if on_skip == "not_applicable" else "MISSING", "skipped": 1}
    op = rule["op"]
    expected = rule.get("expected")
    if op in {"all", "any"}:
        if not isinstance(value, list):
            return {"status": "ERROR", "message": "all/any 需要列表"}
        observations = witness if isinstance(witness, list) else [witness] * len(value)
        if len(observations) != len(value):
            return {"status": "ERROR", "message": "逐轮证据与值的数量不匹配"}
        children = [evaluate(item, rule["check"], source, on_skip) for item, source in zip(value, observations)]
        statuses = [child["status"] for child in children]
        applicable = [status for status in statuses if status != "NOT_APPLICABLE"]
        if not children:
            status = "PASS" if op == "all" else "FAIL"
        elif not applicable:
            status = "NOT_APPLICABLE"
        elif op == "any" and "PASS" in applicable:
            status = "PASS"
        elif "ERROR" in applicable:
            status = "ERROR"
        elif op == "all" and "FAIL" in applicable:
            status = "FAIL"
        elif "MISSING" in applicable:
            status = "MISSING"
        else:
            status = "PASS" if op == "all" else "FAIL"
        return {"status": status, "children": children, "evaluated": len(applicable),
                "skipped": sum(child.get("skipped", 0) for child in children)}
    if op == "exists":
        passed = True
    elif op in {"eq", "ne"}:
        passed = equal(value, expected)
        if op == "ne":
            passed = not passed
    elif op == "count":
        if not isinstance(value, (list, dict, str)):
            return {"status": "ERROR", "message": "计数需要列表、对象或字符串"}
        passed = equal(len(value), expected)
    elif op == "contains":
        if isinstance(value, list):
            passed = any(equal(item, expected) for item in value)
        elif isinstance(value, str) and isinstance(expected, str):
            passed = expected in value
        else:
            return {"status": "ERROR", "message": "contains 需要列表或字符串"}
    elif op in {"gt", "gte", "lt", "lte"}:
        if type(value) not in (int, float) or type(expected) not in (int, float):
            return {"status": "ERROR", "message": "数值比较不能使用布尔、空值或其他类型"}
        passed = {"gt": value > expected, "gte": value >= expected,
                  "lt": value < expected, "lte": value <= expected}[op]
    else:
        return {"status": "ERROR", "message": "不支持的核对操作"}
    return {"status": "PASS" if passed else "FAIL"}
