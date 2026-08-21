"""Single-command interface for the lightweight benchmark MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from financial_agent_reliability.adapters.core import BailianLiveAdapter
from financial_agent_reliability.adapters.generation import resolve_generation
from financial_agent_reliability.adapters.pi import PiAgentLiveAdapter
from financial_agent_reliability.compare import compare_traces
from financial_agent_reliability.config import load_run_config
from financial_agent_reliability.eval_pack import (
    aggregate_eval_bundles,
    analyze_eval_migration,
    load_report_cases,
    replay_eval_pack,
    run_eval_pack,
    validate_eval_pack,
)
from financial_agent_reliability.long_horizon import (
    aggregate_soak,
    run_long_horizon,
)
from financial_agent_reliability.models import (
    BenchInputError,
    audit_taskset,
    load_candidates,
    load_tasks,
)
from financial_agent_reliability.qualification import (
    QualificationError,
    replay_qualification,
    run_qualification,
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

    plan = subparsers.add_parser(
        "plan-live", help="calculate a no-network request and token ceiling"
    )
    plan.add_argument("--tasks", type=pathlib.Path, required=True)
    plan.add_argument("--config", type=pathlib.Path, required=True)
    plan.add_argument("--slice", action="append", dest="slices")
    plan.add_argument("--variant", action="append", dest="variants")
    plan.add_argument("--candidate", action="append", dest="candidate_ids")
    plan.add_argument("--case-id", action="append", dest="case_ids")
    plan.add_argument("--output", type=pathlib.Path, default=None)
    plan.add_argument(
        "--live-stage",
        choices=("smoke", "calibration", "baseline", "supplemental"),
        default=None,
    )

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

    qualify = subparsers.add_parser(
        "qualify", help="run the offline framework qualification mutation matrix"
    )
    qualify.add_argument("--tasks", type=pathlib.Path, required=True)
    qualify.add_argument("--config", type=pathlib.Path, required=True)
    qualify.add_argument("--output-dir", type=pathlib.Path, required=True)
    qualify.add_argument("--run-id", required=True)
    qualify.add_argument("--slice", action="append", dest="slices")
    qualify.add_argument("--variant", action="append", dest="variants")

    replay = subparsers.add_parser(
        "qualify-replay", help="verify and deterministically regrade a qualification bundle"
    )
    replay.add_argument("--tasks", type=pathlib.Path, required=True)
    replay.add_argument("--config", type=pathlib.Path, required=True)
    replay.add_argument("--bundle", type=pathlib.Path, required=True)
    replay.add_argument("--slice", action="append", dest="slices")
    replay.add_argument("--variant", action="append", dest="variants")

    eval_validate = subparsers.add_parser(
        "eval-validate", help="validate a frozen differential evaluation pack"
    )
    eval_validate.add_argument("--pack", type=pathlib.Path, required=True)
    eval_validate.add_argument("--config", type=pathlib.Path, default=None)

    eval_run = subparsers.add_parser(
        "eval-run", help="run offline controls or a preflight-bound live Eval Pack"
    )
    eval_run.add_argument("--pack", type=pathlib.Path, required=True)
    eval_run.add_argument("--output-dir", type=pathlib.Path, required=True)
    eval_run.add_argument("--config", type=pathlib.Path, default=None)
    eval_run.add_argument("--run-id", default=None)
    eval_run.add_argument("--candidate", action="append", dest="candidate_ids")
    eval_run.add_argument("--case-id", action="append", dest="case_ids")
    eval_run.add_argument("--preflight", type=pathlib.Path, default=None)
    eval_run.add_argument(
        "--live-stage",
        choices=("smoke", "calibration", "baseline", "supplemental"),
        default=None,
    )

    eval_replay = subparsers.add_parser(
        "eval-replay", help="verify and regrade a differential evaluation bundle"
    )
    eval_replay.add_argument("--pack", type=pathlib.Path, required=True)
    eval_replay.add_argument("--bundle", type=pathlib.Path, required=True)
    eval_replay.add_argument("--config", type=pathlib.Path, default=None)

    eval_aggregate = subparsers.add_parser(
        "eval-aggregate", help="verify and aggregate candidate-isolated live baseline bundles"
    )
    eval_aggregate.add_argument("--pack", type=pathlib.Path, required=True)
    eval_aggregate.add_argument("--config", type=pathlib.Path, required=True)
    eval_aggregate.add_argument(
        "--bundle", type=pathlib.Path, action="append", dest="bundles", required=True
    )
    eval_aggregate.add_argument("--output", type=pathlib.Path, required=True)
    eval_aggregate.add_argument("--invalid-run-limit", type=int, default=5)

    eval_migration = subparsers.add_parser(
        "eval-migration",
        help="pair old and current report bundles for a no-network protocol migration analysis",
    )
    eval_migration.add_argument("--pack", type=pathlib.Path, required=True)
    eval_migration.add_argument("--config", type=pathlib.Path, required=True)
    eval_migration.add_argument(
        "--old-bundle", type=pathlib.Path, action="append", dest="old_bundles", required=True
    )
    eval_migration.add_argument(
        "--new-bundle", type=pathlib.Path, action="append", dest="new_bundles", required=True
    )
    eval_migration.add_argument("--output", type=pathlib.Path, required=True)
    eval_migration.add_argument("--regression-limit", type=float, default=0.05)
    eval_migration.add_argument("--old-success-failure-limit", type=int, default=5)

    soak = subparsers.add_parser(
        "soak", help="run or resume a durable long-horizon pi harness qualification"
    )
    soak.add_argument("--tasks", type=pathlib.Path, required=True)
    soak.add_argument("--config", type=pathlib.Path, required=True)
    soak.add_argument("--output-dir", type=pathlib.Path, required=True)
    soak.add_argument("--experiment-id", required=True)
    soak.add_argument("--steps", type=int, default=50)
    soak.add_argument("--slice", action="append", dest="slices")
    soak.add_argument("--variant", action="append", dest="variants")
    soak.add_argument("--candidate", action="append", dest="candidate_ids")
    soak.add_argument("--preflight", type=pathlib.Path, required=True)
    soak.add_argument("--cancel-file", type=pathlib.Path, default=None)
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
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(_render(value), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _live_preflight(candidates: list[Any], config_path: pathlib.Path) -> dict[str, Any]:
    adapters = {candidate.adapter for candidate in candidates}
    if not candidates or len(adapters) != 1 or not adapters <= {"bailian-live", "pi-agent-live"}:
        raise BenchInputError("preflight requires one supported live adapter")
    if len(candidates) > 4:
        raise BenchInputError("live preflight request budget exceeded: maximum is 4")
    adapter = (
        PiAgentLiveAdapter(pathlib.Path.cwd())
        if adapters == {"pi-agent-live"}
        else BailianLiveAdapter(pathlib.Path.cwd())
    )
    rows = []
    for candidate in candidates:
        row = dict(adapter.preflight(candidate))
        row.update(
            {
                "candidate_id": candidate.id,
                "agent": candidate.agent,
                "adapter": candidate.adapter,
            }
        )
        rows.append(row)
    config_hashes = sorted({row["config_sha256"] for row in rows})
    config_hash = _sha256(config_path)
    if config_hashes != [config_hash]:
        raise BenchInputError("live candidates must share one run config")
    passed = all(row["status"] == "passed" for row in rows)
    created_at = datetime.now(UTC)
    return {
        "schema_version": "0.1.0",
        "status": "passed" if passed else "blocked",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (created_at + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
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
    try:
        created_at = datetime.fromisoformat(str(report["created_at"]).replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(str(report["expires_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise BenchInputError("preflight validity window is missing or invalid") from exc
    now = datetime.now(UTC)
    if created_at.tzinfo is None or expires_at.tzinfo is None or not created_at <= now < expires_at:
        raise BenchInputError("preflight evidence is expired or not yet valid")
    rows = report.get("models") or []
    expected_candidates = {
        (candidate.id, candidate.model, candidate.agent, candidate.adapter)
        for candidate in candidates
    }
    passed_candidates = {
        (
            row.get("candidate_id"),
            row.get("model"),
            row.get("agent"),
            row.get("adapter"),
        )
        for row in rows
        if isinstance(row, dict)
        and row.get("status") == "passed"
        and (row.get("identity") or {}).get("exact_match") is True
    }
    if not expected_candidates.issubset(passed_candidates):
        raise BenchInputError("preflight exact candidate identities do not match the run")
    versions["config_sha256"] = str(report["config_sha256"])
    versions["preflight_sha256"] = _sha256(path)


def _live_plan(
    tasks: list[dict[str, Any]],
    candidates: list[Any],
    config_path: pathlib.Path,
    *,
    live_stage: str | None = None,
) -> dict[str, Any]:
    if not candidates or any(candidate.adapter != "pi-agent-live" for candidate in candidates):
        raise BenchInputError("plan-live requires only pi-agent-live candidates")
    config = load_run_config(config_path)
    preflight_input_tokens = 256 * len(candidates)
    preflight_output_tokens = 64 * len(candidates)
    matrix_input_tokens = 0
    matrix_output_tokens = 0
    for candidate in candidates:
        model = next(item for item in config.models if item.model_id == candidate.model)
        provider = config.provider(model.provider)
        generation = dict(candidate.config.get("generation") or {})
        generation["seed"] = int(candidate.config.get("seed", 20260819))
        resolved = resolve_generation(
            provider,
            model,
            profile=config.profile(candidate.config.get("profile")),
            candidate=generation,
        )
        turns = int(candidate.config.get("max_provider_turns", 2))
        matrix_output_tokens += len(tasks) * turns * int(resolved.resolved["max_output_tokens"])
        matrix_input_tokens += sum(turns * _task_input_ceiling(task) for task in tasks)
    preflight_requests = len(candidates)
    matrix_requests = len(tasks) * sum(
        int(candidate.config.get("max_provider_turns", 2)) for candidate in candidates
    )
    return {
        "schema_version": "0.1.0",
        "network_calls_performed": 0,
        "config_sha256": _sha256(config_path),
        "models": [candidate.model for candidate in candidates],
        "live_stage": live_stage,
        "case_ids": [task.get("id", task.get("task_id")) for task in tasks],
        "tasks": len(tasks),
        "matrix_cells": len(tasks) * len(candidates),
        "request_ceiling": {
            "preflight": preflight_requests,
            "matrix": matrix_requests,
            "total": preflight_requests + matrix_requests,
            "retries_per_request": 0,
        },
        "token_ceiling": {
            "input_contract": preflight_input_tokens + matrix_input_tokens,
            "output_hard_cap": preflight_output_tokens + matrix_output_tokens,
            "total_planned": preflight_input_tokens
            + matrix_input_tokens
            + preflight_output_tokens
            + matrix_output_tokens,
        },
        "cost_usd_upper_bound": None,
        "cost_basis": "token_plan_unpriced",
        "approval_required": True,
    }


T = TypeVar("T")


def _task_input_ceiling(task: dict[str, Any]) -> int:
    budget = task.get("budget")
    if not isinstance(budget, dict):
        budget = task.get("candidate_payload", {}).get("budget", {})
    return int(budget.get("max_input_tokens", 0))


def _looks_like_report_eval(path: pathlib.Path) -> bool:
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            value = json.loads(raw)
            return isinstance(value, dict) and {"family_id", "gold", "primary_gate"} <= set(value)
    return False


def _exactly_filtered(
    values: list[T], selected: list[str] | None, key: Callable[[T], Any], label: str
) -> list[T]:
    if not selected:
        return values
    if len(selected) != len(set(selected)):
        raise BenchInputError(f"{label} selection contains duplicates")
    wanted = set(selected)
    available = {str(key(value)) for value in values}
    missing = wanted - available
    if missing:
        raise BenchInputError(f"unknown {label} selection: {', '.join(sorted(missing))}")
    return [value for value in values if str(key(value)) in wanted]


def _validate_report_live_slice(
    candidates: list[Any],
    selected: list[str] | None,
    *,
    live_stage: str | None,
    all_case_ids: set[str],
) -> None:
    if len(candidates) != 1:
        raise BenchInputError("report live execution requires one explicitly selected candidate")
    candidate = candidates[0]
    if live_stage is None:
        raise BenchInputError("report live execution requires --live-stage")
    allowed_stages = candidate.config.get("live_eval_stages")
    if not isinstance(allowed_stages, list) or live_stage not in allowed_stages:
        raise BenchInputError(f"candidate does not approve report live stage: {live_stage}")
    approved = candidate.config.get("calibration_case_ids")
    if not isinstance(approved, list) or len(approved) != 10 or len(set(approved)) != 10:
        raise BenchInputError("candidate must register exactly 10 calibration cases")
    if not set(approved) <= all_case_ids:
        raise BenchInputError("candidate calibration selection contains unknown cases")
    if live_stage == "smoke":
        if selected is None or len(selected) != 1 or selected[0] not in approved:
            raise BenchInputError("report live smoke requires one registered calibration case")
    elif live_stage == "calibration":
        if selected is None or set(selected) != set(approved):
            raise BenchInputError(
                "report live calibration must match the 10 registered calibration cases"
            )
    elif live_stage == "baseline":
        if selected is not None:
            raise BenchInputError("report live baseline runs the full pack without --case-id")
        if len(all_case_ids) != 100:
            raise BenchInputError("report live baseline requires an exact 100-case pack")
    elif live_stage == "supplemental":
        if selected is None or not selected or not set(selected) <= all_case_ids:
            raise BenchInputError("report live supplemental requires explicit pack case IDs")
    if candidate.adapter != "pi-agent-live":
        raise BenchInputError("report live execution requires pi-agent-live")


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
        report_live_plan = False
        if args.command == "eval-validate":
            candidates = load_candidates(args.config) if args.config is not None else None
            report = validate_eval_pack(args.pack, candidates=candidates)
            print(_render(report), end="")
            return 0 if report["status"] == "passed" else 2
        if args.command == "eval-run":
            candidates = load_candidates(args.config) if args.config is not None else None
            preflight_sha256 = None
            if candidates is not None:
                candidates = _exactly_filtered(
                    candidates, args.candidate_ids, lambda candidate: candidate.id, "candidate"
                )
                adapters = {candidate.adapter for candidate in candidates}
                if len(adapters) != 1:
                    raise BenchInputError("one eval-run cannot mix mock and live adapters")
                if adapters == {"pi-agent-live"}:
                    if args.candidate_ids is None:
                        raise BenchInputError(
                            "report live execution requires one explicitly selected candidate"
                        )
                    all_case_ids = {case["id"] for case in load_report_cases(args.pack)}
                    _validate_report_live_slice(
                        candidates,
                        args.case_ids,
                        live_stage=args.live_stage,
                        all_case_ids=all_case_ids,
                    )
                    if args.preflight is None:
                        raise BenchInputError("live report eval-run requires --preflight")
                    versions = {"config_sha256": _sha256(args.config)}
                    _bind_live_preflight(args.preflight, candidates, versions)
                    preflight_sha256 = versions["preflight_sha256"]
                elif args.preflight is not None:
                    raise BenchInputError("mock eval-run does not accept --preflight")
                elif args.live_stage is not None:
                    raise BenchInputError("mock eval-run does not accept --live-stage")
            report = run_eval_pack(
                args.pack,
                args.output_dir,
                candidates=candidates,
                case_ids=args.case_ids,
                repository_root=pathlib.Path.cwd() if candidates is not None else None,
                run_id=args.run_id,
                preflight_sha256=preflight_sha256,
                live_stage=args.live_stage,
            )
            print(_render(report), end="")
            if report.get("status") in {
                "paused",
                "operationally_invalid",
                "calibration_failed",
            }:
                return 1
            return 1 if report.get("outcome_counts", {}).get("invalid_run") else 0
        if args.command == "eval-replay":
            candidates = load_candidates(args.config) if args.config is not None else None
            report = replay_eval_pack(args.pack, args.bundle, candidates=candidates)
            print(_render(report), end="")
            return 0
        if args.command == "eval-aggregate":
            candidates = load_candidates(args.config)
            report = aggregate_eval_bundles(
                args.pack,
                args.bundles,
                candidates=candidates,
                invalid_run_limit=args.invalid_run_limit,
            )
            _write_safe_json(args.output, report)
            print(_render({**report, "output": str(args.output)}), end="")
            return 1 if report["status"] == "partial" else 0
        if args.command == "eval-migration":
            candidates = load_candidates(args.config)
            report = analyze_eval_migration(
                args.pack,
                args.old_bundles,
                args.new_bundles,
                candidates=candidates,
                regression_limit=args.regression_limit,
                old_success_failure_limit=args.old_success_failure_limit,
            )
            _write_safe_json(args.output, report)
            rendered = {**report, "cells": "written_to_output", "output": str(args.output)}
            print(_render(rendered), end="")
            return 1 if report["status"] == "completed_review_required" else 0
        if args.command in {
            "validate",
            "preflight",
            "run",
            "soak",
            "qualify",
            "qualify-replay",
        }:
            if args.command != "preflight":
                tasks = load_tasks(args.tasks)
            candidates = load_candidates(args.config)
        if args.command == "plan-live":
            candidates = load_candidates(args.config)
            report_live_plan = _looks_like_report_eval(args.tasks)
            if report_live_plan:
                validation = validate_eval_pack(args.tasks.parent, candidates=candidates)
                if validation["status"] != "passed":
                    raise BenchInputError("report Eval Pack validation failed")
                tasks = load_report_cases(args.tasks.parent)
            else:
                if args.case_ids:
                    raise BenchInputError("--case-id is only supported for report Eval Packs")
                tasks = load_tasks(args.tasks)
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
        if args.command == "plan-live":
            candidates = _exactly_filtered(
                candidates, args.candidate_ids, lambda candidate: candidate.id, "candidate"
            )
            if report_live_plan:
                if args.slices or args.variants:
                    raise BenchInputError(
                        "report live plans use explicit --case-id selection, not slices or variants"
                    )
                all_case_ids = {task["id"] for task in tasks}
                tasks = _exactly_filtered(tasks, args.case_ids, lambda task: task["id"], "case")
                if args.candidate_ids is None:
                    raise BenchInputError(
                        "report live execution requires one explicitly selected candidate"
                    )
                _validate_report_live_slice(
                    candidates,
                    args.case_ids,
                    live_stage=args.live_stage,
                    all_case_ids=all_case_ids,
                )
            else:
                tasks = _filtered(
                    tasks,
                    args.slices,
                    lambda task: task.get("task_card", {}).get("slice"),
                    "slice",
                )
                tasks = _filtered(
                    tasks,
                    args.variants,
                    lambda task: task.get("task_card", {}).get("variant"),
                    "variant",
                )
            report = _live_plan(
                tasks,
                candidates,
                args.config,
                live_stage=args.live_stage if report_live_plan else None,
            )
            if args.output is not None:
                _write_safe_json(args.output, report)
            print(_render(report), end="")
            return 0
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
                tasks_path=args.tasks,
                config_path=args.config,
            )
            if adapters <= {"bailian-live", "pi-agent-live"}:
                if args.preflight is None:
                    raise BenchInputError("live run requires --preflight")
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
        if args.command in {"qualify", "qualify-replay"}:
            tasks = _filtered(
                tasks, args.slices, lambda task: task.get("task_card", {}).get("slice"), "slice"
            )
            tasks = _filtered(
                tasks,
                args.variants,
                lambda task: task.get("task_card", {}).get("variant"),
                "variant",
            )
            if args.command == "qualify":
                versions = version_coordinates(
                    tasks_path=args.tasks,
                    config_path=args.config,
                )
                manifest = run_qualification(
                    tasks,
                    candidates,
                    repository_root=pathlib.Path.cwd(),
                    output_directory=args.output_dir,
                    run_id=args.run_id,
                    versions=versions,
                )
                print(_render({**manifest, "output": str(args.output_dir)}), end="")
                return 0
            report = replay_qualification(tasks, candidates, args.bundle)
            print(_render(report), end="")
            return 0
        if args.command == "soak":
            tasks = _filtered(
                tasks, args.slices, lambda task: task.get("task_card", {}).get("slice"), "slice"
            )
            tasks = _filtered(
                tasks,
                args.variants,
                lambda task: task.get("task_card", {}).get("variant"),
                "variant",
            )
            if len(tasks) != 1:
                raise BenchInputError("soak requires exactly one filtered task")
            candidates = _filtered(
                candidates, args.candidate_ids, lambda candidate: candidate.id, "candidate"
            )
            if any(candidate.adapter != "pi-agent-live" for candidate in candidates):
                raise BenchInputError("soak requires only pi-agent-live candidates")
            versions = version_coordinates(
                tasks_path=args.tasks,
                config_path=args.config,
            )
            _bind_live_preflight(args.preflight, candidates, versions)
            summaries = [
                run_long_horizon(
                    tasks[0],
                    candidate,
                    repository_root=pathlib.Path.cwd(),
                    output_directory=args.output_dir,
                    experiment_id=args.experiment_id,
                    versions=versions,
                    steps=args.steps,
                    cancel_file=args.cancel_file,
                )
                for candidate in candidates
            ]
            report = aggregate_soak(summaries)
            _write_safe_json(args.output_dir / "report.json", report)
            print(_render({**report, "output": str(args.output_dir / "report.json")}), end="")
            return 0 if report["status"] == "completed" else 1
        if args.command == "compare":
            report = compare_traces(read_traces(args.traces))
            rendered = _render(report)
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered, encoding="utf-8")
            print(rendered, end="")
            return 0
    except (BenchInputError, QualificationError, OSError, ValueError) as exc:
        print(_render({"status": "error", "error": str(exc)}), end="", file=sys.stderr)
        return 2
    return 2
