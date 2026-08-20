"""Durable, exactly-once orchestration for long-horizon harness qualification."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import uuid
from datetime import UTC, datetime
from typing import Any

from financial_agent_reliability.adapters.core import (
    CandidateAdapter,
    CandidateRequest,
    OfflineMockTools,
    get_adapter,
)
from financial_agent_reliability.models import Candidate
from financial_agent_reliability.security import scan_persisted_value_for_secrets

SOAK_SCHEMA_VERSION = "0.1.0"
_COMPLETE = {"completed", "recovered"}
_TERMINAL = _COMPLETE | {"incomplete", "cancelled"}


class SoakHardStop(ValueError):
    """Raised when continuing could manufacture a model difference or unsafe side effect."""


class InjectedCrash(RuntimeError):
    """Test-only process interruption after a durable step commit."""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    findings = scan_persisted_value_for_secrets(value)
    if findings:
        raise SoakHardStop("persisted soak state rejected by secret gate: " + ", ".join(findings))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("wb") as handle:
        handle.write(_canonical(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atomic_jsonl(path: pathlib.Path, values: list[dict[str, Any]]) -> None:
    for value in values:
        findings = scan_persisted_value_for_secrets(value)
        if findings:
            raise SoakHardStop(
                "persisted soak trace rejected by secret gate: " + ", ".join(findings)
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("wb") as handle:
        for value in values:
            handle.write(_canonical(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_object(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SoakHardStop(f"soak state is not an object: {path.name}")
    return value


def _fingerprint(
    task: dict[str, Any], candidate: Candidate, versions: dict[str, Any], steps: int
) -> str:
    return _digest(
        {
            "schema_version": SOAK_SCHEMA_VERSION,
            "task_id": task["task_id"],
            "candidate_id": candidate.id,
            "candidate_model": candidate.model,
            "candidate_config_sha256": candidate.config_sha256,
            "versions": versions,
            "target_steps": steps,
        }
    )


def _load_steps(directory: pathlib.Path, fingerprint: str) -> dict[int, dict[str, Any]]:
    completed: dict[int, dict[str, Any]] = {}
    if not directory.exists():
        return completed
    for path in sorted(directory.glob("step-*.json")):
        event = _read_object(path)
        if event.get("schema_version") != SOAK_SCHEMA_VERSION:
            raise SoakHardStop(f"unsupported soak step schema: {path.name}")
        if event.get("fingerprint") != fingerprint:
            raise SoakHardStop(f"soak step fingerprint drift: {path.name}")
        index = event.get("step_index")
        if not isinstance(index, int) or index < 1 or index in completed:
            raise SoakHardStop(f"invalid or duplicate soak step: {path.name}")
        completed[index] = event
    return completed


def _provider_turns(events: tuple[dict[str, Any], ...]) -> int:
    return sum(event.get("type") == "message_end" and "stop_reason" in event for event in events)


def _checkpoint(
    *,
    experiment_id: str,
    attempt_id: str,
    fingerprint: str,
    status: str,
    target_steps: int,
    events: dict[int, dict[str, Any]],
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": SOAK_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "attempt_id": attempt_id,
        "fingerprint": fingerprint,
        "status": status,
        "target_steps": target_steps,
        "completed_step_ids": [events[index]["step_id"] for index in sorted(events)],
        "provider_turns": sum(int(event["provider_turns"]) for event in events.values()),
        "tool_calls": sum(int(event["tool_call_count"]) for event in events.values()),
        "started_at": started_at,
        "updated_at": _timestamp(),
    }


def _summary(
    *,
    checkpoint: dict[str, Any],
    task: dict[str, Any],
    candidate: Candidate,
    events: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    status = str(checkpoint["status"])
    return {
        **checkpoint,
        "task_id": task["task_id"],
        "candidate": {
            "id": candidate.id,
            "model": candidate.model,
            "agent": candidate.agent,
            "adapter": candidate.adapter,
            "config_sha256": candidate.config_sha256,
        },
        "completed_steps": len(events),
        "eligible_for_completed_aggregation": status in _COMPLETE,
        "input_tokens": sum(int(event["metrics"]["input_tokens"]) for event in events.values()),
        "output_tokens": sum(int(event["metrics"]["output_tokens"]) for event in events.values()),
        "latency_ms": sum(int(event["metrics"]["latency_ms"]) for event in events.values()),
        "terminal_error": next(
            (
                event["error"]
                for _, event in sorted(events.items(), reverse=True)
                if event.get("error") is not None
            ),
            None,
        ),
    }


def run_long_horizon(
    task: dict[str, Any],
    candidate: Candidate,
    *,
    repository_root: pathlib.Path,
    output_directory: pathlib.Path,
    experiment_id: str,
    versions: dict[str, Any],
    steps: int = 50,
    cancel_file: pathlib.Path | None = None,
    adapter: CandidateAdapter | None = None,
    crash_after_step: int | None = None,
) -> dict[str, Any]:
    """Run or resume a durable workflow; a committed step is never executed twice."""

    if steps < 1 or steps > 500:
        raise ValueError("soak steps must be between 1 and 500")
    fingerprint = _fingerprint(task, candidate, versions, steps)
    candidate_directory = output_directory / candidate.id
    checkpoint_path = candidate_directory / "checkpoint.json"
    step_directory = candidate_directory / "steps"
    existing_checkpoint = _read_object(checkpoint_path) if checkpoint_path.exists() else None
    if existing_checkpoint is not None and existing_checkpoint.get("fingerprint") != fingerprint:
        raise SoakHardStop("checkpoint fingerprint drift; refusing cross-experiment resume")
    events = _load_steps(step_directory, fingerprint)
    if any(index > steps for index in events):
        raise SoakHardStop("persisted soak step exceeds the configured target")
    resumed = bool(events)
    if existing_checkpoint is not None and existing_checkpoint.get("status") in _TERMINAL:
        _atomic_jsonl(
            candidate_directory / "steps.jsonl", [events[index] for index in sorted(events)]
        )
        return _summary(
            checkpoint=existing_checkpoint, task=task, candidate=candidate, events=events
        )

    attempt_number = 1
    if existing_checkpoint is not None:
        prior = str(existing_checkpoint.get("attempt_id", "attempt-0"))
        try:
            attempt_number = int(prior.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            attempt_number = 2
    attempt_id = f"attempt-{attempt_number}"
    started_at = str((existing_checkpoint or {}).get("started_at") or _timestamp())
    selected_adapter = adapter or get_adapter(candidate.adapter, repository_root=repository_root)
    request = CandidateRequest.from_payload(task["candidate_payload"])
    status = "running"

    for index in range(1, steps + 1):
        if index in events:
            continue
        if cancel_file is not None and cancel_file.exists():
            status = "cancelled"
            break
        step_id = f"step-{index:04d}"
        idempotency_key = _digest(
            {"experiment_id": experiment_id, "candidate_id": candidate.id, "step_id": step_id}
        )
        tools = OfflineMockTools(request)
        try:
            result = selected_adapter.execute(request, candidate, tools)
        except Exception as exc:  # adapter exceptions are terminal evidence, never retried
            result_error = {
                "code": "ADAPTER_EXCEPTION",
                "message": type(exc).__name__,
                "retryable": False,
            }
            result = None
        else:
            result_error = result.error

        calls = tools.calls
        if result is not None and candidate.adapter == "pi-agent-live":
            identity = result.provider_identity or {}
            if (
                identity.get("requested_model") != candidate.model
                or identity.get("response_model") != candidate.model
                or identity.get("exact_match") is not True
            ):
                raise SoakHardStop(
                    f"model identity mismatch at {candidate.id}/{step_id}; stopping real soak"
                )
        if result is not None and result_error is None:
            if (
                len(calls) != 1
                or calls[0].get("action") != "read"
                or calls[0].get("status") != "ok"
            ):
                raise SoakHardStop(
                    f"read-only exactly-once tool contract failed at {candidate.id}/{step_id}"
                )

        event = {
            "schema_version": SOAK_SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "attempt_id": attempt_id,
            "fingerprint": fingerprint,
            "step_id": step_id,
            "step_index": index,
            "idempotency_key": idempotency_key,
            "task_id": task["task_id"],
            "candidate_id": candidate.id,
            "requested_model": candidate.model,
            "provider_identity": result.provider_identity if result is not None else None,
            "provider_observability": (
                result.provider_observability if result is not None else None
            ),
            "provider_turns": _provider_turns(result.agent_events) if result is not None else 0,
            "tool_call_count": len(calls),
            "tool_calls": calls,
            "output": result.output if result is not None else None,
            "error": result_error,
            "metrics": {
                "latency_ms": result.latency_ms if result is not None else 0,
                "input_tokens": result.input_tokens if result is not None else 0,
                "output_tokens": result.output_tokens if result is not None else 0,
            },
            "versions": versions,
            "finished_at": _timestamp(),
        }
        _atomic_json(step_directory / f"{step_id}.json", event)
        events[index] = event
        _atomic_jsonl(
            candidate_directory / "steps.jsonl", [events[item] for item in sorted(events)]
        )
        if crash_after_step == index:
            raise InjectedCrash(f"injected crash after durable commit of {step_id}")
        status = "incomplete" if result_error is not None else "running"
        checkpoint = _checkpoint(
            experiment_id=experiment_id,
            attempt_id=attempt_id,
            fingerprint=fingerprint,
            status=status,
            target_steps=steps,
            events=events,
            started_at=started_at,
        )
        _atomic_json(checkpoint_path, checkpoint)
        if result_error is not None:
            break

    if status == "running":
        status = "recovered" if resumed else "completed"
    checkpoint = _checkpoint(
        experiment_id=experiment_id,
        attempt_id=attempt_id,
        fingerprint=fingerprint,
        status=status,
        target_steps=steps,
        events=events,
        started_at=started_at,
    )
    _atomic_json(checkpoint_path, checkpoint)
    summary = _summary(checkpoint=checkpoint, task=task, candidate=candidate, events=events)
    _atomic_json(candidate_directory / "summary.json", summary)
    return summary


def aggregate_soak(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in summaries if row["eligible_for_completed_aggregation"]]
    return {
        "schema_version": SOAK_SCHEMA_VERSION,
        "status": "completed" if len(eligible) == len(summaries) else "incomplete",
        "runs": summaries,
        "completed_aggregation": {
            "runs": len(eligible),
            "provider_turns": sum(int(row["provider_turns"]) for row in eligible),
            "tool_calls": sum(int(row["tool_calls"]) for row in eligible),
            "input_tokens": sum(int(row["input_tokens"]) for row in eligible),
            "output_tokens": sum(int(row["output_tokens"]) for row in eligible),
            "latency_ms": sum(int(row["latency_ms"]) for row in eligible),
        },
        "excluded_terminal_states": [
            {"candidate_id": row["candidate"]["id"], "status": row["status"]}
            for row in summaries
            if not row["eligible_for_completed_aggregation"]
        ],
        "created_at": _timestamp(),
    }
