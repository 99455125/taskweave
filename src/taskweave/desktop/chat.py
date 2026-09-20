"""Parse pasted web-chat replies without contacting a model."""
import ast
import json
import re
from taskweave.core.validation import TaskError


def _reply_document(text):
    """Find the first valid step document even when the web UI adds prose."""
    candidates = [match.group(1).strip() for match in re.finditer(
        r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE
    )]
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start, character in enumerate(candidate):
            if character != '{':
                continue
            try:
                value, _ = decoder.raw_decode(candidate[start:])
            except ValueError:
                continue
            if isinstance(value, dict) and isinstance(value.get('step_content'), str):
                return value
        # Some web chats emit JSON-shaped text but forget to escape the quotes
        # inside Python. Recover only the two-field envelope we explicitly asked
        # for; normal JSON remains handled above.
        start = re.search(r'\{\s*"step_content"\s*:\s*"', candidate)
        if not start:
            continue
        boundary = re.search(
            r'"\s*,\s*"explanation"\s*:\s*"', candidate[start.end():], re.DOTALL
        )
        if not boundary:
            continue
        source_end = start.end() + boundary.start()
        explanation_start = start.end() + boundary.end()
        closing = re.search(r'"\s*\}\s*$', candidate[explanation_start:], re.DOTALL)
        if not closing:
            continue

        def loose_json_string(value):
            escaped = []
            backslashes = 0
            for character in value:
                if character == '"' and backslashes % 2 == 0:
                    escaped.append('\\')
                escaped.append(character)
                backslashes = backslashes + 1 if character == '\\' else 0
            try:
                return json.loads('"' + ''.join(escaped) + '"')
            except (ValueError, TypeError):
                return value.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')

        return {
            'step_content': loose_json_string(candidate[start.end():source_end]),
            'explanation': loose_json_string(candidate[explanation_start:explanation_start + closing.start()]),
        }
    return None


def parse_chat_reply(text):
    text = text.strip()
    python_match = re.fullmatch(
        r'```(?:python|py)\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE
    )
    if text.startswith('async def run('):
        source, explanation = text, ''
    elif python_match:
        source, explanation = python_match.group(1).strip(), ''
    elif (value := _reply_document(text)) is not None:
        source = value['step_content'].strip()
        explanation = str(value.get('explanation', ''))
    else:
        source, explanation = text, ''
    if not source.startswith('async def run('):
        raise TaskError('CHAT_REPLY_INVALID', '请粘贴包含 step_content 的 JSON 或完整 async def run(ctx, inputs) 代码')
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise TaskError(
            'CHAT_REPLY_INVALID',
            f'step_content Python 语法错误（第 {exc.lineno or 1} 行）：{exc.msg}',
        ) from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.AsyncFunctionDef) or tree.body[0].name != 'run':
        raise TaskError('CHAT_REPLY_INVALID', 'step_content 必须只包含一个 async def run(ctx, inputs)')
    return source + '\n', explanation
