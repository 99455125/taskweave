"""Portable task configuration; no runtime state or environment configuration."""
import asyncio
import json
from taskweave.core.validation import TaskError, normalize_step, check_bindings, check_schema

FORMAT = 'taskweave-task-1'


def export_task(app, task_id):
    task = app.repo.task(task_id)
    steps = app.repo.steps(task_id)
    keys = {step['step_id']: f'step-{i+1}' for i, step in enumerate(steps)}
    documents = []
    for step in steps:
        document = normalize_step(step)
        for binding in document['bindings'].values():
            ref = binding.get('ref', {})
            if ref.get('source') == 'step': ref['step_id'] = keys[ref['step_id']]
        documents.append({'key': keys[step['step_id']], 'document': document})
    return {'format': FORMAT, 'task': {'name': task['name'], 'description': task['description'], 'input_schema': json.loads(task['input_schema_json'])}, 'steps': documents}


def import_task(app, package):
    if not isinstance(package, dict) or package.get('format') != FORMAT:
        raise TaskError('TASK_PACKAGE_INVALID', '需要 taskweave-task-1 任务 JSON')
    task = package.get('task'); entries = package.get('steps')
    if not isinstance(task, dict) or not isinstance(task.get('name'), str) or not task['name'].strip() or not isinstance(entries, list) or len(entries) > 1000:
        raise TaskError('TASK_PACKAGE_INVALID', '任务名称或步骤列表无效')
    schema = task.get('input_schema', {'type': 'object'})
    check_schema(schema)
    documents = []; preceding = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or entry['key'] in preceding or not isinstance(entry.get('document'), dict):
            raise TaskError('TASK_PACKAGE_INVALID', '步骤标识无效或重复')
        document = normalize_step(json.loads(json.dumps(entry['document'])))
        check_bindings(document['bindings'], preceding)
        app.registry.check(document)
        # Includes static source checks and plugin lint without executing a step.
        asyncio.run(app.authoring.validate_step(document))
        documents.append((entry['key'], document)); preceding.add(entry['key'])
    created = app.repo.create_task(task['name'].strip(), schema, task.get('description', ''))
    try:
        mapping = {}
        for key, document in documents:
            for binding in document['bindings'].values():
                ref = binding.get('ref', {})
                if ref.get('source') == 'step': ref['step_id'] = mapping[ref['step_id']]
            saved = app.repo.save_step(created['task_id'], document)
            mapping[key] = saved['step_id']
            app.confirm_step_manual(saved['step_id'], saved['content_hash'])
    except Exception:
        app.repo.delete_task(created['task_id'])
        raise
    return created
