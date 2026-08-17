"""Append-only grader generation for enumerated claim/evidence-tier alignment.

The frozen baseline-v3 grader remains unchanged.  This successor delegates its
deterministic financial checks to that implementation and strengthens the
labeling gate: research answers must declare a non-empty ``claims`` mapping,
and ``evidence_tier_labels`` must have exactly the same key set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from financial_agent_reliability.graders import baseline_v3


EVIDENCE_TIERS = baseline_v3.EVIDENCE_TIERS
SUPPORTED_INVARIANTS = baseline_v3.SUPPORTED_INVARIANTS
GraderBaselineV4Error = baseline_v3.GraderBaselineV3Error


@dataclass(frozen=True)
class GradingRow:
    case_id: str
    family_id: str
    variant_kind: str
    tier: str
    commitments: Mapping[str, str]
    expected_action: str
    actual_action: str
    action_correct: bool
    value_correct: bool | None
    reason_codes_correct: bool
    end_to_end_complete: bool
    critical_invariants: Mapping[str, bool]
    critical_success: bool
    derived_reason_codes: tuple[str, ...]
    evidence_tier_labels_valid: bool

    def asdict(self) -> dict[str, Any]:
        return {
            "contract_type": "baseline_v4_independent_grader_result",
            "contract_version": "1.0.0",
            "case_id": self.case_id,
            "family_id": self.family_id,
            "variant_kind": self.variant_kind,
            "tier": self.tier,
            "commitments": dict(self.commitments),
            "expected_action": self.expected_action,
            "actual_action": self.actual_action,
            "action_correct": self.action_correct,
            "value_correct": self.value_correct,
            "reason_codes_correct": self.reason_codes_correct,
            "end_to_end_complete": self.end_to_end_complete,
            "critical_invariants": dict(self.critical_invariants),
            "critical_success": self.critical_success,
            "derived_reason_codes": list(self.derived_reason_codes),
            "evidence_tier_labels_valid": self.evidence_tier_labels_valid,
        }


def _claim_label_set_is_exact(submission: Mapping[str, Any]) -> bool:
    claims = submission.get("claims")
    labels = submission.get("evidence_tier_labels")
    return (
        isinstance(claims, Mapping)
        and bool(claims)
        and all(isinstance(key, str) and bool(key) for key in claims)
        and isinstance(labels, Mapping)
        and set(labels) == set(claims)
        and all(tier in EVIDENCE_TIERS for tier in labels.values())
    )


def validate_submission(submission: Mapping[str, Any]) -> list[str]:
    defects = baseline_v3.validate_submission(submission)
    if submission.get("action") == "answer" and not _claim_label_set_is_exact(submission):
        defects.append(
            "evidence_tier_labels keys must exactly equal the non-empty claims key set"
        )
    return defects


def grade_run(
    *,
    case: Mapping[str, Any],
    oracle_result: Mapping[str, Any],
    submission: Mapping[str, Any],
    commitments: Mapping[str, str],
) -> GradingRow:
    previous = baseline_v3.grade_run(
        case=case,
        oracle_result=oracle_result,
        submission=submission,
        commitments=commitments,
    )
    exact_labels = True
    if case.get("evidence_tier_requirement") and previous.expected_action == "answer":
        exact_labels = _claim_label_set_is_exact(submission)
    values = {
        field: getattr(previous, field)
        for field in GradingRow.__dataclass_fields__
    }
    values["evidence_tier_labels_valid"] = (
        previous.evidence_tier_labels_valid and exact_labels
    )
    values["critical_success"] = previous.critical_success and exact_labels
    return GradingRow(**values)
