"""Portable task configuration; no runtime state or environment configuration."""

import asyncio
import json

from taskweave.core.task_package import FORMAT, ORIGINS, VALIDATION_STATES, TASK_PACKAGE_SCHEMA
from taskweave.core.validation import (
    TaskError, check_bindings, check_schema, normalize_step,
)


def export_task(app, task_id):
    task = app.repo.task(task_id)
    steps = app.repo.steps(task_id)
    keys = {step["step_id"]: f"step-{index + 1}" for index, step in enumerate(steps)}
    entries = []
    for step in steps:
        document = normalize_step(step)
        for binding in document["bindings"].values():
            ref = binding.get("ref", {})
            if ref.get("source") == "step":
                ref["step_id"] = keys[ref["step_id"]]
        state = (
            "VALIDATED"
            if step.get("validation_state") == "VALIDATED"
            and step.get("verified_hash") == step.get("content_hash")
            else "DRAFT"
        )
        entries.append({
            "key": keys[step["step_id"]],
            "validation_state": state,
            "document": document,
        })
    return {
        "format": FORMAT,
        "origin": "task_export",
        "task": {
            "name": task["name"],
            "description": task["description"],
            "input_schema": json.loads(task["input_schema_json"]),
        },
        "steps": entries,
    }


def validate_task_package(app, package, *, expected_origin=None):
    """Validate and normalize a package without writing or executing anything."""
    if not isinstance(package, dict) or package.get("format") != FORMAT:
        if isinstance(package, dict) and package.get("format") == "taskweave-task-1":
            raise TaskError("TASK_PACKAGE_INVALID", "旧任务包不再兼容，请使用当前版本重新导出")
        raise TaskError("TASK_PACKAGE_INVALID", f"需要 {FORMAT} 任务 JSON")
    if set(package) != {"format", "origin", "task", "steps"}:
        raise TaskError("TASK_PACKAGE_INVALID", "任务包顶层字段必须为 format、origin、task、steps")
    from taskweave.core.validation import validate
    try:
        validate(package, TASK_PACKAGE_SCHEMA)
    except TaskError as exc:
        raise TaskError("TASK_PACKAGE_INVALID", str(exc)) from exc
    origin = package.get("origin")
    if origin not in ORIGINS or expected_origin is not None and origin != expected_origin:
        raise TaskError("TASK_PACKAGE_INVALID", "任务包来源无效")
    task = package.get("task")
    entries = package.get("steps")
    if (
        not isinstance(task, dict)
        or not isinstance(task.get("name"), str)
        or not task["name"].strip()
        or not isinstance(entries, list)
        or len(entries) > 1000
    ):
        raise TaskError("TASK_PACKAGE_INVALID", "任务名称或步骤列表无效")
    task_schema = task.get("input_schema", {"type": "object"})
    check_schema(task_schema)
    normalized = []
    preceding = set()
    diagnostics = []
    for index, entry in enumerate(entries):
        path = f"steps[{index}]"
        if (
            not isinstance(entry, dict)
            or set(entry) != {"key", "validation_state", "document"}
            or not isinstance(entry.get("key"), str)
            or not entry["key"]
            or entry["key"] in preceding
            or entry.get("validation_state") not in VALIDATION_STATES
            or not isinstance(entry.get("document"), dict)
        ):
            raise TaskError("TASK_PACKAGE_INVALID", f"{path} 的标识、状态或内容无效")
        if origin == "ai_generated" and entry["validation_state"] != "DRAFT":
            raise TaskError("TASK_PACKAGE_INVALID", f"{entry['key']}：AI 生成步骤只能为 DRAFT")
        try:
            document = normalize_step(json.loads(json.dumps(entry["document"])))
            check_bindings(document["bindings"], preceding)
            app.registry.check(document)
            must_be_complete = origin == "ai_generated" or entry["validation_state"] == "VALIDATED"
            if must_be_complete:
                asyncio.run(app.authoring.validate_step(document))
            else:
                try:
                    asyncio.run(app.authoring.validate_step(document))
                except TaskError as exc:
                    diagnostics.append({"step_key": entry["key"], "code": exc.code, "message": str(exc)})
        except TaskError as exc:
            raise TaskError("TASK_PACKAGE_INVALID", f"{entry.get('key', path)}：{exc}") from exc
        normalized.append({
            "key": entry["key"],
            "validation_state": entry["validation_state"],
            "document": document,
        })
        preceding.add(entry["key"])
    return {
        "format": FORMAT,
        "origin": origin,
        "task": {
            "name": task["name"].strip(),
            "description": task.get("description", ""),
            "input_schema": task_schema,
        },
        "steps": normalized,
        "diagnostics": diagnostics,
    }


def import_task(app, package):
    checked = validate_task_package(app, package)
    task = checked["task"]
    created = app.repo.create_task(task["name"], task["input_schema"], task["description"])
    try:
        mapping = {}
        saved_steps = []
        for entry in checked["steps"]:
            document = json.loads(json.dumps(entry["document"]))
            for binding in document["bindings"].values():
                ref = binding.get("ref", {})
                if ref.get("source") == "step":
                    ref["step_id"] = mapping[ref["step_id"]]
            saved = app.repo.save_step(created["task_id"], document)
            mapping[entry["key"]] = saved["step_id"]
            saved_steps.append((entry, saved))
        if checked["origin"] == "task_export":
            for entry, saved in saved_steps:
                if entry["validation_state"] == "VALIDATED":
                    app.repo.confirm_imported(saved["step_id"], saved["content_hash"])
    except Exception:
        app.repo.delete_task(created["task_id"])
        raise
    return created
