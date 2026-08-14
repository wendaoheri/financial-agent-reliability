"""Offline tests for the PER-77 v3.11.1 single-unit coverage plan.

The plan covers exactly one unit — case-synthetic-ftw-14-normal-v3 /
deepseek-v4-pro / repeat 2 — invalidated at v3.11 sequence 268 by an
agent-runtime teardown. Contracts stay v3.11, byte-exact; only the plan
version moves. No paid calls, no network, no secret reads.
"""

import json
import pathlib
import unittest

from contracts.run_trace_validator_v3_8 import build_run_id, content_sha256, file_sha256
from financial_agent_reliability.harness.acceptance_v3_11 import (
    BENCHMARK_ID,
    BUNDLE_PATH,
    CONFIG_PATH,
    MASTER_SEED,
    derive_seed,
    validate_contract_bundle,
)
from financial_agent_reliability.harness.acceptance_v3_11_1 import (
    COVERAGE_CASE_ID,
    COVERAGE_MODEL_ID,
    COVERAGE_REPEAT,
    DECLARED_BUNDLE_SHA256,
    DECLARED_CONFIG_FILE_SHA256,
    DECLARED_COVERAGE_PLAN_CORE_SHA256,
    DECLARED_COVERAGE_RUN_ID,
    DECLARED_COVERAGE_SEED,
    DECLARED_V311_PLAN_CORE_SHA256,
    DECLARED_V311_PLAN_SHA256,
    INVALIDATED_RUN_ID,
    INVALIDATED_RUNS_PATH,
    PLAN_PATH,
    ROOT,
    build_coverage_plan,
    coverage_task_row,
    frozen_input_errors,
    historical_plan_run_ids,
    run_id_collision_errors,
    verify_contracts,
    verify_plan,
)


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class SingleUnitCoveragePlanTests(unittest.TestCase):
    def setUp(self):
        self.frozen = load(PLAN_PATH)

    # -- plan integrity ---------------------------------------------------------

    def test_plan_is_reproducible_and_self_consistent(self):
        self.assertEqual(self.frozen, build_coverage_plan(write=False))
        self.assertEqual(verify_plan(), [])

    def test_plan_sha256_recomputes_from_canonical_content(self):
        stripped = dict(self.frozen)
        stripped.pop("plan_sha256", None)
        self.assertEqual(content_sha256(stripped), self.frozen["plan_sha256"])

    def test_plan_version_kind_and_supersedes(self):
        self.assertEqual(self.frozen["plan_version"], "3.11.1")
        self.assertEqual(self.frozen["plan_kind"], "single_unit_coverage")
        self.assertEqual(self.frozen["contract_version"], "3.11.0")
        self.assertEqual(self.frozen["supersedes"]["path"], "contracts/stage3_acceptance_plan.v3.11.json")
        self.assertEqual(self.frozen["supersedes"]["plan_sha256"], DECLARED_V311_PLAN_SHA256)
        self.assertEqual(self.frozen["supersedes"]["sha256"], file_sha256(ROOT / "contracts/stage3_acceptance_plan.v3.11.json"))

    def test_plan_carries_exactly_one_task_and_one_run(self):
        self.assertEqual(len(self.frozen["tasks"]), 1)
        self.assertEqual(len(self.frozen["runs"]), 1)
        self.assertEqual(self.frozen["coverage_run_cap"], 1)
        self.assertEqual(self.frozen["registered_total_run_cap"], 1)
        row = self.frozen["runs"][0]
        task = self.frozen["tasks"][0]
        self.assertEqual(row["sequence"], 1)
        self.assertEqual(row["model_id"], COVERAGE_MODEL_ID)
        self.assertEqual(row["repeat"], COVERAGE_REPEAT)
        self.assertEqual(task["case_id"], COVERAGE_CASE_ID)
        self.assertEqual(task["run_ids"], [row["run_id"]])

    # -- contracts unchanged ----------------------------------------------------

    def test_v311_contracts_are_byte_unchanged(self):
        self.assertEqual(file_sha256(CONFIG_PATH), DECLARED_CONFIG_FILE_SHA256)
        bundle = load(BUNDLE_PATH)
        self.assertEqual(bundle["bundle_sha256"], DECLARED_BUNDLE_SHA256)
        self.assertEqual(content_sha256(bundle["artifacts"]), DECLARED_BUNDLE_SHA256)
        commitments = self.frozen["contract_commitments"]
        self.assertEqual(commitments["contract_bundle_sha256"], DECLARED_BUNDLE_SHA256)
        self.assertEqual(commitments["harness_config_sha256"], DECLARED_CONFIG_FILE_SHA256)
        self.assertFalse(commitments["contracts_changed"])
        self.assertTrue(commitments["prompt_oracle_threshold_reason_case_material_unchanged"])

    def test_zero_drift_over_v35_to_v311_frozen_artifacts(self):
        self.assertEqual(validate_contract_bundle(), [])
        self.assertEqual(verify_contracts(), [])
        self.assertEqual(frozen_input_errors(), [])

    def test_coverage_task_inputs_equal_the_v311_task_row(self):
        v311_task = next(item for item in load(ROOT / "contracts/stage3_acceptance_plan.v3.11.json")["tasks"] if item["case_id"] == COVERAGE_CASE_ID)
        row = coverage_task_row()
        for key in ("case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256", "variant_id", "family_id", "tier", "track"):
            self.assertEqual(row[key], v311_task[key], key)

    # -- seed and identity ------------------------------------------------------

    def test_seed_continuity_with_the_invalidated_unit(self):
        seed = derive_seed(COVERAGE_CASE_ID, COVERAGE_MODEL_ID, COVERAGE_REPEAT)
        self.assertEqual(seed, DECLARED_COVERAGE_SEED)
        row = self.frozen["runs"][0]
        self.assertEqual(row["seed"], seed)
        self.assertEqual(self.frozen["replication_design"]["coverage_seed"], seed)
        self.assertEqual(self.frozen["replication_design"]["master_seed"], MASTER_SEED)
        self.assertEqual(self.frozen["replication_design"]["benchmark_id"], BENCHMARK_ID)
        forensics = load(INVALIDATED_RUNS_PATH)
        self.assertEqual(forensics["entries"][0]["seed"], seed)

    def test_run_identity_rebuilds_to_the_preregistered_run_id(self):
        row = self.frozen["runs"][0]
        self.assertEqual(build_run_id(row["run_identity"]), DECLARED_COVERAGE_RUN_ID)
        self.assertEqual(row["run_identity"]["plan_core_sha256"], DECLARED_COVERAGE_PLAN_CORE_SHA256)
        self.assertEqual(row["run_identity"]["harness_config_sha256"], DECLARED_CONFIG_FILE_SHA256)

    def test_identity_differs_from_seq268_only_in_plan_core(self):
        seq268 = load(INVALIDATED_RUNS_PATH)["entries"][0]["run_identity"]
        coverage = self.frozen["runs"][0]["run_identity"]
        diffs = {key for key in seq268 if seq268[key] != coverage[key]}
        self.assertEqual(diffs, {"plan_core_sha256"})
        self.assertEqual(seq268["plan_core_sha256"], DECLARED_V311_PLAN_CORE_SHA256)

    def test_plan_core_reconstructs_from_single_task_commitments(self):
        task = self.frozen["tasks"][0]
        core = {
            "contract_version": "3.11.0",
            "config_sha256": DECLARED_CONFIG_FILE_SHA256,
            "models": [COVERAGE_MODEL_ID],
            "task_inputs": [{key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}],
        }
        self.assertEqual(content_sha256(core), DECLARED_COVERAGE_PLAN_CORE_SHA256)
        self.assertEqual(self.frozen["plan_core_sha256"], DECLARED_COVERAGE_PLAN_CORE_SHA256)

    def test_run_id_disjoint_from_all_historical_plan_ids(self):
        historical = historical_plan_run_ids()
        self.assertEqual(len(historical), 1540)
        self.assertIn(INVALIDATED_RUN_ID, historical)
        self.assertNotIn(DECLARED_COVERAGE_RUN_ID, historical)
        self.assertEqual(run_id_collision_errors(DECLARED_COVERAGE_RUN_ID), [])

    def test_run_id_collision_detection_fails_closed(self):
        self.assertNotEqual(run_id_collision_errors(INVALIDATED_RUN_ID), [])
        self.assertEqual(run_id_collision_errors(INVALIDATED_RUN_ID), [f"coverage run id collides with a historical v3.5-v3.11 plan run id: {INVALIDATED_RUN_ID}"])

    # -- invalidation forensics preserved, never replaced ------------------------

    def test_forensics_preserved_and_never_replaced(self):
        target = self.frozen["coverage_target"]
        self.assertEqual(target["invalidated_run_id"], INVALIDATED_RUN_ID)
        self.assertEqual(target["invalidated_sequence"], 268)
        self.assertFalse(target["replaces_or_reexecutes_invalidation"])
        self.assertTrue(target["invalidated_run_id_reuse_forbidden"])
        self.assertNotEqual(self.frozen["runs"][0]["run_id"], INVALIDATED_RUN_ID)
        forensics_block = self.frozen["replication_design"]["v3_11_seq268_invalidation_forensics"]
        self.assertTrue(forensics_block["preserved"])
        self.assertFalse(forensics_block["coverage_replaces_or_reexecutes_invalidation"])
        self.assertTrue(INVALIDATED_RUNS_PATH.is_file())
        self.assertTrue((ROOT / forensics_block["checkpoint_residue_path"]).is_file())
        mapping = self.frozen["coverage_map"][DECLARED_COVERAGE_RUN_ID]
        self.assertEqual(mapping["invalidated_run_id"], INVALIDATED_RUN_ID)
        self.assertEqual(mapping["source_sequence"], 268)
        self.assertFalse(mapping["replaces_or_reexecutes"])

    def test_unit_sibling_records_are_pinned_and_valid(self):
        records = self.frozen["coverage_target"]["unit_valid_records"]
        self.assertEqual(records["repeat_1"]["run_id"], "run_6da1eb9e6d67f7e98028259ecd3ba7f7")
        self.assertEqual(records["repeat_3"]["run_id"], "run_04971ef1d91a20a739ed0b7ab70f3a7e")
        for key, repeat in (("repeat_1", 1), ("repeat_3", 3)):
            trace = load(ROOT / records[key]["round"] / "traces" / f"{records[key]['run_id']}.json")
            self.assertEqual(trace["status"], "succeeded")
            self.assertEqual(trace["run_identity"]["repeat"], repeat)
            self.assertEqual(trace["run_identity"]["case_id"], COVERAGE_CASE_ID)
            self.assertEqual(trace["run_identity"]["requested_model_id"], COVERAGE_MODEL_ID)

    # -- authorization discipline -------------------------------------------------

    def test_plan_authorization_requires_separate_binding_and_preflight(self):
        authorization = self.frozen["authorization"]
        self.assertFalse(authorization["paid_calls_authorized"])
        self.assertEqual(authorization["execution_state"], "offline_validation_only")
        self.assertTrue(authorization["separate_plan_bound_authorization_required"])
        self.assertTrue(authorization["passing_identity_preflight_required"])

    def test_execution_artifacts_bind_exactly_one_run_id(self):
        run_dir = ROOT / "runs/stage3/coverage-20260814-v3.11.1"
        authorization = load(run_dir / "authorization.run.json")
        self.assertEqual(authorization["authorized_run_ids"], [DECLARED_COVERAGE_RUN_ID])
        self.assertEqual(authorization["authorized_run_count"], 1)
        self.assertEqual(authorization["denied_run_ids"], [INVALIDATED_RUN_ID])
        self.assertEqual(authorization["plan_sha256"], self.frozen["plan_sha256"])
        self.assertEqual(authorization["plan_core_sha256"], DECLARED_COVERAGE_PLAN_CORE_SHA256)
        self.assertEqual(authorization["contract_bundle_sha256"], DECLARED_BUNDLE_SHA256)
        self.assertEqual(authorization["harness_config_sha256"], DECLARED_CONFIG_FILE_SHA256)
        self.assertFalse(authorization["coverage_replaces_or_reexecutes_invalidation"])
        # PER-79 dispatched the coverage run: the gate records the PER-78 scoped
        # gate review as passed (with its report hash) and the delivery-owner
        # dispatch as authorized. The pre-dispatch invariant was "pending".
        gate = authorization["execution_gate"]
        self.assertEqual(gate["independent_gate_review_status"], "passed")
        self.assertEqual(gate["independent_gate_review_report_sha256"], "0c863c1213c62724bec0e016f2bb36d955bbd0a884dd5e9df55413f062b37b58")
        self.assertEqual(gate["delivery_owner_dispatch_status"], "authorized")
        stripped = dict(authorization)
        stripped.pop("authorization_sha256", None)
        self.assertEqual(authorization["authorization_sha256"], content_sha256(stripped))
        preflight = load(run_dir / "preflight.json")
        self.assertEqual(authorization["preflight_sha256"], preflight["preflight_sha256"])
        self.assertEqual(preflight["plan_sha256"], self.frozen["plan_sha256"])
        self.assertEqual(preflight["carry_over"]["paid_calls_in_this_round"], 0)


if __name__ == "__main__":
    unittest.main()
