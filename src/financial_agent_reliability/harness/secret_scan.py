"""Persisted-secret scan gate (contract C4, PER-323 Stage 2).

Rebuilds the scan gate previously frozen at
``contracts/run_trace_validator_v3_7.py`` (removed with the baseline-v1
frozen directories). ``SECRET_KEYS`` and ``SECRET_TEXT`` are inherited
verbatim from that file (F8); the pattern set may only grow, never shrink.

Rules enforced here and reused by ``inference_config``:

- key names of persisted JSON must not hit ``SECRET_KEYS`` (rule R1);
- persisted string values must not hit ``SECRET_TEXT`` (rule R2);
- credential environment-variable NAMES declared in configuration must not
  contain secret-shaped substrings (``bearer`` / ``sk-`` / ``akid``,
  case-insensitive) so that the scan gate cannot be baited into false
  positives or bypasses (design contract §4.3 R2).
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Mapping

#: F8 (contracts/run_trace_validator_v3_7.py:22) — verbatim.
SECRET_KEYS: frozenset[str] = frozenset(
    {"api_key", "authorization", "bearer_token", "password", "client_secret", "access_token"}
)

#: F8 (contracts/run_trace_validator_v3_7.py:21) — verbatim.
SECRET_TEXT = re.compile(
    r"(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})", re.I
)

#: Design contract §4.3 R2: forbidden substrings inside credential_env names.
CREDENTIAL_ENV_FORBIDDEN = re.compile(r"(?i)(bearer|sk-|akid)")


def scan_persisted_value_for_secrets(value: Any, path: str = "$") -> list[str]:
    """Return JSON-pointer-style paths of secret-shaped keys or string values.

    Verbatim semantics of the frozen gate: mapping keys are matched
    case-insensitively against ``SECRET_KEYS``; string values are searched
    for ``SECRET_TEXT``. Both the key location and its subtree are reported.
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


def check_credential_env_name(name: str, path: str = "$") -> list[str]:
    """Return findings when a credential environment-variable name is secret-shaped."""
    if CREDENTIAL_ENV_FORBIDDEN.search(name):
        return [path]
    return []


def scan_persisted_file(path: pathlib.Path) -> list[str]:
    """Scan one persisted JSON file; returns finding paths (empty = clean)."""
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return scan_persisted_value_for_secrets(payload)
