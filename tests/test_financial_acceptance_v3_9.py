import copy
import json
import pathlib
import unittest

from contracts.run_trace_validator_v3_9 import HarnessContractV39Error, validate_run_trace_v39
from financial_agent_reliability.harness.acceptance_v3_9 import (
    build_contract_manifest,
    build_offline_plan,
    content_sha256,
    grade_candidate_v39,
    independent_expected_from_snapshot,
    oracle_visibility_report,
    read_json,
    repair_is_disclosure_only,
    repaired_projection,
    validate_contract_bundle,
    ROOT,
)


FIXTURES = ROOT / "tests" / "fixtures" / "acceptance_v3_9"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FinancialAcceptanceV39Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = load(FIXTURES / "grader.baseline.json")
        self.projection = load(ROOT / self.fixture["projection_path"])
        self.snapshot = load(ROOT / self.fixture["snapshot_path"])
        self.candidate = self.fixture["candidate"]
        self.trace = self.fixture["trace"]
        self.decimal_fixture = load(FIXTURES / "grader.fkw03.decimal_contract.json")
        self.decimal_projection = load(ROOT / self.decimal_fixture["projection_path"])
        self.decimal_snapshot = load(ROOT / self.decimal_fixture["snapshot_path"])

    def assertTraceRejected(self, mutate, pattern):
        trace = copy.deepcopy(self.trace)
        mutate(trace)
        with self.assertRaisesRegex(HarnessContractV39Error, pattern):
            validate_run_trace_v39(trace)

    def test_attempt_response_identity_http_and_phase_are_derived_not_self_reported(self):
        self.assertEqual(validate_run_trace_v39(self.trace)["status"], "succeeded")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(response_model_id="deepseek-v4-pro"), "attempt response model")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(http_status=429), "HTTP classification")
        self.assertTraceRejected(lambda t: t["logical_requests"][0].update(phase="repair"), "first request must be initial")
        multi = load(FIXTURES / "trace.multi_request_retry.json")
        validate_run_trace_v39(multi)
        changed = copy.deepcopy(multi)
        changed["logical_requests"][2]["phase"] = "initial"
        with self.assertRaisesRegex(HarnessContractV39Error, "phase order"):
            validate_run_trace_v39(changed)

    def test_candidate_trace_and_grader_commitments_are_bound(self):
        result = grade_candidate_v39(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(result["checks"]["candidate_trace_bound"])
        self.assertEqual(result["commitments"]["candidate_sha256"], content_sha256(self.candidate))
        self.assertEqual(result["commitments"]["trace_sha256"], content_sha256(self.trace))
        self.assertEqual(result["grader_sha256"], content_sha256({key: value for key, value in result.items() if key != "grader_sha256"}))
        changed = copy.deepcopy(self.candidate)
        changed["uncertainty"] = "high"
        bad = grade_candidate_v39(changed, self.projection, self.snapshot, self.trace)
        self.assertFalse(bad["checks"]["candidate_trace_bound"])
        self.assertFalse(bad["all_applicable_checks_passed"])

    def test_fkw03_repair_grades_disclosed_six_decimal_contract_through_value_field(self):
        result = grade_candidate_v39(self.decimal_fixture["candidate"], self.decimal_projection, self.decimal_snapshot, self.decimal_fixture["trace"])
        self.assertTrue(result["all_applicable_checks_passed"], result["failed_checks"])
        self.assertTrue(result["checks"]["decimal_lexical_correct"])
        self.assertTrue(result["checks"]["value_semantic_correct"])
        self.assertEqual(self.decimal_fixture["candidate"]["value"]["scaled_value"], "0.000035")
        # The exact quotient was a defensible answer under the v3.8 visible layer;
        # under v3.9 it violates the now-disclosed lexical and semantic contract.
        exact = copy.deepcopy(self.decimal_fixture["candidate"])
        exact["value"]["scaled_value"] = "0.000035215003535366"
        exact_result = grade_candidate_v39(exact, self.decimal_projection, self.decimal_snapshot, self.decimal_fixture["trace"])
        self.assertFalse(exact_result["checks"]["decimal_lexical_correct"])
        self.assertFalse(exact_result["checks"]["value_semantic_correct"])
        # A six-decimal value with the wrong rounding fails semantics but keeps the lexical contract.
        rounded_wrong = copy.deepcopy(self.decimal_fixture["candidate"])
        rounded_wrong["value"]["scaled_value"] = "0.000036"
        wrong_result = grade_candidate_v39(rounded_wrong, self.decimal_projection, self.decimal_snapshot, self.decimal_fixture["trace"])
        self.assertTrue(wrong_result["checks"]["decimal_lexical_correct"])
        self.assertFalse(wrong_result["checks"]["value_semantic_correct"])

    def test_fkw12_default_value_field_stays_backward_compatible(self):
        result = grade_candidate_v39(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(result["checks"]["decimal_lexical_correct"])
        changed = copy.deepcopy(self.candidate)
        changed["value"]["value"] = "36.14793"
        self.assertFalse(grade_candidate_v39(changed, self.projection, self.snapshot, self.trace)["checks"]["decimal_lexical_correct"])

    def test_calculation_requires_real_matching_tool_event_with_v39_implementation(self):
        good = grade_candidate_v39(self.decimal_fixture["candidate"], self.decimal_projection, self.decimal_snapshot, self.decimal_fixture["trace"])
        self.assertTrue(good["checks"]["calculation_correct"])
        self.assertTrue(good["checks"]["method_correct"])
        self.assertTrue(good["checks"]["unit_correct"])
        changed = copy.deepcopy(self.decimal_fixture["trace"])
        changed["tool_events"] = [event for event in changed["tool_events"] if event["tool_name"] != "calculate"]
        self.assertFalse(grade_candidate_v39(self.decimal_fixture["candidate"], self.decimal_projection, self.decimal_snapshot, changed)["checks"]["calculation_correct"])
        changed = copy.deepcopy(self.decimal_fixture["trace"])
        next(event for event in changed["tool_events"] if event["tool_name"] == "calculate")["implementation"] = "decimal_rational_v3_8"
        self.assertFalse(grade_candidate_v39(self.decimal_fixture["candidate"], self.decimal_projection, self.decimal_snapshot, changed)["checks"]["calculation_correct"])
        changed = copy.deepcopy(self.decimal_fixture["trace"])
        next(event for event in changed["tool_events"] if event["tool_name"] == "read_frozen_evidence")["unit_basis_sha256"] = "f" * 64
        self.assertFalse(grade_candidate_v39(self.decimal_fixture["candidate"], self.decimal_projection, self.decimal_snapshot, changed)["checks"]["unit_correct"])

    def test_ledger_terminal_state_is_recomputed_from_state_roots(self):
        trace = load(FIXTURES / "trace.ledger_restored.json")
        self.assertEqual(validate_run_trace_v39(trace)["status"], "succeeded")
        changed = copy.deepcopy(trace)
        changed["environment"]["final_ledger_sha256"] = "f" * 64
        with self.assertRaisesRegex(HarnessContractV39Error, "ledger terminal state"):
            validate_run_trace_v39(changed)
        changed = copy.deepcopy(trace)
        changed["environment"]["final_state_matches_initial"] = True
        next(event for event in reversed(changed["tool_events"]) if event["tool_name"] == "simulated_ledger")["state_after_sha256"] = "e" * 64
        with self.assertRaisesRegex(HarnessContractV39Error, "ledger state chain"):
            validate_run_trace_v39(changed)

    def test_sensitive_scanner_is_a_validator_gate_for_trace_and_companions(self):
        changed = copy.deepcopy(self.trace)
        changed["failure"]["code"] = "Bearer SYNTHETIC_TOKEN_123"
        with self.assertRaisesRegex(HarnessContractV39Error, "secret-like persisted value"):
            validate_run_trace_v39(changed)
        companion = {"diagnostic": "Bearer SYNTHETIC_TOKEN_456"}
        with self.assertRaisesRegex(HarnessContractV39Error, "secret-like persisted value"):
            validate_run_trace_v39(self.trace, scan_companions=[companion])

    def test_visibility_gate_passes_for_all_twelve_frozen_v39_cases(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["tasks"]), 12)
        for task in plan["tasks"]:
            report = oracle_visibility_report(load(ROOT / task["projection_path"]), load(ROOT / task["snapshot_path"]))
            self.assertTrue(report["visible"], f"{task['case_id']}: {report['violations']}")
        persisted = load(FIXTURES / "oracle_visibility.report.json")
        self.assertTrue(persisted["all_visible"])
        self.assertEqual(len(persisted["cases"]), 12)

    def test_visibility_gate_negative_fixtures_catch_invisible_conventions(self):
        persisted = load(FIXTURES / "oracle_visibility.negative.json")
        self.assertTrue(persisted["all_caught"])
        ids = {scenario["id"] for scenario in persisted["scenarios"]}
        self.assertIn("v3.6-fkw-03-undisclosed-six-decimal-convention", ids)
        self.assertIn("v3.6-fkw-07-undisclosed-six-decimal-convention", ids)
        for scenario in persisted["scenarios"]:
            self.assertTrue(scenario["caught"], scenario["id"])
            for code in scenario["expected_codes"]:
                self.assertTrue(any(code in violation for violation in scenario["observed_violations"]), scenario["id"])

    def test_visibility_gate_reproduces_the_v38_audit_finding(self):
        # The gate applied to the v3.8 frozen task set must fail on the exact
        # contract defect the independent audit attributed to fkw-03 (and it also
        # detects the identical latent defect on fkw-07).
        plan = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.8.json")
        failures = {}
        for task in plan["tasks"]:
            report = oracle_visibility_report(load(ROOT / task["projection_path"]), load(ROOT / task["snapshot_path"]))
            if report["violations"]:
                failures[task["case_id"]] = report["violations"]
        self.assertEqual(set(failures), {
            "case-public-fkw-03-single-factor-perturbation-v3",
            "case-public-fkw-07-single-factor-perturbation-v3",
        })
        self.assertTrue(any("undisclosed_quantization_convention" in violation for violation in failures["case-public-fkw-03-single-factor-perturbation-v3"]))

    def test_repair_is_disclosure_only_and_case_design_sourced(self):
        for case_id in ["case-public-fkw-03-single-factor-perturbation-v3", "case-public-fkw-07-single-factor-perturbation-v3"]:
            self.assertEqual(repair_is_disclosure_only(case_id), [])
        # The disclosed convention reproduces the frozen PER-28 v2 case-card oracle
        # values: it is sourced from case design, not from v3.8 candidate answers.
        for case_id, card, snapshot_path in [
            ("case-public-fkw-03-single-factor-perturbation-v3", "cases/public/case_card.FKW-03.single_factor_perturbation.json", "snapshots/public/v2/data_snapshot.FKW-03.json"),
            ("case-public-fkw-07-single-factor-perturbation-v3", "cases/public/case_card.FKW-07.single_factor_perturbation.json", "snapshots/public/v2/data_snapshot.FKW-07.json"),
        ]:
            projection = repaired_projection(case_id)
            snapshot = load(ROOT / snapshot_path)
            expected = independent_expected_from_snapshot(projection, snapshot)
            card_oracle = load(ROOT / card)["oracle"]["expected_value"]
            for key, value in card_oracle.items():
                self.assertEqual(expected["value"][key], value)
            contract = projection["decimal_output_contract"]
            self.assertEqual(contract["rounding_mode"], "ROUND_HALF_EVEN")
            self.assertEqual(contract["value_decimal_places"], 6)
            self.assertEqual(contract["absolute_tolerance"], "0.0000005")
            self.assertTrue(contract["tolerance_does_not_waive_lexical_schema"])
            self.assertEqual(projection["answer_value_schema"]["properties"][contract["value_field"]]["pattern"], contract["value_pattern"])

    def test_v39_is_new_offline_only_and_preserves_all_prior_versions(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["runs"]), 36)
        self.assertFalse(plan["authorization"]["paid_calls_authorized"])
        self.assertTrue(plan["authorization"]["separate_plan_bound_authorization_required"])
        self.assertTrue(plan["authorization"]["passing_identity_preflight_required"])
        self.assertFalse(plan["audit_repair"]["oracle_behavior_changed"])
        ids = {row["run_id"] for row in plan["runs"]}
        for version in ["3.5", "3.6", "3.7", "3.8"]:
            old = load(ROOT / "contracts" / f"stage3_acceptance_plan.v{version}.json")
            self.assertFalse(ids & {row["run_id"] for row in old["runs"]})
        manifest = build_contract_manifest()
        self.assertEqual(validate_contract_bundle(manifest), [])
        self.assertEqual(manifest["supersedes"]["v3_8_bundle_sha256"], "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609")
        self.assertEqual(manifest["preserved"]["v3_8_bundle_sha256"], "39a0853cbe3febdf2b721dfa2aae7c417a2aff1f1f21bb69583b51b6d719f609")
        self.assertFalse(manifest["preserved"]["retroactive_regrading"])


if __name__ == "__main__":
    unittest.main()
