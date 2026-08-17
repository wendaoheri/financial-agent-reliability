"""Canonical hashing helpers for run identity and contract lineage.

Moved verbatim from ``contracts/run_trace_validator.py`` (helper layer of the
baseline-v1 frozen contract bundle, removed per PER-323 cleanup list v1).
These helpers are provider- and baseline-independent, so they live on in the
harness package; run-trace schema validation itself moves to the baseline-v2
contract generation (Stage 3, PER-328).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Mapping


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def build_run_id(identity: Mapping[str, Any]) -> str:
    return f"run_{content_sha256(identity)[:32]}"
