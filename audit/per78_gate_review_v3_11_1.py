"""PER-78 independent gate re-review of the v3.11.1 single-unit coverage plan.

Clean-room, stdlib-only. Imports NO harness / contracts module: every hash,
seed, run id, and self-hash is recomputed from the frozen primitives
(canonical JSON = sorted keys, compact separators, ensure_ascii=False — the
frozen definition) and compared against the implementation-side declared
values. Fails closed on any mismatch. Read-only: writes nothing.

Sections:
  A  plan/plan_core hashes, structure, supersedes chain (v3.11.1 -> v3.5)
  B  contract zero-change: v3.11 bundle/config double-check, v3.5-v3.10 zero drift
  C  no post-hoc selection: seed/run id re-derivation, identity delta vs seq 268,
     disjointness vs the full historical run id universe, forensics preserved
  D  authorization artifact + preflight carry-over chain (v3.10 -> v3.11 -> v3.11.1)
  E  frozen copies in the coverage round dir byte-identical to contracts/
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# --- Implementation-side declared values (PER-77 freeze declaration) ---------
DECL_PLAN_SHA256 = "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b"
DECL_PLAN_CORE_SHA256 = "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b"
DECL_COVERAGE_RUN_ID = "run_0e1e8f4400e16f22f6581e0bb0d9c54d"
DECL_COVERAGE_SEED = 738396034
DECL_CONFIG_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECL_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"
DECL_V311_PLAN_SHA256 = "c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c"
DECL_V311_PLAN_CORE_SHA256 = "559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604"
DECL_V311_PREFLIGHT_SHA256 = "a1abbba96f320194411deffc198c7aab87c39ae534004bead9c1c3ca6ffefd19"
DECL_V310_PREFLIGHT_SHA256 = "669cbd049177d9c7ae7ea9e25bc9dda2fa6abee996061023477354895063ef3f"
DECL_FORENSICS_FILE_SHA256 = "7fd165fa26f83ea925a782c77c81b235fb1665496fb457df6d665547ef8547a7"
DECL_INVALIDATION_REPORT_SHA256 = "3a5189e7ffb4ad093b6508fcb6319bc68248a21de9a70c019685db5849868bda"
DECL_PENDING_INVALIDATIONS_SHA256 = "61c7baecab626a5559702bd8e77a4c2f700dbbd6cdff17102a30fe83fb147946"
DECL_CHECKPOINT_RESIDUE_SHA256 = "68f0e73854ae6341fe829037eaf2ff1a2b560dcbd2b9cfbca8f302e4d28c85b6"
DECL_DEEPSEEK_PARAMETERS_SHA256 = "429e4c973a8a474fc428d84f6eba2f766d147f8f0c4a16b57031a66bf7d0f79f"
DECL_CASE_TOOL_SCHEMA_SHA256 = "118f9266c47e4fdd4256fb19818fecccb770064fd37726d3c9337ce14b2ba601"
# Prior-bundle baselines pinned by the parent-issue metadata (owner baseline),
# cross-checked with the PER-62 independent gate audit report.
PARENT_METADATA_BUNDLE_SHA256 = {
    "3.6": "afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959",
    "3.7": "354e8413e5f3d65351c819a84344435451a27c6b50be7982b77d9f76804bfc44",
    "3.8": "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609",
    "3.9": "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030",
    "3.10": "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180",
    "3.11": "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d",
}
# v3.5 bundle baseline as recorded by the PER-59 v3.6 independent gate audit era
# ledger (historical lineage commitment; v3.5 uses its historical bundle recipe).
V35_BUNDLE_SHA256 = "d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8"

CASE_ID = "case-synthetic-ftw-14-normal-v3"
MODEL_ID = "deepseek-v4-pro"
REPEAT = 2
INVALIDATED_RUN_ID = "run_c0f58d3c0d9227585058c4e4872a468b"
BENCHMARK_ID = "financial-agent-reliability-v3.11"
MASTER_SEED = 20260813

FAILURES: list[str] = []
PASSES = 0


def check(ok: bool, label: str) -> bool:
    global PASSES
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}")
    if ok:
        PASSES += 1
    else:
        FAILURES.append(label)
    return ok


def canonical(value: object) -> str:
    # Frozen definition: sorted keys, compact separators, non-ASCII preserved.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def csha(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fsha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def strip(value: dict, key: str) -> dict:
    out = dict(value)
    out.pop(key, None)
    return out


def main() -> int:
    plan_path = ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json"
    v311_plan_path = ROOT / "contracts/stage3_acceptance_plan.v3.11.json"
    config_path = ROOT / "contracts/run_trace_harness_config.v3.11.json"
    bundle_path = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"
    run_dir = ROOT / "runs/stage3/coverage-20260814-v3.11.1"
    v311_run_dir = ROOT / "runs/stage3/acceptance-20260813-v3.11"

    plan = load(plan_path)
    v311_plan = load(v311_plan_path)
    config = load(config_path)
    bundle = load(bundle_path)

    print("== A. plan / plan_core hashes, structure, supersedes chain ==")
    check(plan.get("plan_sha256") == DECL_PLAN_SHA256, "A1 plan declares the frozen plan_sha256")
    check(csha(strip(plan, "plan_sha256")) == DECL_PLAN_SHA256, "A2 plan_sha256 recomputed from canonical content (any field tamper breaks)")
    check(plan.get("plan_version") == "3.11.1" and plan.get("contract_version") == "3.11.0", "A3 plan-only version bump: plan_version 3.11.1, contract_version stays 3.11.0")
    check(plan.get("plan_kind") == "single_unit_coverage" and plan.get("status") == "frozen_offline_validated", "A4 plan kind/status correct")
    check(len(plan.get("tasks", [])) == 1 and len(plan.get("runs", [])) == 1, "A5 exactly 1 task and 1 run")
    check(plan.get("coverage_run_cap") == 1 and plan.get("registered_total_run_cap") == 1, "A6 run caps both exactly 1")
    task = plan["tasks"][0]
    row = plan["runs"][0]
    check(task["case_id"] == CASE_ID and row["model_id"] == MODEL_ID and row["repeat"] == REPEAT and row["sequence"] == 1, "A7 the single unit is exactly the seq 268 unit (case/model/repeat)")
    check(row["run_id"] == DECL_COVERAGE_RUN_ID and row["run_id"] in task["run_ids"] and len(task["run_ids"]) == 1, "A8 run row binds the declared coverage run id")
    # plan_core reconstruction from frozen primitives
    core = {
        "contract_version": "3.11.0",
        "config_sha256": fsha(config_path),
        "models": [MODEL_ID],
        "task_inputs": [{k: task[k] for k in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}],
    }
    check(csha(core) == DECL_PLAN_CORE_SHA256, "A9 plan_core_sha256 independently reconstructed")
    check(plan.get("plan_core_sha256") == DECL_PLAN_CORE_SHA256, "A10 plan declares the same plan_core_sha256")
    # supersedes chain: v3.11.1 -> v3.11 -> ... -> v3.5
    sup = plan["supersedes"]
    check(sup["path"] == "contracts/stage3_acceptance_plan.v3.11.json" and sup["plan_sha256"] == DECL_V311_PLAN_SHA256, "A11 supersedes targets the v3.11 continuation plan with its content hash")
    check(sup["sha256"] == fsha(v311_plan_path), "A12 supersedes.sha256 equals the measured v3.11 plan file hash")
    check(csha(strip(v311_plan, "plan_sha256")) == DECL_V311_PLAN_SHA256, "A13 v3.11 plan self-hash recomputed (file unmodified)")
    check(v311_plan.get("plan_core_sha256") == DECL_V311_PLAN_CORE_SHA256, "A14 v3.11 plan_core_sha256 unchanged")
    # Owner-baseline plan-hash pins (parent issue metadata) close the loop:
    # pointer == metadata pin == recomputed content hash.
    METADATA_PLAN_PINS = {
        "contracts/stage3_acceptance_plan.v3.10.json": "009b1ea126b462bf873a555dbc7ced91b900d88728d94e5d208ee3a95c3ed4ec",
        "contracts/stage3_acceptance_plan.v3.9.json": "235b0415bf43c356a5f2c3801a7793606ed5e943a5e8ce60f0aa3b20abeeb185",
        "contracts/stage3_acceptance_plan.v3.8.json": "636d94fbb6d08d58adfd018dfba6115bb44ac193480a5380e3228c623a4c3d22",
        "contracts/stage3_acceptance_plan.v3.7.json": "aa17d6bedb283663b24d50b42ac475c9bba61597a183f7524314b65cad90acd3",
        "contracts/stage3_acceptance_plan.v3.6.json": "7874bd77c0862a797bcde2f88851b89041ee12dd71e2dd50a1764dbd502844b1",
    }
    chain_ok, chain_hops, cursor = True, [], v311_plan
    for expected_path in [
        "contracts/stage3_acceptance_plan.v3.10.json",
        "contracts/stage3_acceptance_plan.v3.9.json",
        "contracts/stage3_acceptance_plan.v3.8.json",
        "contracts/stage3_acceptance_plan.v3.7.json",
        "contracts/stage3_acceptance_plan.v3.6.json",
        "contracts/stage3_acceptance_plan.v3.5.json",
    ]:
        s = cursor.get("supersedes") or {}
        target = ROOT / s.get("path", "")
        if s.get("path") != expected_path or not target.is_file() or s.get("sha256") != fsha(target):
            chain_ok = False
            break
        cursor = load(target)
        # v3.5-v3.11 plans carry no plan_version field; pin each hop by
        # recomputing the content self-hash against the pointer's plan_sha256.
        if "plan_sha256" in s and s["plan_sha256"] != csha(strip(cursor, "plan_sha256")):
            chain_ok = False
            break
        if expected_path in METADATA_PLAN_PINS and s.get("plan_sha256") != METADATA_PLAN_PINS[expected_path]:
            chain_ok = False
            break
        chain_hops.append(expected_path)
    check(chain_ok and len(chain_hops) == 6, f"A15 supersedes chain v3.11 -> v3.10 -> ... -> v3.5 continuous ({len(chain_hops)} hops), file + self-hash verified at every hop")
    check(cursor.get("supersedes") is None, "A16 v3.5 is the plan-chain root (supersedes null)")

    print("== B. contract zero-change (v3.11 double-check; v3.5-v3.10 zero drift) ==")
    check(fsha(config_path) == DECL_CONFIG_SHA256, "B1 v3.11 config file hash unchanged")
    check(bundle.get("bundle_sha256") == DECL_BUNDLE_SHA256, "B2 v3.11 bundle_sha256 field unchanged")
    check(csha(bundle["artifacts"]) == DECL_BUNDLE_SHA256, "B3 bundle_sha256 recomputed from artifact list (double-check)")
    drift = [a["path"] for a in bundle["artifacts"] if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
    check(not drift, f"B4 all {len(bundle['artifacts'])} v3.11 bundle artifacts byte-exact on disk" + (f" (drift: {drift})" if drift else ""))
    # config commitments carried by the bundle match the config file
    cfg_in_bundle = next(a for a in bundle["artifacts"] if a["path"] == "contracts/run_trace_harness_config.v3.11.json")
    check(cfg_in_bundle["sha256"] == DECL_CONFIG_SHA256, "B5 bundle pins the same config hash")
    check(plan["contract_commitments"]["contract_bundle_sha256"] == DECL_BUNDLE_SHA256 and plan["contract_commitments"]["harness_config_sha256"] == DECL_CONFIG_SHA256, "B6 plan commits to the unchanged bundle + config")
    check(plan["contract_commitments"]["contracts_changed"] is False and plan["contract_commitments"]["prompt_oracle_threshold_reason_case_material_unchanged"] is True, "B7 plan declares zero contract / prompt / oracle / threshold / reason / material change")
    # v3.5-v3.10 zero drift: each frozen bundle self-consistent + hash pinned by parent metadata baseline
    for version in ["3.6", "3.7", "3.8", "3.9", "3.10"]:
        old_bundle = load(ROOT / f"contracts/stage3_acceptance_contracts.frozen.v{version}.json")
        ok_field = old_bundle.get("bundle_sha256") == PARENT_METADATA_BUNDLE_SHA256[version]
        ok_self = csha(old_bundle["artifacts"]) == old_bundle.get("bundle_sha256")
        bad = [a["path"] for a in old_bundle["artifacts"] if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
        check(ok_field and ok_self and not bad, f"B8 v{version} frozen bundle: baseline hash + artifact-list recomputation + {len(old_bundle['artifacts'])} on-disk artifact hashes" + (f" (drift: {bad})" if bad else ""))
    v35_bundle = load(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.5.json")
    v35_bad = [a["path"] for a in v35_bundle["artifacts"] if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
    check(v35_bundle.get("bundle_sha256") == V35_BUNDLE_SHA256 and not v35_bad, f"B9 v3.5 frozen bundle: lineage baseline hash + {len(v35_bundle['artifacts'])} on-disk artifact hashes" + (f" (drift: {v35_bad})" if v35_bad else ""))

    print("== C. no post-hoc selection (identity delta, seed, disjointness, forensics) ==")
    # seed re-derivation from the unchanged frozen formula
    seed = int(csha({"benchmark_id": BENCHMARK_ID, "case_id": CASE_ID, "master_seed": MASTER_SEED, "repeat": REPEAT, "requested_model_id": MODEL_ID})[:16], 16) % 2**32
    check(seed == DECL_COVERAGE_SEED == row["seed"], "C1 seed re-derived from unchanged formula = 738396034 (equals seq 268 seed)")
    check(plan["replication_design"]["master_seed"] == MASTER_SEED and plan["replication_design"]["benchmark_id"] == BENCHMARK_ID, "C2 master_seed 20260813 and benchmark_id v3.11 unchanged")
    # run id re-derivation
    identity = {
        "benchmark_id": BENCHMARK_ID,
        "case_id": CASE_ID,
        "harness_config_sha256": fsha(config_path),
        "plan_core_sha256": DECL_PLAN_CORE_SHA256,
        "repeat": REPEAT,
        "requested_model_id": MODEL_ID,
        "seed": seed,
        "variant_id": row["run_identity"]["variant_id"],
    }
    check("run_" + csha(identity)[:32] == DECL_COVERAGE_RUN_ID, "C3 coverage run_id re-derived exactly")
    check(row["run_identity"] == identity, "C4 plan run_identity equals the clean-room identity")
    # seq 268 ground truth from the frozen v3.11 plan and the forensics
    seq268_rows = [r for r in v311_plan["runs"] if r["sequence"] == 268]
    check(len(seq268_rows) == 1 and seq268_rows[0]["run_id"] == INVALIDATED_RUN_ID, "C5 v3.11 plan sequence 268 is exactly the invalidated run")
    seq268 = seq268_rows[0]
    check(seq268["model_id"] == MODEL_ID and seq268["repeat"] == REPEAT and seq268["seed"] == DECL_COVERAGE_SEED, "C6 seq 268 unit fields equal the coverage unit")
    forensics_path = v311_run_dir / "invalidated-runs.json"
    check(fsha(forensics_path) == DECL_FORENSICS_FILE_SHA256, "C7 invalidated-runs.json file hash preserved")
    forensics = load(forensics_path)
    check(forensics.get("report_sha256") == csha(strip(forensics, "report_sha256")) == DECL_INVALIDATION_REPORT_SHA256, "C8 invalidation report self-hash recomputed and preserved")
    check(len(forensics["entries"]) == 1, "C9 forensics hold exactly one entry")
    entry = forensics["entries"][0]
    check(entry["run_identity"] == seq268["run_identity"], "C10 forensics identity equals the v3.11 plan seq 268 identity")
    diffs = {k for k in seq268["run_identity"] if seq268["run_identity"][k] != identity[k]} | {k for k in identity if k not in seq268["run_identity"]}
    check(diffs == {"plan_core_sha256"}, f"C11 coverage identity differs from seq 268 ONLY in plan_core_sha256 (diff={sorted(diffs)})")
    check(seq268["run_identity"]["plan_core_sha256"] == DECL_V311_PLAN_CORE_SHA256, "C12 seq 268 keeps the v3.11 plan_core commitment")
    check(entry["replaced_or_reexecuted"] is False, "C13 seq 268 remains unreplaced in the forensics")
    check(plan["coverage_target"]["invalidated_run_id"] == INVALIDATED_RUN_ID and plan["coverage_target"]["invalidated_sequence"] == 268 and plan["coverage_target"]["invalidated_seed"] == DECL_COVERAGE_SEED, "C14 plan pins the invalidated run id / sequence / seed")
    check(plan["coverage_target"]["replaces_or_reexecutes_invalidation"] is False and plan["coverage_target"]["invalidated_run_id_reuse_forbidden"] is True, "C15 plan forbids replacing/reusing the invalidated id")
    mapping = plan["coverage_map"]
    check(list(mapping) == [DECL_COVERAGE_RUN_ID] and mapping[DECL_COVERAGE_RUN_ID]["invalidated_run_id"] == INVALIDATED_RUN_ID and mapping[DECL_COVERAGE_RUN_ID]["source_sequence"] == 268 and mapping[DECL_COVERAGE_RUN_ID]["replaces_or_reexecutes"] is False, "C16 coverage_map links the new run to seq 268 without replacement")
    check(fsha(v311_run_dir / "pending-invalidations.json") == DECL_PENDING_INVALIDATIONS_SHA256, "C17 pending-invalidations.json preserved")
    check(fsha(v311_run_dir / "checkpoints" / f"{INVALIDATED_RUN_ID}.jsonl") == DECL_CHECKPOINT_RESIDUE_SHA256, "C18 seq 268 checkpoint residue preserved")
    # historical universe disjointness
    historical: list[str] = []
    per_plan_counts: dict[str, int] = {}
    for version in ["3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11"]:
        rows = load(ROOT / f"contracts/stage3_acceptance_plan.v{version}.json")["runs"]
        per_plan_counts[version] = len(rows)
        historical.extend(r["run_id"] for r in rows)
    uniq = set(historical)
    check(len(historical) == len(uniq), f"C19 historical run ids internally unique ({len(historical)} rows)")
    check(len(uniq) == 1540, f"C20 historical universe size = 1540 (got {len(uniq)}; per-plan {per_plan_counts})")
    check(INVALIDATED_RUN_ID in uniq, "C21 seq 268 run id is inside the historical universe")
    check(DECL_COVERAGE_RUN_ID not in uniq, "C22 coverage run id disjoint from all 1540 historical plan run ids")
    check(DECL_COVERAGE_RUN_ID != INVALIDATED_RUN_ID, "C23 coverage run id does not reuse the invalidated id")
    # checkpoint payload cross-check: the run_started event committed to the v3.11 plan hash and tool-schema vector
    terminal = entry["checkpoint_forensics"]["terminal_event"]
    check(terminal["event_type"] == "run_started" and entry["checkpoint_forensics"]["event_count"] == 1, "C24 checkpoint forensics hold only run_started (mid-unit teardown)")
    check(terminal["payload"]["plan_sha256"] == DECL_V311_PLAN_SHA256 and terminal["payload"]["tool_schema_sha256"] == DECL_CASE_TOOL_SCHEMA_SHA256, "C25 checkpoint payload binds the v3.11 plan hash and the coverage case tool-schema vector")

    print("== D. authorization artifact + preflight carry-over chain ==")
    auth = load(run_dir / "authorization.run.json")
    check(auth.get("authorization_sha256") == csha(strip(auth, "authorization_sha256")), "D1 authorization self-hash recomputed")
    check(auth["authorization_kind"] == "financial_acceptance_single_unit_coverage_run" and auth["contract_type"] == "stage3_run_authorization", "D2 authorization kind correct")
    check(auth["authorized_run_ids"] == [DECL_COVERAGE_RUN_ID] and auth["authorized_run_count"] == 1 and auth["maximum_runs"] == 1, "D3 exactly 1 authorized run id / count / maximum_runs")
    check(auth["exact_model_ids"] == [MODEL_ID], "D4 exact_model_ids is exactly [deepseek-v4-pro]")
    check(auth["denied_run_ids"] == [INVALIDATED_RUN_ID], "D5 denied_run_ids is exactly the invalidated seq 268 id")
    check(auth["coverage_replaces_or_reexecutes_invalidation"] is False, "D6 authorization keeps no-replacement discipline")
    check(auth["plan_sha256"] == DECL_PLAN_SHA256 and auth["plan_core_sha256"] == DECL_PLAN_CORE_SHA256, "D7 authorization binds the recomputed plan + plan_core hashes")
    check(auth["contract_bundle_sha256"] == DECL_BUNDLE_SHA256 and auth["harness_config_sha256"] == DECL_CONFIG_SHA256, "D8 authorization binds the unchanged bundle + config hashes")
    check(auth["authorized_unit"] == {"case_id": CASE_ID, "requested_model_id": MODEL_ID, "repeat": REPEAT, "seed": DECL_COVERAGE_SEED}, "D9 authorized_unit is exactly the coverage unit")
    gate = auth["execution_gate"]
    check(gate["independent_gate_review_required"] is True and gate["independent_gate_review_status"] == "pending" and gate["delivery_owner_dispatch_required"] is True, "D10 execution gate: independent review required, status pending, dispatch required")
    check(auth["paid_calls_authorized"] is True and auth["plan_path"] == "contracts/stage3_acceptance_plan.v3.11.1.json", "D11 paid authorization artifact binds the v3.11.1 plan path")
    basis = auth["authorization_basis"]
    check(basis["issue"] == "PER-77" and basis["parent_issue_id"] == "45640133-7162-4832-aef6-94d0a3900bd6" and basis["paid_authorization_scope"] == "standing_all_paid_runs_owner_2026_08_12", "D12 authorization basis cites PER-77 / parent issue / standing owner scope")
    budget = config["resource_budget"]
    check(auth["maximum_model_requests_per_run"] == budget["max_model_requests"], f"D13 per-run request cap ({auth['maximum_model_requests_per_run']}) equals frozen config max_model_requests ({budget['max_model_requests']})")
    # preflight carry-over chain: coverage <- v3.11 <- v3.10
    preflight = load(run_dir / "preflight.json")
    check(preflight.get("preflight_sha256") == csha(strip(preflight, "preflight_sha256")), "D14 coverage preflight self-hash recomputed")
    check(auth["preflight_sha256"] == preflight["preflight_sha256"], "D15 authorization binds the carry-over preflight hash")
    check(preflight["plan_sha256"] == DECL_PLAN_SHA256 and preflight["contract_version"] == "3.11.0", "D16 preflight binds the coverage plan hash under contract 3.11.0")
    check(preflight["decision"] == "passed_1_of_1" and preflight["counts"] == {"requested": 1, "passed": 1, "blocked": 0}, "D17 preflight passes 1 of 1 for the coverage model")
    check(preflight["carry_over"]["paid_calls_in_this_round"] == 0 and preflight["carry_over"]["results_copied_from_source"] is True, "D18 zero paid preflight calls in the coverage round")
    source_preflight = load(v311_run_dir / "preflight.json")
    check(source_preflight.get("preflight_sha256") == csha(strip(source_preflight, "preflight_sha256")) == DECL_V311_PREFLIGHT_SHA256, "D19 v3.11 source preflight self-hash recomputed (a1abbba9...)")
    check(preflight["carry_over"]["source_preflight_sha256"] == DECL_V311_PREFLIGHT_SHA256, "D20 carry-over cites the v3.11 source preflight")
    src_deepseek = next((r for r in source_preflight["results"] if r["model_id"] == MODEL_ID), None)
    cov_deepseek = preflight["results"][0] if len(preflight["results"]) == 1 else None
    check(src_deepseek is not None and cov_deepseek is not None and cov_deepseek == src_deepseek and src_deepseek.get("passed") is True, "D21 coverage preflight result is byte-equal to the source deepseek-v4-pro result (passed)")
    check(cov_deepseek is not None and cov_deepseek.get("parameters_sha256") == DECL_DEEPSEEK_PARAMETERS_SHA256, "D22 deepseek parameters commitment pinned (429e4c97...)")
    check(config["request_commitments"]["parameters_sha256_by_model"][MODEL_ID] == DECL_DEEPSEEK_PARAMETERS_SHA256, "D23 unchanged config commits to the same deepseek parameters hash")
    check(preflight["endpoint_id"] == source_preflight.get("endpoint_id"), "D24 endpoint id carried over unchanged")
    # one more chain hop: v3.11 preflight is itself the carry-over of the v3.10 preflight
    v310_preflight_candidates = sorted((v311_run_dir.parent / "acceptance-20260813-v3.10").glob("preflight*.json"))
    if check(bool(v310_preflight_candidates), "D25 v3.10 preflight artifact located"):
        v310_preflight = load(v310_preflight_candidates[0])
        check(v310_preflight.get("preflight_sha256") == csha(strip(v310_preflight, "preflight_sha256")) == DECL_V310_PREFLIGHT_SHA256, "D26 v3.10 preflight self-hash recomputed (669cbd04...)")
        src_ds_v310 = next((r for r in v310_preflight["results"] if r["model_id"] == MODEL_ID), None)
        check(src_ds_v310 is not None and src_ds_v310 == src_deepseek, "D27 deepseek preflight result identical across v3.10 -> v3.11 (parameters + endpoint commitments unchanged)")
    # case material + tool-schema vector equality between the two plans
    v311_task = next(t for t in v311_plan["tasks"] if t["case_id"] == CASE_ID)
    for key in ["source_case_path", "source_case_sha256", "projection_path", "projection_sha256", "snapshot_path", "snapshot_sha256", "family_id", "variant_id", "tier", "track", "tool_schema_sha256"]:
        check(task[key] == v311_task[key], f"D28 coverage task row field equals frozen v3.11 task row: {key}")
    for key in ["source_case_path", "projection_path", "snapshot_path"]:
        check(fsha(ROOT / task[key]) == task[key.replace("_path", "_sha256")], f"D29 case material on disk matches committed hash: {task[key]}")
    check(task["tool_schema_sha256"] == DECL_CASE_TOOL_SCHEMA_SHA256, "D30 tool-schema vector equals the declared 118f9266... vector")

    print("== E. frozen copies in the coverage round dir ==")
    for name in ["stage3_acceptance_plan.v3.11.1.json", "run_trace_harness_config.v3.11.json", "stage3_acceptance_contracts.frozen.v3.11.json"]:
        check(fsha(run_dir / name) == fsha(ROOT / "contracts" / name), f"E1 frozen copy byte-identical to contracts/: {name}")
    check(fsha(run_dir / "stage3_acceptance_plan.v3.11.1.json") == fsha(plan_path) and load(run_dir / "stage3_acceptance_plan.v3.11.1.json").get("plan_sha256") == DECL_PLAN_SHA256, "E2 round-dir plan copy carries the frozen plan_sha256")

    print()
    print(f"PASSES: {PASSES}; FAILURES: {len(FAILURES)}")
    if FAILURES:
        for f in FAILURES:
            print(f"  FAILED: {f}")
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
