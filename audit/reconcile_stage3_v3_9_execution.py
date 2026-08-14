"""Independent reconciliation of the PER-55 v3.9 paid execution (36 units).

Deterministic, read-only over the frozen run directory. Re-validates frozen
input hashes, the preflight artifact, and every run's checkpoint chain,
trace, and grader; then aggregates counts required by the PER-55 acceptance
gate. Writes ``summary.json`` into the run directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
from typing import Any, Mapping

from contracts.run_trace_validator_v3_7 import scan_persisted_value_for_secrets
from contracts.run_trace_validator_v3_8 import (
    build_run_id,
    content_sha256,
    file_sha256,
)
from contracts.run_trace_validator_v3_9 import validate_run_trace_v39
from harness.acceptance_v3_9 import grade_candidate_v39, read_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "contracts/stage3_acceptance_plan.v3.9.json"
BUNDLE_PATH = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.9.json"
CONFIG_PATH = ROOT / "contracts/run_trace_harness_config.v3.9.json"
EXPECTED = {
    "bundle_content_sha256": "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030",
    "plan_sha256": "235b0415bf43c356a5f2c3801a7793606ed5e943a5e8ce60f0aa3b20abeeb185",
    "plan_core_sha256": "bf1d1ed48b0f5728b0f2f71bcd13af91dc7a9ed586c0f2ffbe9cebaf7e804ebd",
    "config_sha256": "e06b3fae6acf1ab76716c3a507163601fa6249f6160a8dbfce1216f8080e0cfa",
}
ZERO_SHA = "0" * 64


def verify_frozen_inputs() -> list[str]:
    errors: list[str] = []
    plan = read_json(PLAN_PATH)
    stripped = copy.deepcopy(plan)
    stripped.pop("plan_sha256", None)
    if content_sha256(stripped) != EXPECTED["plan_sha256"]:
        errors.append("plan content hash drift")
    if plan.get("plan_sha256") != EXPECTED["plan_sha256"]:
        errors.append("plan self hash drift")
    if plan.get("plan_core_sha256") != EXPECTED["plan_core_sha256"]:
        errors.append("plan_core hash drift")
    if file_sha256(CONFIG_PATH) != EXPECTED["config_sha256"]:
        errors.append("config file hash drift")
    bundle = read_json(BUNDLE_PATH)
    if bundle.get("bundle_sha256") != EXPECTED["bundle_content_sha256"]:
        errors.append("bundle content hash drift")
    if content_sha256(bundle.get("artifacts", [])) != bundle.get("bundle_sha256"):
        errors.append("bundle artifact-list mismatch")
    for item in bundle.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.is_file() or file_sha256(path) != item["sha256"]:
            errors.append(f"artifact drift:{item['path']}")
    return errors


def verify_preflight(plan: Mapping[str, Any], preflight: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    artifact = copy.deepcopy(preflight)
    claimed = artifact.pop("preflight_sha256", None)
    if claimed != content_sha256(artifact):
        errors.append("preflight self hash mismatch")
    if preflight.get("plan_sha256") != plan.get("plan_sha256"):
        errors.append("preflight not plan-bound")
    if preflight.get("contract_version") != "3.9.0" or preflight.get("contract_type") != "stage3_identity_preflight":
        errors.append("preflight contract identity wrong")
    if preflight.get("decision") != "passed_3_of_3":
        errors.append("preflight decision not passed_3_of_3")
    counts = preflight.get("counts", {})
    if counts.get("requested") != 3 or counts.get("passed") != 3 or counts.get("blocked") != 0:
        errors.append("preflight counts not 3/3")
    for row in preflight.get("results", []):
        if row.get("response_model_id") != row.get("model_id") or not row.get("passed") or not row.get("parameters_honored") or not row.get("tool_capability_passed"):
            errors.append(f"preflight unit failed:{row.get('model_id')}")
    return errors


def verify_checkpoint_chain(path: pathlib.Path, trace: Mapping[str, Any], plan_sha: str) -> tuple[int, list[str]]:
    errors: list[str] = []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous = ZERO_SHA
    last_sha = None
    for offset, event in enumerate(lines):
        if scan_persisted_value_for_secrets(event):
            errors.append(f"checkpoint[{offset}] secret-like value")
        claimed = event.pop("event_sha256", None)
        recomputed = content_sha256(event)
        if claimed != recomputed:
            errors.append(f"checkpoint[{offset}] event hash mismatch")
        if event.get("previous_event_sha256") != previous:
            errors.append(f"checkpoint[{offset}] chain broken")
        if event.get("offset") != offset:
            errors.append(f"checkpoint[{offset}] offset gap")
        if event.get("run_id") != trace.get("run_id"):
            errors.append(f"checkpoint[{offset}] run id mismatch")
        previous = claimed
        last_sha = claimed
        event["event_sha256"] = claimed
    if lines and lines[0].get("event_type") != "run_started":
        errors.append("checkpoint does not start with run_started")
    if lines and lines[0].get("payload", {}).get("plan_sha256") != plan_sha:
        errors.append("checkpoint run_started not plan-bound")
    if lines and lines[-1].get("event_type") != "run_completed":
        errors.append("checkpoint does not end with run_completed")
    checkpoint = trace.get("checkpoint", {})
    if checkpoint.get("event_count") != len(lines):
        errors.append("trace checkpoint event_count mismatch")
    if checkpoint.get("final_event_sha256") != last_sha:
        errors.append("trace checkpoint final event mismatch")
    if lines and lines[-1].get("payload", {}).get("status") != trace.get("status"):
        errors.append("checkpoint terminal status mismatch")
    return len(lines), errors


def reconcile_run(run_dir: pathlib.Path, row: Mapping[str, Any], task: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    run_id = row["run_id"]
    errors: list[str] = []
    if build_run_id(row["run_identity"]) != run_id:
        errors.append("run id derivation mismatch")
    trace = read_json(run_dir / "traces" / f"{run_id}.json")
    candidate_path = run_dir / "candidates" / f"{run_id}.json"
    candidate = read_json(candidate_path) if candidate_path.is_file() else None
    grader = read_json(run_dir / "graders" / f"{run_id}.json")
    projection = read_json(ROOT / task["projection_path"])
    snapshot = read_json(ROOT / task["snapshot_path"])
    if file_sha256(ROOT / task["projection_path"]) != task["projection_sha256"] or file_sha256(ROOT / task["snapshot_path"]) != task["snapshot_sha256"]:
        errors.append("frozen projection/snapshot drift")

    # Independent schema + contract validation (secret scan included).
    try:
        validate_run_trace_v39(trace, plan=dict(plan), scan_companions=[candidate] if candidate is not None else [])
    except Exception as exc:  # noqa: BLE001 - collect every rejection for the full picture
        errors.append(f"validator rejected trace:{exc}")
    if scan_persisted_value_for_secrets(grader):
        errors.append("grader secret-like value")

    checkpoint_events, checkpoint_errors = verify_checkpoint_chain(run_dir / "checkpoints" / f"{run_id}.jsonl", trace, plan["plan_sha256"])
    errors += checkpoint_errors

    # Deterministic grader recompute must equal the persisted grader.
    recomputed = grade_candidate_v39(candidate, projection, snapshot, trace)
    if recomputed != grader:
        errors.append("grader not deterministically reproducible")

    # Usage cross-checks.
    attempts = [attempt for request in trace["logical_requests"] for attempt in request["attempts"]]
    usage = trace.get("usage", {})
    if usage.get("model_requests") != len(trace["logical_requests"]) or usage.get("provider_attempts") != len(attempts) or usage.get("tool_calls") != len(trace.get("tool_events", [])):
        errors.append("usage counts inconsistent")
    if usage.get("total_tokens") != sum(item.get("input_tokens", 0) + item.get("output_tokens", 0) for item in attempts):
        errors.append("token total inconsistent")

    # Identity / fallback.
    requested = row["model_id"]
    fallbacks = [item for item in attempts if item.get("response_model_id") is not None and item.get("response_model_id") != requested]
    identity_valid = all(item.get("response_model_id") in (None, requested) for item in attempts) and trace.get("provider", {}).get("response_model_id") in (None, requested)

    environment = trace.get("environment", {})
    record = {
        "run_id": run_id,
        "case_id": task["case_id"],
        "model_id": requested,
        "status": trace["status"],
        "failure_class": trace.get("failure", {}).get("class"),
        "model_requests": usage.get("model_requests"),
        "provider_attempts": usage.get("provider_attempts"),
        "tool_calls": usage.get("tool_calls"),
        "total_tokens": usage.get("total_tokens"),
        "duration_ms": sum(item.get("duration_ms", 0) for item in attempts),
        "checkpoint_events": checkpoint_events,
        "identity_valid": identity_valid,
        "fallback_attempts": len(fallbacks),
        "candidate_scored": trace.get("result", {}).get("candidate_scored"),
        "structured_output_valid": trace.get("result", {}).get("structured_output_valid"),
        "all_applicable_checks_passed": grader.get("all_applicable_checks_passed"),
        "value_semantic_correct": grader.get("checks", {}).get("value_semantic_correct"),
        "failed_checks": grader.get("failed_checks", []),
        "provider_failures": sum(1 for item in attempts if item.get("classification") == "provider_or_runtime_failure"),
        "provider_error_codes": sorted({item.get("provider_error_code") for item in attempts if item.get("provider_error_code")}),
        "real_side_effects": environment.get("real_side_effects"),
        "terminal_state_safe": environment.get("final_state_matches_initial") is (environment.get("initial_ledger_sha256") == environment.get("final_ledger_sha256")),
        "errors": errors,
    }
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--preflight", required=True)
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).resolve()

    errors = verify_frozen_inputs()
    plan = read_json(PLAN_PATH)
    preflight = read_json(pathlib.Path(args.preflight))
    errors += verify_preflight(plan, preflight)

    task_by_run = {run_id: task for task in plan["tasks"] for run_id in task["run_ids"]}
    records = [reconcile_run(run_dir, row, task_by_run[row["run_id"]], plan) for row in plan["runs"]]
    errors += [f"{record['run_id']}:{item}" for record in records for item in record["errors"]]

    def count(predicate) -> int:
        return sum(1 for record in records if predicate(record))

    by_model: dict[str, dict[str, Any]] = {}
    for model in sorted({record["model_id"] for record in records}):
        subset = [record for record in records if record["model_id"] == model]
        by_model[model] = {
            "runs": len(subset),
            "succeeded": sum(1 for item in subset if item["status"] == "succeeded"),
            "candidate_failed": sum(1 for item in subset if item["status"] == "candidate_failed"),
            "invalid_provider_or_runtime": sum(1 for item in subset if item["status"] == "invalid_provider_or_runtime"),
            "structured_results": sum(1 for item in subset if item["structured_output_valid"]),
            "value_semantic_correct": sum(1 for item in subset if item["value_semantic_correct"] is True),
            "all_applicable_checks_passed": sum(1 for item in subset if item["all_applicable_checks_passed"]),
            "provider_attempts": sum(item["provider_attempts"] for item in subset),
            "provider_failures": sum(item["provider_failures"] for item in subset),
            "total_tokens": sum(item["total_tokens"] for item in subset),
            "duration_ms": sum(item["duration_ms"] for item in subset),
            "failed_check_frequency": {},
        }
        frequency: dict[str, int] = {}
        for item in subset:
            for code in item["failed_checks"]:
                frequency[code] = frequency.get(code, 0) + 1
        by_model[model]["failed_check_frequency"] = dict(sorted(frequency.items()))

    summary = {
        "contract_type": "stage3_financial_acceptance_summary",
        "contract_version": "3.9.0",
        "status": "completed" if not errors else "reconciliation_errors",
        "plan_sha256": plan["plan_sha256"],
        "preflight_sha256": preflight["preflight_sha256"],
        "frozen_input_hashes": EXPECTED,
        "counts": {
            "planned": len(plan["runs"]),
            "traces": count(lambda record: True),
            "graders": count(lambda record: True),
            "checkpoints": count(lambda record: record["checkpoint_events"] > 0),
            "checkpoint_events": sum(record["checkpoint_events"] for record in records),
            "identity_valid": count(lambda record: record["identity_valid"]),
            "succeeded": count(lambda record: record["status"] == "succeeded"),
            "candidate_failed": count(lambda record: record["status"] == "candidate_failed"),
            "invalid_provider_or_runtime": count(lambda record: record["status"] == "invalid_provider_or_runtime"),
            "structured_results": count(lambda record: record["structured_output_valid"]),
            "all_applicable_checks_passed": count(lambda record: record["all_applicable_checks_passed"]),
            "value_semantic_correct": count(lambda record: record["value_semantic_correct"] is True),
            "fallback": sum(record["fallback_attempts"] for record in records),
            "secret_leakage": sum(1 for error in errors if "secret" in error),
            "unsafe_or_real_side_effect": count(lambda record: record["real_side_effects"] is True or not record["terminal_state_safe"]),
            "provider_attempts": sum(record["provider_attempts"] for record in records),
            "provider_failures": sum(record["provider_failures"] for record in records),
            "total_tokens": sum(record["total_tokens"] for record in records),
            "total_duration_ms": sum(record["duration_ms"] for record in records),
        },
        "by_model": by_model,
        "provider_error_codes": sorted({code for record in records for code in record["provider_error_codes"]}),
        "cost_usd": None,
        "cost_status": "provider_response_does_not_supply_cost",
        "reconciliation_errors": errors,
        "records": records,
    }
    output_path = run_dir / "summary.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": not errors, "errors": len(errors), "summary": str(output_path), "counts": summary["counts"]}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
