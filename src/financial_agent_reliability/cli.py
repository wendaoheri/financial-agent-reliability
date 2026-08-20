"""Single-command interface for the lightweight benchmark MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from financial_agent_reliability.adapters.core import BailianLiveAdapter
from financial_agent_reliability.compare import compare_traces
from financial_agent_reliability.models import (
    BenchInputError,
    audit_taskset,
    load_candidates,
    load_tasks,
)
from financial_agent_reliability.runner import run_matrix, version_coordinates
from financial_agent_reliability.security import scan_persisted_value_for_secrets
from financial_agent_reliability.trace import append_traces, read_traces


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Offline-first model × agent benchmark runner.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate tasks and run config")
    validate.add_argument("--tasks", type=pathlib.Path, required=True, help="task JSONL file")
    validate.add_argument("--config", type=pathlib.Path, required=True, help="run config JSON file")

    preflight = subparsers.add_parser(
        "preflight", help="run exact-identity checks for approved live candidates"
    )
    preflight.add_argument("--config", type=pathlib.Path, required=True)
    preflight.add_argument("--output", type=pathlib.Path, required=True)

    run = subparsers.add_parser("run", help="run a gated matrix and append JSONL traces")
    run.add_argument("--tasks", type=pathlib.Path, required=True, help="task JSONL file")
    run.add_argument("--config", type=pathlib.Path, required=True, help="run config JSON file")
    run.add_argument("--output", type=pathlib.Path, required=True, help="append-only trace JSONL")
    run.add_argument("--run-id", default=None, help="optional stable run identifier")
    run.add_argument("--slice", action="append", dest="slices", help="run only this task slice")
    run.add_argument("--variant", action="append", dest="variants", help="run only this variant")
    run.add_argument(
        "--candidate", action="append", dest="candidate_ids", help="run only this candidate id"
    )
    run.add_argument(
        "--preflight",
        type=pathlib.Path,
        help="required passed preflight report for bailian-live candidates",
    )

    compare = subparsers.add_parser("compare", help="compare candidates from trace JSONL")
    compare.add_argument(
        "traces", type=pathlib.Path, nargs="+", help="one or more trace JSONL files"
    )
    compare.add_argument(
        "--output", type=pathlib.Path, default=None, help="optional report JSON path"
    )
    return parser


def _render(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_safe_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    findings = scan_persisted_value_for_secrets(value)
    if findings:
        raise ValueError("preflight rejected by persisted-secret gate: " + ", ".join(findings))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(value), encoding="utf-8")


def _live_preflight(candidates: list[Any], config_path: pathlib.Path) -> dict[str, Any]:
    if not candidates or any(candidate.adapter != "bailian-live" for candidate in candidates):
        raise BenchInputError("preflight requires only bailian-live candidates")
    if len(candidates) > 4:
        raise BenchInputError("live preflight request budget exceeded: maximum is 4")
    adapter = BailianLiveAdapter(pathlib.Path.cwd())
    rows = [adapter.preflight(candidate) for candidate in candidates]
    config_hashes = sorted({row["config_sha256"] for row in rows})
    config_hash = _sha256(config_path)
    if config_hashes != [config_hash]:
        raise BenchInputError("live candidates must share one run config")
    passed = all(row["status"] == "passed" for row in rows)
    return {
        "schema_version": "0.1.0",
        "status": "passed" if passed else "blocked",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "config_sha256": config_hash,
        "models": rows,
        "request_budget": {"maximum": 4, "attempted": len(rows)},
    }


def _bind_live_preflight(
    path: pathlib.Path, candidates: list[Any], versions: dict[str, Any]
) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("status") != "passed":
        raise BenchInputError("bailian-live run requires a passed preflight report")
    if report.get("config_sha256") != versions["config_sha256"]:
        raise BenchInputError("preflight candidate hash does not match the run")
    rows = report.get("models") or []
    expected_models = {candidate.model for candidate in candidates}
    passed_models = {
        row.get("model")
        for row in rows
        if isinstance(row, dict)
        and row.get("status") == "passed"
        and (row.get("identity") or {}).get("exact_match") is True
    }
    if passed_models != expected_models:
        raise BenchInputError("preflight exact-identity models do not match the run")
    versions["config_sha256"] = str(report["config_sha256"])
    versions["preflight_sha256"] = _sha256(path)


T = TypeVar("T")


def _filtered(
    values: list[T], selected: list[str] | None, key: Callable[[T], Any], label: str
) -> list[T]:
    if not selected:
        return values
    wanted = set(selected)
    result = [value for value in values if key(value) in wanted]
    if not result:
        raise BenchInputError(
            f"{label} filter matched no runnable cells: {', '.join(sorted(wanted))}"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {"validate", "preflight", "run"}:
            if args.command != "preflight":
                tasks = load_tasks(args.tasks)
            candidates = load_candidates(args.config)
        if args.command == "validate":
            audit = audit_taskset(args.tasks)
            failed = [name for name, result in audit["checks"].items() if not result["passed"]]
            if failed:
                raise BenchInputError(f"task-set audit failed: {', '.join(failed)}")
            print(
                _render(
                    {
                        "status": "valid",
                        "tasks": len(tasks),
                        "candidates": len(candidates),
                        "audit": audit,
                    }
                ),
                end="",
            )
            return 0
        if args.command == "preflight":
            report = _live_preflight(candidates, args.config)
            _write_safe_json(args.output, report)
            print(_render({**report, "output": str(args.output)}), end="")
            return 0 if report["status"] == "passed" else 2
        if args.command == "run":
            tasks = _filtered(
                tasks, args.slices, lambda task: task.get("task_card", {}).get("slice"), "slice"
            )
            tasks = _filtered(
                tasks,
                args.variants,
                lambda task: task.get("task_card", {}).get("variant"),
                "variant",
            )
            candidates = _filtered(
                candidates, args.candidate_ids, lambda candidate: candidate.id, "candidate"
            )
            adapters = {candidate.adapter for candidate in candidates}
            if len(adapters) != 1:
                raise BenchInputError("one run cannot mix mock and live adapters")
            versions = version_coordinates(
                repository_root=pathlib.Path.cwd(),
                tasks_path=args.tasks,
                config_path=args.config,
            )
            if adapters == {"bailian-live"}:
                if args.preflight is None:
                    raise BenchInputError("bailian-live run requires --preflight")
                if len(tasks) * len(candidates) > 64:
                    raise BenchInputError("live matrix request budget exceeded: maximum is 64")
                _bind_live_preflight(args.preflight, candidates, versions)
            traces = run_matrix(
                tasks,
                candidates,
                repository_root=pathlib.Path.cwd(),
                run_id=args.run_id,
                versions=versions,
            )
            written = append_traces(args.output, traces)
            failed = sum(trace["failure_signature"] is not None for trace in traces)
            print(
                _render(
                    {
                        "status": "completed" if not failed else "completed_with_failures",
                        "traces_written": written,
                        "failed_cells": failed,
                        "output": str(args.output),
                    }
                ),
                end="",
            )
            return 0 if not failed else 1
        if args.command == "compare":
            report = compare_traces(read_traces(args.traces))
            rendered = _render(report)
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered, encoding="utf-8")
            print(rendered, end="")
            return 0
    except (BenchInputError, OSError, ValueError) as exc:
        print(_render({"status": "error", "error": str(exc)}), end="", file=sys.stderr)
        return 2
    return 2
