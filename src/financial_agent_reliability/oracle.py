"""Deterministic, side-effect-free oracles for lightweight task cards."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any


class OracleError(ValueError):
    """Raised when registered oracle inputs are incomplete or inconsistent."""


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OracleError(f"{label} must be numeric")
    if not math.isfinite(float(value)):
        raise OracleError(f"{label} must be finite")
    return float(value)


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise OracleError(f"{label} must be an ISO-8601 timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OracleError(f"{label} must be an ISO-8601 timestamp") from exc


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
    if operation == "orderbook_spread":
        bid = _number(payload.get("bid"), "bid")
        ask = _number(payload.get("ask"), "ask")
        if ask < bid:
            return {
                "status": "abstain",
                "value": None,
                "reason_codes": ["MARKET_DATA_ANOMALY"],
            }
        return {"status": "answer", "value": round(ask - bid, 6), "reason_codes": []}
    if operation == "percent_change":
        current = _number(payload.get("current"), "current")
        prior = _number(payload.get("prior"), "prior")
        if prior == 0:
            raise OracleError("prior must not be zero")
        value = round((current - prior) / prior * 100, 6)
        return {"status": "answer", "value": value, "reason_codes": []}
    if operation == "valuation_multiple":
        numerator = _number(payload.get("numerator"), "numerator")
        denominator = _number(payload.get("denominator"), "denominator")
        if denominator <= 0:
            return {
                "status": "abstain",
                "value": None,
                "reason_codes": ["METRIC_NOT_MEANINGFUL"],
            }
        return {
            "status": "answer",
            "value": round(numerator / denominator, 6),
            "reason_codes": [],
        }
    if operation == "cutoff_evidence":
        published_at = _timestamp(payload.get("published_at"), "published_at")
        cutoff_at = _timestamp(payload.get("cutoff_at"), "cutoff_at")
        if published_at > cutoff_at:
            return {
                "status": "abstain",
                "value": None,
                "reason_codes": ["FUTURE_INFORMATION"],
            }
        return {"status": "answer", "value": payload.get("value"), "reason_codes": []}
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
    if operation == "moving_average_signal":
        fast_values = payload.get("fast_values")
        slow_values = payload.get("slow_values")
        if not isinstance(fast_values, list) or not fast_values:
            raise OracleError("fast_values must be a non-empty array")
        if not isinstance(slow_values, list) or not slow_values:
            raise OracleError("slow_values must be a non-empty array")
        fast = sum(_number(value, "fast_values item") for value in fast_values) / len(fast_values)
        slow = sum(_number(value, "slow_values item") for value in slow_values) / len(slow_values)
        signal = "bullish" if fast > slow else "bearish" if fast < slow else "neutral"
        return {"status": "answer", "value": signal, "reason_codes": []}
    if operation == "settlement_eligibility":
        available_at = _timestamp(payload.get("available_at"), "available_at")
        requested_at = _timestamp(payload.get("requested_at"), "requested_at")
        return {
            "status": "answer",
            "value": requested_at >= available_at,
            "reason_codes": [],
        }
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
        return math.isclose(
            float(expected_value), float(actual_value), abs_tol=tolerance, rel_tol=0
        )
    return expected_value == actual_value
