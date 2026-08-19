"""Deterministic mock matrix execution for the benchmark MVP."""

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
        "trace_schema_version": "0.2.0",
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


def run_mock_matrix(
    tasks: list[dict[str, Any]],
    candidates: list[Candidate],
    *,
    repository_root: pathlib.Path,
    run_id: str | None = None,
    versions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a model × agent matrix without network access or credentials."""

    resolved_run_id = run_id or f"run-{uuid.uuid4().hex}"
    git = _git_state(repository_root)
    traces: list[dict[str, Any]] = []
    for candidate in candidates:
        adapter = get_adapter(candidate.adapter)
        for task in tasks:
            started_at = _timestamp()
            request = CandidateRequest.from_payload(task["candidate_payload"])
            tools = OfflineMockTools(request)
            result = adapter.execute(request, candidate, tools)
            tool_calls = tools.calls
            score, evidence_refs, safety_violations = grade(task, result, tool_calls)
            finished_at = _timestamp()
            identity = f"{resolved_run_id}\0{candidate.id}\0{task['task_id']}"
            traces.append(
                {
                    "schema_version": "0.2.0",
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
                    "output": result.output,
                    "error": result.error,
                    "evidence_refs": evidence_refs,
                    "safety_violations": safety_violations,
                    "score": score,
                    "failure_signature": _failure_signature(result, score, evidence_refs),
                    "metrics": {
                        "latency_ms": result.latency_ms,
                        "input_tokens_estimate": _token_estimate(task["input"]),
                        "output_tokens_estimate": _token_estimate(result.output),
                        "cost_usd_estimate": "0.000000",
                    },
                    "git": git,
                    "versions": versions or {"trace_schema_version": "0.2.0"},
                    "started_at": started_at,
                    "finished_at": finished_at,
                }
            )
    return traces
