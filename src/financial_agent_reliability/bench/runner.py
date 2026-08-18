"""Deterministic mock matrix execution for the benchmark MVP."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from financial_agent_reliability.bench.model import Candidate


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


def _mock_output(task: dict[str, Any], candidate: Candidate) -> Any:
    if "expected_output" in task:
        return task["expected_output"]
    return {
        "mock": True,
        "candidate_id": candidate.id,
        "echo": task["input"],
    }


def run_mock_matrix(
    tasks: list[dict[str, Any]],
    candidates: list[Candidate],
    *,
    repository_root: pathlib.Path,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run a model × agent matrix without network access or credentials."""

    resolved_run_id = run_id or f"run-{uuid.uuid4().hex}"
    git = _git_state(repository_root)
    traces: list[dict[str, Any]] = []
    for candidate in candidates:
        for task in tasks:
            started_at = _timestamp()
            started_ns = time.monotonic_ns()
            output = _mock_output(task, candidate)
            finished_at = _timestamp()
            identity = f"{resolved_run_id}\0{candidate.id}\0{task['task_id']}"
            traces.append(
                {
                    "schema_version": "0.1.0",
                    "trace_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "run_id": resolved_run_id,
                    "task": {"id": task["task_id"]},
                    "candidate": {
                        "id": candidate.id,
                        "model": candidate.model,
                        "agent": candidate.agent,
                        "adapter": candidate.adapter,
                        "config": candidate.config,
                        "config_sha256": candidate.config_sha256,
                    },
                    "input": task["input"],
                    "tool_calls": [],
                    "output": output,
                    "error": None,
                    "metrics": {
                        "latency_ms": max(0, (time.monotonic_ns() - started_ns) // 1_000_000),
                        "input_tokens_estimate": _token_estimate(task["input"]),
                        "output_tokens_estimate": _token_estimate(output),
                        "cost_usd_estimate": "0.000000",
                    },
                    "git": git,
                    "started_at": started_at,
                    "finished_at": finished_at,
                }
            )
    return traces
