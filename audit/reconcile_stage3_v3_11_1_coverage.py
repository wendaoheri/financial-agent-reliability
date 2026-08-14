"""Independent reconciliation of the PER-79 v3.11.1 single-unit coverage paid run.

Deterministic, read-only over the frozen coverage run directory. Re-validates
the frozen v3.11 inputs (unchanged bundle + config), the v3.11.1 coverage plan,
the plan-bound carry-over preflight, and the single-unit coverage authorization
(gate review passed + delivery-owner dispatch authorized); reconciles the one
executed run's checkpoint chain, trace, and grader (validator bound to the
v3.11.1 coverage plan); confirms the seq 268 invalidation forensics remain
preserved and unreplaced in the v3.11 round directory; and writes
``summary.json`` into the coverage run directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
from typing import Any, Mapping

from contracts.run_trace_validator_v3_7 import scan_persisted_value_for_secrets
from contracts.run_trace_validator_v3_8 import build_run_id, content_sha256, file_sha256
from contracts.run_trace_validator_v3_11 import validate_run_trace_v311
from harness.acceptance_v3_11 import grade_candidate_v311, read_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json"
BUNDLE_PATH = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"
CONFIG_PATH = ROOT / "contracts/run_trace_harness_config.v3.11.json"
V311_RUN_DIR = ROOT / "runs/stage3/acceptance-20260813-v3.11"

EXPECTED = {
    "plan_sha256": "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b",
    "plan_core_sha256": "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b",
    "config_sha256": "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e",
    "bundle_content_sha256": "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d",
    "gate_report_sha256": "0c863c1213c62724bec0e016f2bb36d955bbd0a884dd5e9df55413f062b37b58",
    "coverage_run_id": "run_0e1e8f4400e16f22f6581e0bb0d9c54d",
    "invalidated_run_id": "run_c0f58d3c0d9227585058c4e4872a468b",
    "case_id": "case-synthetic-ftw-14-normal-v3",
    "model_id": "deepseek-v4-pro",
    "repeat": 2,
    "seed": 738396034,
}
# seq 268 forensics commitments (must remain preserved, unreplaced, in v3.11 dir)
FORENSICS = {
    "invalidated_runs_file_sha256": "7fd165fa26f83ea925a782c77c81b235fb1665496fb457df6d665547ef8547a7",
    "invalidation_report_sha256": "3a5189e7ffb4ad093b6508fcb6319bc68248a21de9a70c019685db5849868bda",
    "pending_invalidations_file_sha256": "61c7baecab626a5559702bd8e77a4c2f700dbbd6cdff17102a30fe83fb147946",
    "checkpoint_residue_sha256": "68f0e73854ae6341fe829037eaf2ff1a2b560dcbd2b9cfbca8f302e4d28c85b6",
}
ZERO_SHA = "0" * 64


def verify_frozen_inputs() -> list[str]:
    errors: list[str] = []
    plan = read_json(PLAN_PATH)
    stripped = copy.deepcopy(plan)
    stripped.pop("plan_sha256", None)
    if content_sha256(stripped) != EXPECTED["plan_sha256"]:
        errors.append("coverage plan content hash drift")
    if plan.get("plan_sha256") != EXPECTED["plan_sha256"]:
        errors.append("coverage plan self hash drift")
    if plan.get("plan_core_sha256") != EXPECTED["plan_core_sha256"]:
        errors.append("coverage plan_core hash drift")
    if file_sha256(CONFIG_PATH) != EXPECTED["config_sha256"]:
        errors.append("v3.11 config file hash drift (contracts must be unchanged)")
    bundle = read_json(BUNDLE_PATH)
    if bundle.get("bundle_sha256") != EXPECTED["bundle_content_sha256"]:
        errors.append("v3.11 bundle content hash drift (contracts must be unchanged)")
    if content_sha256(bundle.get("artifacts", [])) != bundle.get("bundle_sha256"):
        errors.append("v3.11 bundle artifact-list mismatch")
    for item in bundle.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.is_file() or file_sha256(path) != item["sha256"]:
            errors.append(f"v3.11 artifact drift:{item['path']}")
    return errors


def verify_preflight(plan: Mapping[str, Any], preflight: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    artifact = copy.deepcopy(preflight)
    claimed = artifact.pop("preflight_sha256", None)
    if claimed != content_sha256(artifact):
        errors.append("coverage preflight self hash mismatch")
    if preflight.get("plan_sha256") != plan.get("plan_sha256"):
        errors.append("coverage preflight not plan-bound")
    if preflight.get("contract_version") != "3.11.0" or preflight.get("contract_type") != "stage3_identity_preflight":
        errors.append("coverage preflight contract identity wrong")
    if preflight.get("decision") != "passed_1_of_1":
        errors.append("coverage preflight decision not passed_1_of_1")
    counts = preflight.get("counts", {})
    if counts.get("requested") != 1 or counts.get("passed") != 1 or counts.get("blocked") != 0:
        errors.append("coverage preflight counts not 1/1")
    if preflight.get("carry_over", {}).get("paid_calls_in_this_round") != 0:
        errors.append("coverage preflight carry-over must declare zero paid calls")
    for row in preflight.get("results", []):
        if row.get("response_model_id") != row.get("model_id") or not row.get("passed") or not row.get("parameters_honored") or not row.get("tool_capability_passed"):
            errors.append(f"coverage preflight unit failed:{row.get('model_id')}")
    return errors


def verify_authorization(plan: Mapping[str, Any], preflight: Mapping[str, Any], authorization: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if authorization.get("paid_calls_authorized") is not True or authorization.get("authorization_kind") != "financial_acceptance_single_unit_coverage_run":
        errors.append("authorization kind/paid flag wrong")
    stripped = copy.deepcopy(authorization)
    claimed = stripped.pop("authorization_sha256", None)
    if claimed != content_sha256(stripped):
        errors.append("authorization self hash mismatch")
    if authorization.get("plan_sha256") != plan.get("plan_sha256"):
        errors.append("authorization not bound to the coverage plan")
    if authorization.get("plan_core_sha256") != EXPECTED["plan_core_sha256"]:
        errors.append("authorization plan_core binding drift")
    if authorization.get("contract_bundle_sha256") != EXPECTED["bundle_content_sha256"] or authorization.get("harness_config_sha256") != EXPECTED["config_sha256"]:
        errors.append("authorization contract binding drift")
    if authorization.get("preflight_sha256") != preflight.get("preflight_sha256"):
        errors.append("authorization not preflight-bound")
    if authorization.get("exact_model_ids") != [EXPECTED["model_id"]]:
        errors.append("authorization model scope wrong")
    if authorization.get("authorized_run_ids") != [EXPECTED["coverage_run_id"]] or authorization.get("authorized_run_count") != 1 or authorization.get("maximum_runs") != 1:
        errors.append("authorization must bind exactly the one coverage run id with caps of 1")
    if authorization.get("denied_run_ids") != [EXPECTED["invalidated_run_id"]]:
        errors.append("authorization must deny exactly the invalidated seq 268 run id")
    if authorization.get("coverage_replaces_or_reexecutes_invalidation") is not False:
        errors.append("authorization must preserve no-replacement discipline")
    gate = authorization.get("execution_gate", {})
    if gate.get("independent_gate_review_status") != "passed" or gate.get("independent_gate_review_report_sha256") != EXPECTED["gate_report_sha256"]:
        errors.append("execution gate must record the PER-78 review as passed with its report hash")
    if gate.get("delivery_owner_dispatch_status") != "authorized":
        errors.append("execution gate must record delivery-owner dispatch as authorized")
    return errors


def verify_forensics_preserved() -> list[str]:
    errors: list[str] = []
    invalidated_runs_path = V311_RUN_DIR / "invalidated-runs.json"
    pending_path = V311_RUN_DIR / "pending-invalidations.json"
    residue_path = V311_RUN_DIR / "checkpoints" / f"{EXPECTED['invalidated_run_id']}.jsonl"
    if file_sha256(invalidated_runs_path) != FORENSICS["invalidated_runs_file_sha256"]:
        errors.append("seq 268 invalidated-runs.json drift")
    forensics = read_json(invalidated_runs_path)
    if forensics.get("report_sha256") != FORENSICS["invalidation_report_sha256"]:
        errors.append("seq 268 invalidation report_sha256 drift")
    if file_sha256(pending_path) != FORENSICS["pending_invalidations_file_sha256"]:
        errors.append("seq 268 pending-invalidations.json drift")
    if file_sha256(residue_path) != FORENSICS["checkpoint_residue_sha256"]:
        errors.append("seq 268 checkpoint residue drift")
    entries = forensics.get("entries", [])
    if len(entries) != 1:
        errors.append("seq 268 forensics must hold exactly one entry")
    else:
        entry = entries[0]
        if entry.get("run_id") != EXPECTED["invalidated_run_id"] or entry.get("replaced_or_reexecuted") is not False:
            errors.append("seq 268 forensics entry altered or replaced")
    return errors


def verify_checkpoint_chain(path: pathlib.Path, trace: Mapping[str, Any], plan_sha: str) -> tuple[int, list[str]]:
    errors: list[str] = []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous = ZERO_SHA
    for offset, event in enumerate(lines):
        if scan_persisted_value_for_secrets(event):
            errors.append(f"checkpoint[{offset}] secret-like value")
        claimed = event.pop("event_sha256", None)
        if claimed != content_sha256(event):
            errors.append(f"checkpoint[{offset}] event hash mismatch")
        if event.get("previous_event_sha256") != previous:
            errors.append(f"checkpoint[{offset}] chain broken")
        if event.get("offset") != offset:
            errors.append(f"checkpoint[{offset}] offset gap")
        if event.get("run_id") != trace.get("run_id"):
            errors.append(f"checkpoint[{offset}] run id mismatch")
        previous = claimed
        event["event_sha256"] = claimed
    if not lines or lines[0].get("event_type") != "run_started":
        errors.append("checkpoint does not start with run_started")
    elif lines[0].get("payload", {}).get("plan_sha256") != plan_sha:
        errors.append("checkpoint run_started not bound to the coverage plan")
    if not lines or lines[-1].get("event_type") != "run_completed":
        errors.append("checkpoint does not end with run_completed")
    last_sha = lines[-1].get("event_sha256") if lines else None
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

    # Independent schema + contract validation, validator bound to the coverage
    # plan (the coverage run carries the v3.11.1 plan_core commitment).
    try:
        validate_run_trace_v311(trace, plan=dict(plan), scan_companions=[candidate] if candidate is not None else [])
    except Exception as exc:  # noqa: BLE001 - collect every rejection
        errors.append(f"validator rejected trace:{exc}")
    if scan_persisted_value_for_secrets(grader):
        errors.append("grader secret-like value")

    checkpoint_events, checkpoint_errors = verify_checkpoint_chain(run_dir / "checkpoints" / f"{run_id}.jsonl", trace, plan["plan_sha256"])
    errors += checkpoint_errors

    # Deterministic grader recompute must equal the persisted grader.
    recomputed = grade_candidate_v311(candidate, projection, snapshot, trace)
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
    identity_drift = [key for key in row["run_identity"] if trace.get("run_identity", {}).get(key) != row["run_identity"][key]]
    if identity_drift:
        errors.append(f"trace run_identity drift vs plan declaration:{identity_drift}")

    environment = trace.get("environment", {})
    return {
        "run_id": run_id,
        "sequence": row["sequence"],
        "case_id": task["case_id"],
        "variant_id": task["variant_id"],
        "tier": task["tier"],
        "repeat": row["repeat"],
        "model_id": requested,
        "seed": row["seed"],
        "status": trace["status"],
        "failure_class": trace.get("failure", {}).get("class"),
        "model_requests": usage.get("model_requests"),
        "provider_attempts": usage.get("provider_attempts"),
        "retries_used": sum(request.get("retries_used", 0) for request in trace["logical_requests"]),
        "tool_calls": usage.get("tool_calls"),
        "total_tokens": usage.get("total_tokens"),
        "duration_ms": sum(item.get("duration_ms", 0) for item in attempts),
        "checkpoint_events": checkpoint_events,
        "identity_valid": identity_valid,
        "identity_drift": identity_drift,
        "fallback_attempts": len(fallbacks),
        "candidate_scored": trace.get("result", {}).get("candidate_scored"),
        "structured_output_valid": trace.get("result", {}).get("structured_output_valid"),
        "candidate_output_sha256": trace.get("result", {}).get("candidate_output_sha256"),
        "all_applicable_checks_passed": grader.get("all_applicable_checks_passed"),
        "value_semantic_correct": grader.get("checks", {}).get("value_semantic_correct"),
        "failed_checks": grader.get("failed_checks", []),
        "grader_checks": grader.get("checks", {}),
        "provider_failures": sum(1 for item in attempts if item.get("classification") == "provider_or_runtime_failure"),
        "provider_error_codes": sorted({item.get("provider_error_code") for item in attempts if item.get("provider_error_code")}),
        "real_side_effects": environment.get("real_side_effects"),
        "terminal_state_safe": environment.get("final_state_matches_initial") is (environment.get("initial_ledger_sha256") == environment.get("final_ledger_sha256")),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--authorization", required=True)
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).resolve()

    errors = verify_frozen_inputs()
    plan = read_json(PLAN_PATH)
    preflight = read_json(pathlib.Path(args.preflight))
    authorization = read_json(pathlib.Path(args.authorization))
    errors += verify_preflight(plan, preflight)
    errors += verify_authorization(plan, preflight, authorization)
    errors += verify_forensics_preserved()

    if len(plan["runs"]) != 1 or len(plan["tasks"]) != 1 or plan.get("coverage_run_cap") != 1 or plan.get("registered_total_run_cap") != 1:
        errors.append("coverage plan must carry exactly 1 task/run with caps of 1")
    row = plan["runs"][0]
    task = plan["tasks"][0]
    if row["run_id"] != EXPECTED["coverage_run_id"] or row["model_id"] != EXPECTED["model_id"] or row["repeat"] != EXPECTED["repeat"] or row["seed"] != EXPECTED["seed"]:
        errors.append("coverage run row is not exactly the seq 268 unit")

    record = reconcile_run(run_dir, row, task, plan)
    errors += [f"{record['run_id']}:{item}" for item in record["errors"]]

    # No stray artifacts: exactly the one frozen identity.
    expected_ids = {EXPECTED["coverage_run_id"]}
    for sub in ["traces", "graders", "candidates", "checkpoints"]:
        directory = run_dir / sub
        stems = {path.stem for path in directory.glob("*")} if directory.is_dir() else set()
        if stems != expected_ids:
            errors.append(f"{sub} artifacts deviate from the single frozen identity (extra={sorted(stems - expected_ids)[:3]} missing={len(expected_ids - stems)})")

    # Secret scan over driver logs persisted in the run directory.
    for log_name in ["driver-progress.jsonl", "driver-console.log"]:
        log_path = run_dir / log_name
        if log_path.is_file() and scan_persisted_value_for_secrets(log_path.read_text(encoding="utf-8")):
            errors.append(f"{log_name} secret-like value")

    summary = {
        "contract_type": "stage3_financial_acceptance_summary",
        "contract_version": "3.11.0",
        "plan_kind": "single_unit_coverage",
        "status": "completed" if not errors else "reconciliation_errors",
        "plan_sha256": plan["plan_sha256"],
        "plan_core_sha256": plan["plan_core_sha256"],
        "preflight_sha256": preflight["preflight_sha256"],
        "preflight_carry_over_source_sha256": preflight.get("carry_over", {}).get("source_preflight_sha256"),
        "frozen_input_hashes": {k: EXPECTED[k] for k in ["plan_sha256", "plan_core_sha256", "config_sha256", "bundle_content_sha256"]},
        "gate_review": {"issue": "PER-78", "report_sha256": EXPECTED["gate_report_sha256"], "result": "pass"},
        "coverage_target": {
            "invalidated_run_id": EXPECTED["invalidated_run_id"],
            "invalidated_sequence": 268,
            "case_id": EXPECTED["case_id"],
            "model_id": EXPECTED["model_id"],
            "repeat": EXPECTED["repeat"],
            "seed": EXPECTED["seed"],
            "replaces_or_reexecutes_invalidation": False,
            "seq268_forensics_preserved": not any("seq 268" in item for item in errors),
        },
        "counts": {
            "planned": 1,
            "frozen": 1 if not record["errors"] else 0,
            "invalidated": 0,
            "traces": 1,
            "graders": 1,
            "checkpoints": 1 if record["checkpoint_events"] > 0 else 0,
            "checkpoint_events": record["checkpoint_events"],
            "identity_valid": 1 if record["identity_valid"] and not record["identity_drift"] else 0,
            "succeeded": 1 if record["status"] == "succeeded" else 0,
            "candidate_failed": 1 if record["status"] == "candidate_failed" else 0,
            "invalid_provider_or_runtime": 1 if record["status"] == "invalid_provider_or_runtime" else 0,
            "structured_results": 1 if record["structured_output_valid"] else 0,
            "all_applicable_checks_passed": 1 if record["all_applicable_checks_passed"] else 0,
            "value_semantic_correct": 1 if record["value_semantic_correct"] is True else 0,
            "fallback": record["fallback_attempts"],
            "secret_leakage": sum(1 for item in errors if "secret" in item),
            "unsafe_or_real_side_effect": 1 if record["real_side_effects"] is True or not record["terminal_state_safe"] else 0,
            "provider_attempts": record["provider_attempts"],
            "provider_failures": record["provider_failures"],
            "retries_used": record["retries_used"],
            "total_tokens": record["total_tokens"],
            "total_duration_ms": record["duration_ms"],
        },
        "provider_error_codes": record["provider_error_codes"],
        "cost_usd": None,
        "cost_status": "provider_response_does_not_supply_cost",
        "reconciliation_errors": errors,
        "records": [record],
    }
    output_path = run_dir / "summary.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": not errors, "errors": len(errors), "summary": str(output_path), "counts": summary["counts"], "status": record["status"], "all_applicable_checks_passed": record["all_applicable_checks_passed"]}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
