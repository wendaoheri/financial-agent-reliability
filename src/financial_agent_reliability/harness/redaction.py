"""Central recursive redaction used before any persistent logging."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REDACTED = "[REDACTED]"
_SECRET_FIELDS = {
    "authorization",
    "proxy-authorization",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "set-cookie",
    "x-api-key",
}
_VALUE_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"),
    re.compile(r"(?i)BENCH_BAILIAN_API_KEY\s*[=:]\s*[^\s]+"),
)


def _redact_string(value: str) -> str:
    result = value
    for pattern in _VALUE_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact(value: Any) -> Any:
    """Return a JSON-compatible copy with secret fields and values removed."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if str(key).lower() in _SECRET_FIELDS else redact(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(child) for child in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value
