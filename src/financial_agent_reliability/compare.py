"""Read-only, deterministic aggregation for lightweight benchmark traces."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any


def _mean_interval(values: list[float]) -> dict[str, Any]:
    mean = statistics.fmean(values)
    if len(values) < 2:
        return {"mean": round(mean, 3), "lower": None, "upper": None, "confidence": 0.95}
    critical = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        21: 2.080,
        22: 2.074,
        23: 2.069,
        24: 2.064,
        25: 2.060,
        26: 2.056,
        27: 2.052,
        28: 2.048,
        29: 2.045,
        30: 2.042,
    }.get(len(values) - 1, 1.96)
    margin = critical * statistics.stdev(values) / math.sqrt(len(values))
    return {
        "mean": round(mean, 3),
        "lower": round(mean - margin, 3),
        "upper": round(mean + margin, 3),
        "confidence": 0.95,
    }


def _wilson_interval(values: list[float]) -> dict[str, Any]:
    count = len(values)
    successes = sum(values)
    proportion = successes / count
    z = 1.96
    denominator = 1 + z * z / count
    center = (proportion + z * z / (2 * count)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / count + z * z / (4 * count * count))
        / denominator
    )
    return {
        "mean": round(proportion, 3),
        "lower": round(max(0.0, center - margin), 3),
        "upper": round(min(1.0, center + margin), 3),
        "confidence": 0.95,
        "method": "wilson",
    }


def _paired_contrasts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contrasts: list[dict[str, Any]] = []
    for axis, other_axis in (("agent", "model"), ("model", "agent")):
        values = sorted({row["candidate"][axis] for row in rows})
        for first_index, first in enumerate(values):
            for second in values[first_index + 1 :]:
                paired: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
                for row in rows:
                    if row["candidate"][axis] not in {first, second}:
                        continue
                    key = (row["run_id"], row["task"]["id"], row["candidate"][other_axis])
                    paired[key][row["candidate"][axis]] = row
                complete = [pair for pair in paired.values() if first in pair and second in pair]
                deltas: dict[str, list[float]] = {
                    "correctness": [],
                    "evidence_quality": [],
                    "safety": [],
                    "quality_score": [],
                    "tool_calls": [],
                }
                for pair in complete:
                    left, right = pair[first], pair[second]
                    for metric in ("correctness", "evidence_quality", "safety"):
                        deltas[metric].append(float(right["score"][metric] - left["score"][metric]))
                    left_quality = left["score"]["correctness"] + left["score"]["evidence_quality"]
                    right_quality = (
                        right["score"]["correctness"] + right["score"]["evidence_quality"]
                    )
                    deltas["quality_score"].append(float(right_quality - left_quality))
                    deltas["tool_calls"].append(
                        float(len(right["tool_calls"]) - len(left["tool_calls"]))
                    )
                observed_variation = any(
                    any(delta != 0 for delta in metric_deltas) for metric_deltas in deltas.values()
                )
                contrasts.append(
                    {
                        "axis": axis,
                        "contrast": f"{second} - {first}",
                        "paired_cells": len(complete),
                        "status": "identifiable"
                        if complete and observed_variation
                        else "non_identifiable",
                        "status_reason": (
                            "paired execution produced observable intervention effects"
                            if complete and observed_variation
                            else "no observable execution or outcome variation on the paired cells"
                            if complete
                            else "no complete paired cells"
                        ),
                        "delta_intervals_95": {
                            metric: _mean_interval(metric_deltas) if metric_deltas else None
                            for metric, metric_deltas in deltas.items()
                        },
                    }
                )
    return contrasts


def _summary(rows: list[dict[str, Any]], *, include_contrasts: bool = False) -> dict[str, Any]:
    eligible = [row for row in rows if row["score"]["eligible_for_quality_aggregation"]]
    signatures = Counter(
        row["failure_signature"]["code"] for row in rows if row.get("failure_signature") is not None
    )
    quality_total = sum(
        row["score"]["correctness"] + row["score"]["evidence_quality"] for row in eligible
    )
    summary = {
        "runs": len(rows),
        "errors": sum(row["error"] is not None for row in rows),
        "hard_gate_failures": sum(not row["score"]["hard_gate_passed"] for row in rows),
        "scores": {
            "average_correctness": round(
                sum(row["score"]["correctness"] for row in rows) / len(rows), 3
            ),
            "average_evidence_quality": round(
                sum(row["score"]["evidence_quality"] for row in rows) / len(rows), 3
            ),
            "safety_pass_rate": round(sum(row["score"]["safety"] for row in rows) / len(rows), 3),
            "eligible_quality_runs": len(eligible),
            "average_quality_score": round(quality_total / len(eligible), 3) if eligible else None,
        },
        "operational_metrics": {
            "average_latency_ms": round(
                sum(row["metrics"]["latency_ms"] for row in rows) / len(rows), 3
            ),
            "input_tokens_estimate": sum(row["metrics"]["input_tokens_estimate"] for row in rows),
            "output_tokens_estimate": sum(row["metrics"]["output_tokens_estimate"] for row in rows),
            "cost_usd_estimate": (
                f"{sum(Decimal(row['metrics']['cost_usd_estimate']) for row in rows):.6f}"
            ),
            "cost_bases": sorted({row["metrics"].get("cost_basis", "unspecified") for row in rows}),
        },
        "failure_signatures": [
            {"code": code, "count": signatures[code]} for code in sorted(signatures)
        ],
        "uncertainty_95": {
            "average_correctness": _mean_interval(
                [float(row["score"]["correctness"]) for row in rows]
            ),
            "average_evidence_quality": _mean_interval(
                [float(row["score"]["evidence_quality"]) for row in rows]
            ),
            "safety_pass_rate": _wilson_interval([float(row["score"]["safety"]) for row in rows]),
            "effective_sample_size": len(rows),
        },
    }
    if include_contrasts:
        summary["paired_contrasts"] = _paired_contrasts(rows)
    return summary


def _grouped(
    traces: list[dict[str, Any]], key: Any, label: str, *, include_contrasts: bool = False
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        buckets[str(key(trace))].append(trace)
    return [
        {label: value, **_summary(buckets[value], include_contrasts=include_contrasts)}
        for value in sorted(buckets)
    ]


def compare_traces(traces: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(traces)
    if not rows:
        raise ValueError("compare requires at least one trace")
    candidates = _grouped(rows, lambda row: row["candidate"]["id"], "candidate_id")
    return {
        "schema_version": "0.3.0",
        "matrix": {
            "models": sorted({row["candidate"]["model"] for row in rows}),
            "agents": sorted({row["candidate"]["agent"] for row in rows}),
            "candidates": sorted({row["candidate"]["id"] for row in rows}),
            "tasks": sorted({row["task"]["id"] for row in rows}),
        },
        "overall": _summary(rows, include_contrasts=True),
        "by_candidate": candidates,
        "by_model": _grouped(rows, lambda row: row["candidate"]["model"], "model"),
        "by_agent": _grouped(rows, lambda row: row["candidate"]["agent"], "agent"),
        "by_slice": _grouped(
            rows, lambda row: row["task"]["slice"], "slice", include_contrasts=True
        ),
        "by_variant": _grouped(
            rows, lambda row: row["task"]["variant"], "variant", include_contrasts=True
        ),
    }
