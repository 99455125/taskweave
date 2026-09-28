"""Portable task configuration; no runtime state or environment configuration."""

import asyncio
import json

from taskweave.core.task_package import FORMAT, ORIGINS, VALIDATION_STATES, TASK_PACKAGE_SCHEMA
from taskweave.core.validation import (
    TaskError, check_bindings, check_schema, normalize_step,
)


def export_task(tasks, steps_repository, step_contexts, task_id):
    task = tasks.task(task_id)
    steps = steps_repository.steps(task_id)
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
    context_groups = []
    for step in steps:
        for group in step_contexts.list_step_contexts(step['step_id']):
            context_groups.append({
                'step_key': keys[step['step_id']], 'provider_id': group['provider_id'],
                'name': group['name'], 'context_notes': group.get('context_notes',''),
                'order_index': group['order_index'],
                'captures': [{key: capture[key] for key in ('label','request','items','views','include_view','captured_at','source_page','operation_notes','send_preview')}
                             for item in group['captures']
                             for capture in [step_contexts.get_step_context_capture(group['context_id'], item['capture_id'])]],
            })
    result = {
        "format": FORMAT,
        "origin": "task_export",
        "task": {
            "name": task["name"],
            "description": task["description"],
            "input_schema": json.loads(task["input_schema_json"]),
        },
        "steps": entries,
        "contexts": context_groups,
    }
    return result


def validate_task_package(registry, authoring, package, *, expected_origin=None):
    """Validate and normalize a package without writing or executing anything."""
    if not isinstance(package, dict) or package.get("format") != FORMAT:
        if isinstance(package, dict) and package.get("format") == "taskweave-task-1":
            raise TaskError("TASK_PACKAGE_INVALID", "旧任务包不再兼容，请使用当前版本重新导出")
        raise TaskError("TASK_PACKAGE_INVALID", f"需要 {FORMAT} 任务 JSON")
    if set(package) not in ({"format", "origin", "task", "steps"}, {"format", "origin", "task", "steps", "contexts"}):
        raise TaskError("TASK_PACKAGE_INVALID", "任务包顶层字段无效")
    if package.get('contexts') and package.get('origin') != 'task_export':
        raise TaskError('TASK_PACKAGE_INVALID', '只有任务导出包可以包含上下文组')
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
            registry.check(document)
            must_be_complete = origin == "ai_generated" or entry["validation_state"] == "VALIDATED"
            if origin == "ai_generated" and document["step_content"] == "":
                pass  # An AI planning draft may defer code until the user collects more evidence.
            elif must_be_complete:
                asyncio.run(authoring.validate_step(document))
            else:
                try:
                    asyncio.run(authoring.validate_step(document))
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
    normalized_contexts=[]
    for index, group in enumerate(package.get('contexts', [])):
        if not isinstance(group,dict) or set(group)!={'step_key','provider_id','name','context_notes','order_index','captures'} or group['step_key'] not in preceding or not isinstance(group['captures'],list):
            raise TaskError('TASK_PACKAGE_INVALID',f'contexts[{index}] 结构无效')
        if not isinstance(group['name'],str) or not group['name'].strip() or not isinstance(group['context_notes'],str) or not isinstance(group['order_index'],int):
            raise TaskError('TASK_PACKAGE_INVALID',f'contexts[{index}] 元数据无效')
        captures=[]
        for position,capture in enumerate(group['captures']):
            if not isinstance(capture,dict) or not {'request','items','views','include_view','captured_at','source_page'} <= set(capture) or not isinstance(capture['items'],list) or not isinstance(capture['views'],list):
                raise TaskError('TASK_PACKAGE_INVALID',f'contexts[{index}].captures[{position}] 无效')
            captures.append({key:capture[key] for key in ('label','request','items','views','include_view','captured_at','source_page','operation_notes','send_preview') if key in capture})
        normalized_contexts.append({**group,'captures':captures})
    result = {
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
    if 'contexts' in package:
        result['contexts'] = normalized_contexts
    return result


def import_task(tasks, steps_repository, step_contexts, uow, registry, authoring, package):
    checked = validate_task_package(registry, authoring, package)
    task = checked["task"]
    with uow.transaction():
        created = tasks.create_task(task["name"], task["input_schema"], task["description"])
        try:
            mapping = {}
            saved_steps = []
            for entry in checked["steps"]:
                document = json.loads(json.dumps(entry["document"]))
                for binding in document["bindings"].values():
                    ref = binding.get("ref", {})
                    if ref.get("source") == "step":
                        ref["step_id"] = mapping[ref["step_id"]]
                saved = steps_repository.save_step(created["task_id"], document)
                mapping[entry["key"]] = saved["step_id"]
                saved_steps.append((entry, saved))
            step_ids={entry['key']:saved['step_id'] for entry,saved in saved_steps}
            for group in checked.get('contexts',[]):
                target_step=step_ids[group['step_key']]
                saved_group=step_contexts.create_step_context_group(target_step,group['provider_id'],group['name'],group['context_notes'])
                for capture in group['captures']:
                    step_contexts.append_step_context_capture(saved_group['context_id'],capture,request=capture['request'],include_view=capture['include_view'],source_page=capture['source_page'],label=capture.get('label',''),captured_at=capture['captured_at'])
            if checked["origin"] == "task_export":
                for entry, saved in saved_steps:
                    if entry["validation_state"] == "VALIDATED":
                        steps_repository.confirm_imported(saved["step_id"], saved["content_hash"])
        except Exception:
            tasks.delete_task(created["task_id"])
            raise
    return created
