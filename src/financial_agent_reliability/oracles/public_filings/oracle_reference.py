"""Independent recomputation for baseline-v2 public-filing Gold cases.

Second implementation required by the Gold promotion gate (two independent
implementations must agree). Written deliberately differently from
``oracle.py``: fractions-based arithmetic, explicit scans instead of dict
lookups, and its own control flow. Agreement between the two implementations
is asserted by the baseline-v2 test suite, never assumed.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
from typing import Any, Mapping


def _outcome(status: str, value: Any, reasons: list[str] | None = None) -> dict[str, Any]:
    return {"status": status, "value": value, "reason_codes": reasons or []}


def _scan_period(rows: list[Mapping[str, Any]], wanted: str) -> Mapping[str, Any] | None:
    found = None
    for row in rows:
        payload = row.get("payload", {})
        if str(payload.get("period_end")) == wanted:
            if found is not None:
                return None  # ambiguous period registration cannot be scored
            found = row
    return found


def recompute(
    snapshot: Mapping[str, Any] | None, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    if inputs.get("diagnostic_reason"):
        return _outcome("abstain", None, [str(inputs["diagnostic_reason"])])
    rows = [] if snapshot is None else list(snapshot.get("records", []))
    if not rows:
        return _outcome("abstain", None, ["INSUFFICIENT_EVIDENCE"])

    operation = str(inputs.get("operation", ""))
    if operation == "yoy_growth_rate":
        base_row = _scan_period(rows, str(inputs.get("base_period_end")))
        target_row = _scan_period(rows, str(inputs.get("target_period_end")))
        if base_row is None or target_row is None:
            return _outcome("abstain", None, ["INSUFFICIENT_EVIDENCE"])
        precision = int(inputs.get("precision", -1))
        if precision < 0 or precision > 12:
            return _outcome("abstain", None, ["UNREGISTERED_PRECISION"])
        base = Fraction(str(base_row["payload"]["value"]))
        target = Fraction(str(target_row["payload"]["value"]))
        if base == 0:
            return _outcome("abstain", None, ["UNDEFINED_BASE_VALUE"])
        ratio = (target - base) / base * 100
        quantized = Decimal(ratio.numerator) / Decimal(ratio.denominator)
        rendered = str(
            quantized.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN)
        )
        return _outcome(
            "answer",
            {
                "base_period_end": str(inputs.get("base_period_end")),
                "target_period_end": str(inputs.get("target_period_end")),
                "growth_percent": rendered,
            },
        )
    if operation == "select_latest_available":
        cutoff = str(inputs.get("available_at_cutoff"))
        best: Mapping[str, Any] | None = None
        best_key = ("", "")
        for row in rows:
            available = str(row.get("available_at"))
            if available > cutoff:
                continue
            key = (str(row["payload"]["period_end"]), available)
            if key > best_key:
                best, best_key = row, key
        if best is None:
            return _outcome("abstain", None, ["INSUFFICIENT_EVIDENCE"])
        return _outcome(
            "answer",
            {
                "period_end": str(best["payload"]["period_end"]),
                "value": str(best["payload"]["value"]),
            },
        )
    return _outcome("abstain", None, ["METHOD_NOT_REGISTERED"])
