"""Sequential, bounded matrix execution for the benchmark MVP."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Any

from financial_agent_reliability.bench.model import Candidate
from financial_agent_reliability.bench.adapters import CandidateRequest, OfflineMockTools, get_adapter
from financial_agent_reliability.bench.graders import grade
from financial_agent_reliability.bench.trace import CURRENT_TRACE_VERSION
from financial_agent_reliability.harness.secret_scan import scan_persisted_value_for_secrets


_PROVIDER_ERROR_CODES = {
    "TIMEOUT",
    "RATE_LIMITED",
    "PROVIDER_UNAVAILABLE",
    "AUTHENTICATION_FAILED",
    "PERMISSION_DENIED",
    "PROVIDER_REJECTED_REQUEST",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token_estimate(value: Any) -> int:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return (len(rendered) + 3) // 4


def _git_state(root: pathlib.Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version_coordinates(
    *, repository_root: pathlib.Path, tasks_path: pathlib.Path, candidates_path: pathlib.Path
) -> dict[str, Any]:
    """Return the version evidence needed to reproduce one lightweight run."""

    coordinates: dict[str, Any] = {
        "taskset_sha256": _sha256(tasks_path),
        "candidates_sha256": _sha256(candidates_path),
        "trace_schema_version": CURRENT_TRACE_VERSION,
    }
    for name, key in (("uv.lock", "python_lock_sha256"), ("package-lock.json", "node_lock_sha256")):
        path = repository_root / name
        coordinates[key] = _sha256(path) if path.is_file() else None
    return coordinates


def _failure_signature(
    result: Any, score: dict[str, Any], evidence_refs: list[str]
) -> dict[str, str] | None:
    if result.error is not None:
        code = str(result.error["code"])
    elif not score["hard_gate_passed"]:
        code = "SAFETY_HARD_GATE"
    elif not evidence_refs:
        code = "MISSING_EVIDENCE"
    elif score["correctness"] < 4:
        code = "WRONG_ANSWER"
    else:
        return None
    return {
        "code": code,
        "phenomenon": code.lower().replace("_", " "),
        "attribution_hypothesis": "candidate adapter behavior",
        "next_validation": "re-run the same filtered cell with behavior=pass",
    }


def run_matrix(
    tasks: list[dict[str, Any]],
    candidates: list[Candidate],
    *,
    repository_root: pathlib.Path,
    run_id: str | None = None,
    versions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a model × agent matrix sequentially and stop on provider error-rate breach."""

    resolved_run_id = run_id or f"run-{uuid.uuid4().hex}"
    git = _git_state(repository_root)
    traces: list[dict[str, Any]] = []
    provider_attempts = 0
    provider_errors = 0
    adapters = {
        candidate.id: get_adapter(candidate.adapter, repository_root=repository_root)
        for candidate in candidates
    }
    # Task-major round-robin prevents a slow first model from starving every
    # other model before a provider stop condition has enough evidence.
    for task in tasks:
        for candidate in candidates:
            adapter = adapters[candidate.id]
            started_at = _timestamp()
            request = CandidateRequest.from_payload(task["candidate_payload"])
            tools = OfflineMockTools(request)
            result = adapter.execute(request, candidate, tools)
            error_code = str((result.error or {}).get("code", ""))
            if candidate.adapter == "bailian-live":
                provider_attempts += 1
                provider_errors += error_code in _PROVIDER_ERROR_CODES
            tool_calls = tools.calls
            score, evidence_refs, safety_violations = grade(task, result, tool_calls)
            finished_at = _timestamp()
            identity = f"{resolved_run_id}\0{candidate.id}\0{task['task_id']}"
            traces.append(
                {
                    "schema_version": CURRENT_TRACE_VERSION,
                    "trace_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "run_id": resolved_run_id,
                    "task": {
                        "id": task["task_id"],
                        "slice": task.get("task_card", {}).get("slice", "legacy"),
                        "variant": task.get("task_card", {}).get("variant", "default"),
                    },
                    "candidate": {
                        "id": candidate.id,
                        "model": candidate.model,
                        "agent": candidate.agent,
                        "adapter": candidate.adapter,
                        "adapter_version": adapter.version,
                        "config": candidate.config,
                        "config_sha256": candidate.config_sha256,
                    },
                    "input": task["input"],
                    "tool_calls": tool_calls,
                    "provider_identity": result.provider_identity,
                    "provider_observability": result.provider_observability,
                    "output": result.output,
                    "error": result.error,
                    "evidence_refs": evidence_refs,
                    "safety_violations": safety_violations,
                    "score": score,
                    "failure_signature": _failure_signature(result, score, evidence_refs),
                    "metrics": {
                        "latency_ms": result.latency_ms,
                        "input_tokens_estimate": result.input_tokens or _token_estimate(task["input"]),
                        "output_tokens_estimate": result.output_tokens or _token_estimate(result.output),
                        "cost_usd_estimate": "0.000000",
                        "cost_basis": result.cost_basis,
                    },
                    "git": git,
                    "versions": versions or {"trace_schema_version": CURRENT_TRACE_VERSION},
                    "started_at": started_at,
                    "finished_at": finished_at,
                }
            )
            findings = scan_persisted_value_for_secrets(traces[-1])
            if findings:
                raise ValueError(
                    "trace rejected by persisted-secret gate: " + ", ".join(findings)
                )
            if candidate.adapter == "bailian-live" and (
                not score["hard_gate_passed"]
                or error_code == "IDENTITY_MISMATCH"
                or (
                    provider_attempts >= 10
                    and provider_errors / provider_attempts > 0.10
                )
            ):
                return traces
    return traces


run_mock_matrix = run_matrix
