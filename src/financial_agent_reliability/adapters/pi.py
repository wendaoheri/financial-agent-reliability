"""Exact-pinned pi-agent-core adapters for offline fixtures and gated live pilots."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time
from collections.abc import Mapping
from importlib import resources

from financial_agent_reliability.adapters.core import (
    AdapterResult,
    CandidateRequest,
    OfflineMockTools,
)
from financial_agent_reliability.adapters.generation import resolve_generation
from financial_agent_reliability.adapters.settings import BailianSettings
from financial_agent_reliability.config import load_run_config
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
                "output_contract": request.output_contract,
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


class PiAgentLiveAdapter:
    """Run the pinned pi Agent against an explicitly approved Bailian endpoint."""

    name = "pi-agent-live"
    version = "pi-agent-core@0.73.1"

    def __init__(
        self,
        repository_root: pathlib.Path,
        *,
        env: Mapping[str, str] = os.environ,
    ) -> None:
        self._root = repository_root
        self._env = env

    @staticmethod
    def _script() -> pathlib.Path:
        return pathlib.Path(
            str(
                resources.files("financial_agent_reliability.adapters").joinpath(
                    "pi_live_runtime.mjs"
                )
            )
        )

    def _runtime(self, candidate: Candidate) -> tuple[dict[str, object], str]:
        config = load_run_config(candidate.source_path.resolve())
        try:
            model = next(item for item in config.models if item.model_id == candidate.model)
        except StopIteration as exc:
            raise ValueError(
                f"candidate model is absent from run config: {candidate.model}"
            ) from exc
        settings = BailianSettings.from_config(config, self._env, model.provider)
        provider = config.provider(model.provider)
        generation = dict(candidate.config.get("generation") or {})
        generation["seed"] = int(candidate.config.get("seed", 20260819))
        resolved = resolve_generation(
            provider,
            model,
            profile=config.profile(candidate.config.get("profile")),
            candidate=generation,
        )
        runtime: dict[str, object] = {
            "base_url": settings.base_url,
            "endpoint_id": settings.endpoint_id,
            "timeout_ms": max(1, round(provider.timeout_seconds * 1000)),
            "parameters": dict(resolved.effective_parameters),
            "generation_profile": resolved.trace_record(),
            "reasoning": model.capabilities.get("reasoning") == "required",
            "max_provider_turns": int(candidate.config.get("max_provider_turns", 2)),
        }
        return runtime, config.source_sha256

    def _invoke(self, payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        node = shutil.which("node")
        if node is None:
            raise ValueError("pi-agent-live requires Node.js on PATH")
        completed = subprocess.run(
            [node, str(self._script())],
            input=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            cwd=self._root,
            env=dict(self._env),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("pi live runtime returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("pi live runtime result must be an object")
        if completed.returncode != 0 and result.get("error") is None:
            result["error"] = {
                "code": "PI_AGENT_ERROR",
                "message": "pi live runtime exited unsuccessfully",
                "retryable": False,
            }
        return result

    @staticmethod
    def _candidate_payload(candidate: Candidate) -> dict[str, object]:
        return {
            "id": candidate.id,
            "model": candidate.model,
            "agent": candidate.agent,
            "config": candidate.config,
        }

    def preflight(self, candidate: Candidate) -> dict[str, object]:
        # pi-ai stores the requested model in AssistantMessage.model and only
        # populates responseModel when the provider returns a *different* ID.
        # Use the minimal direct transport here so the bound preflight retains
        # affirmative exact-response identity evidence from the raw SSE model.
        from financial_agent_reliability.adapters.core import BailianLiveAdapter

        return BailianLiveAdapter(self._root, env=self._env).preflight(candidate)

    def execute(
        self, request: CandidateRequest, candidate: Candidate, tools: OfflineMockTools
    ) -> AdapterResult:
        runtime, _config_sha256 = self._runtime(candidate)
        payload = {
            "mode": "run",
            "request": {
                "task_id": request.task_id,
                "input": request.input,
                "tools": list(request.tools),
                "resources": list(request.resources),
                "budget": request.budget,
                "output_contract": request.output_contract,
            },
            "candidate": self._candidate_payload(candidate),
            "runtime": runtime,
        }
        turns = int(runtime["max_provider_turns"])
        timeout = (float(runtime["timeout_ms"]) / 1000) * turns + 5
        try:
            result = self._invoke(payload, timeout)
        except subprocess.TimeoutExpired:
            return AdapterResult(
                output=None,
                error={
                    "code": "TIMEOUT",
                    "message": "pi live runtime timed out",
                    "retryable": True,
                },
                latency_ms=max(0, round(timeout * 1000)),
                cost_basis="token_plan_unpriced",
            )
        for call in result.get("tool_calls") or []:
            if (
                not isinstance(call, dict)
                or call.get("action") != "read"
                or call.get("status") != "ok"
            ):
                raise ValueError("pi live runtime emitted a non-read or failed fixture call")
            tools.invoke(str(call.get("tool")))
        usage = result.get("usage") or {}
        events = result.get("agent_events") or []
        if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
            raise ValueError("pi live runtime agent_events must be an array of objects")
        return AdapterResult(
            output=result.get("output"),
            error=result.get("error"),
            latency_ms=max(0, int(result.get("latency_ms", 0))),
            final_output_raw=(
                str(result["final_output_raw"])
                if isinstance(result.get("final_output_raw"), str)
                else None
            ),
            input_tokens=max(0, int(usage.get("input_tokens", 0))),
            output_tokens=max(0, int(usage.get("output_tokens", 0))),
            provider_identity=result.get("provider_identity"),
            cost_basis="token_plan_unpriced",
            provider_observability=result.get("provider_observability"),
            agent_events=tuple(events),
        )
