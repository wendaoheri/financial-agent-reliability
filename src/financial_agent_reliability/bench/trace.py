"""Trace serialization and schema validation."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable, Iterator
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from financial_agent_reliability.harness.secret_scan import (
    scan_persisted_value_for_secrets,
)


SCHEMA_DIR = pathlib.Path(__file__).parent / "contracts"
CURRENT_TRACE_VERSION = "0.4.0"
SCHEMA_PATHS = {
    "0.1.0": SCHEMA_DIR / "trace.schema.v0.1.json",
    "0.2.0": SCHEMA_DIR / "trace.schema.v0.2.json",
    "0.3.0": SCHEMA_DIR / "trace.schema.v0.3.json",
    CURRENT_TRACE_VERSION: SCHEMA_DIR / "trace.schema.v0.4.json",
}


def trace_validator(version: str = CURRENT_TRACE_VERSION) -> Draft202012Validator:
    try:
        path = SCHEMA_PATHS[version]
    except KeyError as exc:
        raise ValueError(f"unsupported trace schema_version: {version}") from exc
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
            raise ValueError(
                "trace rejected by persisted-secret gate: " + ", ".join(findings)
            )
        rendered.append(json.dumps(trace, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for line in rendered:
            handle.write(line + "\n")
    return len(rendered)
