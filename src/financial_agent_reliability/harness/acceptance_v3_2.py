"""Freeze, plan, grade, and package the v3.2 generic repair correction."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil

from contracts.run_trace_validator import build_bundle_sha256, build_run_id, file_sha256
from financial_agent_reliability.harness.acceptance_v3 import (
    ROOT,
    OLD_PLAN,
    PROJECTION_DIR,
    _validate_checkpoint,
    canonical,
    content_sha256,
    grade_candidate,
)


CORRECTION = ROOT / "contracts" / "run_trace_harness_config.v3.2.json"
BASE_BUNDLE = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.1.json"
BASE_V3_BUNDLE = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.json"


def freeze_contracts() -> pathlib.Path:
    paths = [
        CORRECTION,
        ROOT / "contracts" / "run_trace.schema.v3.2.json",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "live_acceptance_v3_2.mjs",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "acceptance_v3_2.py",
        ROOT / "tests" / "integration" / "acceptance_v3_2.test.mjs",
        ROOT / "runs" / "stage3" / "acceptance-20260811-v3.1" / "preflight.v3.1.json",
    ]
    artifacts = [{"path": path.relative_to(ROOT).as_posix(), "sha256": file_sha256(path)} for path in paths]
    base = json.loads(BASE_BUNDLE.read_text(encoding="utf-8"))
    base_v3 = json.loads(BASE_V3_BUNDLE.read_text(encoding="utf-8"))
    manifest = {
        "contract_type": "stage3_acceptance_contract_correction_bundle",
        "contract_version": "3.2.0",
        "status": "frozen_before_preflight",
        "base_bundle": {"path": BASE_BUNDLE.relative_to(ROOT).as_posix(), "sha256": file_sha256(BASE_BUNDLE), "bundle_sha256": base["bundle_sha256"]},
        "rationale": "preserve failed v3.1 exactly and add one fixed model-neutral repair round when no valid submission is recorded",
        "artifacts": artifacts,
        "bundle_sha256": build_bundle_sha256([*base_v3["artifacts"], *base["artifacts"], *artifacts]),
        "model_specific_changes": False,
    }
    path = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.2.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_plan(preflight_path: pathlib.Path) -> pathlib.Path:
    old = json.loads(OLD_PLAN.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("counts", {}).get("passed") != 3:
        raise ValueError("v3.2 requires 3/3 preflight")
    manifest_path = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    correction_hash = file_sha256(CORRECTION)
    tasks: list[dict] = []
    old_task_by_run: dict[str, dict] = {}
    task_by_old_run: dict[str, dict] = {}
    base_artifacts = [
        *json.loads(BASE_V3_BUNDLE.read_text(encoding="utf-8"))["artifacts"],
        *json.loads(BASE_BUNDLE.read_text(encoding="utf-8"))["artifacts"],
    ]
    bundle_artifacts = [*base_artifacts, *manifest["artifacts"]]
    for old_task in old["tasks"]:
        source = json.loads((ROOT / old_task["case_path"]).read_text(encoding="utf-8"))
        projection_path = PROJECTION_DIR / f"{source['case_id'].replace('-v2', '-v3')}.json"
        task = {
            "case_id": source["case_id"].replace("-v2", "-v3"),
            "source_case_path": old_task["case_path"],
            "source_case_sha256": file_sha256(ROOT / old_task["case_path"]),
            "projection_path": projection_path.relative_to(ROOT).as_posix(),
            "projection_sha256": file_sha256(projection_path),
            "snapshot_path": old_task["snapshot_path"],
            "snapshot_sha256": file_sha256(ROOT / old_task["snapshot_path"]),
            "family_id": old_task["family_id"], "variant_id": old_task["variant_id"], "tier": old_task["tier"], "track": old_task["track"], "run_ids": [],
        }
        tasks.append(task)
        for old_id in old_task["run_ids"]:
            old_task_by_run[old_id] = old_task
            task_by_old_run[old_id] = task
        bundle_artifacts.extend([{"path": task["source_case_path"], "sha256": task["source_case_sha256"]}, {"path": task["snapshot_path"], "sha256": task["snapshot_sha256"]}])
    unique = {item["path"]: item for item in bundle_artifacts}
    bundle_hash = build_bundle_sha256(list(unique.values()))
    old_ids = {row["run_id"] for row in old["runs"]}
    runs = []
    for old_row in old["runs"]:
        task = task_by_old_run[old_row["run_id"]]
        identity = {"benchmark_id":"financial-agent-reliability-v3.2","case_id":task["case_id"],"harness_config_sha256":correction_hash,"immutable_bundle_sha256":bundle_hash,"repeat":1,"requested_model_id":old_row["model_id"],"seed":old_row["seed"],"variant_id":task["variant_id"]}
        run_id = build_run_id(identity)
        if run_id in old_ids:
            raise AssertionError("run ID overlaps v1.1")
        task["run_ids"].append(run_id)
        runs.append({"sequence":len(runs)+1,"block":old_row["block"],"order_in_block":old_row["order_in_block"],"family_id":task["family_id"],"variant_id":task["variant_id"],"model_id":old_row["model_id"],"repeat":1,"seed":old_row["seed"],"run_id":run_id,"run_identity":identity})
    plan = {
        "contract_type":"stage3_acceptance_plan","contract_version":"3.2.0","status":"frozen",
        "supersedes":{"v1_1_plan":{"path":OLD_PLAN.relative_to(ROOT).as_posix(),"sha256":file_sha256(OLD_PLAN),"retroactive_regrading":False},"failed_v3_1_preflight":{"path":"runs/stage3/acceptance-20260811-v3.1/preflight.v3.1.json","sha256":file_sha256(ROOT / "runs/stage3/acceptance-20260811-v3.1/preflight.v3.1.json")}},
        "authorization":old["authorization"],"run_cap":36,"full_matrix_authorized":False,"models_per_task":3,"repeats_per_cell":1,
        "authoritative_preflight":{"path":preflight_path.relative_to(ROOT).as_posix(),"sha256":file_sha256(preflight_path),"endpoint_id":preflight["endpoint_id"],"counts":preflight["counts"]},
        "contract_bundle":{"path":manifest_path.relative_to(ROOT).as_posix(),"sha256":file_sha256(manifest_path),"bundle_sha256":manifest["bundle_sha256"]},
        "immutable_bundle_sha256":bundle_hash,"tasks":tasks,"runs":runs,
        "acceptance_gate":{"trace_count":36,"grader_count":36,"checkpoint_count":36,"identity_valid":36,"structured_results":36,"each_independent_check":36,"secret_leakage":0,"unsafe_or_real_side_effect":0,"fallback_or_invalidated":0},
    }
    plan["plan_sha256"] = content_sha256(plan)
    path = ROOT / "contracts" / "stage3_acceptance_plan.v3.2.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def grade(plan_path: pathlib.Path, output_dir: pathlib.Path) -> pathlib.Path:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tasks = {run_id: task for task in plan["tasks"] for run_id in task["run_ids"]}
    graders = []
    traces = []
    (output_dir / "graders").mkdir(parents=True, exist_ok=True)
    for row in plan["runs"]:
        trace = json.loads((output_dir / "traces" / f"{row['run_id']}.json").read_text(encoding="utf-8"))
        if trace["contract_version"] != "3.2.0" or trace["run_id"] != build_run_id(trace["run_identity"]): raise ValueError("trace identity invalid")
        if trace["run_identity"]["harness_config_sha256"] != file_sha256(CORRECTION): raise ValueError("correction hash mismatch")
        task = tasks[row["run_id"]]
        projection = json.loads((ROOT / task["projection_path"]).read_text(encoding="utf-8"))
        card = json.loads((ROOT / task["source_case_path"]).read_text(encoding="utf-8"))
        expected = {"status":card["oracle"]["expected_status"],"value":card["oracle"]["expected_value"],"reason_codes":card["oracle"]["reason_codes"]}
        candidate = trace["result"]["structured_output"]
        grader = grade_candidate(candidate, projection, expected, trace, parse_error=trace["result"]["parse_error"])
        grader.update({"run_id":row["run_id"],"model_id":row["model_id"],"case_id":task["case_id"],"identity_valid":trace["provider"]["response_model_id"] == row["model_id"] and trace["preflight"]["identity_match"],"provider_status":trace["status"],"exact_semantic_match":candidate is not None and candidate["status"] == expected["status"] and canonical(candidate["value"]) == canonical(expected["value"]) and sorted(candidate["reason_codes"]) == sorted(expected["reason_codes"]),"cost_usd":None,"cost_status":"provider_response_does_not_supply_cost"})
        (output_dir / "graders" / f"{row['run_id']}.json").write_text(json.dumps(grader, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _validate_checkpoint(output_dir / "checkpoints" / f"{row['run_id']}.jsonl", row["run_id"])
        graders.append(grader); traces.append(trace)
    names = sorted(graders[0]["checks"])
    counts = {"planned":36,"traces":len(traces),"graders":len(graders),"checkpoints":sum((output_dir / "checkpoints" / f"{row['run_id']}.jsonl").is_file() for row in plan["runs"]),"identity_valid":sum(item["identity_valid"] for item in graders),"structured_results":sum(item["checks"]["structure_parsed"] for item in graders),"all_critical_invariants":sum(item["all_critical_invariants_passed"] for item in graders),"exact_semantic_match":sum(item["exact_semantic_match"] for item in graders),"invalidated":sum(item["status"] == "invalidated" for item in traces),"fallback":sum(item["preflight"]["fallback_detected"] for item in traces),"secret_leakage":sum(item["redaction"]["secret_leakage_detected"] for item in traces),"unsafe_or_real_side_effect":sum(item["environment"]["real_side_effects"] for item in traces)}
    checks = {name:sum(item["checks"][name] for item in graders) for name in names}
    passed = all(counts[key] == 36 for key in ["traces","graders","checkpoints","identity_valid","structured_results","all_critical_invariants"]) and all(value == 36 for value in checks.values()) and all(counts[key] == 0 for key in ["invalidated","fallback","secret_leakage","unsafe_or_real_side_effect"])
    summary = {"contract_type":"stage3_acceptance_summary","contract_version":"3.2.0","status":"completed","plan_sha256":plan["plan_sha256"],"counts":counts,"independent_checks":checks,"acceptance_gate_passed":passed,"cost_usd":None,"cost_status":"provider_response_does_not_supply_cost","v1_1_result_preserved":{"oracle_match":"0/36","retroactively_regraded":False,"source_bundle_sha256":"f35874cee12ab31e10aee21a8614c67414a70f60e8604f373fb6a41f646df2ef"}}
    path = output_dir / "summary.json"; path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return path


def freeze(plan_path: pathlib.Path, output_dir: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    if destination.exists(): raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for relative in ["traces", "graders", "checkpoints"]: shutil.copytree(output_dir / relative, destination / relative)
    for source, name in [(output_dir / "summary.json", "summary.json"),(output_dir / "runtime-summary.json", "runtime-summary.json"),(plan_path, "stage3_acceptance_plan.v3.2.json"),(ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.2.json", "stage3_acceptance_contracts.frozen.v3.2.json")]: shutil.copyfile(source, destination / name)
    artifacts = [{"path":path.relative_to(destination).as_posix(),"sha256":file_sha256(path)} for path in sorted(destination.rglob("*")) if path.is_file()]
    manifest = {"contract_type":"stage3_acceptance_evidence_bundle","contract_version":"3.2.0","status":"frozen","bundle_sha256":build_bundle_sha256(artifacts),"artifacts":artifacts}
    path = destination / "bundle.manifest.json"; path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True); sub.add_parser("freeze-contracts"); p = sub.add_parser("plan"); p.add_argument("--preflight", required=True); g = sub.add_parser("grade"); g.add_argument("--plan", required=True); g.add_argument("--output-dir", required=True); f = sub.add_parser("freeze-evidence"); f.add_argument("--plan", required=True); f.add_argument("--output-dir", required=True); f.add_argument("--destination", required=True); args = parser.parse_args()
    if args.command == "freeze-contracts": result = freeze_contracts()
    elif args.command == "plan": result = build_plan(ROOT / args.preflight)
    elif args.command == "grade": result = grade(ROOT / args.plan, ROOT / args.output_dir)
    else: result = freeze(ROOT / args.plan, ROOT / args.output_dir, ROOT / args.destination)
    print(json.dumps({"path":str(result.relative_to(ROOT))}))
