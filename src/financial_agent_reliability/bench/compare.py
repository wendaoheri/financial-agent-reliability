"""Read-only, deterministic aggregation for lightweight benchmark traces."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Iterable


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row["score"]["eligible_for_quality_aggregation"]]
    signatures = Counter(
        row["failure_signature"]["code"]
        for row in rows
        if row.get("failure_signature") is not None
    )
    quality_total = sum(
        row["score"]["correctness"] + row["score"]["evidence_quality"] for row in eligible
    )
    return {
        "runs": len(rows),
        "errors": sum(row["error"] is not None for row in rows),
        "hard_gate_failures": sum(not row["score"]["hard_gate_passed"] for row in rows),
        "scores": {
            "average_correctness": round(sum(row["score"]["correctness"] for row in rows) / len(rows), 3),
            "average_evidence_quality": round(sum(row["score"]["evidence_quality"] for row in rows) / len(rows), 3),
            "safety_pass_rate": round(sum(row["score"]["safety"] for row in rows) / len(rows), 3),
            "eligible_quality_runs": len(eligible),
            "average_quality_score": round(quality_total / len(eligible), 3) if eligible else None,
        },
        "operational_metrics": {
            "average_latency_ms": round(sum(row["metrics"]["latency_ms"] for row in rows) / len(rows), 3),
            "input_tokens_estimate": sum(row["metrics"]["input_tokens_estimate"] for row in rows),
            "output_tokens_estimate": sum(row["metrics"]["output_tokens_estimate"] for row in rows),
            "cost_usd_estimate": f"{sum(Decimal(row['metrics']['cost_usd_estimate']) for row in rows):.6f}",
        },
        "failure_signatures": [
            {"code": code, "count": signatures[code]} for code in sorted(signatures)
        ],
    }


def _grouped(
    traces: list[dict[str, Any]], key: Any, label: str
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        buckets[str(key(trace))].append(trace)
    return [{label: value, **_summary(buckets[value])} for value in sorted(buckets)]


def compare_traces(traces: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(traces)
    if not rows:
        raise ValueError("compare requires at least one trace")
    candidates = _grouped(rows, lambda row: row["candidate"]["id"], "candidate_id")
    legacy_candidates = [{**candidate, "traces": candidate["runs"]} for candidate in candidates]
    return {
        "schema_version": "0.2.0",
        "matrix": {
            "models": sorted({row["candidate"]["model"] for row in rows}),
            "agents": sorted({row["candidate"]["agent"] for row in rows}),
            "candidates": sorted({row["candidate"]["id"] for row in rows}),
            "tasks": sorted({row["task"]["id"] for row in rows}),
        },
        "overall": _summary(rows),
        "by_candidate": candidates,
        "by_model": _grouped(rows, lambda row: row["candidate"]["model"], "model"),
        "by_agent": _grouped(rows, lambda row: row["candidate"]["agent"], "agent"),
        "by_slice": _grouped(rows, lambda row: row["task"]["slice"], "slice"),
        "by_variant": _grouped(rows, lambda row: row["task"]["variant"], "variant"),
        "candidates": legacy_candidates,
    }
