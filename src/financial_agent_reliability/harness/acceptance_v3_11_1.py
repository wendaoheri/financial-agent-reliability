"""Single-unit coverage plan v3.11.1 for the PER-77 seq 268 runtime incident.

PER-77 covers exactly one unit lost to an agent-runtime failure in the v3.11
550-run continuation round: sequence 268
(``run_c0f58d3c0d9227585058c4e4872a468b``, deepseek-v4-pro /
case-synthetic-ftw-14-normal-v3 / repeat 2) was torn down by the agent runtime
(session teardown) mid-unit with only a ``run_started`` checkpoint event, and
was invalidated report-only under the frozen ``no_post_hoc_selection`` policy
(forensics: ``runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json``).

Scope discipline (identical to the PER-61 v3.11 supersession):
- Zero contract change. The v3.11 contract bundle
  (``b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d``) and the
  v3.11 harness config
  (``bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e``) remain
  byte-exact. Only the plan version moves: this module freezes
  ``contracts/stage3_acceptance_plan.v3.11.1.json``, whose ``supersedes`` points
  at the v3.11 continuation plan.
- The new plan carries exactly ONE task/run: the invalidated unit
  (case-synthetic-ftw-14-normal-v3, deepseek-v4-pro, repeat 2). The seed is
  re-derived from the unchanged frozen formula with the unchanged master seed
  (20260813), so it equals the invalidated seq 268 seed 738396034; identity
  separation comes exclusively from the new ``plan_core_sha256`` commitment,
  never from reselecting case, model, repeat, or seed.
- ``coverage_replaces_or_reexecutes_invalidation`` is false: the seq 268
  forensics (invalidated-runs.json, pending-invalidations.json, checkpoint
  residue) are preserved permanently; the coverage run never replaces, deletes,
  or reuses the invalidated run id.
- No paid calls, no candidate/model requests, no preflight, no secret reads:
  offline plan construction and validation only. Execution happens in a later
  round under the standing owner authorization, after the independent gate
  re-review, via the single-run authorization artifact built by
  ``audit/build_stage3_v3_11_1_execution_artifacts.py``.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from contracts.run_trace_validator_v3_8 import build_run_id, content_sha256, file_sha256
from financial_agent_reliability.harness.acceptance_v3_7 import tool_schemas_v37
from financial_agent_reliability.harness.acceptance_v3_10 import VARIANT_IDS, case_card_index, projection_case_id, read_json, write_json
from financial_agent_reliability.harness.acceptance_v3_11 import (
    BENCHMARK_ID,
    CONFIG_PATH,
    BUNDLE_PATH,
    CONTRACT_VERSION,
    MASTER_SEED,
    PLAN_PATH as V311_PLAN_PATH,
    derive_seed,
    validate_contract_bundle,
    visibility_gate_errors,
)


ROOT = pathlib.Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json"
PROJECTION_DIR = ROOT / "cases/candidate_v3_11"
V311_RUN_DIR = ROOT / "runs/stage3/acceptance-20260813-v3.11"
V310_RUN_DIR = ROOT / "runs/stage3/acceptance-20260813-v3.10"

PLAN_VERSION = "3.11.1"
PLAN_KIND = "single_unit_coverage"

# --- The invalidated unit (PER-63 continuation round, seq 268) --------------
COVERAGE_CASE_ID = "case-synthetic-ftw-14-normal-v3"
COVERAGE_MODEL_ID = "deepseek-v4-pro"
COVERAGE_REPEAT = 2
INVALIDATED_RUN_ID = "run_c0f58d3c0d9227585058c4e4872a468b"
INVALIDATED_SEQUENCE = 268

# --- Fail-closed commitments to the unchanged v3.11 contracts ----------------
DECLARED_V311_PLAN_SHA256 = "c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c"
DECLARED_V311_PLAN_CORE_SHA256 = "559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604"
DECLARED_CONFIG_FILE_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECLARED_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"

# --- Fail-closed commitments to the seq 268 invalidation forensics -----------
DECLARED_INVALIDATED_SEED = 738396034
DECLARED_V311_INVALIDATED_RUNS_FILE_SHA256 = "7fd165fa26f83ea925a782c77c81b235fb1665496fb457df6d665547ef8547a7"
DECLARED_V311_INVALIDATION_REPORT_SHA256 = "3a5189e7ffb4ad093b6508fcb6319bc68248a21de9a70c019685db5849868bda"
DECLARED_PENDING_INVALIDATIONS_FILE_SHA256 = "61c7baecab626a5559702bd8e77a4c2f700dbbd6cdff17102a30fe83fb147946"
DECLARED_CHECKPOINT_RESIDUE_SHA256 = "68f0e73854ae6341fe829037eaf2ff1a2b560dcbd2b9cfbca8f302e4d28c85b6"
CHECKPOINT_RESIDUE_PATH = V311_RUN_DIR / "checkpoints" / f"{INVALIDATED_RUN_ID}.jsonl"
INVALIDATED_RUNS_PATH = V311_RUN_DIR / "invalidated-runs.json"
PENDING_INVALIDATIONS_PATH = V311_RUN_DIR / "pending-invalidations.json"

# --- The unit's two already-valid sibling records ----------------------------
UNIT_REPEAT1_RECORD = {
    "round": "runs/stage3/acceptance-20260813-v3.10",
    "plan_version": "3.10.0",
    "sequence": 258,
    "run_id": "run_6da1eb9e6d67f7e98028259ecd3ba7f7",
    "trace_sha256": "9edcccd01cf5c4811d3199651126165fe9de807837352f2f80c17b62925fdd3b",
}
UNIT_REPEAT3_RECORD = {
    "round": "runs/stage3/acceptance-20260813-v3.11",
    "plan_version": "3.11.0",
    "sequence": 538,
    "run_id": "run_04971ef1d91a20a739ed0b7ab70f3a7e",
    "trace_sha256": "1436bc4008b3c1cbef61beefbf1cd37b3ea366269364df234c19017eef18e50a",
}

# --- Fail-closed commitments to the derived coverage identity ----------------
# These are the deterministic outputs of the unchanged seed formula plus the new
# single-task plan_core; pinning them makes any frozen-input drift fail loudly.
DECLARED_COVERAGE_SEED = 738396034
DECLARED_COVERAGE_PLAN_CORE_SHA256 = "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b"
DECLARED_COVERAGE_RUN_ID = "run_0e1e8f4400e16f22f6581e0bb0d9c54d"
COVERAGE_RUN_COUNT = 1

HISTORICAL_PLAN_VERSIONS = ["3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11"]


class CoveragePlanError(ValueError):
    pass


def _fail_closed(errors: list[str]) -> None:
    if errors:
        raise CoveragePlanError("; ".join(errors))


def frozen_input_errors() -> list[str]:
    """Pre-write integrity checks on every frozen input this plan depends on."""
    errors: list[str] = []
    v311_plan = read_json(V311_PLAN_PATH)
    if v311_plan.get("plan_sha256") != DECLARED_V311_PLAN_SHA256:
        errors.append("v3.11 plan_sha256 drift")
    if v311_plan.get("plan_core_sha256") != DECLARED_V311_PLAN_CORE_SHA256:
        errors.append("v3.11 plan_core_sha256 drift")
    if file_sha256(CONFIG_PATH) != DECLARED_CONFIG_FILE_SHA256:
        errors.append("v3.11 harness config drift")
    bundle = read_json(BUNDLE_PATH)
    if bundle.get("bundle_sha256") != DECLARED_BUNDLE_SHA256:
        errors.append("v3.11 contract bundle drift")
    if content_sha256(bundle.get("artifacts", [])) != DECLARED_BUNDLE_SHA256:
        errors.append("v3.11 contract bundle artifact-list mismatch")
    forensics = read_json(INVALIDATED_RUNS_PATH)
    if file_sha256(INVALIDATED_RUNS_PATH) != DECLARED_V311_INVALIDATED_RUNS_FILE_SHA256:
        errors.append("v3.11 invalidated-runs.json drift")
    if forensics.get("report_sha256") != DECLARED_V311_INVALIDATION_REPORT_SHA256:
        errors.append("v3.11 invalidation report_sha256 drift")
    if file_sha256(PENDING_INVALIDATIONS_PATH) != DECLARED_PENDING_INVALIDATIONS_FILE_SHA256:
        errors.append("v3.11 pending-invalidations.json drift")
    if file_sha256(CHECKPOINT_RESIDUE_PATH) != DECLARED_CHECKPOINT_RESIDUE_SHA256:
        errors.append("seq 268 checkpoint residue drift")
    entries = forensics.get("entries", [])
    if len(entries) != 1:
        errors.append("v3.11 invalidation forensics must hold exactly the seq 268 entry")
    else:
        entry = entries[0]
        if (
            entry.get("run_id") != INVALIDATED_RUN_ID
            or entry.get("sequence") != INVALIDATED_SEQUENCE
            or entry.get("case_id") != COVERAGE_CASE_ID
            or entry.get("model_id") != COVERAGE_MODEL_ID
            or entry.get("repeat") != COVERAGE_REPEAT
            or entry.get("seed") != DECLARED_INVALIDATED_SEED
            or entry.get("replaced_or_reexecuted") is not False
        ):
            errors.append("seq 268 forensics entry does not match the coverage target")
    for record, repeat in ((UNIT_REPEAT1_RECORD, 1), (UNIT_REPEAT3_RECORD, 3)):
        trace_path = ROOT / record["round"] / "traces" / f"{record['run_id']}.json"
        if not trace_path.is_file() or file_sha256(trace_path) != record["trace_sha256"]:
            errors.append(f"unit repeat-{repeat} trace drift:{record['run_id']}")
        else:
            trace = read_json(trace_path)
            identity = trace.get("run_identity", {})
            if (
                trace.get("status") != "succeeded"
                or identity.get("case_id") != COVERAGE_CASE_ID
                or identity.get("requested_model_id") != COVERAGE_MODEL_ID
                or identity.get("repeat") != repeat
            ):
                errors.append(f"unit repeat-{repeat} trace identity mismatch:{record['run_id']}")
    return errors


def coverage_task_row() -> dict[str, Any]:
    """The single task row, rebuilt from disk exactly as v3.11 built it."""
    entry = next(item for item in case_card_index() if projection_case_id(item["card"]) == COVERAGE_CASE_ID)
    projection_path = PROJECTION_DIR / f"{COVERAGE_CASE_ID}.json"
    return {
        "case_id": COVERAGE_CASE_ID,
        "source_case_path": entry["card_path"].relative_to(ROOT).as_posix(),
        "source_case_sha256": file_sha256(entry["card_path"]),
        "projection_path": projection_path.relative_to(ROOT).as_posix(),
        "projection_sha256": file_sha256(projection_path),
        "snapshot_path": entry["snapshot_path"].relative_to(ROOT).as_posix(),
        "snapshot_sha256": file_sha256(entry["snapshot_path"]),
        "family_id": entry["family_id"],
        "variant_id": VARIANT_IDS[entry["variant"]],
        "tier": entry["card"]["quality"]["tier"],
        "track": entry["track"],
        "tool_schema_sha256": content_sha256(tool_schemas_v37(read_json(projection_path))),
        "run_ids": [],
    }


def build_coverage_plan(*, write: bool = True) -> dict[str, Any]:
    _fail_closed(frozen_input_errors())
    v311_plan = read_json(V311_PLAN_PATH)
    config_hash = file_sha256(CONFIG_PATH)

    task = coverage_task_row()
    v311_task = next(item for item in v311_plan["tasks"] if item["case_id"] == COVERAGE_CASE_ID)
    same_inputs = {key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256", "variant_id", "family_id", "tier", "track"]}
    if same_inputs != {key: v311_task[key] for key in same_inputs}:
        raise CoveragePlanError("coverage task inputs differ from the frozen v3.11 task row")

    core = {
        "contract_version": CONTRACT_VERSION,
        "config_sha256": config_hash,
        "models": [COVERAGE_MODEL_ID],
        "task_inputs": [{key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}],
    }
    core_hash = content_sha256(core)
    if core_hash != DECLARED_COVERAGE_PLAN_CORE_SHA256:
        raise CoveragePlanError(f"plan_core drift: {core_hash}")

    seed = derive_seed(COVERAGE_CASE_ID, COVERAGE_MODEL_ID, COVERAGE_REPEAT)
    if seed != DECLARED_COVERAGE_SEED:
        raise CoveragePlanError(f"coverage seed drift: {seed}")
    identity = {
        "benchmark_id": BENCHMARK_ID,
        "case_id": COVERAGE_CASE_ID,
        "harness_config_sha256": config_hash,
        "plan_core_sha256": core_hash,
        "repeat": COVERAGE_REPEAT,
        "requested_model_id": COVERAGE_MODEL_ID,
        "seed": seed,
        "variant_id": task["variant_id"],
    }
    run_id = build_run_id(identity)
    if run_id != DECLARED_COVERAGE_RUN_ID:
        raise CoveragePlanError(f"coverage run id drift: {run_id}")
    if run_id == INVALIDATED_RUN_ID:
        raise CoveragePlanError("coverage run id must never equal the invalidated seq 268 run id")
    _fail_closed(run_id_collision_errors(run_id))

    task["run_ids"].append(run_id)
    row = {"sequence": 1, "model_id": COVERAGE_MODEL_ID, "repeat": COVERAGE_REPEAT, "seed": seed, "run_id": run_id, "run_identity": identity}
    forensics_reason = read_json(INVALIDATED_RUNS_PATH)["entries"][0]["reason"]
    plan = {
        "contract_type": "stage3_financial_acceptance_plan",
        "contract_version": CONTRACT_VERSION,
        "plan_version": PLAN_VERSION,
        "plan_kind": PLAN_KIND,
        "status": "frozen_offline_validated",
        "supersedes": {
            "path": "contracts/stage3_acceptance_plan.v3.11.json",
            "sha256": file_sha256(V311_PLAN_PATH),
            "plan_sha256": DECLARED_V311_PLAN_SHA256,
            "rationale": (
                "PER-77 single-unit coverage: v3.11 continuation sequence 268 "
                "(deepseek-v4-pro / case-synthetic-ftw-14-normal-v3 / repeat 2) was torn "
                "down by the agent runtime mid-unit and invalidated report-only under the "
                "frozen no_post_hoc_selection policy; this plan supersedes the v3.11 "
                "continuation plan for exactly that one unit. Contracts are unchanged: the "
                "v3.11 bundle and harness config remain byte-exact."
            ),
        },
        "contract_commitments": {
            "contract_bundle_path": "contracts/stage3_acceptance_contracts.frozen.v3.11.json",
            "contract_bundle_sha256": DECLARED_BUNDLE_SHA256,
            "harness_config_path": "contracts/run_trace_harness_config.v3.11.json",
            "harness_config_sha256": DECLARED_CONFIG_FILE_SHA256,
            "contracts_changed": False,
            "prompt_oracle_threshold_reason_case_material_unchanged": True,
        },
        "coverage_target": {
            "issue": "PER-77",
            "source_round_path": "runs/stage3/acceptance-20260813-v3.11",
            "source_plan_sha256": DECLARED_V311_PLAN_SHA256,
            "invalidated_run_id": INVALIDATED_RUN_ID,
            "invalidated_sequence": INVALIDATED_SEQUENCE,
            "case_id": COVERAGE_CASE_ID,
            "model_id": COVERAGE_MODEL_ID,
            "repeat": COVERAGE_REPEAT,
            "invalidated_seed": DECLARED_INVALIDATED_SEED,
            "invalidation_reason": forensics_reason,
            "unit_valid_records": {"repeat_1": UNIT_REPEAT1_RECORD, "repeat_3": UNIT_REPEAT3_RECORD},
            "coverage_repeat": COVERAGE_REPEAT,
            "replaces_or_reexecutes_invalidation": False,
            "invalidated_run_id_reuse_forbidden": True,
            "requirement": (
                "the v0.1 confirmed scope requires at least 3 valid repeats per (case, model) "
                "unit; PER-32 pass^3 and ranking stability need this third valid repeat"
            ),
        },
        "authorization": {
            "paid_calls_authorized": False,
            "execution_state": "offline_validation_only",
            "separate_plan_bound_authorization_required": True,
            "passing_identity_preflight_required": True,
        },
        "coverage_run_cap": COVERAGE_RUN_COUNT,
        "registered_total_run_cap": COVERAGE_RUN_COUNT,
        "replication_design": {
            "master_seed": MASTER_SEED,
            "benchmark_id": BENCHMARK_ID,
            "kind": PLAN_KIND,
            "seed_derivation": (
                "seed = int(sha256(canonical_json({benchmark_id, case_id, master_seed, repeat, requested_model_id}))[:16], 16) mod 2^32; "
                "canonical_json sorts keys, uses compact separators, and preserves non-ASCII; the derivation is order-independent; "
                "the formula continues v3.5-v3.11 unchanged with the v3.11 benchmark id"
            ),
            "coverage_seed": seed,
            "seed_continuity_note": (
                "the coverage seed is re-derived from the unchanged frozen formula with the "
                "unchanged master_seed and the v3.11 benchmark id, so it equals the "
                "invalidated seq 268 seed; identity separation from seq 268 comes exclusively "
                "from the new plan_core_sha256 commitment of this superseding plan, never from "
                "reselecting case, model, repeat, or seed"
            ),
            "no_post_hoc_selection": True,
            "invalidation_policy": (
                "invalidated units are reported against their frozen identities; replacements require a new plan version "
                "and are never silently reselected"
            ),
            "v3_11_seq268_invalidation_forensics": {
                "preserved": True,
                "invalidated_runs_path": "runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json",
                "invalidated_runs_file_sha256": DECLARED_V311_INVALIDATED_RUNS_FILE_SHA256,
                "invalidation_report_sha256": DECLARED_V311_INVALIDATION_REPORT_SHA256,
                "pending_invalidations_path": "runs/stage3/acceptance-20260813-v3.11/pending-invalidations.json",
                "pending_invalidations_file_sha256": DECLARED_PENDING_INVALIDATIONS_FILE_SHA256,
                "checkpoint_residue_path": "runs/stage3/acceptance-20260813-v3.11/checkpoints/run_c0f58d3c0d9227585058c4e4872a468b.jsonl",
                "checkpoint_residue_sha256": DECLARED_CHECKPOINT_RESIDUE_SHA256,
                "entry_count": 1,
                "coverage_replaces_or_reexecutes_invalidation": False,
            },
        },
        "coverage_map": {
            run_id: {
                "invalidated_run_id": INVALIDATED_RUN_ID,
                "source_round": "runs/stage3/acceptance-20260813-v3.11",
                "source_sequence": INVALIDATED_SEQUENCE,
                "case_id": COVERAGE_CASE_ID,
                "model_id": COVERAGE_MODEL_ID,
                "repeat": COVERAGE_REPEAT,
                "replaces_or_reexecutes": False,
            }
        },
        "plan_core_sha256": core_hash,
        "fairness": {
            "same_prompt_tools_budget_retry_grader": True,
            "models": [COVERAGE_MODEL_ID],
            "basis": (
                "prompt, tool schemas, resource budget, retry policy, and grader are inherited "
                "byte-identical from the frozen v3.11 contract bundle; the unit's repeat 1 "
                "(v3.10 round) and repeat 3 (v3.11 round) records were produced under the same "
                "commitments, and v3.10 frozen units remain valid and comparable under v3.11"
            ),
        },
        "tasks": [task],
        "runs": [row],
    }
    plan["plan_sha256"] = content_sha256(plan)
    if write:
        write_json(PLAN_PATH, plan)
    return plan


def historical_plan_run_ids() -> set[str]:
    ids: set[str] = set()
    for version in HISTORICAL_PLAN_VERSIONS:
        ids.update(row["run_id"] for row in read_json(ROOT / f"contracts/stage3_acceptance_plan.v{version}.json")["runs"])
    return ids


def run_id_collision_errors(run_id: str) -> list[str]:
    historical = historical_plan_run_ids()
    if run_id in historical:
        return [f"coverage run id collides with a historical v3.5-v3.11 plan run id: {run_id}"]
    return []


def verify_plan() -> list[str]:
    errors: list[str] = []
    actual = read_json(PLAN_PATH)
    if actual != build_coverage_plan(write=False):
        errors.append("coverage plan not reproducible")
    stripped = dict(actual)
    stripped.pop("plan_sha256", None)
    if content_sha256(stripped) != actual.get("plan_sha256"):
        errors.append("coverage plan_sha256 self-hash mismatch")
    errors.extend(run_id_collision_errors(actual["runs"][0]["run_id"]))
    return errors


def verify_contracts() -> list[str]:
    """Zero-drift proof over the v3.5-v3.11 frozen artifacts plus the coverage plan."""
    errors = validate_contract_bundle()
    if file_sha256(CONFIG_PATH) != DECLARED_CONFIG_FILE_SHA256:
        errors.append("v3.11 harness config drift")
    bundle = read_json(BUNDLE_PATH)
    if bundle.get("bundle_sha256") != DECLARED_BUNDLE_SHA256:
        errors.append("v3.11 contract bundle drift")
    if read_json(V311_PLAN_PATH).get("plan_sha256") != DECLARED_V311_PLAN_SHA256:
        errors.append("v3.11 plan drift")
    errors.extend(verify_plan())
    errors.extend(visibility_gate_errors(read_json(PLAN_PATH)))
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze-plan", "verify-plan", "verify-contracts"])
    args = parser.parse_args()
    if args.command == "freeze-plan":
        plan = build_coverage_plan(write=True)
        print(json.dumps({
            "path": str(PLAN_PATH.relative_to(ROOT)),
            "plan_version": plan["plan_version"],
            "plan_sha256": plan["plan_sha256"],
            "plan_core_sha256": plan["plan_core_sha256"],
            "coverage_run_id": plan["runs"][0]["run_id"],
            "coverage_seed": plan["runs"][0]["seed"],
        }))
    elif args.command == "verify-plan":
        errors = verify_plan()
        print(json.dumps({"valid": not errors, "errors": errors, "plan_sha256": read_json(PLAN_PATH).get("plan_sha256")}))
        raise SystemExit(0 if not errors else 2)
    else:
        errors = verify_contracts()
        print(json.dumps({"valid": not errors, "errors": errors}))
        raise SystemExit(0 if not errors else 2)
