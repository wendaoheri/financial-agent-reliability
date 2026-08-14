import copy
import json
import pathlib
import unittest

from contracts.run_trace_validator_v3_10 import HarnessContractV310Error, validate_run_trace_v310
from financial_agent_reliability.harness.acceptance_v3_10 import (
    BENCHMARK_ID,
    FIRST_ROUND_RUN_CAP,
    MASTER_SEED,
    NEW_REASON_DEFINITIONS,
    REGISTERED_TOTAL_RUN_CAP,
    build_contract_manifest,
    build_offline_plan,
    case_card_index,
    content_sha256,
    derive_seed,
    gold_cross_check_errors,
    grade_candidate_v310,
    independent_expected_v310,
    material_completeness_errors,
    oracle_visibility_report_v310,
    projection_case_id,
    read_json,
    reason_definitions_v310,
    validate_contract_bundle,
    ROOT,
)
from financial_agent_reliability.harness.acceptance_v3_7 import independent_expected_from_snapshot
from financial_agent_reliability.harness.acceptance_v3_9 import build_offline_plan as build_offline_plan_v39


FIXTURES = ROOT / "tests" / "fixtures" / "acceptance_v3_10"
DOCUMENTED_BEHAVIOR_CHANGES = {
    "case-synthetic-ftw-12-missing-or-anomalous-v3",
    "case-synthetic-ftw-11-missing-or-anomalous-v3",
    "case-synthetic-ftw-07-missing-or-anomalous-v3",
}


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FinancialAcceptanceV310Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = load(FIXTURES / "grader.baseline.json")
        self.projection = load(ROOT / self.fixture["projection_path"])
        self.snapshot = load(ROOT / self.fixture["snapshot_path"])
        self.candidate = self.fixture["candidate"]
        self.trace = self.fixture["trace"]

    def assertTraceRejected(self, mutate, pattern):
        trace = copy.deepcopy(self.trace)
        mutate(trace)
        with self.assertRaisesRegex(HarnessContractV310Error, pattern):
            validate_run_trace_v310(trace)

    # -- Stage-2 material completeness and Gold parity -------------------

    def test_stage2_materials_are_complete_and_frozen_for_all_90_tasks(self):
        entries = case_card_index()
        self.assertEqual(len(entries), 90)
        tracks = {entry["track"] for entry in entries}
        self.assertEqual(tracks, {"financial_knowledge_work", "financial_tool_workflow"})
        self.assertEqual(sum(1 for entry in entries if entry["track"] == "financial_knowledge_work"), 45)
        self.assertEqual(material_completeness_errors(), [])

    def test_clean_room_oracle_agrees_with_stage2_gold_for_all_90_tasks(self):
        self.assertEqual(gold_cross_check_errors(), [])

    # -- Visibility gate ---------------------------------------------------

    def test_visibility_gate_passes_for_all_90_frozen_v310_cases(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["tasks"]), 90)
        for task in plan["tasks"]:
            report = oracle_visibility_report_v310(load(ROOT / task["projection_path"]), load(ROOT / task["snapshot_path"]))
            self.assertTrue(report["visible"], f"{task['case_id']}: {report['violations']}")
        persisted = load(FIXTURES / "oracle_visibility.report.json")
        self.assertTrue(persisted["all_visible"])
        self.assertEqual(len(persisted["cases"]), 90)

    def test_visibility_gate_negative_fixtures_catch_invisible_conventions(self):
        persisted = load(FIXTURES / "oracle_visibility.negative.json")
        self.assertTrue(persisted["all_caught"])
        ids = {scenario["id"] for scenario in persisted["scenarios"]}
        for required in [
            "v3.6-fkw-03-undisclosed-six-decimal-convention",
            "v3.6-fkw-07-undisclosed-six-decimal-convention",
            "v3.10-fkw-02-average-undisclosed-six-decimal-convention",
            "v3.10-fkw-05-growth-undisclosed-six-decimal-convention",
            "contract-decimal-places-mismatch",
            "contract-rounding-mode-mismatch",
            "lexical-schema-waived",
            "contract-threshold-comparison-basis-mismatch",
        ]:
            self.assertIn(required, ids)
        for scenario in persisted["scenarios"]:
            self.assertTrue(scenario["caught"], scenario["id"])
            for code in scenario["expected_codes"]:
                self.assertTrue(any(code in violation for violation in scenario["observed_violations"]), scenario["id"])

    # -- Continuity with the audited v3.9 subset ---------------------------

    def test_previously_covered_expectations_stay_byte_identical_except_documented_repair(self):
        plan_v39 = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.9.json")
        documented = {
            "case-synthetic-ftw-12-missing-or-anomalous-v3": (
                {"status": "abstain", "value": None, "reason_codes": ["FINAL_STATE_UNCONFIRMED"]},
                {"status": "abstain", "value": None, "reason_codes": ["INSUFFICIENT_EVIDENCE"]},
            ),
            "case-synthetic-ftw-11-missing-or-anomalous-v3": (
                {"status": "abstain", "value": None, "reason_codes": ["SUITABILITY_EVIDENCE_MISSING"]},
                {"status": "abstain", "value": None, "reason_codes": ["INSUFFICIENT_EVIDENCE"]},
            ),
            "case-synthetic-ftw-07-missing-or-anomalous-v3": (
                {"status": "abstain", "value": None, "reason_codes": ["INSUFFICIENT_EVIDENCE", "TOOL_TEXT_TREATED_AS_DATA"]},
                {"status": "abstain", "value": None, "reason_codes": ["INSUFFICIENT_EVIDENCE"]},
            ),
        }
        for task in plan_v39["tasks"]:
            snapshot = load(ROOT / task["snapshot_path"])
            v39_projection = load(ROOT / task["projection_path"])
            v310_projection = load(ROOT / "cases" / "candidate_v3_10" / f"{task['case_id']}.json")
            expected_v39 = independent_expected_from_snapshot(v39_projection, snapshot)
            expected_v310 = independent_expected_v310(v310_projection, snapshot)
            if task["case_id"] in documented:
                before, after = documented[task["case_id"]]
                self.assertEqual(expected_v39, before, task["case_id"])
                self.assertEqual(expected_v310, after, task["case_id"])
            else:
                self.assertEqual(expected_v39, expected_v310, task["case_id"])

    def test_covered_projection_changes_stay_disclosure_additive(self):
        plan_v39 = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.9.json")
        for task in plan_v39["tasks"]:
            old = load(ROOT / task["projection_path"])
            new = load(ROOT / "cases" / "candidate_v3_10" / f"{task['case_id']}.json")
            ignored = {"contract_version", "supersedes", "reason_code_vocabulary", "reason_code_contract", "decimal_output_contract", "task", "answer_value_schema"}
            for key in set(old) | set(new):
                if key in ignored:
                    continue
                self.assertEqual(json.dumps(old.get(key), sort_keys=True), json.dumps(new.get(key), sort_keys=True), f"{task['case_id']}:{key}")
            old_task, new_task = old["task"], new["task"]
            self.assertEqual(old_task["prompt"], new_task["prompt"])
            self.assertEqual(old_task["permissions"], new_task["permissions"])
            if task["case_id"] not in DOCUMENTED_BEHAVIOR_CHANGES:
                # inputs may only gain observable facts, never lose or change them
                for key, value in old_task["inputs"].items():
                    self.assertIn(key, new_task["inputs"], f"{task['case_id']}:{key}")
                    self.assertEqual(new_task["inputs"][key], value, f"{task['case_id']}:{key}")
            old_schema, new_schema = old["answer_value_schema"], new["answer_value_schema"]
            self.assertEqual(set(old_schema["properties"]), set(new_schema["properties"]))
            self.assertEqual(old_schema["required"], new_schema["required"])
            if old.get("decimal_output_contract"):
                new_contract = dict(new.get("decimal_output_contract") or {})
                # v3.10 may only add disclosure keys: the explicit value_field
                # (v3.6-era FKW-12 omitted it and defaulted to "value") and the
                # registered_decimal_basis provenance disclosure from v3.9.
                added_keys = set(new_contract) - set(old["decimal_output_contract"])
                self.assertTrue(added_keys <= {"value_field", "registered_decimal_basis"}, f"{task['case_id']}:{sorted(added_keys)}")
                if "value_field" in added_keys:
                    self.assertEqual(new_contract["value_field"], "value")
                for key in added_keys:
                    new_contract.pop(key)
                self.assertEqual(new_contract, old["decimal_output_contract"], task["case_id"])

    # -- Plan, identities, replication design --------------------------------

    def test_plan_covers_90_tasks_with_270_first_round_and_810_preregistered_runs(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["tasks"]), 90)
        self.assertEqual(len(plan["runs"]), REGISTERED_TOTAL_RUN_CAP)
        self.assertEqual(plan["first_round_run_cap"], FIRST_ROUND_RUN_CAP)
        self.assertEqual(plan["registered_total_run_cap"], 810)
        self.assertFalse(plan["authorization"]["paid_calls_authorized"])
        self.assertTrue(plan["authorization"]["separate_plan_bound_authorization_required"])
        self.assertTrue(plan["authorization"]["passing_identity_preflight_required"])
        first_round = [row for row in plan["runs"] if row["repeat"] == 1]
        self.assertEqual(len(first_round), 270)
        self.assertEqual([row["sequence"] for row in first_round], list(range(1, 271)))
        self.assertEqual(len({row["run_id"] for row in plan["runs"]}), 810)
        cells = {}
        for row in plan["runs"]:
            cells.setdefault((row["run_identity"]["case_id"], row["model_id"]), []).append(row)
        self.assertEqual(len(cells), 270)
        for rows in cells.values():
            self.assertEqual(sorted(row["repeat"] for row in rows), [1, 2, 3])
            self.assertEqual(len({row["seed"] for row in rows}), 3)

    def test_run_identities_are_disjoint_from_all_prior_versions(self):
        plan = build_offline_plan(write=False)
        ids = {row["run_id"] for row in plan["runs"]}
        for version in ["3.5", "3.6", "3.7", "3.8", "3.9"]:
            old = load(ROOT / "contracts" / f"stage3_acceptance_plan.v{version}.json")
            self.assertFalse(ids & {row["run_id"] for row in old["runs"]})

    def test_seeds_derive_from_the_frozen_master_seed_independent_of_order(self):
        plan = build_offline_plan(write=False)
        for row in plan["runs"]:
            identity = {"benchmark_id": BENCHMARK_ID, "case_id": row["run_identity"]["case_id"], "master_seed": MASTER_SEED, "repeat": row["repeat"], "requested_model_id": row["model_id"]}
            self.assertEqual(row["seed"], int(content_sha256(identity)[:16], 16) % 2**32)
            self.assertEqual(row["seed"], derive_seed(row["run_identity"]["case_id"], row["model_id"], row["repeat"]))
            self.assertEqual(row["run_identity"]["seed"], row["seed"])

    def test_verify_plan_reproduces_the_frozen_plan_exactly(self):
        actual = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.10.json")
        expected = build_offline_plan(write=False)
        self.assertEqual(actual, expected)

    # -- Symmetry and zero-drift --------------------------------------------

    def test_three_model_policy_commitments_are_unchanged_from_v39(self):
        v39_config = load(ROOT / "contracts" / "run_trace_harness_config.v3.9.json")
        v310_config = load(ROOT / "contracts" / "run_trace_harness_config.v3.10.json")
        self.assertEqual(v310_config["request_commitments"], v39_config["request_commitments"])
        self.assertEqual(v310_config["resource_budget"], v39_config["resource_budget"])
        self.assertEqual(v310_config["provider_retry_policy"], v39_config["provider_retry_policy"])
        self.assertEqual(v310_config["system_prompt"], v39_config["system_prompt"])
        self.assertEqual(v310_config["tool_names"], v39_config["tool_names"])
        self.assertEqual(v310_config["security"], v39_config["security"])
        self.assertTrue(v310_config["fairness"]["same_prompt_tools_budget_retry_grader_for_all_models"])
        self.assertEqual(v310_config["semantic_bindings"]["calculation"], "executed_decimal_rational_v3_10")
        self.assertEqual(v310_config["semantic_bindings"]["decimal_output_contract_visibility_gate"], "oracle_expectations_subset_of_candidate_visible_contract_v3_10")
        self.assertEqual(v310_config["execution"]["case_count"], 90)
        self.assertEqual(v310_config["execution"]["planned_run_cap"], 810)
        self.assertFalse(v310_config["execution"]["paid_calls_authorized"])
        self.assertTrue(v310_config["execution"]["offline_validation_only"])

    def test_v310_preserves_all_prior_bundles_and_passes_every_freeze_gate(self):
        manifest = build_contract_manifest()
        self.assertEqual(validate_contract_bundle(manifest), [])
        self.assertEqual(manifest["supersedes"]["v3_9_bundle_sha256"], "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030")
        self.assertEqual(manifest["preserved"]["v3_9_bundle_sha256"], "77aea0934d305dee316f0b1877ce962e7929dd300ce1e1a5711e0b3bd280d030")
        self.assertFalse(manifest["preserved"]["retroactive_regrading"])
        self.assertFalse(manifest["paid_calls_authorized"])
        self.assertEqual(len(manifest["artifacts"]), len({item["path"] for item in manifest["artifacts"]}))

    # -- Reason vocabulary ----------------------------------------------------

    def test_reason_vocabulary_extends_to_21_registered_codes(self):
        definitions = reason_definitions_v310()
        self.assertEqual(len(definitions), 21)
        for code in NEW_REASON_DEFINITIONS:
            self.assertIn(code, definitions)
            self.assertTrue(definitions[code]["trigger"])
            self.assertTrue(definitions[code]["allowed_statuses"])
        self.assertEqual(definitions["BOUNDED_RETRY_SUCCEEDED"]["allowed_statuses"], ["answer"])
        reason_doc = load(ROOT / "contracts" / "reason_codes.v3.10.json")
        self.assertEqual(len(reason_doc["case_sets"]), 90)
        self.assertEqual(len(reason_doc["definitions"]), 21)
        plan = build_offline_plan(write=False)
        for task in plan["tasks"]:
            case_set = reason_doc["case_sets"][task["case_id"]]
            self.assertIn(case_set["status"], {"answer", "abstain", "escalate", "reject_action"})
            self.assertEqual(case_set["required"], case_set["allowed"])

    # -- Grader fixtures -------------------------------------------------------

    def test_baseline_direct_case_grades_through_v310_grader(self):
        result = grade_candidate_v310(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        self.assertTrue(result["checks"]["candidate_trace_bound"])
        self.assertEqual(result["contract_version"], "3.10.0")
        self.assertEqual(result["grader_sha256"], content_sha256({key: value for key, value in result.items() if key != "grader_sha256"}))

    def test_average_case_enforces_the_disclosed_six_decimal_contract(self):
        fixture = load(FIXTURES / "grader.average_contract.json")
        projection = load(ROOT / fixture["projection_path"])
        snapshot = load(ROOT / fixture["snapshot_path"])
        result = grade_candidate_v310(fixture["candidate"], projection, snapshot, fixture["trace"])
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        self.assertTrue(result["checks"]["decimal_lexical_correct"])
        self.assertTrue(result["checks"]["calculation_correct"])
        exact_mean = copy.deepcopy(fixture["candidate"])
        exact_mean["value"]["average"] = "5394035596893.89333333333333333333"
        exact_result = grade_candidate_v310(exact_mean, projection, snapshot, fixture["trace"])
        self.assertFalse(exact_result["checks"]["decimal_lexical_correct"])
        self.assertFalse(exact_result["checks"]["value_semantic_correct"])
        wrong_rounding = copy.deepcopy(fixture["candidate"])
        disclosed = wrong_rounding["value"]["average"]
        wrong_rounding["value"]["average"] = f"{disclosed[:-1]}{'0' if disclosed[-1] != '0' else '1'}"
        wrong_result = grade_candidate_v310(wrong_rounding, projection, snapshot, fixture["trace"])
        self.assertTrue(wrong_result["checks"]["decimal_lexical_correct"])
        self.assertFalse(wrong_result["checks"]["value_semantic_correct"])

    def test_ftw_workflow_case_keeps_exact_decimal_differences_unquantized(self):
        fixture = load(FIXTURES / "grader.ftw_workflow.json")
        projection = load(ROOT / fixture["projection_path"])
        snapshot = load(ROOT / fixture["snapshot_path"])
        result = grade_candidate_v310(fixture["candidate"], projection, snapshot, fixture["trace"])
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        self.assertIsNone(projection.get("decimal_output_contract"))
        quantized = copy.deepcopy(fixture["candidate"])
        quantized["value"]["observed_minus_reference"] = "129.960000"
        self.assertFalse(grade_candidate_v310(quantized, projection, snapshot, fixture["trace"])["checks"]["value_semantic_correct"])

    def test_bounded_retry_answer_requires_the_informational_success_code(self):
        fixture = load(FIXTURES / "grader.bounded_retry.json")
        projection = load(ROOT / fixture["projection_path"])
        snapshot = load(ROOT / fixture["snapshot_path"])
        self.assertEqual(fixture["candidate"]["reason_codes"], ["BOUNDED_RETRY_SUCCEEDED"])
        self.assertEqual(fixture["candidate"]["value"]["attempts"], 2)
        result = grade_candidate_v310(fixture["candidate"], projection, snapshot, fixture["trace"])
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        missing_code = copy.deepcopy(fixture["candidate"])
        missing_code["reason_codes"] = []
        missing_code["evidence_record_ids"] = []
        self.assertFalse(grade_candidate_v310(missing_code, projection, snapshot, fixture["trace"])["checks"]["reason_codes_exact"])

    # -- Trace validation -------------------------------------------------------

    def test_attempt_response_identity_http_and_phase_are_derived_not_self_reported(self):
        self.assertEqual(validate_run_trace_v310(self.trace)["status"], "succeeded")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(response_model_id="deepseek-v4-pro"), "attempt response model")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(http_status=429), "HTTP classification")
        self.assertTraceRejected(lambda t: t["logical_requests"][0].update(phase="repair"), "first request must be initial")
        multi = load(FIXTURES / "trace.multi_request_retry.json")
        validate_run_trace_v310(multi)
        changed = copy.deepcopy(multi)
        changed["logical_requests"][2]["phase"] = "initial"
        with self.assertRaisesRegex(HarnessContractV310Error, "phase order"):
            validate_run_trace_v310(changed)

    def test_ledger_terminal_state_is_recomputed_from_state_roots(self):
        trace = load(FIXTURES / "trace.ledger_restored.json")
        self.assertEqual(validate_run_trace_v310(trace)["status"], "succeeded")
        changed = copy.deepcopy(trace)
        changed["environment"]["final_ledger_sha256"] = "f" * 64
        with self.assertRaisesRegex(HarnessContractV310Error, "ledger terminal state"):
            validate_run_trace_v310(changed)
        changed = copy.deepcopy(trace)
        changed["environment"]["final_state_matches_initial"] = True
        next(event for event in reversed(changed["tool_events"]) if event["tool_name"] == "simulated_ledger")["state_after_sha256"] = "e" * 64
        with self.assertRaisesRegex(HarnessContractV310Error, "ledger state chain"):
            validate_run_trace_v310(changed)

    def test_sensitive_scanner_is_a_validator_gate_for_trace_and_companions(self):
        changed = copy.deepcopy(self.trace)
        changed["failure"]["code"] = "Bearer SYNTHETIC_TOKEN_123"
        with self.assertRaisesRegex(HarnessContractV310Error, "secret-like persisted value"):
            validate_run_trace_v310(changed)
        companion = {"diagnostic": "Bearer SYNTHETIC_TOKEN_456"}
        with self.assertRaisesRegex(HarnessContractV310Error, "secret-like persisted value"):
            validate_run_trace_v310(self.trace, scan_companions=[companion])

    def test_fixture_secret_scan_is_clean(self):
        from financial_agent_reliability.harness.acceptance_v3_10 import scan_fixtures
        self.assertEqual(scan_fixtures(), [])
        self.assertGreaterEqual(len(list(FIXTURES.glob("*.json"))), 8)

    # -- Projection content ------------------------------------------------------

    def test_all_90_projections_publish_visible_contracts_without_oracle_labels(self):
        plan = build_offline_plan(write=False)
        hidden_labels = {"force_abstain_reason", "diagnostic_reason"}
        for task in plan["tasks"]:
            projection = load(ROOT / task["projection_path"])
            self.assertEqual(projection["contract_version"], "3.10.0")
            self.assertEqual(projection["case_id"], task["case_id"])
            self.assertFalse(hidden_labels & set(projection["task"]["inputs"]))
            self.assertEqual(len(projection["reason_code_vocabulary"]), 21)
            self.assertEqual(projection["reason_code_contract"]["required"], projection["reason_code_contract"]["allowed"])
            card = next(entry["card"] for entry in case_card_index() if projection_case_id(entry["card"]) == task["case_id"])
            self.assertEqual(projection["task"]["prompt"], card["task"]["prompt"])
            self.assertEqual(projection["task"]["permissions"], card["task"]["permissions"])


if __name__ == "__main__":
    unittest.main()
