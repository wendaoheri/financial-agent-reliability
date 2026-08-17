"""Deterministic production oracle for baseline-v2 public-filing cases.

The oracle reads only canonical XBRL fact records frozen into a
``data_snapshot`` object. It performs no network, account, order, or
candidate-output I/O.

Registered operations
---------------------
``yoy_growth_rate``
    Inputs: ``base_period_end``, ``target_period_end`` (ISO dates present in
    ``records[].payload.period_end``), ``precision`` (decimal places, 0-12).
    Value: ``(target - base) / base * 100`` rendered as a decimal string
    quantized to ``precision`` places with ROUND_HALF_EVEN.

``select_latest_available``
    Inputs: ``available_at_cutoff`` (RFC 3339 UTC timestamp). Selects the
    record with the greatest ``payload.period_end`` among records whose
    ``available_at`` is lexicographically not greater than the cutoff
    (records use a uniform RFC 3339 UTC format, so lexicographic order is
    chronological). Ties break on the greatest ``available_at``.
    Value: the selected record's ``payload.value`` as a decimal string.

Any missing period record, empty snapshot, or unregistered operation
abstains instead of guessing; abstention reasons are stable reason codes.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping


def _result(status: str, value: Any, *reasons: str) -> dict[str, Any]:
    return {"status": status, "value": value, "reason_codes": list(reasons)}


def _records(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(snapshot.get("records", []))


def _record_for_end(
    records: list[Mapping[str, Any]], period_end: str
) -> Mapping[str, Any] | None:
    for record in records:
        if str(record["payload"]["period_end"]) == period_end:
            return record
    return None


def evaluate(
    snapshot: Mapping[str, Any] | None, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the registered outcome for one public-filing case."""

    diagnostic_reason = inputs.get("diagnostic_reason")
    if diagnostic_reason:
        return _result("abstain", None, str(diagnostic_reason))
    if snapshot is None or not _records(snapshot):
        return _result("abstain", None, "INSUFFICIENT_EVIDENCE")

    records = _records(snapshot)
    operation = str(inputs["operation"])
    if operation == "yoy_growth_rate":
        base_record = _record_for_end(records, str(inputs["base_period_end"]))
        target_record = _record_for_end(records, str(inputs["target_period_end"]))
        if base_record is None or target_record is None:
            return _result("abstain", None, "INSUFFICIENT_EVIDENCE")
        base_value = Decimal(str(base_record["payload"]["value"]))
        target_value = Decimal(str(target_record["payload"]["value"]))
        if base_value == 0:
            return _result("abstain", None, "UNDEFINED_BASE_VALUE")
        precision = int(inputs["precision"])
        if not 0 <= precision <= 12:
            return _result("abstain", None, "UNREGISTERED_PRECISION")
        growth = (target_value - base_value) / base_value * Decimal(100)
        rendered = str(
            growth.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN)
        )
        return _result(
            "answer",
            {
                "base_period_end": str(inputs["base_period_end"]),
                "target_period_end": str(inputs["target_period_end"]),
                "growth_percent": rendered,
            },
        )
    if operation == "select_latest_available":
        cutoff = str(inputs["available_at_cutoff"])
        eligible = [
            record
            for record in records
            if str(record["available_at"]) <= cutoff
        ]
        if not eligible:
            return _result("abstain", None, "INSUFFICIENT_EVIDENCE")
        selected = max(
            eligible,
            key=lambda record: (
                str(record["payload"]["period_end"]),
                str(record["available_at"]),
            ),
        )
        return _result(
            "answer",
            {
                "period_end": str(selected["payload"]["period_end"]),
                "value": str(selected["payload"]["value"]),
            },
        )
    return _result("abstain", None, "METHOD_NOT_REGISTERED")
