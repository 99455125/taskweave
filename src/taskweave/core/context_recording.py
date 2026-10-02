"""Optional recording wire validation; no browser, UI or storage dependency."""
import json
from taskweave.core.ports import ContextRecordingBatch, ContextRecordingCommand
from taskweave.core.context_collection import serialize_context_collection
from taskweave.core.validation import TaskError

OPERATIONS = {'start', 'pause', 'resume', 'stop', 'read', 'ack', 'discard'}
STATES = {'RECORDING', 'PAUSED', 'STOPPED', 'DISCARDED'}
MAX_BATCH_BYTES = 2 * 1024 * 1024


def _counter(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 128 and value == value.strip()


def recording_command(operation, *, recording_id=None, after=0, through=None, limit=100):
    if not isinstance(operation, str) or operation not in OPERATIONS or not _counter(after) or type(limit) is not int or not 1 <= limit <= 100:
        raise TaskError('CONTEXT_RECORDING_REQUEST_INVALID', '录制命令或读取范围无效')
    if operation == 'start':
        valid_id = recording_id is None
    else:
        valid_id = _identifier(recording_id)
    if not valid_id or (operation == 'ack' and not _counter(through)) or (operation != 'ack' and through is not None):
        raise TaskError('CONTEXT_RECORDING_REQUEST_INVALID', '录制身份或确认游标无效')
    if operation != 'read' and after != 0:
        raise TaskError('CONTEXT_RECORDING_REQUEST_INVALID', 'after 仅用于读取')
    return ContextRecordingCommand(operation, recording_id, after, through, limit)


def serialize_recording_batch(batch, renderers):
    if (not isinstance(batch, ContextRecordingBatch) or not _identifier(batch.recording_id)
            or not isinstance(batch.state, str) or batch.state not in STATES or not _counter(batch.cursor)
            or not _counter(batch.available_after) or batch.available_after > batch.cursor
            or not _counter(batch.dropped_count) or type(batch.has_more) is not bool):
        raise TaskError('CONTEXT_RECORDING_RESULT_INVALID', '插件录制结果或游标无效')
    capture = serialize_context_collection(batch.collection, renderers)
    if len(capture['items']) > 200 or len(capture['views']) > 100:
        raise TaskError('CONTEXT_RECORDING_RESULT_INVALID', '录制证据批次超过数量限制')
    result = {'recording_id':batch.recording_id, 'state':batch.state, 'cursor':batch.cursor,
              'available_after':batch.available_after, 'dropped_count':batch.dropped_count,
              'has_more':batch.has_more, 'capture':capture}
    try:
        size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (TypeError, ValueError):
        raise TaskError('CONTEXT_RECORDING_RESULT_INVALID', '录制结果必须是有限 JSON') from None
    if size > MAX_BATCH_BYTES:
        raise TaskError('CONTEXT_RECORDING_RESULT_INVALID', '录制证据批次超过 2MB，请缩小批次或关闭预览')
    return result
