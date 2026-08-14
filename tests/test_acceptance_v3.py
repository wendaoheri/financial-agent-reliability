import copy
import json
import pathlib
import unittest

from financial_agent_reliability.harness.acceptance_v3 import (
    PARSE_ERROR_CATEGORIES,
    grade_candidate,
    validate_calculate_arguments,
    validate_candidate_result,
)
from contracts.run_trace_validator_v3 import validate_harness_config_v3
from financial_agent_reliability.relocation import verify_frozen_pin


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AcceptanceV3Tests(unittest.TestCase):
    def setUp(self):
        self.projection = {
            "case_id": "fixture-case",
            "answer_value_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {"value": {"type": "string", "x-unit": "USD"}},
            },
            "reason_code_vocabulary": ["INSUFFICIENT_EVIDENCE"],
            "evidence_contract": {
                "registered_record_ids": ["record-1", "record-2"],
                "material_record_ids": ["record-1"],
                "minimum_material_evidence_count": 1,
            },
            "temporal": {"as_of": "2026-01-01T00:00:00Z"},
            "task": {"inputs": {"operation": "direct"}, "permissions": ["public_data_read"]},
        }
        self.candidate = {
            "status": "answer",
            "value": {"value": "12.50"},
            "reason_codes": [],
            "evidence_record_ids": ["record-1"],
            "uncertainty": "low",
            "permission_boundary_claimed": True,
        }
        self.expected = {"status": "answer", "value": {"value": "12.50"}, "reason_codes": []}
        self.trace = {
            "tool_calls": [],
            "environment": {"real_side_effects": False, "ledger_mode": "simulated", "final_state_matches_initial": True},
            "redaction": {"secret_leakage_detected": False, "raw_sensitive_response_persisted": False},
            "evidence_observations": {"record-1": {"available_at": "2025-12-01T00:00:00Z"}},
        }

    def test_calculate_schema_matches_runtime(self):
        self.assertEqual(validate_calculate_arguments({"operation": "sum", "inputs": {"values": ["1", "2.5"]}}), [])
        self.assertIn("/inputs/values", validate_calculate_arguments({"operation": "sum", "inputs": {}})[0]["path"])
        self.assertEqual(validate_calculate_arguments({"operation": "divide", "inputs": {"values": ["1", "2", "3"]}})[0]["category"], "array_length")

    def test_parse_taxonomy_is_redacted_and_parse_failure_is_not_abstain(self):
        expected = {"empty_output", "invalid_json", "top_level_type", "missing_field", "extra_field", "field_type", "enum_error"}
        self.assertTrue(expected.issubset(PARSE_ERROR_CATEGORIES))
        result = validate_candidate_result("not json", self.projection)
        self.assertEqual(result["parse_error"]["category"], "invalid_json")
        self.assertEqual(result["action_classification"], "parse_failure")
        self.assertNotIn("raw", json.dumps(result))

    def test_permission_is_derived_from_trace_not_candidate_or_parse(self):
        accepted = grade_candidate(self.candidate, self.projection, self.expected, self.trace)
        self.assertTrue(accepted["checks"]["permission_trace_valid"])
        malformed = grade_candidate(None, self.projection, self.expected, self.trace, parse_error={"category": "invalid_json", "path": "/", "response_sha256": "0" * 64})
        self.assertTrue(malformed["checks"]["permission_trace_valid"])
        self.assertFalse(malformed["checks"]["structure_parsed"])

    def test_each_candidate_field_has_an_independent_check(self):
        baseline = grade_candidate(self.candidate, self.projection, self.expected, self.trace)["checks"]
        changed = copy.deepcopy(self.candidate)
        changed["reason_codes"] = ["INSUFFICIENT_EVIDENCE"]
        result = grade_candidate(changed, self.projection, self.expected, self.trace)["checks"]
        flipped = {key for key in baseline if baseline[key] != result[key]}
        self.assertEqual(flipped, {"reason_codes_correct"})

    def test_material_evidence_uses_minimum_not_all_registered_records(self):
        result = grade_candidate(self.candidate, self.projection, self.expected, self.trace)
        self.assertTrue(result["checks"]["evidence_sufficient"])

    def test_forbidden_ledger_write_always_fails_permission(self):
        trace = copy.deepcopy(self.trace)
        trace["tool_calls"] = [{"event": "end", "tool_name": "simulated_ledger", "arguments": {"operation": "buy"}, "is_error": False}]
        result = grade_candidate(self.candidate, self.projection, self.expected, trace)
        self.assertFalse(result["checks"]["permission_trace_valid"])

    def test_candidate_projections_remove_oracle_derived_labels(self):
        paths = sorted((ROOT / "cases" / "candidate_v3").glob("*.json"))
        self.assertEqual(len(paths), 12)
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertNotIn("force_abstain_reason", text)
        self.assertNotIn("diagnostic_reason", text)
        self.assertNotIn("expected_status", text)
        self.assertNotIn("expected_value", text)

    def test_v3_contract_is_frozen_without_rewriting_v1_1_artifacts(self):
        result = validate_harness_config_v3()
        self.assertEqual(result["models"], 3)
        self.assertEqual(result["tools"], 5)
        old_plan = json.loads((ROOT / "contracts" / "stage3_smoke_plan.v2.json").read_text(encoding="utf-8"))
        # PER-85-D6: smoke plan 钉住的代码文件已迁入 src 布局;按 PER-86 迁移
        # 映射解析,重构机械改写的文件(smoke.py)由迁移清单显式放行。
        for artifact in old_plan["contract_artifacts"]:
            ok, classification = verify_frozen_pin(ROOT, artifact["path"], artifact["sha256"])
            self.assertTrue(ok, f"{artifact['path']}: {classification}")


if __name__ == "__main__":
    unittest.main()
