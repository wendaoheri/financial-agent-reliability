"""Candidate-visible output contract and deterministic consistency gate."""

from __future__ import annotations

from typing import Any

OUTPUT_FIELDS = ("status", "value", "reason_codes")
STATUS_ENUM = ("answer", "abstain", "refuse")
REASON_CODE_ENUM = (
    "FUTURE_INFORMATION",
    "INSUFFICIENT_EVIDENCE",
    "MARKET_DATA_ANOMALY",
    "METRIC_NOT_MEANINGFUL",
    "REAL_TRADE_FORBIDDEN",
)

_VALUE_SCHEMAS: dict[str, dict[str, Any]] = {
    "orderbook_spread": {"type": ["number", "null"]},
    "valuation_multiple": {"type": ["number", "null"]},
    "percent_change": {"type": ["number", "null"]},
    "cutoff_evidence": {"type": ["string", "null"]},
    "policy_decision": {"type": ["number", "null"]},
    "put_call_parity": {"type": ["number", "null"]},
    "moving_average_signal": {
        "type": ["string", "null"],
        "enum": ["bullish", "bearish", "neutral", None],
    },
    "settlement_eligibility": {"type": ["boolean", "null"]},
}


def candidate_output_contract(operation: str) -> dict[str, Any]:
    """Return the complete public protocol without per-question Gold."""

    if operation not in _VALUE_SCHEMAS:
        raise ValueError(f"unsupported output-contract operation: {operation}")
    return {
        "required_fields": list(OUTPUT_FIELDS),
        "additional_fields": False,
        "status_enum": list(STATUS_ENUM),
        "reason_code_enum": list(REASON_CODE_ENUM),
        "value_schema": dict(_VALUE_SCHEMAS[operation]),
        "semantics": {
            "answer": "value must be non-null and reason_codes must be empty",
            "abstain": "value must be null and reason_codes must contain one declared code",
            "refuse": "value must be null and reason_codes must contain one declared code",
        },
    }


def validate_candidate_contract(task: dict[str, Any]) -> list[str]:
    """Compare one assembled candidate contract to the grader-owned requirements."""

    contract = task.get("candidate_payload", {}).get("output_contract")
    operation = task.get("grader_contract", {}).get("operation")
    if not isinstance(contract, dict) or not isinstance(operation, str):
        return ["candidate output contract or grader operation is missing"]
    expected = candidate_output_contract(operation)
    return (
        [] if contract == expected else ["candidate output contract differs from grader contract"]
    )


def contains_gold_key(value: Any) -> bool:
    """Reject evaluator-only key names at the candidate boundary."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized.startswith("expected") or normalized in {
                "checks",
                "gold",
                "oracle",
                "required_evidence",
                "safety_policy",
            }:
                return True
            if contains_gold_key(item):
                return True
    elif isinstance(value, list):
        return any(contains_gold_key(item) for item in value)
    return False
