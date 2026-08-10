"""Independent fixture oracle; it does not import the contract validator."""

from decimal import Decimal


def evaluate(snapshot: dict, threshold_pct: str) -> dict:
    change_pct = snapshot["records"][0]["payload"]["change_pct"]
    return {
        "is_material": abs(Decimal(change_pct)) >= Decimal(threshold_pct),
        "change_pct": change_pct,
        "threshold_pct": threshold_pct,
    }
