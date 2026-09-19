"""Parse pasted web-chat replies without contacting a model."""
import json
import re
from taskweave.core.validation import TaskError


def parse_chat_reply(text):
    text = text.strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json|python|py)?\s*\n(.*?)\n```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, dict) and isinstance(value.get('step_content'), str):
        source = value['step_content'].strip()
        explanation = str(value.get('explanation', ''))
    else:
        source, explanation = text, ''
    if not source.startswith('async def run('):
        raise TaskError('CHAT_REPLY_INVALID', '请粘贴包含 step_content 的 JSON 或完整 async def run(ctx, inputs) 代码')
    return source + '\n', explanation
