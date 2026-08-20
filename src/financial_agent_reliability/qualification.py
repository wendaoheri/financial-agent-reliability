"""Framework qualification through the same production runner and grader path."""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter
from types import SimpleNamespace
from typing import Any

from financial_agent_reliability.contracts import validate_candidate_output
from financial_agent_reliability.grading import grade_components
from financial_agent_reliability.models import Candidate
from financial_agent_reliability.runner import (
    _failure_signature,
    classify_outcome,
    run_matrix,
)
from financial_agent_reliability.security import scan_persisted_value_for_secrets
from financial_agent_reliability.trace import append_traces, read_traces


class QualificationError(ValueError):
    """Raised when qualification evidence differs from its preregistered matrix."""


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_map(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {task["task_id"]: task for task in tasks}


def _candidate_map(candidates: list[Candidate]) -> dict[str, Candidate]:
    return {candidate.id: candidate for candidate in candidates}


def derive_evidence(
    tasks: list[dict[str, Any]], candidates: list[Candidate], traces: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Regrade persisted trace inputs and derive matrix, aggregate, and signatures."""

    task_by_id = _task_map(tasks)
    candidate_by_id = _candidate_map(candidates)
    matrix: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    outcomes: Counter[str] = Counter()
    for trace in traces:
        task = task_by_id[trace["task"]["id"]]
        candidate = candidate_by_id[trace["candidate"]["id"]]
        protocol_errors = validate_candidate_output(
            task["candidate_payload"]["output_contract"], trace["output"]
        )
        effective_error = trace["error"]
        if effective_error is None and protocol_errors:
            effective_error = {
                "code": "INVALID_MODEL_OUTPUT",
                "message": protocol_errors[0],
                "retryable": False,
            }
        if effective_error != trace["error"]:
            raise QualificationError(f"persisted protocol classification drift for {candidate.id}")
        result = SimpleNamespace(output=trace["output"], error=effective_error)
        score, evidence_refs, violations, components = grade_components(
            task, result, trace["tool_calls"]
        )
        outcome = classify_outcome(result, score)
        expectation = candidate.config.get("qualification")
        if not isinstance(expectation, dict):
            raise QualificationError(f"candidate {candidate.id} lacks qualification expectation")
        expected = {
            "outcome": expectation.get("expected_outcome"),
            "score": expectation.get("expected_score"),
            "components": expectation.get("expected_components"),
        }
        actual = {"outcome": outcome, "score": score, "components": components}
        matched = actual == expected
        matrix.append(
            {
                "case_id": candidate.id,
                "task_id": task["task_id"],
                "mutation": expectation.get("mutation"),
                "expected": expected,
                "actual": actual,
                "matched": matched,
            }
        )
        outcomes[outcome] += 1
        signature = _failure_signature(
            result,
            score,
            evidence_refs,
            run_id=trace["run_id"],
            task_id=task["task_id"],
            candidate_id=candidate.id,
            outcome=outcome,
        )
        if signature is not None:
            failures.append(signature)
        if score != trace["score"] or violations != trace["safety_violations"]:
            raise QualificationError(f"persisted score drift for {candidate.id}")
        if signature != trace["failure_signature"]:
            raise QualificationError(f"persisted failure-signature drift for {candidate.id}")

    denominator = outcomes["candidate_success"] + outcomes["candidate_failure"]
    aggregate = {
        "classification_accuracy": (
            sum(row["matched"] for row in matrix) / len(matrix) if matrix else 0.0
        ),
        "outcome_counts": {
            name: outcomes[name]
            for name in ("candidate_success", "candidate_failure", "invalid_run")
        },
        "csr": outcomes["candidate_success"] / denominator if denominator else None,
        "csr_denominator": denominator,
        "invalid_runs_excluded": outcomes["invalid_run"],
        "model_failure_signature_count": len(failures),
    }
    return matrix, aggregate, failures


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(_render(value), encoding="utf-8")


def run_qualification(
    tasks: list[dict[str, Any]],
    candidates: list[Candidate],
    *,
    repository_root: pathlib.Path,
    output_directory: pathlib.Path,
    run_id: str,
    versions: dict[str, Any],
) -> dict[str, Any]:
    """Execute and persist the preregistered mutation matrix as a closed bundle."""

    if len(tasks) != 1:
        raise QualificationError("qualification requires exactly one filtered task")
    output_directory.mkdir(parents=True, exist_ok=False)
    traces = run_matrix(
        tasks,
        candidates,
        repository_root=repository_root,
        run_id=run_id,
        versions=versions,
    )
    trace_path = output_directory / "traces.jsonl"
    append_traces(trace_path, traces)
    matrix, aggregate, failures = derive_evidence(tasks, candidates, traces)
    _write_json(output_directory / "calibration_matrix.json", matrix)
    _write_json(output_directory / "aggregate.json", aggregate)
    _write_json(output_directory / "failure_signatures.json", failures)
    secret_findings = scan_persisted_value_for_secrets(
        {"traces": traces, "matrix": matrix, "aggregate": aggregate, "failures": failures}
    )
    _write_json(
        output_directory / "secret_scan.json",
        {"status": "passed" if not secret_findings else "failed", "findings": secret_findings},
    )
    artifacts = []
    for name in (
        "traces.jsonl",
        "calibration_matrix.json",
        "aggregate.json",
        "failure_signatures.json",
        "secret_scan.json",
    ):
        path = output_directory / name
        artifacts.append({"path": name, "sha256": _sha256(path), "bytes": path.stat().st_size})
    passed = aggregate["classification_accuracy"] == 1.0 and not secret_findings
    manifest = {
        "contract_type": "framework_qualification_bundle",
        "contract_version": "1.0.0",
        "status": "passed" if passed else "failed",
        "run_id": run_id,
        "eval_pack_id": versions["eval_pack_id"],
        "runner_protocol_version": versions["runner_protocol_version"],
        "artifacts": artifacts,
    }
    _write_json(output_directory / "manifest.json", manifest)
    if not passed:
        raise QualificationError("qualification matrix or secret scan failed")
    return manifest


def replay_qualification(
    tasks: list[dict[str, Any]], candidates: list[Candidate], bundle: pathlib.Path
) -> dict[str, Any]:
    """Verify hashes, then deterministically regrade and compare every derived artifact."""

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    registered = {item["path"]: item["sha256"] for item in manifest.get("artifacts", [])}
    actual_files = {path.name for path in bundle.iterdir() if path.is_file()} - {"manifest.json"}
    if actual_files != set(registered):
        raise QualificationError("bundle contains missing or unregistered artifacts")
    for name, expected_hash in registered.items():
        if _sha256(bundle / name) != expected_hash:
            raise QualificationError(f"bundle hash mismatch: {name}")
    traces = list(read_traces([bundle / "traces.jsonl"]))
    coordinates = {
        (trace["versions"].get("eval_pack_id"), trace["versions"].get("runner_protocol_version"))
        for trace in traces
    }
    expected_coordinates = {(manifest.get("eval_pack_id"), manifest.get("runner_protocol_version"))}
    if coordinates != expected_coordinates:
        raise QualificationError("trace Eval Pack or runner protocol differs from manifest")
    matrix, aggregate, failures = derive_evidence(tasks, candidates, traces)
    expected = {
        "calibration_matrix.json": matrix,
        "aggregate.json": aggregate,
        "failure_signatures.json": failures,
    }
    for name, value in expected.items():
        persisted = json.loads((bundle / name).read_text(encoding="utf-8"))
        if persisted != value:
            raise QualificationError(f"deterministic replay mismatch: {name}")
    return {
        "status": "passed",
        "traces_regraded": len(traces),
        "artifacts_verified": len(registered),
        "eval_pack_id": manifest["eval_pack_id"],
        "runner_protocol_version": manifest["runner_protocol_version"],
        "outcome_counts": aggregate["outcome_counts"],
    }
