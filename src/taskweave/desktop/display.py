"""Human-readable execution metadata; storage and business data stay unchanged."""
import json


def step_names(run, fallback=()):
    definition = json.loads(run.get('definition_json') or '{}')
    return {step['step_id']: f"{index}. {step.get('name') or '未命名步骤'}"
            for index, step in enumerate(definition.get('steps', fallback), 1)}


def execution_title(run):
    kind = '调试' if run.get('mode') == 'TRIAL' else '执行'
    return kind + ' · ' + (run.get('started_at') or '未开始')


def readable_metadata(value, names):
    """Format infrastructure records only, preserving embedded business values."""
    if isinstance(value, list):
        return [readable_metadata(item, names) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {'event_id', 'attempt_id', 'run_id', 'task_id', 'result_id', 'command_id',
                   'content_hash', 'definition_hash', 'execution_path'}:
            continue
        if key == 'step_id':
            result['步骤'] = names.get(item, '未知步骤')
        elif key == 'payload_json':
            try:
                result['内容'] = readable_metadata(json.loads(item), names)
            except (TypeError, ValueError):
                result['内容'] = item
        elif key in {'data', 'inputs', 'outputs', 'inputs_json', 'output_json', 'input_summary_json', 'step_content'}:
            result[key] = item
        else:
            result[key] = readable_metadata(item, names)
    return result


def image_reference(payload, stored):
    """Resolve references only among this attempt's authorized file results."""
    if isinstance(payload, dict):
        if 'image_base64' in payload:
            return payload
        reference = payload.get('output') or payload.get('result_id')
        if reference is None and payload.get('capture'):
            reference = 'capture' if 'capture' in stored else payload['capture']
    else:
        reference = payload
    if not isinstance(reference, str):
        raise ValueError('截图需要保存的图片引用或 image_base64')
    for name, value in stored.items():
        if (name == reference or value.get('result_id') == reference) and value.get('path') and value.get('media_type', '').startswith('image/'):
            return {'output': name}
    # Older screenshot data contains a staging UUID, not the persisted result ID.
    import uuid
    try:
        uuid.UUID(reference)
    except ValueError:
        raise ValueError('未找到本次步骤保存的图片：' + reference) from None
    images = [name for name, value in stored.items() if value.get('path') and value.get('media_type', '').startswith('image/')]
    if len(images) == 1:
        return {'output': images[0]}
    raise ValueError('图片引用无法唯一匹配；请使用 {output: 文件结果名称}，并保存截图输出')

