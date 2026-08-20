"""Candidate-visible output contract and deterministic consistency gate."""

from __future__ import annotations

import math
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


def validate_candidate_output(contract: dict[str, Any], output: Any) -> list[str]:
    """Validate one parsed candidate output against the complete public contract."""

    if not isinstance(output, dict):
        return ["output must be a JSON object"]
    required = contract.get("required_fields")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        return ["output contract required_fields is invalid"]
    keys = set(output)
    missing = set(required) - keys
    if missing:
        return [f"missing required fields: {', '.join(sorted(missing))}"]
    if contract.get("additional_fields") is False and keys != set(required):
        return ["output contains additional fields"]

    status = output.get("status")
    if status not in contract.get("status_enum", []):
        return ["status is outside the declared enum"]
    reasons = output.get("reason_codes")
    if (
        not isinstance(reasons, list)
        or any(not isinstance(item, str) for item in reasons)
        or len(reasons) != len(set(reasons))
    ):
        return ["reason_codes must be a unique string array"]
    allowed_reasons = contract.get("reason_code_enum")
    if not isinstance(allowed_reasons, list) or any(
        item not in allowed_reasons for item in reasons
    ):
        return ["reason_codes contains an undeclared code"]

    value = output.get("value")
    value_schema = contract.get("value_schema")
    if not isinstance(value_schema, dict) or not _matches_value_schema(value_schema, value):
        return ["value does not match the declared schema"]
    if status == "answer" and (value is None or reasons):
        return ["answer requires a non-null value and no reason codes"]
    if status in {"abstain", "refuse"} and (value is not None or len(reasons) != 1):
        return [f"{status} requires a null value and exactly one reason code"]
    return []


def _matches_value_schema(schema: dict[str, Any], value: Any) -> bool:
    declared = schema.get("type")
    types = declared if isinstance(declared, list) else [declared]
    matches_type = any(
        (
            kind == "null"
            and value is None
            or kind == "number"
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            or kind == "string"
            and isinstance(value, str)
            or kind == "boolean"
            and isinstance(value, bool)
        )
        for kind in types
    )
    return matches_type and ("enum" not in schema or value in schema["enum"])


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
