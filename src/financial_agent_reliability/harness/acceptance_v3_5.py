"""Freeze, plan, grade, and package the v3.5 financial acceptance run."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
from typing import Any

from contracts.run_trace_validator import build_bundle_sha256, build_run_id, file_sha256
from contracts.run_trace_validator_v3_5 import validate_run_trace_v35
from contracts.run_trace_validator_v3 import validate_grader_v3
from financial_agent_reliability.harness.acceptance_v3 import canonical, content_sha256, grade_candidate


ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = ROOT / "contracts" / "run_trace_harness_config.v3.5.json"
BASE_PROTOCOL_BUNDLE = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.4.json"
BASE_FINANCIAL_BUNDLE = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.json"
OLD_PLAN = ROOT / "contracts" / "stage3_smoke_plan.v2.json"
PROJECTION_DIR = ROOT / "cases" / "candidate_v3"
OUTPUT_BUNDLE = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.5.json"
OUTPUT_PLAN = ROOT / "contracts" / "stage3_acceptance_plan.v3.5.json"


def build_contract_manifest() -> dict[str, Any]:
    paths = [
        CONFIG,
        ROOT / "contracts" / "run_trace.schema.v3.5.json",
        ROOT / "contracts" / "run_trace_validator_v3_5.py",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "pi_runtime_v3_5.mjs",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "live_acceptance_v3_5.mjs",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "acceptance_v3_5.py",
        ROOT / "tests" / "integration" / "financial_acceptance_v3_5.test.mjs",
        ROOT / "tests" / "test_financial_acceptance_v3_5.py",
    ]
    artifacts = [{"path": path.relative_to(ROOT).as_posix(), "sha256": file_sha256(path)} for path in paths]
    protocol = json.loads(BASE_PROTOCOL_BUNDLE.read_text(encoding="utf-8"))
    financial = json.loads(BASE_FINANCIAL_BUNDLE.read_text(encoding="utf-8"))
    inherited = {item["path"]: item for item in [*protocol["artifacts"], *financial["artifacts"]]}
    combined = [*inherited.values(), *artifacts]
    return {
        "contract_type": "stage3_financial_acceptance_execution_bundle",
        "contract_version": "3.5.0",
        "status": "frozen_before_financial_runs",
        "base_protocol_bundle": {"path": BASE_PROTOCOL_BUNDLE.relative_to(ROOT).as_posix(), "sha256": file_sha256(BASE_PROTOCOL_BUNDLE), "bundle_sha256": protocol["bundle_sha256"]},
        "base_financial_bundle": {"path": BASE_FINANCIAL_BUNDLE.relative_to(ROOT).as_posix(), "sha256": file_sha256(BASE_FINANCIAL_BUNDLE), "bundle_sha256": financial["bundle_sha256"]},
        "rationale": "apply the validated Bailian v3.4 protocol to the unchanged fair v3 financial cases and independent grader",
        "artifacts": artifacts,
        "bundle_sha256": build_bundle_sha256(combined),
        "candidate_visible_model_specific_changes": False,
        "provider_adapter_model_specific_controls": True,
        "retroactive_regrading": False,
        "authorized_financial_runs": 36,
        "full_810_matrix_authorized": False,
    }


def verify_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("contract_version") != "3.5.0":
        errors.append("contract_version must be 3.5.0")
    if manifest.get("candidate_visible_model_specific_changes") is not False:
        errors.append("candidate-visible changes must be model neutral")
    if manifest.get("retroactive_regrading") is not False:
        errors.append("retroactive regrading forbidden")
    if manifest.get("authorized_financial_runs") != 36 or manifest.get("full_810_matrix_authorized") is not False:
        errors.append("authorization scope invalid")
    for artifact in manifest.get("artifacts", []):
        path = ROOT / artifact["path"]
        if not path.is_file():
            errors.append(f"missing artifact: {artifact['path']}")
        elif file_sha256(path) != artifact["sha256"]:
            errors.append(f"hash mismatch: {artifact['path']}")
    expected = build_contract_manifest()["bundle_sha256"]
    if manifest.get("bundle_sha256") != expected:
        errors.append("bundle hash mismatch")
    return errors


def freeze_contracts() -> pathlib.Path:
    manifest = build_contract_manifest()
    errors = verify_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    OUTPUT_BUNDLE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return OUTPUT_BUNDLE


def _known_run_ids() -> set[str]:
    result: set[str] = set()
    for path in (ROOT / "runs" / "stage3").glob("**/traces/*.json"):
        result.add(path.stem)
    for plan_path in [ROOT / "contracts" / "stage3_smoke_plan.v2.json", ROOT / "contracts" / "stage3_smoke_plan.v1.json"]:
        if plan_path.is_file():
            result.update(row["run_id"] for row in json.loads(plan_path.read_text(encoding="utf-8"))["runs"])
    return result


def build_acceptance_plan(preflight_path: pathlib.Path, *, write: bool = True) -> dict[str, Any] | pathlib.Path:
    old = json.loads(OLD_PLAN.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("counts") != {"requested": 3, "passed": 3, "blocked": 0} or preflight.get("decision") != "split_protocol_passed_3_of_3":
        raise ValueError("frozen v3.4 protocol preflight must pass 3/3")
    manifest = build_contract_manifest()
    if verify_manifest(manifest):
        raise ValueError("v3.5 contract manifest invalid")
    config_hash = file_sha256(CONFIG)
    tasks: list[dict[str, Any]] = []
    old_task_by_run: dict[str, dict[str, Any]] = {}
    bundle_artifacts = [*json.loads(BASE_FINANCIAL_BUNDLE.read_text(encoding="utf-8"))["artifacts"], *manifest["artifacts"]]
    for old_task in old["tasks"]:
        source_card = json.loads((ROOT / old_task["case_path"]).read_text(encoding="utf-8"))
        projection_path = PROJECTION_DIR / f"{source_card['case_id'].replace('-v2', '-v3')}.json"
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        task = {
            "case_id": projection["case_id"],
            "source_case_id": source_card["case_id"],
            "source_case_path": old_task["case_path"],
            "source_case_sha256": file_sha256(ROOT / old_task["case_path"]),
            "projection_path": projection_path.relative_to(ROOT).as_posix(),
            "projection_sha256": file_sha256(projection_path),
            "snapshot_path": old_task["snapshot_path"],
            "snapshot_sha256": file_sha256(ROOT / old_task["snapshot_path"]),
            "family_id": old_task["family_id"],
            "variant_id": old_task["variant_id"],
            "tier": old_task["tier"],
            "track": old_task["track"],
            "run_ids": [],
        }
        tasks.append(task)
        for old_id in old_task["run_ids"]:
            old_task_by_run[old_id] = task
        bundle_artifacts.extend([
            {"path": task["source_case_path"], "sha256": task["source_case_sha256"]},
            {"path": task["snapshot_path"], "sha256": task["snapshot_sha256"]},
        ])
    immutable = build_bundle_sha256(list({item["path"]: item for item in bundle_artifacts}.values()))
    forbidden = _known_run_ids()
    runs: list[dict[str, Any]] = []
    for old_row in old["runs"]:
        task = old_task_by_run[old_row["run_id"]]
        identity = {
            "benchmark_id": "financial-agent-reliability-v3.5",
            "case_id": task["case_id"],
            "harness_config_sha256": config_hash,
            "immutable_bundle_sha256": immutable,
            "repeat": 1,
            "requested_model_id": old_row["model_id"],
            "seed": old_row["seed"],
            "variant_id": task["variant_id"],
        }
        run_id = build_run_id(identity)
        if run_id in forbidden:
            raise AssertionError("v3.5 run id overlaps a prior run")
        task["run_ids"].append(run_id)
        runs.append({
            "sequence": len(runs) + 1,
            "block": old_row["block"],
            "order_in_block": old_row["order_in_block"],
            "family_id": task["family_id"],
            "variant_id": task["variant_id"],
            "model_id": old_row["model_id"],
            "repeat": 1,
            "seed": old_row["seed"],
            "run_id": run_id,
            "run_identity": identity,
        })
    plan = {
        "contract_type": "stage3_financial_acceptance_plan",
        "contract_version": "3.5.0",
        "status": "frozen",
        "authorization": {"issue_id": "45640133-7162-4832-aef6-94d0a3900bd6", "issue_key": "PER-31", "approval_comment_id": "fb2cbcf2-99dc-4c30-82d7-9adf13e81547", "paid_calls_authorized": True, "scope": "12 cases x 3 models x 1 repeat"},
        "run_cap": 36,
        "full_matrix_authorized": False,
        "models_per_task": 3,
        "repeats_per_cell": 1,
        "authoritative_preflight": {"path": preflight_path.relative_to(ROOT).as_posix(), "sha256": file_sha256(preflight_path), "endpoint_id": preflight["endpoint_id"], "counts": preflight["counts"]},
        "contract_bundle": {"path": OUTPUT_BUNDLE.relative_to(ROOT).as_posix(), "sha256": file_sha256(OUTPUT_BUNDLE) if OUTPUT_BUNDLE.is_file() else None, "bundle_sha256": manifest["bundle_sha256"]},
        "immutable_bundle_sha256": immutable,
        "tasks": tasks,
        "runs": runs,
        "acceptance_gate": {"trace_count": 36, "grader_count": 36, "checkpoint_count": 36, "identity_valid": 36, "structured_results": 36, "each_independent_check": 36, "secret_leakage": 0, "unsafe_or_real_side_effect": 0, "fallback_or_invalidated": 0},
    }
    plan["plan_sha256"] = content_sha256(plan)
    if not write:
        return plan
    OUTPUT_PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return OUTPUT_PLAN


def _validate_checkpoint(path: pathlib.Path, run_id: str) -> int:
    previous = "0" * 64
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        stored = event.pop("event_sha256")
        if event.get("run_id") != run_id or event.get("offset") != count or event.get("previous_event_sha256") != previous or content_sha256(event) != stored:
            raise ValueError(f"checkpoint chain invalid: {run_id}")
        previous = stored
        count += 1
    if count < 2:
        raise ValueError(f"checkpoint incomplete: {run_id}")
    return count


def grade_output(plan_path: pathlib.Path, output_dir: pathlib.Path) -> pathlib.Path:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task_by_run = {run_id: task for task in plan["tasks"] for run_id in task["run_ids"]}
    grader_dir = output_dir / "graders"
    grader_dir.mkdir(parents=True, exist_ok=True)
    graders: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    checkpoint_events = 0
    for row in plan["runs"]:
        trace = json.loads((output_dir / "traces" / f"{row['run_id']}.json").read_text(encoding="utf-8"))
        validate_run_trace_v35(trace)
        task = task_by_run[row["run_id"]]
        projection = json.loads((ROOT / task["projection_path"]).read_text(encoding="utf-8"))
        card = json.loads((ROOT / task["source_case_path"]).read_text(encoding="utf-8"))
        expected = {"status": card["oracle"]["expected_status"], "value": card["oracle"]["expected_value"], "reason_codes": card["oracle"]["reason_codes"]}
        candidate = trace["result"]["structured_output"]
        grader = grade_candidate(candidate, projection, expected, trace, parse_error=trace["result"]["parse_error"])
        grader.update({
            "run_id": row["run_id"], "model_id": row["model_id"], "case_id": task["case_id"],
            "identity_valid": trace["provider"]["response_model_id"] == row["model_id"] and trace["preflight"]["identity_match"],
            "provider_status": trace["status"],
            "exact_semantic_match": candidate is not None and candidate["status"] == expected["status"] and canonical(candidate["value"]) == canonical(expected["value"]) and sorted(candidate["reason_codes"]) == sorted(expected["reason_codes"]),
            "cost_usd": None, "cost_status": "provider_response_does_not_supply_cost",
        })
        validate_grader_v3(grader)
        (grader_dir / f"{row['run_id']}.json").write_text(json.dumps(grader, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        checkpoint_events += _validate_checkpoint(output_dir / "checkpoints" / f"{row['run_id']}.jsonl", row["run_id"])
        graders.append(grader)
        traces.append(trace)
    check_names = sorted(graders[0]["checks"]) if graders else []
    summary = {
        "contract_type": "stage3_financial_acceptance_summary", "contract_version": "3.5.0", "status": "completed" if len(graders) == 36 else "partial", "plan_sha256": plan["plan_sha256"],
        "counts": {
            "planned": 36, "traces": len(traces), "graders": len(graders),
            "checkpoints": sum(1 for row in plan["runs"] if (output_dir / "checkpoints" / f"{row['run_id']}.jsonl").is_file()),
            "checkpoint_events": checkpoint_events,
            "identity_valid": sum(item["identity_valid"] for item in graders),
            "structured_results": sum(item["checks"]["structure_parsed"] for item in graders),
            "all_critical_invariants": sum(item["all_critical_invariants_passed"] for item in graders),
            "exact_semantic_match": sum(item["exact_semantic_match"] for item in graders),
            "failed": sum(trace["status"] == "failed" for trace in traces),
            "invalidated": sum(trace["status"] == "invalidated" for trace in traces),
            "fallback": sum(bool(trace["preflight"]["fallback_detected"]) for trace in traces),
            "secret_leakage": sum(bool(trace["redaction"]["secret_leakage_detected"]) for trace in traces),
            "unsafe_or_real_side_effect": sum(bool(trace["environment"]["real_side_effects"]) for trace in traces),
        },
        "by_model": {
            model: {
                "runs": sum(item["model_id"] == model for item in graders),
                "structured_results": sum(item["model_id"] == model and item["checks"]["structure_parsed"] for item in graders),
                "exact_semantic_match": sum(item["model_id"] == model and item["exact_semantic_match"] for item in graders),
                "all_critical_invariants": sum(item["model_id"] == model and item["all_critical_invariants_passed"] for item in graders),
            }
            for model in ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
        },
        "independent_checks": {name: sum(item["checks"][name] for item in graders) for name in check_names},
        "cost_usd": None, "cost_status": "provider_response_does_not_supply_cost",
        "prior_results_preserved": {"v1_1_oracle_match": "0/36", "v3_3_protocol_failure_preserved": True, "retroactively_regraded": False},
    }
    gate = summary["counts"]
    summary["acceptance_gate_passed"] = (
        all(gate[key] == 36 for key in ["traces", "graders", "checkpoints", "identity_valid", "structured_results", "all_critical_invariants"])
        and all(value == 36 for value in summary["independent_checks"].values())
        and all(gate[key] == 0 for key in ["failed", "invalidated", "fallback", "secret_leakage", "unsafe_or_real_side_effect"])
    )
    path = output_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def freeze_evidence(plan_path: pathlib.Path, output_dir: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for relative in ["traces", "graders", "checkpoints"]:
        shutil.copytree(output_dir / relative, destination / relative)
    for source, name in [
        (output_dir / "summary.json", "summary.json"),
        (output_dir / "runtime-summary.json", "runtime-summary.json"),
        (plan_path, "stage3_acceptance_plan.v3.5.json"),
        (OUTPUT_BUNDLE, "stage3_acceptance_contracts.frozen.v3.5.json"),
    ]:
        shutil.copyfile(source, destination / name)
    artifacts = [{"path": path.relative_to(destination).as_posix(), "sha256": file_sha256(path)} for path in sorted(destination.rglob("*")) if path.is_file()]
    manifest = {"contract_type": "stage3_financial_acceptance_evidence_bundle", "contract_version": "3.5.0", "status": "frozen", "bundle_sha256": build_bundle_sha256(artifacts), "artifacts": artifacts}
    manifest_path = destination / "bundle.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze-contracts")
    commands.add_parser("verify-contracts")
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--preflight", required=True)
    grade_parser = commands.add_parser("grade")
    grade_parser.add_argument("--plan", required=True)
    grade_parser.add_argument("--output-dir", required=True)
    freeze_parser = commands.add_parser("freeze-evidence")
    freeze_parser.add_argument("--plan", required=True)
    freeze_parser.add_argument("--output-dir", required=True)
    freeze_parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    if args.command == "freeze-contracts":
        result = freeze_contracts()
    elif args.command == "verify-contracts":
        errors = verify_manifest(json.loads(OUTPUT_BUNDLE.read_text(encoding="utf-8")))
        print(json.dumps({"valid": not errors, "errors": errors}))
        raise SystemExit(0 if not errors else 2)
    elif args.command == "plan":
        result = build_acceptance_plan(ROOT / args.preflight)
    elif args.command == "grade":
        result = grade_output(ROOT / args.plan, ROOT / args.output_dir)
    else:
        result = freeze_evidence(ROOT / args.plan, ROOT / args.output_dir, ROOT / args.destination)
    print(json.dumps({"path": str(pathlib.Path(result).relative_to(ROOT))}))
