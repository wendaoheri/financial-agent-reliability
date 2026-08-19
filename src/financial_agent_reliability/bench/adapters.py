"""Thin, offline candidate adapter boundary for benchmark execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from financial_agent_reliability.bench.model import Candidate


@dataclass(frozen=True)
class AdapterResult:
    output: Any
    tool_calls: list[dict[str, Any]]
    error: dict[str, Any] | None
    evidence_refs: list[str]
    safety_violations: list[str]
    latency_ms: int


class CandidateAdapter(Protocol):
    """Candidate execution contract kept independent from tasks and the runner."""

    name: str
    version: str

    def execute(self, task: dict[str, Any], candidate: Candidate) -> AdapterResult: ...


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
        "safety_violation",
    }

    def execute(self, task: dict[str, Any], candidate: Candidate) -> AdapterResult:
        behavior = candidate.config.get("behavior", "pass")
        if behavior not in self._BEHAVIORS:
            raise ValueError(f"unsupported mock behavior: {behavior}")
        required_evidence = list(task.get("required_evidence", []))
        latency_ms = int(candidate.config.get("latency_ms", 1))
        output = task.get("expected_output", {"mock": True, "echo": task["input"]})
        tool_calls: list[dict[str, Any]] = []
        error = None
        safety_violations: list[str] = []

        if behavior == "failure":
            output = None
            error = {"code": "ADAPTER_FAILURE", "message": "injected mock failure", "retryable": False}
        elif behavior == "timeout":
            output = None
            latency_ms = int(task.get("budget", {}).get("timeout_ms", latency_ms))
            error = {"code": "TIMEOUT", "message": "injected mock timeout", "retryable": True}
        elif behavior == "tool_error":
            output = None
            tool_calls = [{"tool": "mock_read", "status": "error", "error_code": "MOCK_TOOL_ERROR"}]
            error = {"code": "TOOL_ERROR", "message": "injected mock tool exception", "retryable": True}
        elif behavior == "missing_evidence":
            required_evidence = []
        elif behavior == "safety_violation":
            tool_calls = [{"tool": "mock_forbidden_write", "status": "blocked", "simulated": True}]
            safety_violations = ["FORBIDDEN_ACTION_ATTEMPTED"]

        return AdapterResult(
            output=output,
            tool_calls=tool_calls,
            error=error,
            evidence_refs=required_evidence,
            safety_violations=safety_violations,
            latency_ms=max(0, latency_ms),
        )


_ADAPTERS: dict[str, CandidateAdapter] = {"mock": MockAdapter()}


def get_adapter(name: str) -> CandidateAdapter:
    try:
        return _ADAPTERS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported candidate adapter: {name}") from exc
