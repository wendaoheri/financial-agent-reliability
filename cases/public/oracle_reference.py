"""Independent reference implementation for PER-28 Gold-oracle agreement tests."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping


def _text(number: Decimal) -> str:
    result = f"{number.quantize(Decimal('0.000001'), rounding=ROUND_HALF_EVEN):f}"
    return result.rstrip("0").rstrip(".") or "0"


def recompute(snapshot: Mapping[str, Any] | None, inputs: Mapping[str, Any]) -> dict[str, Any]:
    reason = inputs.get("force_abstain_reason")
    if reason is not None:
        return {"status": "abstain", "value": None, "reason_codes": [str(reason)]}
    if snapshot is None or len(snapshot.get("records", [])) == 0:
        return {"status": "abstain", "value": None, "reason_codes": ["INSUFFICIENT_EVIDENCE"]}

    table: dict[str, dict[str, Decimal]] = {}
    for item in snapshot["records"]:
        row = item["payload"]
        table.setdefault(row["country_code"], {})[row["year"]] = Decimal(row["value"])
    country_names = sorted(table)
    op = inputs["operation"]
    output: Any

    if op == "direct":
        year = str(inputs["target_year"])
        output = {"value": _text(table[country_names[0]][year]), "year": year}
    elif op == "average":
        years = list(map(str, inputs["years"]))
        total = Decimal(0)
        for year in years:
            total += table[country_names[0]][year]
        output = {"average": _text(total / len(years)), "years": years}
    elif op == "scale":
        number = table[country_names[0]][str(inputs["target_year"])]
        output = {"scaled_value": _text(number / Decimal(str(inputs["divisor"]))), "divisor": str(inputs["divisor"])}
    elif op == "basis":
        basis = str(inputs["accounting_basis"])
        number = table[country_names[0]][str(inputs["target_year"])]
        if basis == "reported_value":
            output = {"basis": basis, "value": _text(number)}
        elif basis == "prior_year_index_100":
            denominator = table[country_names[0]][str(inputs["base_year"])]
            output = {"basis": basis, "value": _text(Decimal(100) * number / denominator)}
        else:
            return {"status": "abstain", "value": None, "reason_codes": ["METHOD_NOT_REGISTERED"]}
    elif op == "growth":
        first = table[country_names[0]][str(inputs["start_year"])]
        last = table[country_names[0]][str(inputs["end_year"])]
        output = {"growth_pct": _text(Decimal(100) * (last - first) / abs(first)), "start_year": str(inputs["start_year"]), "end_year": str(inputs["end_year"])}
    elif op == "sum_countries":
        year = str(inputs["target_year"])
        chosen = list(map(str, inputs["included_countries"]))
        output = {"sum": _text(sum((table[name][year] for name in chosen), Decimal(0))), "countries": chosen, "year": year}
    elif op == "method":
        method = str(inputs["method"])
        observations = table[country_names[0]]
        years = sorted(observations)
        if method == "latest_value":
            number = observations[years[-1]]
        elif method == "three_year_average":
            number = sum((observations[year] for year in years[-3:]), Decimal(0)) / Decimal(3)
        else:
            return {"status": "abstain", "value": None, "reason_codes": ["METHOD_NOT_REGISTERED"]}
        output = {"method": method, "value": _text(number)}
    elif op == "regime":
        observations = table[country_names[0]]
        years = sorted(observations)
        delta = Decimal(100) * (observations[years[-1]] - observations[years[-2]]) / abs(observations[years[-2]])
        output = {"regime": str(inputs["event_regime"]), "adjusted_change_pct": _text(delta * Decimal(str(inputs["regime_multiplier"])))}
    elif op == "language_invariant":
        output = {"value": _text(table[country_names[0]][str(inputs["target_year"])]), "language": str(inputs["language"])}
    elif op == "modality_invariant":
        output = {"value": _text(table[country_names[0]][str(inputs["target_year"])]), "modality": str(inputs["modality"])}
    elif op == "threshold":
        number = table[country_names[0]][str(inputs["target_year"])]
        barrier = Decimal(str(inputs["threshold"]))
        output = {"meets_threshold": number >= barrier, "value": _text(number), "threshold": _text(barrier)}
    else:
        return {"status": "abstain", "value": None, "reason_codes": ["METHOD_NOT_REGISTERED"]}
    return {"status": "answer", "value": output, "reason_codes": []}
