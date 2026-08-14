"""PER-77 pre-execution identity check (clean-room, independent of harness code).

Re-derives, from the frozen formulas alone, the single v3.11.1 coverage run
identity (case-synthetic-ftw-14-normal-v3 / deepseek-v4-pro / repeat 2) and
verifies it against the frozen v3.11.1 plan; reconstructs plan_core; proves the
v3.11 contracts (bundle + config) are byte-unchanged; confirms the seq 268
invalidation forensics are preserved and never replaced; confirms the coverage
identity differs from the invalidated seq 268 identity in the plan_core
commitment only; checks disjointness against every historical v3.5-v3.11 plan
run id; and verifies the authorization artifact binds exactly the one
authorized run id. Fails closed on any mismatch.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- Declared commitments (from the PER-77 freeze) ----------------------------
DECLARED_PLAN_SHA256 = "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b"
DECLARED_PLAN_CORE_SHA256 = "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b"
DECLARED_COVERAGE_RUN_ID = "run_0e1e8f4400e16f22f6581e0bb0d9c54d"
DECLARED_COVERAGE_SEED = 738396034
DECLARED_CONFIG_FILE_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECLARED_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"
DECLARED_V311_PLAN_SHA256 = "c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c"
DECLARED_V311_PLAN_CORE_SHA256 = "559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604"
DECLARED_V311_INVALIDATED_RUNS_FILE_SHA256 = "7fd165fa26f83ea925a782c77c81b235fb1665496fb457df6d665547ef8547a7"
DECLARED_V311_INVALIDATION_REPORT_SHA256 = "3a5189e7ffb4ad093b6508fcb6319bc68248a21de9a70c019685db5849868bda"
DECLARED_PENDING_INVALIDATIONS_FILE_SHA256 = "61c7baecab626a5559702bd8e77a4c2f700dbbd6cdff17102a30fe83fb147946"
DECLARED_CHECKPOINT_RESIDUE_SHA256 = "68f0e73854ae6341fe829037eaf2ff1a2b560dcbd2b9cfbca8f302e4d28c85b6"
COVERAGE_CASE_ID = "case-synthetic-ftw-14-normal-v3"
COVERAGE_MODEL_ID = "deepseek-v4-pro"
COVERAGE_REPEAT = 2
INVALIDATED_RUN_ID = "run_c0f58d3c0d9227585058c4e4872a468b"

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILURES.append(label)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_seed(benchmark_id: str, case_id: str, master_seed: int, repeat: int, model_id: str) -> int:
    identity = {
        "benchmark_id": benchmark_id,
        "case_id": case_id,
        "master_seed": master_seed,
        "repeat": repeat,
        "requested_model_id": model_id,
    }
    return int(sha256_text(canonical(identity))[:16], 16) % 2**32


def main() -> int:
    plan = json.loads((ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json").read_text(encoding="utf-8"))
    v311_plan = json.loads((ROOT / "contracts/stage3_acceptance_plan.v3.11.json").read_text(encoding="utf-8"))
    config_path = ROOT / "contracts/run_trace_harness_config.v3.11.json"
    bundle_path = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"

    # 1. frozen input hashes (contracts unchanged)
    check(plan.get("plan_sha256") == DECLARED_PLAN_SHA256, "coverage plan_sha256 matches declared value")
    plan_stripped = dict(plan)
    plan_stripped.pop("plan_sha256", None)
    check(sha256_text(canonical(plan_stripped)) == DECLARED_PLAN_SHA256, "coverage plan_sha256 recomputed from canonical content")
    check(plan.get("plan_core_sha256") == DECLARED_PLAN_CORE_SHA256, "coverage plan_core_sha256 matches declared value")
    check(v311_plan.get("plan_sha256") == DECLARED_V311_PLAN_SHA256, "v3.11 continuation plan_sha256 unchanged")
    check(v311_plan.get("plan_core_sha256") == DECLARED_V311_PLAN_CORE_SHA256, "v3.11 continuation plan_core_sha256 unchanged")
    check(sha256_file(config_path) == DECLARED_CONFIG_FILE_SHA256, "v3.11 config file hash unchanged")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    check(bundle.get("bundle_sha256") == DECLARED_BUNDLE_SHA256, "v3.11 contract bundle_sha256 unchanged")
    check(sha256_text(canonical(bundle["artifacts"])) == DECLARED_BUNDLE_SHA256, "v3.11 bundle_sha256 recomputed from artifact list")
    for item in bundle.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            check(False, f"v3.11 artifact drift: {item['path']}")
            break
    else:
        check(True, "all v3.11 bundle artifacts byte-exact on disk")
    check(plan["contract_commitments"]["contract_bundle_sha256"] == DECLARED_BUNDLE_SHA256 and plan["contract_commitments"]["harness_config_sha256"] == DECLARED_CONFIG_FILE_SHA256, "plan commits to the unchanged bundle + config hashes")
    check(plan["contract_commitments"]["contracts_changed"] is False, "plan declares zero contract change")

    # 2. supersedes points exactly at the v3.11 continuation plan
    supersedes = plan["supersedes"]
    check(supersedes["path"] == "contracts/stage3_acceptance_plan.v3.11.json" and supersedes["plan_sha256"] == DECLARED_V311_PLAN_SHA256, "supersedes targets the v3.11 continuation plan")

    # 3. plan_core clean-room reconstruction
    design = plan["replication_design"]
    core = {
        "contract_version": "3.11.0",
        "config_sha256": sha256_file(config_path),
        "models": plan["fairness"]["models"],
        "task_inputs": [
            {key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for task in sorted(plan["tasks"], key=lambda item: item["case_id"])
        ],
    }
    check(sha256_text(canonical(core)) == DECLARED_PLAN_CORE_SHA256, "coverage plan_core independently reconstructed")
    check(plan["fairness"]["models"] == [COVERAGE_MODEL_ID], "plan registers exactly the one coverage model")

    # 4. the plan carries exactly one task and one run; identity re-derived
    check(len(plan["tasks"]) == 1 and len(plan["runs"]) == 1, "exactly 1 task and 1 run")
    check(plan.get("coverage_run_cap") == 1 and plan.get("registered_total_run_cap") == 1, "run caps are exactly 1")
    row = plan["runs"][0]
    task = plan["tasks"][0]
    check(row["sequence"] == 1 and row["model_id"] == COVERAGE_MODEL_ID and row["repeat"] == COVERAGE_REPEAT, "run row is the coverage unit at sequence 1")
    check(task["case_id"] == COVERAGE_CASE_ID and row["run_id"] in task["run_ids"], "task row is the coverage case and binds the run")
    seed = derive_seed(design["benchmark_id"], COVERAGE_CASE_ID, design["master_seed"], COVERAGE_REPEAT, COVERAGE_MODEL_ID)
    check(design["master_seed"] == 20260813 and design["benchmark_id"] == "financial-agent-reliability-v3.11", "master_seed and benchmark_id unchanged")
    check(seed == DECLARED_COVERAGE_SEED == row["seed"], "coverage seed re-derived from the unchanged formula (equals seq 268 seed)")
    rebuilt_identity = {
        "benchmark_id": design["benchmark_id"],
        "case_id": COVERAGE_CASE_ID,
        "harness_config_sha256": sha256_file(config_path),
        "plan_core_sha256": DECLARED_PLAN_CORE_SHA256,
        "repeat": COVERAGE_REPEAT,
        "requested_model_id": COVERAGE_MODEL_ID,
        "seed": seed,
        "variant_id": row["run_identity"]["variant_id"],
    }
    check("run_" + sha256_text(canonical(rebuilt_identity))[:32] == DECLARED_COVERAGE_RUN_ID == row["run_id"], "coverage run_id re-derived exactly")
    check(row["run_identity"] == rebuilt_identity, "plan run_identity equals the clean-room identity")

    # 5. identity separation from the invalidated seq 268 identity: plan_core only
    forensics_path = ROOT / "runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json"
    check(sha256_file(forensics_path) == DECLARED_V311_INVALIDATED_RUNS_FILE_SHA256, "v3.11 invalidated-runs.json forensics hash preserved")
    forensics = json.loads(forensics_path.read_text(encoding="utf-8"))
    check(forensics.get("report_sha256") == DECLARED_V311_INVALIDATION_REPORT_SHA256, "invalidation report_sha256 preserved")
    entry = forensics["entries"][0]
    seq268_identity = entry["run_identity"]
    diffs = {key for key in seq268_identity if seq268_identity[key] != rebuilt_identity[key]}
    check(diffs == {"plan_core_sha256"}, "coverage identity differs from seq 268 identity ONLY in plan_core_sha256")
    check(seq268_identity["plan_core_sha256"] == DECLARED_V311_PLAN_CORE_SHA256, "seq 268 identity keeps the v3.11 plan_core commitment")
    check(entry["replaced_or_reexecuted"] is False, "seq 268 remains unreplaced in the forensics")
    check(entry["seed"] == DECLARED_COVERAGE_SEED, "seq 268 forensics seed equals the coverage seed")
    checkpoint_path = ROOT / "runs/stage3/acceptance-20260813-v3.11/checkpoints" / f"{INVALIDATED_RUN_ID}.jsonl"
    check(sha256_file(checkpoint_path) == DECLARED_CHECKPOINT_RESIDUE_SHA256, "seq 268 checkpoint residue preserved")
    pending_path = ROOT / "runs/stage3/acceptance-20260813-v3.11/pending-invalidations.json"
    check(sha256_file(pending_path) == DECLARED_PENDING_INVALIDATIONS_FILE_SHA256, "seq 268 pending-invalidations preserved")
    check(plan["coverage_target"]["invalidated_run_id"] == INVALIDATED_RUN_ID and plan["coverage_target"]["invalidated_sequence"] == 268, "plan pins the invalidated run id and sequence")
    check(plan["coverage_target"]["replaces_or_reexecutes_invalidation"] is False and plan["coverage_target"]["invalidated_run_id_reuse_forbidden"] is True, "plan forbids replacing/reusing the invalidated run id")
    mapping = plan["coverage_map"][row["run_id"]]
    check(mapping["invalidated_run_id"] == INVALIDATED_RUN_ID and mapping["replaces_or_reexecutes"] is False, "coverage_map links the new run to seq 268 without replacement")

    # 6. disjointness against ALL historical v3.5-v3.11 plan run ids
    historical: set[str] = set()
    for version in ["3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11"]:
        old = json.loads((ROOT / f"contracts/stage3_acceptance_plan.v{version}.json").read_text(encoding="utf-8"))
        historical.update(item["run_id"] for item in old["runs"])
    check(len(historical) == 1540, f"historical universe covers all v3.5-v3.11 plans ({len(historical)} ids)")
    check(INVALIDATED_RUN_ID in historical, "seq 268 run id is part of the historical universe")
    check(row["run_id"] not in historical, "coverage run id disjoint from all historical plan ids")
    check(row["run_id"] != INVALIDATED_RUN_ID, "coverage run id does not reuse the invalidated run id")

    # 7. authorization artifact binds exactly the one run id
    run_dir = ROOT / "runs/stage3/coverage-20260814-v3.11.1"
    authorization = json.loads((run_dir / "authorization.run.json").read_text(encoding="utf-8"))
    auth_stripped = dict(authorization)
    auth_stripped.pop("authorization_sha256", None)
    check(authorization.get("authorization_sha256") == sha256_text(canonical(auth_stripped)), "authorization self-hash recomputed")
    check(authorization["authorization_kind"] == "financial_acceptance_single_unit_coverage_run", "authorization kind is the single-unit coverage kind")
    check(authorization["authorized_run_ids"] == [DECLARED_COVERAGE_RUN_ID] and authorization["authorized_run_count"] == 1, "authorization authorizes exactly the 1 coverage run id")
    check(authorization["denied_run_ids"] == [INVALIDATED_RUN_ID], "authorization denies exactly the invalidated seq 268 run id")
    check(authorization["plan_sha256"] == DECLARED_PLAN_SHA256 and authorization["plan_core_sha256"] == DECLARED_PLAN_CORE_SHA256, "authorization binds the coverage plan + plan_core hashes")
    check(authorization["contract_bundle_sha256"] == DECLARED_BUNDLE_SHA256 and authorization["harness_config_sha256"] == DECLARED_CONFIG_FILE_SHA256, "authorization binds the unchanged contract hashes")
    check(authorization["exact_model_ids"] == [COVERAGE_MODEL_ID], "authorization scope is the single coverage model")
    check(authorization["authorized_unit"] == {"case_id": COVERAGE_CASE_ID, "requested_model_id": COVERAGE_MODEL_ID, "repeat": COVERAGE_REPEAT, "seed": DECLARED_COVERAGE_SEED}, "authorization binds the exact coverage unit")
    check(authorization["coverage_replaces_or_reexecutes_invalidation"] is False, "authorization preserves the no-replacement discipline")
    check(authorization["execution_gate"]["independent_gate_review_status"] == "pending", "execution gate is pending independent review")
    preflight = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
    preflight_stripped = dict(preflight)
    preflight_stripped.pop("preflight_sha256", None)
    check(preflight.get("preflight_sha256") == sha256_text(canonical(preflight_stripped)), "preflight self-hash recomputed")
    check(authorization["preflight_sha256"] == preflight["preflight_sha256"], "authorization binds the carry-over preflight hash")
    check(preflight["plan_sha256"] == DECLARED_PLAN_SHA256, "preflight binds the coverage plan hash")
    check(preflight["carry_over"]["paid_calls_in_this_round"] == 0 and preflight["decision"] == "passed_1_of_1", "preflight carry-over made no paid calls and passes for the coverage model")

    # 8. authorization scope template export
    out = ROOT / "audit" / "v3_11_1_coverage_authorized_run_ids.json"
    out.write_text(json.dumps([DECLARED_COVERAGE_RUN_ID], indent=0) + "\n", encoding="utf-8")
    check(True, "1 authorized run id exported for artifact binding")

    print()
    if FAILURES:
        print(f"RESULT: FAIL — {len(FAILURES)} check(s) failed")
        return 1
    print("RESULT: PASS — pre-execution coverage identity verification green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
