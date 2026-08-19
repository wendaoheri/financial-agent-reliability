"""Single-command interface for the lightweight benchmark MVP."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from financial_agent_reliability.bench.compare import compare_traces
from financial_agent_reliability.bench.model import (
    BenchInputError,
    audit_taskset,
    load_candidates,
    load_tasks,
)
from financial_agent_reliability.bench.runner import run_mock_matrix, version_coordinates
from financial_agent_reliability.bench.trace import append_traces, read_traces


ROOT = pathlib.Path(__file__).resolve().parents[3]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Offline-first model × agent benchmark runner.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate tasks and candidate config")
    validate.add_argument("--tasks", type=pathlib.Path, required=True, help="task JSONL file")
    validate.add_argument("--candidates", type=pathlib.Path, required=True, help="candidate JSON file")

    run = subparsers.add_parser("run", help="run the offline mock matrix and append JSONL traces")
    run.add_argument("--tasks", type=pathlib.Path, required=True, help="task JSONL file")
    run.add_argument("--candidates", type=pathlib.Path, required=True, help="candidate JSON file")
    run.add_argument("--output", type=pathlib.Path, required=True, help="append-only trace JSONL")
    run.add_argument("--run-id", default=None, help="optional stable run identifier")
    run.add_argument("--slice", action="append", dest="slices", help="run only this task slice")
    run.add_argument("--variant", action="append", dest="variants", help="run only this variant")
    run.add_argument("--candidate", action="append", dest="candidate_ids", help="run only this candidate id")

    compare = subparsers.add_parser("compare", help="compare candidates from trace JSONL")
    compare.add_argument("traces", type=pathlib.Path, nargs="+", help="one or more trace JSONL files")
    compare.add_argument("--output", type=pathlib.Path, default=None, help="optional report JSON path")
    return parser


def _render(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


T = TypeVar("T")


def _filtered(
    values: list[T], selected: list[str] | None, key: Callable[[T], Any], label: str
) -> list[T]:
    if not selected:
        return values
    wanted = set(selected)
    result = [value for value in values if key(value) in wanted]
    if not result:
        raise BenchInputError(f"{label} filter matched no runnable cells: {', '.join(sorted(wanted))}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in {"validate", "run"}:
            tasks = load_tasks(args.tasks)
            candidates = load_candidates(args.candidates)
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
        if args.command == "run":
            tasks = _filtered(tasks, args.slices, lambda task: task.get("task_card", {}).get("slice"), "slice")
            tasks = _filtered(tasks, args.variants, lambda task: task.get("task_card", {}).get("variant"), "variant")
            candidates = _filtered(candidates, args.candidate_ids, lambda candidate: candidate.id, "candidate")
            traces = run_mock_matrix(
                tasks,
                candidates,
                repository_root=ROOT,
                run_id=args.run_id,
                versions=version_coordinates(
                    repository_root=ROOT,
                    tasks_path=args.tasks,
                    candidates_path=args.candidates,
                ),
            )
            written = append_traces(args.output, traces)
            failed = sum(
                trace["failure_signature"] is not None
                for trace in traces
            )
            print(_render({"status": "completed" if not failed else "completed_with_failures", "traces_written": written, "failed_cells": failed, "output": str(args.output)}), end="")
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
