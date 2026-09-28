"""Best-effort metadata redaction; business outputs are explicit user data."""

import os
import re
import json
from pathlib import Path


class PrivacySettings:
    """Presentation and AI redaction preferences; captured evidence stays raw."""

    KEYS = ("redact_on_display", "redact_for_ai")

    def __init__(self, home):
        self.path = Path(home) / "workbench.json"

    def get(self):
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        return {key: stored.get(key) if isinstance(stored.get(key), bool) else True for key in self.KEYS}

    def update(self, *, redact_on_display, redact_for_ai):
        if not isinstance(redact_on_display, bool) or not isinstance(redact_for_ai, bool):
            raise ValueError("脱敏设置必须是布尔值")
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        stored.update(redact_on_display=redact_on_display, redact_for_ai=redact_for_ai)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return self.get()

SENSITIVE = re.compile(
    r"password|passwd|secret|token|api.?key|authorization|cookie|credential|account|username",
    re.I,
)


def redact(value, max_string_length=65536):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if SENSITIVE.search(k) else redact(v, max_string_length)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, max_string_length) for v in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except ValueError:
                pass
            else:
                if isinstance(parsed, (dict, list)):
                    cleaned = json.dumps(redact(parsed, None), ensure_ascii=False)
                    return cleaned if max_string_length is None else cleaned[:max_string_length]
        for name, secret in os.environ.items():
            if SENSITIVE.search(name) and len(secret) >= 4:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
        value = re.sub(
            r"(?i)((?:token|password|api[_-]?key|secret|username|account)\s*[=:]\s*)[^\s,;]+",
            r"\1[REDACTED]",
            value,
        )
        return value if max_string_length is None else value[:max_string_length]
    return value


def redact_collected_context(capture, renderers):
    """Redact textual evidence without cutting opaque image bytes in previews."""
    views = []
    for view in capture.get("views", []):
        data = view.get("data")
        renderer = renderers.get(view.get("renderer"), {})
        if renderer.get("type") == "image" and isinstance(data, dict) and isinstance(data.get("image_base64"), str):
            cleaned = redact({key: value for key, value in data.items() if key != "image_base64"}, None)
            cleaned["image_base64"] = data["image_base64"]
            views.append({**redact({key: value for key, value in view.items() if key != "data"}, None), "data": cleaned})
        else:
            views.append(redact(view, None))
    return {"items": redact(capture.get("items", []), None), "views": views}


def redact_ai_payload(value):
    """Keep opted-in image bytes opaque while redacting all textual AI evidence."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return redact(value, None)
        if isinstance(decoded, (dict, list)):
            return json.dumps(redact_ai_payload(decoded), ensure_ascii=False)
        return redact(value, None)
    if isinstance(value, list):
        return [redact_ai_payload(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if SENSITIVE.search(key):
                result[key] = "[REDACTED]"
            elif key == "preview_items" and isinstance(child, list):
                result[key] = [
                    {**redact_ai_payload({k: v for k, v in item.items() if k != "content"}), "content": item.get("content")}
                    if isinstance(item, dict) and item.get("kind") == "image" else redact_ai_payload(item)
                    for item in child
                ]
            else:
                result[key] = redact_ai_payload(child)
        return result
    return value
