"""Best-effort metadata redaction; business outputs are explicit user data."""

import os
import re

SENSITIVE = re.compile(
    r"password|passwd|secret|token|api.?key|authorization|cookie|credential|account|username",
    re.I,
)


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if SENSITIVE.search(k) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for name, secret in os.environ.items():
            if SENSITIVE.search(name) and len(secret) >= 4:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
        value = re.sub(
            r"(?i)((?:token|password|api[_-]?key|secret|username|account)\s*[=:]\s*)[^\s,;]+",
            r"\1[REDACTED]",
            value,
        )
        return value[:65536]
    return value
