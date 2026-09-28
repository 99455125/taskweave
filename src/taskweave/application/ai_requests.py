"""Shared AI request-size settings and UTF-8 accounting."""

import json
from pathlib import Path

from taskweave.core.validation import TaskError

DEFAULT_AI_REQUEST_LIMIT_KIB = 2048
MAX_AI_REQUEST_LIMIT_KIB = 4096


class AISettings:
    def __init__(self, home):
        self.path = Path(home) / "workbench.json"

    def _all(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self):
        value = self._all().get("ai_request_limit_kib", DEFAULT_AI_REQUEST_LIMIT_KIB)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_AI_REQUEST_LIMIT_KIB:
            value = DEFAULT_AI_REQUEST_LIMIT_KIB
        return {"ai_request_limit_kib": value, "request_limit_bytes": value * 1024}

    def update(self, ai_request_limit_kib):
        if isinstance(ai_request_limit_kib, bool) or not isinstance(ai_request_limit_kib, int) or not 1 <= ai_request_limit_kib <= MAX_AI_REQUEST_LIMIT_KIB:
            raise TaskError("FORM_INVALID", "AI 请求大小上限必须是 1–4096 的整数 KB")
        value = self._all(); value["ai_request_limit_kib"] = ai_request_limit_kib
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get()


def utf8_size(value):
    return len(value.encode("utf-8") if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def ensure_limit(actual_bytes, limit_bytes, breakdown=None):
    if actual_bytes > limit_bytes:
        raise TaskError("CONTEXT_TOO_LARGE", f"AI 请求 {actual_bytes} 字节，超过上限 {limit_bytes} 字节；请提高设置或主动删除上下文。")


def preview_messages(messages):
    """Return text messages plus selected images, bound to their capture labels."""
    import json
    result, attachments = [], []
    def project(value, context=""):
        if isinstance(value, list):
            return [project(item, context) for item in value]
        if not isinstance(value, dict):
            return value
        context = value.get("label") or value.get("name") or context
        output = {}
        for key, items in value.items():
            if key == "preview_items" and isinstance(items, list):
                output[key] = []
                for item in items:
                    if item.get("kind") == "image":
                        filename = f"context-preview-{len(attachments)+1}." + {"image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(item.get("mime_type"), "png")
                        attachments.append({"name": filename, "title": context + " · " + item.get("title", "预览"),
                                            "mime_type": item.get("mime_type", "image/png"), "data": item["content"]})
                        output[key].append({"kind": "image", "attachment": filename, "title": item.get("title")})
                    else:
                        output[key].append(item)
            else:
                output[key] = project(items, context)
        return output
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            try:
                value = json.loads(content)
            except (ValueError, TypeError):
                value = None
            if isinstance(value, (dict, list)):
                content = json.dumps(project(value), ensure_ascii=False)
        result.append({**message, "content": content})
    return result, attachments


def web_chat_export(messages):
    import json
    clean, attachments = preview_messages(messages)
    text = "\n\n".join(m["role"] + ":\n" + (m.get("content") or "") for m in clean)
    if attachments:
        text += "\n\n请同时上传以下图片附件（文件名对应采集项预览）：\n" + "\n".join(
            f'{item["name"]}：{item["title"]}' for item in attachments)
    return text, attachments
