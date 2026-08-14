"""PER-77 execution-artifact builder for the v3.11.1 single-unit coverage round.

Deterministic. Builds, into the coverage round directory:
  1. frozen copies of the v3.11.1 coverage plan, the unchanged v3.11 config,
     and the unchanged v3.11 contract bundle;
  2. the plan-bound identity-preflight artifact as a documented carry-over of
     the v3.11 preflight (a1abbba9...d19, itself a PER-63 carry-over of the
     v3.10 preflight 669cbd04...ef3f). The carry-over is justified because the
     v3.11 harness config is byte-identical under this plan (bc19cdaf...), and
     the coverage case's tool-schema vector plus the deepseek-v4-pro parameter
     commitments are unchanged; only plan/plan_core commitments differ, and they
     are outside the preflight's identity elements. No paid preflight calls are
     made;
  3. the paid single-unit coverage authorization artifact binding EXACTLY the
     one preregistered coverage run id under the owner's standing
     authorization, with explicit denial of the invalidated seq 268 run id and
     a reject-out-of-scope rule for every other run id.

The authorization artifact is preregistered with execution_gate pending: the
independent gate re-review must pass and the delivery owner must dispatch the
execution round before this artifact may be consumed. Fails closed on any hash
mismatch. Never reads, prints, or persists secrets.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs" / "stage3" / "coverage-20260814-v3.11.1"

# --- Fail-closed commitments --------------------------------------------------
DECLARED_PLAN_SHA256 = "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b"
DECLARED_PLAN_CORE_SHA256 = "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b"
DECLARED_COVERAGE_RUN_ID = "run_0e1e8f4400e16f22f6581e0bb0d9c54d"
DECLARED_COVERAGE_SEED = 738396034
DECLARED_CONFIG_FILE_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECLARED_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"
DECLARED_V311_PLAN_SHA256 = "c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c"
SOURCE_PREFLIGHT_SHA256 = "a1abbba96f320194411deffc198c7aab87c39ae534004bead9c1c3ca6ffefd19"
SOURCE_PREFLIGHT_PATH = ROOT / "runs" / "stage3" / "acceptance-20260813-v3.11" / "preflight.json"
SOURCE_ENDPOINT_ID = "bailian_98bd231ca931"
V311_PLAN_PATH = ROOT / "contracts" / "stage3_acceptance_plan.v3.11.json"

COVERAGE_CASE_ID = "case-synthetic-ftw-14-normal-v3"
COVERAGE_MODEL_ID = "deepseek-v4-pro"
COVERAGE_REPEAT = 2
INVALIDATED_RUN_ID = "run_c0f58d3c0d9227585058c4e4872a468b"
DECLARED_CASE_TOOL_SCHEMA_SHA256 = "118f9266c47e4fdd4256fb19818fecccb770064fd37726d3c9337ce14b2ba601"
DECLARED_DEEPSEEK_PARAMETERS_SHA256 = "429e4c973a8a474fc428d84f6eba2f766d147f8f0c4a16b57031a66bf7d0f79f"

AUTHORIZATION_BASIS = {
    "issue": "PER-77",
    "parent_issue_id": "45640133-7162-4832-aef6-94d0a3900bd6",
    "paid_authorization_scope": "standing_all_paid_runs_owner_2026_08_12",
    "standing_authorization_recorded_in": "parent issue metadata key paid_authorization_scope",
    "metadata_keys": [
        "candidate_runs_allowed=true",
        "stage3_acceptance_runs_authorized=true",
        "paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12",
    ],
    "delivery_decision_metadata": "stage3_next_decision=per64_single_unit_coverage_then_per32",
    "authorized_on": "2026-08-14",
    "preflight_carry_over": (
        "the v3.11 preflight (a1abbba9...) carries over because the v3.11 harness config "
        "is byte-identical (bc19cdaf...) under the coverage plan and the coverage case's "
        "tool-schema vector plus the deepseek-v4-pro parameter commitments are unchanged; "
        "no paid preflight calls are made in the coverage round"
    ),
}

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


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    plan = json.loads((ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json").read_text(encoding="utf-8"))
    v311_plan = json.loads(V311_PLAN_PATH.read_text(encoding="utf-8"))
    config_path = ROOT / "contracts/run_trace_harness_config.v3.11.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    bundle_path = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"

    # --- frozen-input integrity (fail closed) --------------------------------
    stripped = dict(plan)
    stripped.pop("plan_sha256", None)
    check(plan.get("plan_sha256") == DECLARED_PLAN_SHA256, "coverage plan self-hash matches declared value")
    check(sha256_text(canonical(stripped)) == DECLARED_PLAN_SHA256, "coverage plan content hash recomputed")
    check(plan.get("plan_core_sha256") == DECLARED_PLAN_CORE_SHA256, "coverage plan_core hash matches declared value")
    check(len(plan.get("runs", [])) == 1 and plan.get("coverage_run_cap") == 1, "coverage plan carries exactly 1 run")
    row = plan["runs"][0]
    check(row["run_id"] == DECLARED_COVERAGE_RUN_ID and row["seed"] == DECLARED_COVERAGE_SEED, "coverage run id and seed match declared values")
    check(row["model_id"] == COVERAGE_MODEL_ID and row["repeat"] == COVERAGE_REPEAT and row["run_identity"]["case_id"] == COVERAGE_CASE_ID, "coverage unit is exactly (ftw-14-normal, deepseek-v4-pro, repeat 2)")
    check(row["run_id"] != INVALIDATED_RUN_ID, "coverage run id does not reuse the invalidated seq 268 run id")
    check(plan["coverage_target"]["invalidated_run_id"] == INVALIDATED_RUN_ID, "plan pins the invalidated seq 268 run id")
    check(plan["coverage_target"]["replaces_or_reexecutes_invalidation"] is False, "plan declares no replacement/re-execution of the invalidation")
    check(v311_plan.get("plan_sha256") == DECLARED_V311_PLAN_SHA256, "v3.11 continuation plan hash matches declared value")
    check(sha256_file(config_path) == DECLARED_CONFIG_FILE_SHA256, "config file hash matches declared value (contracts unchanged)")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    check(bundle.get("bundle_sha256") == DECLARED_BUNDLE_SHA256, "contract bundle hash matches declared value (contracts unchanged)")
    check(sha256_text(canonical(bundle["artifacts"])) == DECLARED_BUNDLE_SHA256, "contract bundle artifact-list hash recomputed")
    check(plan["contract_commitments"]["contract_bundle_sha256"] == DECLARED_BUNDLE_SHA256, "plan commits to the unchanged v3.11 bundle")
    check(plan["contract_commitments"]["harness_config_sha256"] == DECLARED_CONFIG_FILE_SHA256, "plan commits to the unchanged v3.11 config")

    # --- carry-over source integrity ------------------------------------------
    source = json.loads(SOURCE_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    source_stripped = dict(source)
    source_stripped.pop("preflight_sha256", None)
    check(source.get("preflight_sha256") == SOURCE_PREFLIGHT_SHA256, "source v3.11 preflight declares the carry-over hash")
    check(sha256_text(canonical(source_stripped)) == SOURCE_PREFLIGHT_SHA256, "source v3.11 preflight self-hash recomputed")
    check(source.get("decision") == "passed_3_of_3" and source.get("counts") == {"requested": 3, "passed": 3, "blocked": 0}, "source preflight is a passing 3-of-3 artifact")
    check(source.get("endpoint_id") == SOURCE_ENDPOINT_ID, "source preflight endpoint id is the carried-over endpoint")
    deepseek_source = next((item for item in source["results"] if item["model_id"] == COVERAGE_MODEL_ID), None)
    check(deepseek_source is not None and deepseek_source["passed"] is True, "source preflight deepseek-v4-pro result passed")
    check(deepseek_source is not None and deepseek_source["parameters_sha256"] == DECLARED_DEEPSEEK_PARAMETERS_SHA256, "source preflight deepseek parameters hash pinned")
    check(config["request_commitments"]["parameters_sha256_by_model"][COVERAGE_MODEL_ID] == DECLARED_DEEPSEEK_PARAMETERS_SHA256, "unchanged config still commits to the same deepseek parameters hash")

    # --- coverage case tool-schema vector unchanged ----------------------------
    coverage_task = plan["tasks"][0]
    v311_task = next(item for item in v311_plan["tasks"] if item["case_id"] == COVERAGE_CASE_ID)
    check(coverage_task["tool_schema_sha256"] == DECLARED_CASE_TOOL_SCHEMA_SHA256, "coverage plan tool-schema vector pinned")
    check(v311_task["tool_schema_sha256"] == DECLARED_CASE_TOOL_SCHEMA_SHA256, "v3.11 plan tool-schema vector identical for the coverage case")
    for key in ["source_case_sha256", "projection_sha256", "snapshot_sha256"]:
        check(coverage_task[key] == v311_task[key], f"coverage case material unchanged: {key}")

    if FAILURES:
        print(f"RESULT: FAIL — {len(FAILURES)} check(s) failed; nothing written")
        return 1

    # --- 1. frozen copies ------------------------------------------------------
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("stage3_acceptance_plan.v3.11.1.json", "run_trace_harness_config.v3.11.json", "stage3_acceptance_contracts.frozen.v3.11.json"):
        shutil.copyfile(ROOT / "contracts" / name, RUN_DIR / name)
        check(sha256_file(RUN_DIR / name) == sha256_file(ROOT / "contracts" / name), f"frozen copy byte-identical: {name}")

    # --- 2. carry-over preflight artifact --------------------------------------
    preflight = {
        "contract_type": "stage3_identity_preflight",
        "contract_version": "3.11.0",
        "plan_sha256": DECLARED_PLAN_SHA256,
        "endpoint_id": SOURCE_ENDPOINT_ID,
        "carry_over": {
            "source_contract_version": "3.11.0",
            "source_preflight_sha256": SOURCE_PREFLIGHT_SHA256,
            "source_preflight_path": "runs/stage3/acceptance-20260813-v3.11/preflight.json",
            "source_chain": (
                "v3.10 preflight 669cbd049177d9c7ae7ea9e25bc9dda2fa6abee996061023477354895063ef3f carried into "
                "v3.11 (validated by the PER-62 independent gate audit and re-verified pre-execution by PER-63); "
                "this artifact carries the v3.11 result forward to the v3.11.1 coverage plan"
            ),
            "paid_calls_in_this_round": 0,
            "results_copied_from_source": True,
            "basis": (
                "the v3.11 harness config is byte-identical under the coverage plan, so the system prompt, "
                "provider retry policy, and per-model parameter commitments bound by the source preflight are "
                "unchanged; the coverage case's tool-schema vector is identical in the v3.11 and v3.11.1 plans; "
                "only plan/plan_core commitments differ, and they are outside the preflight's identity elements"
            ),
            "verified": {
                "source_preflight_self_hash_recomputed": True,
                "harness_config_file_sha256_equal": True,
                "deepseek_parameters_sha256_equal_to_config_commitment": True,
                "coverage_case_tool_schema_vector_equal_between_plans": True,
                "coverage_case_material_hashes_equal_between_plans": True,
                "endpoint_id_equal": True,
            },
        },
        "results": [deepseek_source],
        "counts": {"requested": 1, "passed": 1, "blocked": 0},
        "decision": "passed_1_of_1",
        "raw_provider_response_stored": False,
    }
    preflight["preflight_sha256"] = sha256_text(canonical({k: v for k, v in preflight.items() if k != "preflight_sha256"}))
    write_json(RUN_DIR / "preflight.json", preflight)
    check(True, f"carry-over preflight artifact written (preflight_sha256={preflight['preflight_sha256'][:12]}…)")

    # --- 3. paid single-unit coverage authorization ----------------------------
    authorization = {
        "contract_type": "stage3_run_authorization",
        "authorization_kind": "financial_acceptance_single_unit_coverage_run",
        "paid_calls_authorized": True,
        "execution_gate": {
            "independent_gate_review_required": True,
            "independent_gate_review_status": "pending",
            "delivery_owner_dispatch_required": True,
            "issue": "PER-77",
        },
        "execution_round_dir": "runs/stage3/coverage-20260814-v3.11.1",
        "plan_path": "contracts/stage3_acceptance_plan.v3.11.1.json",
        "plan_sha256": DECLARED_PLAN_SHA256,
        "plan_core_sha256": DECLARED_PLAN_CORE_SHA256,
        "contract_bundle_path": "contracts/stage3_acceptance_contracts.frozen.v3.11.json",
        "contract_bundle_sha256": DECLARED_BUNDLE_SHA256,
        "harness_config_path": "contracts/run_trace_harness_config.v3.11.json",
        "harness_config_sha256": DECLARED_CONFIG_FILE_SHA256,
        "preflight_path": "runs/stage3/coverage-20260814-v3.11.1/preflight.json",
        "preflight_sha256": preflight["preflight_sha256"],
        "exact_model_ids": [COVERAGE_MODEL_ID],
        "authorized_run_ids": [row["run_id"]],
        "authorized_run_count": 1,
        "authorized_unit": {
            "case_id": COVERAGE_CASE_ID,
            "requested_model_id": COVERAGE_MODEL_ID,
            "repeat": COVERAGE_REPEAT,
            "seed": DECLARED_COVERAGE_SEED,
        },
        "denied_run_ids": [INVALIDATED_RUN_ID],
        "denied_scope_note": (
            "the invalidated seq 268 run id must never be executed, reused, replaced, or deleted; "
            "its forensics (invalidated-runs.json, pending-invalidations.json, checkpoint residue) "
            "are preserved permanently"
        ),
        "coverage_replaces_or_reexecutes_invalidation": False,
        "maximum_runs": 1,
        "maximum_model_requests_per_run": 8,
        "out_of_scope_policy": (
            "any run_id not exactly in authorized_run_ids — including all historical v3.5-v3.11 plan "
            "run ids and every denied id — must be rejected by the execution driver before any "
            "provider request"
        ),
        "authorization_basis": AUTHORIZATION_BASIS,
    }
    authorization["authorization_sha256"] = sha256_text(canonical({k: v for k, v in authorization.items() if k != "authorization_sha256"}))
    check(len(authorization["authorized_run_ids"]) == 1 and authorization["authorized_run_ids"][0] == DECLARED_COVERAGE_RUN_ID, "authorization binds exactly the 1 preregistered coverage run id")
    check(INVALIDATED_RUN_ID in authorization["denied_run_ids"], "authorization explicitly denies the invalidated seq 268 run id")
    write_json(RUN_DIR / "authorization.run.json", authorization)
    check(True, "single-unit coverage authorization artifact written")

    print(f"RUN_DIR: {RUN_DIR}")
    print("RESULT: PASS — execution artifacts built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
