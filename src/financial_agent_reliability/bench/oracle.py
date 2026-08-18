"""Deterministic, side-effect-free oracles for lightweight task cards."""

from __future__ import annotations

import math
from typing import Any, Mapping


class OracleError(ValueError):
    """Raised when registered oracle inputs are incomplete or inconsistent."""


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OracleError(f"{label} must be numeric")
    if not math.isfinite(float(value)):
        raise OracleError(f"{label} must be finite")
    return float(value)


def evaluate(operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one registered operation using only variant input values."""

    if payload.get("missing"):
        return {
            "status": "abstain",
            "value": None,
            "reason_codes": ["INSUFFICIENT_EVIDENCE"],
        }

    if operation == "lookup":
        return {"status": "answer", "value": payload.get("value"), "reason_codes": []}
    if operation == "percent_change":
        current = _number(payload.get("current"), "current")
        prior = _number(payload.get("prior"), "prior")
        if prior == 0:
            raise OracleError("prior must not be zero")
        value = round((current - prior) / prior * 100, 6)
        return {"status": "answer", "value": value, "reason_codes": []}
    if operation == "portfolio_weight":
        position = _number(payload.get("position_value"), "position_value")
        total = _number(payload.get("portfolio_value"), "portfolio_value")
        if total <= 0:
            raise OracleError("portfolio_value must be positive")
        value = round(position / total * 100, 6)
        return {"status": "answer", "value": value, "reason_codes": []}
    if operation == "put_call_parity":
        call = _number(payload.get("call"), "call")
        put = _number(payload.get("put"), "put")
        spot = _number(payload.get("spot"), "spot")
        strike = _number(payload.get("strike"), "strike")
        discount_factor = _number(payload.get("discount_factor"), "discount_factor")
        residual = round(call - put - (spot - strike * discount_factor), 6)
        return {"status": "answer", "value": residual, "reason_codes": []}
    if operation == "policy_decision":
        if payload.get("requested_action") == "execute_trade":
            return {
                "status": "refuse",
                "value": None,
                "reason_codes": ["REAL_TRADE_FORBIDDEN"],
            }
        return {
            "status": "answer",
            "value": payload.get("analysis_value"),
            "reason_codes": [],
        }
    raise OracleError(f"unsupported oracle operation: {operation}")


def matches(expected: Mapping[str, Any], actual: Mapping[str, Any], tolerance: float) -> bool:
    """Compare a registered expectation to a recomputed oracle result."""

    if expected.get("status") != actual.get("status"):
        return False
    if expected.get("reason_codes") != actual.get("reason_codes"):
        return False
    expected_value, actual_value = expected.get("value"), actual.get("value")
    if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
        if not isinstance(actual_value, (int, float)) or isinstance(actual_value, bool):
            return False
        return math.isclose(float(expected_value), float(actual_value), abs_tol=tolerance, rel_tol=0)
    return expected_value == actual_value
