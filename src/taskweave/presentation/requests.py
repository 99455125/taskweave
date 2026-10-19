"""Candidate validation and compatibility export for retained application requests."""
from taskweave.application.authoring_sessions import AuthoringRequests
from taskweave.core.validation import TaskError


async def validate_candidate(call, request, is_current, current_code, trials):
    """Recheck saved version, editable code and current repair evidence."""
    if request is None:
        return
    if not is_current():
        raise TaskError('EDIT_CONFLICT', 'AI 请求或当前步骤已变化，请重新查看结果。')
    saved, params = request['saved'], request['params']
    latest = await call('step.get', step_id=saved['step_id'])
    if not is_current():
        raise TaskError('EDIT_CONFLICT')
    if latest['content_hash'] != saved['content_hash'] or current_code() != saved['step_content']:
        raise TaskError('EDIT_CONFLICT', '步骤已修改，上次 AI 结果不能采纳，请重新生成。')
    feedback = params.get('feedback') or {}
    if feedback.get('run_id'):
        run_id = feedback['run_id']
        run = await call('run.get', run_id=run_id)
        if not is_current():
            raise TaskError('EDIT_CONFLICT')
        failure = next((a for a in reversed(run.get('attempts', []))
                        if a.get('valid') and a.get('status') in {'FAILED', 'UNKNOWN'}), None)
        if (trials.get(saved['step_id']) != run_id or failure is None
                or failure.get('step_id') != saved['step_id']
                or failure.get('attempt_id') != feedback.get('attempt_id')):
            raise TaskError('VALIDATION_EVIDENCE_INVALID', '调试尝试已变化，请重新生成修复建议。')
