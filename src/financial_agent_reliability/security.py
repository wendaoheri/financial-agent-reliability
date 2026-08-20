"""Small persisted-secret scan gate for configs and traces.

Rules enforced here and reused by run configuration loading:

- key names of persisted JSON must not hit ``SECRET_KEYS`` (rule R1);
- persisted string values must not hit ``SECRET_TEXT`` (rule R2);
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Mapping
from typing import Any

SECRET_KEYS: frozenset[str] = frozenset(
    {"api_key", "authorization", "bearer_token", "password", "client_secret", "access_token"}
)

SECRET_TEXT = re.compile(
    r"(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})", re.I
)


def scan_persisted_value_for_secrets(value: Any, path: str = "$") -> list[str]:
    """Return JSON-pointer-style paths of secret-shaped keys or string values.

    Mapping keys are matched case-insensitively against ``SECRET_KEYS``;
    string values are searched for ``SECRET_TEXT``.
    """
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in SECRET_KEYS:
                findings.append(child_path)
            findings.extend(scan_persisted_value_for_secrets(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_persisted_value_for_secrets(child, f"{path}[{index}]"))
    elif isinstance(value, str) and SECRET_TEXT.search(value):
        findings.append(path)
    return findings


def scan_persisted_file(path: pathlib.Path) -> list[str]:
    """Scan one persisted JSON file; returns finding paths (empty = clean)."""
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return scan_persisted_value_for_secrets(payload)
