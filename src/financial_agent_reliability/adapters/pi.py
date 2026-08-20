"""Pinned pi-agent-core adapter using a deterministic, zero-cost fixture transport."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import time
from importlib import resources

from financial_agent_reliability.adapters.core import (
    AdapterResult,
    CandidateRequest,
    OfflineMockTools,
)
from financial_agent_reliability.models import Candidate


class PiAgentOfflineAdapter:
    """Exercise the real pi Agent loop without any provider or external-account access."""

    name = "pi-agent-offline"
    version = "pi-agent-core@0.73.1"

    def __init__(self, repository_root: pathlib.Path) -> None:
        self._root = repository_root

    @staticmethod
    def _script() -> pathlib.Path:
        return pathlib.Path(
            str(resources.files("financial_agent_reliability.adapters").joinpath("pi_runtime.mjs"))
        )

    def execute(
        self, request: CandidateRequest, candidate: Candidate, tools: OfflineMockTools
    ) -> AdapterResult:
        node = shutil.which("node")
        if node is None:
            raise ValueError("pi-agent-offline requires Node.js on PATH")
        payload = {
            "request": {
                "task_id": request.task_id,
                "input": request.input,
                "tools": list(request.tools),
                "resources": list(request.resources),
                "budget": request.budget,
            },
            "candidate": {
                "id": candidate.id,
                "model": candidate.model,
                "agent": candidate.agent,
                "config": candidate.config,
            },
        }
        started = time.perf_counter()
        timeout_seconds = max(0.001, float(request.budget.get("timeout_ms", 3000)) / 1000)
        try:
            completed = subprocess.run(
                [node, str(self._script())],
                input=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                cwd=self._root,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                output=None,
                error={
                    "code": "TIMEOUT",
                    "message": "pi agent fixture timed out",
                    "retryable": True,
                },
                latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
                agent_events=(),
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("pi runtime returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("pi runtime result must be an object")
        runtime = result.get("runtime")
        if completed.returncode == 0 and runtime != {
            "package": "@mariozechner/pi-agent-core",
            "version": "0.73.1",
        }:
            raise ValueError("pi runtime identity mismatch")
        for call in result.get("tool_calls") or []:
            if not isinstance(call, dict):
                raise ValueError("pi runtime tool call must be an object")
            if call.get("action") != "read" or call.get("status") != "ok":
                raise ValueError("pi runtime emitted a non-read or failed fixture call")
            tools.invoke(str(call.get("tool")))
        usage = result.get("usage") or {}
        error = result.get("error")
        if completed.returncode != 0 and error is None:
            error = {
                "code": "PI_AGENT_ERROR",
                "message": "pi runtime exited unsuccessfully",
                "retryable": False,
            }
        events = result.get("agent_events") or []
        if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
            raise ValueError("pi runtime agent_events must be an array of objects")
        return AdapterResult(
            output=result.get("output"),
            error=error,
            latency_ms=max(0, int(result.get("latency_ms", 0))),
            input_tokens=max(0, int(usage.get("input_tokens", 0))),
            output_tokens=max(0, int(usage.get("output_tokens", 0))),
            agent_events=tuple(events),
        )
