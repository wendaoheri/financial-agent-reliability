import copy
import json
import pathlib
import tempfile
import unittest

from contracts.run_trace_validator_v3_7 import HarnessContractV37Error, validate_run_trace_v37
from financial_agent_reliability.harness.acceptance_v3_7 import (
    ALL_CHECKS,
    build_contract_manifest,
    build_offline_plan,
    content_sha256,
    derive_reason_codes_v37,
    grade_candidate_v37,
    independent_expected_from_snapshot,
    tool_schemas_v37,
    validate_contract_bundle,
    validate_preserved_v35_plan,
    validate_reason_code_set_v37,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "acceptance_v3_7"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FinancialAcceptanceV37Tests(unittest.TestCase):
    def setUp(self):
        self.baseline = load(FIXTURES / "grader.baseline.json")
        self.projection = load(ROOT / self.baseline["projection_path"])
        self.snapshot = load(ROOT / self.baseline["snapshot_path"])
        self.candidate = self.baseline["candidate"]
        self.trace = self.baseline["trace"]

    def assertTraceRejected(self, mutator, pattern):
        value = copy.deepcopy(self.trace)
        mutator(value)
        with self.assertRaisesRegex(HarnessContractV37Error, pattern):
            validate_run_trace_v37(value)

    def test_plan_is_new_offline_only_and_has_no_expected_answers(self):
        plan = build_offline_plan(write=False)
        self.assertEqual(len(plan["runs"]), 36)
        self.assertEqual(len({row["run_id"] for row in plan["runs"]}), 36)
        self.assertFalse(plan["authorization"]["paid_calls_authorized"])
        self.assertNotIn("expected", json.dumps(plan).lower())
        old = load(ROOT / "contracts" / "stage3_acceptance_plan.v3.6.json")
        self.assertFalse({row["run_id"] for row in plan["runs"]} & {row["run_id"] for row in old["runs"]})
        for task in plan["tasks"]:
            projection = load(ROOT / task["projection_path"])
            self.assertEqual(task["tool_schema_sha256"], content_sha256(tool_schemas_v37(projection)))

    def test_identity_plan_and_request_commitments_are_hard_gates(self):
        self.assertEqual(validate_run_trace_v37(self.trace)["status"], "succeeded")
        self.assertTraceRejected(lambda t: t["provider"].update(response_model_id="unexpected-fallback"), "response model")
        self.assertTraceRejected(lambda t: t["logical_requests"][0]["attempts"][0].update(model_id="deepseek-v4-pro"), "attempt model")
        self.assertTraceRejected(lambda t: t["logical_requests"][0].update(tool_schema_sha256="not-a-hash"), "tool_schema_sha256")
        self.assertTraceRejected(lambda t: t["logical_requests"][0].update(parameters_sha256="f" * 64), "parameters hash")
        self.assertTraceRejected(lambda t: t["run_identity"].update(seed=99), "plan membership")

    def test_multi_request_retry_accounting_reconciles_to_budget(self):
        trace = load(FIXTURES / "trace.multi_request_retry.json")
        result = validate_run_trace_v37(trace)
        self.assertEqual(result["logical_requests"], 3)
        self.assertEqual(result["provider_attempts"], 4)
        changed = copy.deepcopy(trace)
        changed["usage"]["model_requests"] = 2
        with self.assertRaisesRegex(HarnessContractV37Error, "model request accounting"):
            validate_run_trace_v37(changed)
        changed = copy.deepcopy(trace)
        changed["logical_requests"][1]["attempts"][1]["payload_sha256"] = "e" * 64
        with self.assertRaisesRegex(HarnessContractV37Error, "identical replay"):
            validate_run_trace_v37(changed)

    def test_wire_schema_required_fields_and_additional_fields_are_enforced(self):
        good = grade_candidate_v37(self.candidate, self.projection, self.snapshot, self.trace)
        self.assertTrue(good["checks"]["structure_parsed"])
        for field in ["uncertainty", "permission_boundary_claimed"]:
            changed = copy.deepcopy(self.candidate)
            changed.pop(field)
            result = grade_candidate_v37(changed, self.projection, self.snapshot, self.trace)
            self.assertFalse(result["checks"]["structure_parsed"], field)
        changed = copy.deepcopy(self.candidate)
        changed["unexpected"] = True
        self.assertFalse(grade_candidate_v37(changed, self.projection, self.snapshot, self.trace)["checks"]["structure_parsed"])

    def test_evidence_and_pit_are_based_on_observations_not_candidate_claims(self):
        changed = copy.deepcopy(self.trace)
        changed["evidence_observations"] = []
        result = grade_candidate_v37(self.candidate, self.projection, self.snapshot, changed)
        self.assertFalse(result["checks"]["evidence_provenance_valid"])
        self.assertFalse(result["checks"]["evidence_sufficient"])
        changed = copy.deepcopy(self.trace)
        changed["evidence_observations"][0]["available_at"] = "2099-01-01T00:00:00Z"
        self.assertFalse(grade_candidate_v37(self.candidate, self.projection, self.snapshot, changed)["checks"]["pit_valid"])
        cited_without_read = copy.deepcopy(self.candidate)
        cited_without_read["evidence_record_ids"] = [self.projection["evidence_contract"]["registered_record_ids"][0]]
        self.assertFalse(grade_candidate_v37(cited_without_read, self.projection, self.snapshot, self.trace)["checks"]["evidence_provenance_valid"])

    def test_independent_oracle_uses_snapshot_and_not_source_oracle(self):
        expected = independent_expected_from_snapshot(self.projection, self.snapshot)
        self.assertEqual(expected["value"]["value"], "36.147934")
        poisoned = copy.deepcopy(self.projection)
        poisoned["oracle"] = {"value": "999"}
        self.assertEqual(independent_expected_from_snapshot(poisoned, self.snapshot), expected)

    def test_independent_unit_method_calculation_and_security_checks(self):
        good = grade_candidate_v37(self.candidate, self.projection, self.snapshot, self.trace)
        for check in ["unit_correct", "method_correct", "calculation_correct", "no_secret_leakage"]:
            self.assertTrue(good["checks"][check])
        mutations = {
            "unit_correct": lambda t: t["analysis_observations"]["unit"].update(observed="currency"),
            "method_correct": lambda t: t["analysis_observations"]["method"].update(observed="three_year_average"),
            "calculation_correct": lambda t: t["analysis_observations"]["calculation"].update(output_sha256="f" * 64),
        }
        for check, mutate in mutations.items():
            changed = copy.deepcopy(self.trace)
            mutate(changed)
            self.assertFalse(grade_candidate_v37(self.candidate, self.projection, self.snapshot, changed)["checks"][check], check)
        leaked = copy.deepcopy(self.trace)
        leaked["provider"]["diagnostic"] = "Bearer synthetic-token-123"
        with self.assertRaisesRegex(HarnessContractV37Error, "secret"):
            validate_run_trace_v37(leaked)
        self.assertFalse(grade_candidate_v37(self.candidate, self.projection, self.snapshot, leaked)["checks"]["no_secret_leakage"])

    def test_permission_grade_uses_trace_not_candidate_self_report(self):
        self_report_false = copy.deepcopy(self.candidate)
        self_report_false["permission_boundary_claimed"] = False
        self.assertTrue(grade_candidate_v37(self_report_false, self.projection, self.snapshot, self.trace)["checks"]["permission_boundary_respected"])
        changed = copy.deepcopy(self.trace)
        changed["permission"]["observed_operations"].append("simulated_ledger")
        self.assertFalse(grade_candidate_v37(self.candidate, self.projection, self.snapshot, changed)["checks"]["permission_boundary_respected"])
        changed = copy.deepcopy(self.trace)
        changed["permission"]["declared_permissions"] = []
        self.assertFalse(grade_candidate_v37(self.candidate, self.projection, self.snapshot, changed)["checks"]["permission_boundary_respected"])

    def test_reason_code_vocabulary_has_positive_negative_and_suppression_fixtures(self):
        matrix = load(FIXTURES / "reason_code_matrix.json")
        self.assertEqual(len(matrix), 18)
        observed = set()
        for row in matrix:
            projection = {"task": {"inputs": row["inputs"], "permissions": row.get("permissions", [])}, "evidence_contract": row.get("evidence_contract", {})}
            actual = derive_reason_codes_v37(projection, row.get("runtime_facts", {}))
            self.assertEqual(actual, row["expected"], row["code"])
            self.assertIn(row["code"], actual)
            negative_projection = {"task": {"inputs": row["negative_inputs"], "permissions": row.get("negative_permissions", [])}, "evidence_contract": row.get("negative_evidence_contract", {})}
            self.assertNotIn(row["code"], derive_reason_codes_v37(negative_projection, row.get("negative_runtime_facts", {})), f"negative:{row['code']}")
            observed.add(row["code"])
        vocabulary = set(load(ROOT / "contracts" / "reason_codes.v3.7.json")["definitions"])
        self.assertEqual(observed, vocabulary)
        suppressed = {"task": {"inputs": {"ambiguous_source_authority": True}, "permissions": []}, "evidence_contract": {"registered_record_ids": [], "minimum_material_evidence_count": 1}}
        self.assertEqual(derive_reason_codes_v37(suppressed), ["AMBIGUOUS_SOURCE_AUTHORITY"])

    def test_all_reason_codes_enforce_allowed_status_and_exact_set(self):
        definitions = load(ROOT / "contracts" / "reason_codes.v3.7.json")["definitions"]
        for row in load(FIXTURES / "reason_code_matrix.json"):
            projection = {"task": {"inputs": row["inputs"], "permissions": row.get("permissions", [])}, "evidence_contract": row.get("evidence_contract", {})}
            allowed = definitions[row["code"]]["allowed_statuses"][0]
            self.assertEqual(validate_reason_code_set_v37(row["expected"], allowed, projection, row.get("runtime_facts", {})), [], row["code"])
            disallowed = [status for status in ["answer", "abstain", "escalate", "reject_action"] if status not in definitions[row["code"]]["allowed_statuses"]]
            if disallowed:
                self.assertTrue(any(item.startswith("status:") for item in validate_reason_code_set_v37(row["expected"], disallowed[0], projection, row.get("runtime_facts", {}))), row["code"])

    def test_strict_schemas_cover_every_grader_check(self):
        trace_schema = load(ROOT / "contracts" / "run_trace.schema.v3.7.json")
        grader_schema = load(ROOT / "contracts" / "stage3_independent_grader_result.schema.v3.7.json")
        for field in ["run_identity", "provider", "result", "permission", "environment", "redaction"]:
            self.assertFalse(trace_schema["properties"][field].get("additionalProperties", True), field)
        self.assertFalse(trace_schema["properties"]["logical_requests"]["items"]["additionalProperties"])
        checks = grader_schema["properties"]["checks"]
        self.assertEqual(set(checks["required"]), set(ALL_CHECKS))
        self.assertFalse(checks["additionalProperties"])

    def test_bundle_recomputes_and_v35_v36_are_pinned(self):
        manifest = build_contract_manifest()
        self.assertEqual(validate_contract_bundle(manifest), [])
        self.assertEqual(manifest["supersedes"]["v3_6_bundle_sha256"], "afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959")
        self.assertEqual(manifest["preserved"]["v3_5_bundle_sha256"], "d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8")

    def test_preserved_v35_plan_is_validated_without_regeneration(self):
        self.assertEqual(validate_preserved_v35_plan(), [])


if __name__ == "__main__":
    unittest.main()
