"""Deterministic production oracle for PER-28 public-source cases.

The oracle consumes only canonical snapshot records and registered task inputs.
It never reads an upstream benchmark answer or candidate-model output.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping


SCALE = Decimal("0.000001")


def _canonical_decimal(value: Decimal) -> str:
    rendered = format(value.quantize(SCALE, rounding=ROUND_HALF_EVEN), "f")
    rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _values(snapshot: Mapping[str, Any]) -> dict[tuple[str, str], Decimal]:
    values: dict[tuple[str, str], Decimal] = {}
    for record in snapshot["records"]:
        payload = record["payload"]
        values[(payload["country_code"], payload["year"])] = Decimal(payload["value"])
    return values


def _answer(value: Any) -> dict[str, Any]:
    return {"status": "answer", "value": value, "reason_codes": []}


def _abstain(reason: str) -> dict[str, Any]:
    return {"status": "abstain", "value": None, "reason_codes": [reason]}


def evaluate(snapshot: Mapping[str, Any] | None, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a registered case deterministically."""

    if inputs.get("force_abstain_reason"):
        return _abstain(str(inputs["force_abstain_reason"]))
    if snapshot is None or not snapshot.get("records"):
        return _abstain("INSUFFICIENT_EVIDENCE")

    values = _values(snapshot)
    countries = sorted({country for country, _ in values})
    operation = inputs["operation"]

    if operation == "direct":
        value = values[(countries[0], str(inputs["target_year"]))]
        return _answer({"value": _canonical_decimal(value), "year": str(inputs["target_year"])})

    if operation == "average":
        years = [str(year) for year in inputs["years"]]
        result = sum(values[(countries[0], year)] for year in years) / Decimal(len(years))
        return _answer({"average": _canonical_decimal(result), "years": years})

    if operation == "scale":
        raw = values[(countries[0], str(inputs["target_year"]))]
        divisor = Decimal(str(inputs["divisor"]))
        return _answer({"scaled_value": _canonical_decimal(raw / divisor), "divisor": str(inputs["divisor"])})

    if operation == "basis":
        current = values[(countries[0], str(inputs["target_year"]))]
        basis = str(inputs["accounting_basis"])
        if basis == "reported_value":
            result = current
        elif basis == "prior_year_index_100":
            prior = values[(countries[0], str(inputs["base_year"]))]
            result = current / prior * Decimal(100)
        else:
            return _abstain("METHOD_NOT_REGISTERED")
        return _answer({"basis": basis, "value": _canonical_decimal(result)})

    if operation == "growth":
        start = values[(countries[0], str(inputs["start_year"]))]
        end = values[(countries[0], str(inputs["end_year"]))]
        result = (end - start) / abs(start) * Decimal(100)
        return _answer({"growth_pct": _canonical_decimal(result), "start_year": str(inputs["start_year"]), "end_year": str(inputs["end_year"])})

    if operation == "sum_countries":
        year = str(inputs["target_year"])
        selected = [str(country) for country in inputs["included_countries"]]
        result = sum(values[(country, year)] for country in selected)
        return _answer({"sum": _canonical_decimal(result), "countries": selected, "year": year})

    if operation == "method":
        method = str(inputs["method"])
        years = sorted(year for country, year in values if country == countries[0])
        if method == "latest_value":
            result = values[(countries[0], years[-1])]
        elif method == "three_year_average":
            result = sum(values[(countries[0], year)] for year in years[-3:]) / Decimal(3)
        else:
            return _abstain("METHOD_NOT_REGISTERED")
        return _answer({"method": method, "value": _canonical_decimal(result)})

    if operation == "regime":
        years = sorted(year for country, year in values if country == countries[0])
        start = values[(countries[0], years[-2])]
        end = values[(countries[0], years[-1])]
        change = (end - start) / abs(start) * Decimal(100)
        multiplier = Decimal(str(inputs["regime_multiplier"]))
        return _answer({"regime": str(inputs["event_regime"]), "adjusted_change_pct": _canonical_decimal(change * multiplier)})

    if operation == "language_invariant":
        value = values[(countries[0], str(inputs["target_year"]))]
        return _answer({"value": _canonical_decimal(value), "language": str(inputs["language"])})

    if operation == "modality_invariant":
        value = values[(countries[0], str(inputs["target_year"]))]
        return _answer({"value": _canonical_decimal(value), "modality": str(inputs["modality"])})

    if operation == "threshold":
        value = values[(countries[0], str(inputs["target_year"]))]
        threshold = Decimal(str(inputs["threshold"]))
        return _answer({"meets_threshold": value >= threshold, "value": _canonical_decimal(value), "threshold": _canonical_decimal(threshold)})

    return _abstain("METHOD_NOT_REGISTERED")
