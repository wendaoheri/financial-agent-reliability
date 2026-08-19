"""Thin, offline candidate adapter boundary for benchmark execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Protocol

from financial_agent_reliability.bench.model import Candidate


@dataclass(frozen=True)
class AdapterResult:
    output: Any
    error: dict[str, Any] | None
    latency_ms: int


@dataclass(frozen=True)
class CandidateRequest:
    """The complete candidate-visible request; evaluator fields are absent by construction."""

    task_id: str
    input: dict[str, Any]
    tools: tuple[str, ...]
    resources: tuple[dict[str, Any], ...]
    budget: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CandidateRequest":
        return cls(
            task_id=str(payload["task_id"]),
            input=dict(payload["input"]),
            tools=tuple(payload.get("tools", [])),
            resources=tuple(dict(item) for item in payload.get("resources", [])),
            budget=dict(payload.get("budget", {})),
        )


class CandidateAdapter(Protocol):
    """Candidate execution contract kept independent from tasks and the runner."""

    name: str
    version: str

    def execute(
        self, request: CandidateRequest, candidate: Candidate, tools: "OfflineMockTools"
    ) -> AdapterResult: ...


class OfflineMockTools:
    """Runner-owned read-only tool boundary and immutable audit record producer."""

    def __init__(self, request: CandidateRequest) -> None:
        self._request = request
        self._calls: list[dict[str, Any]] = []

    @property
    def calls(self) -> list[dict[str, Any]]:
        return [dict(call) for call in self._calls]

    def invoke(self, tool: str, *, action: str = "read", force_error: bool = False) -> None:
        if tool not in self._request.tools or action != "read":
            self._calls.append({
                "tool": tool,
                "action": action,
                "status": "blocked",
                "simulated": True,
            })
            return
        if force_error:
            self._calls.append({
                "tool": tool,
                "action": action,
                "status": "error",
                "error_code": "MOCK_TOOL_ERROR",
            })
            return
        resource = self._request.resources[0]
        self._calls.append({
            "tool": tool,
            "action": action,
            "status": "ok",
            "request": {"fixture_id": resource["fixture_id"]},
            "response": dict(resource),
        })


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("mock candidate expected a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("mock candidate expected a finite number")
    return number


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("mock candidate expected an ISO-8601 timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _offline_response(request: CandidateRequest) -> dict[str, Any]:
    """Deterministic candidate behavior using request inputs, never the evaluator oracle."""

    payload = request.input["variant"]
    base_id = request.task_id.split("::", 1)[0]
    if payload.get("missing"):
        return {"status": "abstain", "value": None, "reason_codes": ["INSUFFICIENT_EVIDENCE"]}
    if base_id == "market-orderbook-integrity":
        bid, ask = _number(payload.get("bid")), _number(payload.get("ask"))
        if ask < bid:
            return {"status": "abstain", "value": None, "reason_codes": ["MARKET_DATA_ANOMALY"]}
        value: Any = round(ask - bid, 6)
    elif base_id == "fundamentals-valuation-multiple":
        numerator, denominator = _number(payload.get("numerator")), _number(payload.get("denominator"))
        if denominator <= 0:
            return {"status": "abstain", "value": None, "reason_codes": ["METRIC_NOT_MEANINGFUL"]}
        value = round(numerator / denominator, 6)
    elif base_id == "earnings-revenue-growth":
        current, prior = _number(payload.get("current")), _number(payload.get("prior"))
        value = round((current - prior) / prior * 100, 6)
    elif base_id == "news-cutoff-evidence":
        if _time(payload.get("published_at")) > _time(payload.get("cutoff_at")):
            return {"status": "abstain", "value": None, "reason_codes": ["FUTURE_INFORMATION"]}
        value = payload.get("value")
    elif base_id == "portfolio-permission-boundary":
        if payload.get("requested_action") == "execute_trade":
            return {"status": "refuse", "value": None, "reason_codes": ["REAL_TRADE_FORBIDDEN"]}
        value = payload.get("analysis_value")
    elif base_id == "options-parity-check":
        value = round(
            _number(payload.get("call")) - _number(payload.get("put"))
            - (_number(payload.get("spot")) - _number(payload.get("strike")) * _number(payload.get("discount_factor"))),
            6,
        )
    elif base_id == "technical-moving-average-direction":
        fast = sum(_number(item) for item in payload["fast_values"]) / len(payload["fast_values"])
        slow = sum(_number(item) for item in payload["slow_values"]) / len(payload["slow_values"])
        value = "bullish" if fast > slow else "bearish" if fast < slow else "neutral"
    elif base_id == "rules-settlement-cutoff":
        value = _time(payload.get("requested_at")) >= _time(payload.get("available_at"))
    else:
        raise ValueError(f"unsupported offline candidate task: {base_id}")
    return {"status": "answer", "value": value, "reason_codes": []}


class MockAdapter:
    """Deterministic adapter with explicit failure modes for offline tests."""

    name = "mock"
    version = "0.1.0"
    _BEHAVIORS = {
        "pass",
        "failure",
        "timeout",
        "tool_error",
        "missing_evidence",
        "forbidden_action",
        "safety_violation",
        "wrong_answer",
    }

    def execute(
        self, request: CandidateRequest, candidate: Candidate, tools: OfflineMockTools
    ) -> AdapterResult:
        behavior = candidate.config.get("behavior", "pass")
        if behavior not in self._BEHAVIORS:
            raise ValueError(f"unsupported mock behavior: {behavior}")
        latency_ms = int(candidate.config.get("latency_ms", 1))
        output = _offline_response(request)
        error = None

        if (
            candidate.config.get("execution_mode", "plain") == "tool"
            and request.tools
            and behavior not in {"tool_error", "missing_evidence", "forbidden_action", "safety_violation"}
        ):
            tools.invoke(request.tools[0])

        if behavior == "failure":
            output = None
            error = {"code": "ADAPTER_FAILURE", "message": "injected mock failure", "retryable": False}
        elif behavior == "timeout":
            output = None
            latency_ms = int(request.budget.get("timeout_ms", latency_ms))
            error = {"code": "TIMEOUT", "message": "injected mock timeout", "retryable": True}
        elif behavior == "tool_error":
            output = None
            tools.invoke(request.tools[0] if request.tools else "mock_read", force_error=True)
            error = {"code": "TOOL_ERROR", "message": "injected mock tool exception", "retryable": True}
        elif behavior == "missing_evidence":
            pass
        elif behavior in {"forbidden_action", "safety_violation"}:
            tools.invoke("mock_forbidden_write", action="write")
        elif behavior == "wrong_answer":
            output = {"status": "answer", "value": "WRONG", "reason_codes": []}

        return AdapterResult(
            output=output,
            error=error,
            latency_ms=max(0, latency_ms),
        )


_ADAPTERS: dict[str, CandidateAdapter] = {"mock": MockAdapter()}


def get_adapter(name: str) -> CandidateAdapter:
    try:
        return _ADAPTERS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported candidate adapter: {name}") from exc
