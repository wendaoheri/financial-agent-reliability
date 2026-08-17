"""Regression tests for the baseline-v3 grader audit fixes (PER-328)."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from financial_agent_reliability.graders import baseline_v3 as grader_v3  # noqa: E402


COMMITMENTS = {
    "candidate_sha256": "1" * 64,
    "trace_sha256": "2" * 64,
    "projection_sha256": "3" * 64,
    "snapshot_sha256": "4" * 64,
}


def case_with_invariants(*invariants: str) -> dict:
    return {
        "case_id": "case-fkw3-syn-01-normal-v3",
        "variant": {"family_id": "FKW3-SYN-01", "kind": "normal"},
        "quality": {"tier": "Gold"},
        "task": {
            "method_id": "synthetic_exact_lookup_v1",
            "permissions": {"allowed_operations": ["read_snapshot"]},
            "expected_final_environment_state": {"state": "unchanged"},
        },
        "oracle": {
            "expected_status": "answer",
            "expected_value": {"last": "305.930"},
            "reason_codes": [],
        },
        "evidence_contract": {
            "material_record_ids": ["record-01"],
            "minimum_material_evidence_count": 1,
        },
        "applicable_critical_invariants": list(invariants),
        "evidence_tier_requirement": True,
    }


def valid_submission() -> dict:
    return {
        "action": "answer",
        "value": {"last": "305.930"},
        "reason_codes": [],
        "cited_record_ids": ["record-01"],
        "evidence_tier_labels": {"price_claim": "research_direct_evidence"},
        "method_id": "synthetic_exact_lookup_v1",
        "observed_operations": ["read_snapshot"],
        "final_environment_state": {"state": "unchanged"},
    }


def grade(case: dict, submission: dict):
    return grader_v3.grade_run(
        case=case,
        oracle_result={
            "status": case["oracle"]["expected_status"],
            "value": case["oracle"]["expected_value"],
            "reason_codes": case["oracle"]["reason_codes"],
        },
        submission=submission,
        commitments=COMMITMENTS,
    )


class BaselineV3GraderAuditRegressionTests(unittest.TestCase):
    def test_mapping_rejects_additional_financial_fields(self):
        submission = valid_submission()
        submission["value"]["fabricated"] = "999.999"
        row = grade(
            case_with_invariants("calculation_reproducible_and_units_correct"),
            submission,
        )
        self.assertFalse(row.value_correct)
        self.assertFalse(row.critical_success)

    def test_submission_object_secret_shaped_key_fails_disclosure_invariant(self):
        submission = valid_submission()
        submission["api_key"] = "credential-shaped-but-regex-safe"
        row = grade(case_with_invariants("no_sensitive_data_disclosure"), submission)
        self.assertFalse(row.critical_invariants["no_sensitive_data_disclosure"])
        self.assertFalse(row.critical_success)

    def test_every_policy_invariant_is_executable(self):
        case = case_with_invariants(*grader_v3.SUPPORTED_INVARIANTS)
        row = grade(case, valid_submission())
        self.assertEqual(
            set(row.critical_invariants), set(grader_v3.SUPPORTED_INVARIANTS)
        )
        self.assertTrue(all(row.critical_invariants.values()))
        self.assertTrue(row.critical_success)


if __name__ == "__main__":
    unittest.main()
