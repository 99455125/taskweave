"""Human-readable execution metadata; storage and business data stay unchanged."""
import json


def decode_inline_image(encoded, mime):
    """Reject damaged inline captures before the browser displays black pixels."""
    import base64
    import binascii

    if mime not in {'image/png', 'image/jpeg', 'image/webp'} or len(encoded) > 14 * 1024 * 1024:
        raise ValueError('图片格式不支持或超过 10MB')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('截图数据不完整，请重新采集上下文') from exc
    if len(data) > 10 * 1024 * 1024:
        raise ValueError('图片格式不支持或超过 10MB')
    if mime == 'image/png' and (not data.startswith(b'\x89PNG\r\n\x1a\n') or not data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82')):
        raise ValueError('截图数据不完整，请重新采集上下文')
    return data


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
