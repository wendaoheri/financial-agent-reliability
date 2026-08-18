"""Read-only aggregation for lightweight benchmark traces."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def compare_traces(traces: Iterable[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        buckets[trace["candidate"]["id"]].append(trace)
    candidates: list[dict[str, Any]] = []
    for candidate_id in sorted(buckets):
        rows = buckets[candidate_id]
        first = rows[0]["candidate"]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "model": first["model"],
                "agent": first["agent"],
                "traces": len(rows),
                "errors": sum(row["error"] is not None for row in rows),
                "average_latency_ms": round(
                    sum(row["metrics"]["latency_ms"] for row in rows) / len(rows), 3
                ),
                "input_tokens_estimate": sum(
                    row["metrics"]["input_tokens_estimate"] for row in rows
                ),
                "output_tokens_estimate": sum(
                    row["metrics"]["output_tokens_estimate"] for row in rows
                ),
                "cost_usd_estimate": f"{sum(float(row['metrics']['cost_usd_estimate']) for row in rows):.6f}",
            }
        )
    return {"schema_version": "0.1.0", "candidates": candidates}
