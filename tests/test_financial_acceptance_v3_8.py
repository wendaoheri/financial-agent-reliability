import copy
import json
import pathlib
import unittest

from contracts.run_trace_validator_v3_8 import HarnessContractV38Error, validate_run_trace_v38
from financial_agent_reliability.harness.acceptance_v3_8 import (
    build_contract_manifest,
    build_offline_plan,
    content_sha256,
    grade_candidate_v38,
    validate_contract_bundle,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "acceptance_v3_8"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FinancialAcceptanceV38Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = load(FIXTURES / "grader.baseline.json")
        self.projection = load(ROOT / self.fixture["projection_path"])
        self.snapshot = load(ROOT / self.fixture["snapshot_path"])
        self.candidate = self.fixture["candidate"]
        self.trace = self.fixture["trace"]

    def assertTraceRejected(self, mutate, pattern):
        trace = copy.deepcopy(self.trace)
        mutate(trace)
        with self.assertRaisesRegex(HarnessContractV38Error, pattern):
            validate_run_trace_v38(trace)

    def test_attempt_response_identity_http_and_phase_are_derived_not_self_reported(self):
        self.assertEqual(validate_run_trace_v38(self.trace)["status"], "succeeded")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(response_model_id="deepseek-v4-pro"), "attempt response model")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(http_status=429), "HTTP classification")
        self.assertTraceRejected(lambda t: t["logical_requests"][0].update(phase="repair"), "first request must be initial")
        multi = load(FIXTURES / "trace.multi_request_retry.json")
        validate_run_trace_v38(multi)
        changed = copy.deepcopy(multi)
        changed["logical_requests"][2]["phase"] = "initial"
        with self.assertRaisesRegex(HarnessContractV38Error, "phase order"):
            validate_run_trace_v38(changed)

    def test_candidate_trace_and_grader_commitments_are_bound(self):
        result = grade_candidate_v38(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(result["checks"]["candidate_trace_bound"])
        self.assertEqual(result["commitments"]["candidate_sha256"], content_sha256(self.candidate))
        self.assertEqual(result["commitments"]["trace_sha256"], content_sha256(self.trace))
        self.assertEqual(result["grader_sha256"], content_sha256({key: value for key, value in result.items() if key != "grader_sha256"}))
        changed = copy.deepcopy(self.candidate)
        changed["uncertainty"] = "high"
        bad = grade_candidate_v38(changed, self.projection, self.snapshot, self.trace)
        self.assertFalse(bad["checks"]["candidate_trace_bound"])
        self.assertFalse(bad["all_applicable_checks_passed"])

    def test_evidence_sufficiency_is_cited_intersect_observed_intersect_material(self):
        changed = copy.deepcopy(self.candidate)
        changed["evidence_record_ids"] = []
        result = grade_candidate_v38(changed, self.projection, self.snapshot, self.trace)
        self.assertFalse(result["checks"]["evidence_sufficient"])
        self.assertFalse(result["checks"]["evidence_provenance_valid"])
        changed = copy.deepcopy(self.trace)
        changed["evidence_observations"] = []
        changed["result"]["candidate_output_sha256"] = content_sha256(self.candidate)
        result = grade_candidate_v38(self.candidate, self.projection, self.snapshot, changed)
        self.assertFalse(result["checks"]["evidence_sufficient"])
        changed = copy.deepcopy(self.trace)
        changed["tool_events"] = [event for event in changed["tool_events"] if event["tool_name"] != "read_frozen_evidence"]
        result = grade_candidate_v38(self.candidate, self.projection, self.snapshot, changed)
        self.assertFalse(result["checks"]["evidence_provenance_valid"])
        self.assertFalse(result["checks"]["evidence_sufficient"])

    def test_calculation_requires_real_matching_tool_event(self):
        good = grade_candidate_v38(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(good["checks"]["calculation_correct"])
        self.assertTrue(good["checks"]["method_correct"])
        self.assertTrue(good["checks"]["unit_correct"])
        changed = copy.deepcopy(self.trace)
        changed["tool_events"] = [event for event in changed["tool_events"] if event["tool_name"] != "calculate"]
        result = grade_candidate_v38(self.candidate, self.projection, self.snapshot, changed)
        self.assertFalse(result["checks"]["calculation_correct"])
        changed = copy.deepcopy(self.trace)
        next(event for event in changed["tool_events"] if event["tool_name"] == "calculate")["output_sha256"] = "f" * 64
        self.assertFalse(grade_candidate_v38(self.candidate, self.projection, self.snapshot, changed)["checks"]["calculation_correct"])
        changed = copy.deepcopy(self.trace)
        next(event for event in changed["tool_events"] if event["tool_name"] == "read_frozen_evidence")["unit_basis_sha256"] = "f" * 64
        self.assertFalse(grade_candidate_v38(self.candidate, self.projection, self.snapshot, changed)["checks"]["unit_correct"])

    def test_ledger_terminal_state_is_recomputed_from_state_roots(self):
        trace = load(FIXTURES / "trace.ledger_restored.json")
        self.assertEqual(validate_run_trace_v38(trace)["status"], "succeeded")
        changed = copy.deepcopy(trace)
        changed["environment"]["final_ledger_sha256"] = "f" * 64
        with self.assertRaisesRegex(HarnessContractV38Error, "ledger terminal state"):
            validate_run_trace_v38(changed)
        changed = copy.deepcopy(trace)
        changed["environment"]["final_state_matches_initial"] = True
        next(event for event in reversed(changed["tool_events"]) if event["tool_name"] == "simulated_ledger")["state_after_sha256"] = "e" * 64
        with self.assertRaisesRegex(HarnessContractV38Error, "ledger state chain"):
            validate_run_trace_v38(changed)

    def test_sensitive_scanner_is_a_validator_gate_for_trace_and_companions(self):
        changed = copy.deepcopy(self.trace)
        changed["failure"]["code"] = "Bearer SYNTHETIC_TOKEN_123"
        with self.assertRaisesRegex(HarnessContractV38Error, "secret-like persisted value"):
            validate_run_trace_v38(changed)
        companion = {"diagnostic": "Bearer SYNTHETIC_TOKEN_456"}
        with self.assertRaisesRegex(HarnessContractV38Error, "secret-like persisted value"):
            validate_run_trace_v38(self.trace, scan_companions=[companion])

    def test_v38_is_new_offline_only_and_preserves_all_prior_versions(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["runs"]), 36)
        self.assertFalse(plan["authorization"]["paid_calls_authorized"])
        ids = {row["run_id"] for row in plan["runs"]}
        for version in ["3.5", "3.6", "3.7"]:
            old = load(ROOT / "contracts" / f"stage3_acceptance_plan.v{version}.json")
            self.assertFalse(ids & {row["run_id"] for row in old["runs"]})
        manifest = build_contract_manifest()
        self.assertEqual(validate_contract_bundle(manifest), [])
        self.assertEqual(manifest["supersedes"]["v3_7_bundle_sha256"], "354e8413e5f3d65351c819a84344435451a27c6b50be7982b77d9f76804bfc44")


if __name__ == "__main__":
    unittest.main()
