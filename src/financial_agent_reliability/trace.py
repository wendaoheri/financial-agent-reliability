"""Trace serialization and schema validation."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable, Iterator
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from financial_agent_reliability.security import (
    scan_persisted_value_for_secrets,
)

CURRENT_TRACE_VERSION = "0.5.0"


def trace_validator(version: str = CURRENT_TRACE_VERSION) -> Draft202012Validator:
    if version != CURRENT_TRACE_VERSION:
        raise ValueError(f"unsupported trace schema_version: {version}")
    path = resources.files("financial_agent_reliability.schemas").joinpath("trace.schema.json")
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_trace(trace: dict[str, Any]) -> None:
    trace_validator(str(trace.get("schema_version"))).validate(trace)


def read_traces(paths: Iterable[pathlib.Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                trace = json.loads(raw)
                validate_trace(trace)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                if isinstance(exc, json.JSONDecodeError):
                    detail = exc.msg
                else:
                    detail = str(exc)
                raise ValueError(f"{path}:{line_number}: invalid trace: {detail}") from exc
            yield trace


def append_traces(path: pathlib.Path, traces: Iterable[dict[str, Any]]) -> int:
    rendered: list[str] = []
    for trace in traces:
        validate_trace(trace)
        findings = scan_persisted_value_for_secrets(trace)
        if findings:
            raise ValueError("trace rejected by persisted-secret gate: " + ", ".join(findings))
        rendered.append(
            json.dumps(trace, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for line in rendered:
            handle.write(line + "\n")
    return len(rendered)
