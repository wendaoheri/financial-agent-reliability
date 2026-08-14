#!/usr/bin/env python3
"""Deterministic validator and scorer for the PER-80 v2 grader contract.

Scoring semantics are identical to the frozen v1 scorer (contracts/grader.py):
same Gold-only scope, 50/50 track weights, case-family clustering, CSR,
pass^3, abstention rates, evidence accuracy, high-loss rates, cluster
bootstrap, Holm-Bonferroni pairwise tests, and the five preregistered leader
gates, with every threshold read from contracts/grader_policy.v1.json
(unchanged). Only the declared inputs change, per the preregistration v1.1
addendum: the executed model roster, the executed variant vocabulary, the
case-level tier registry, the registered action normalization, and the
registered L0-L4 loss mapping. No run is rerun and no v1 artifact is altered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import random
import statistics
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence


ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "contracts" / "grader_policy.v1.json"
PREREG_V1_PATH = ROOT / "preregistration" / "benchmark_preregistration.v1.json"
PREREG_PATH = ROOT / "preregistration" / "benchmark_preregistration.v1.1.json"
MANIFEST_PATH = ROOT / "contracts" / "grader_contract.frozen.v2.json"
MANIFEST_V1_PATH = ROOT / "contracts" / "grader_contract.frozen.v1.json"
CONTRACT_VERSION = "2.0.0"
ALLOWED_ACTIONS = {"answer", "abstain", "escalate", "reject_action"}
ALLOWED_LOSSES = {"L0", "L1", "L2", "L3", "L4"}


class GraderValidationError(ValueError):
    """All machine-detectable contract failures, reported together."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: str | pathlib.Path) -> Any:
    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )


def file_sha256(path: str | pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_frozen_contract() -> dict[str, int]:
    """Validate preregistration-policy consistency without inspecting results."""

    policy = load_json(POLICY_PATH)
    prereg = load_json(PREREG_PATH)
    checklist = load_json(ROOT / "audit" / "acceptance_checklist.v1.json")
    errors: list[str] = []

    _require(policy.get("status") == "frozen", "policy status must be frozen", errors)
    _require(
        prereg.get("status") == "frozen_addendum",
        "preregistration v1.1 must carry status frozen_addendum",
        errors,
    )
    _require(
        prereg.get("revision_type") == "addendum",
        "preregistration v1.1 must be an addendum revision",
        errors,
    )
    _require(
        prereg.get("supersedes", {}).get("sha256") == file_sha256(PREREG_V1_PATH),
        "preregistration v1.1 supersedes commitment does not match the frozen v1 file",
        errors,
    )
    tracks = policy.get("ranking_scope", {}).get("tracks", {})
    _require(
        tracks == {
            "financial_knowledge_work": "0.500000",
            "financial_tool_workflow": "0.500000",
        },
        "ranking tracks must be exactly 50/50",
        errors,
    )
    _require(
        policy.get("ranking_scope", {}).get("included_tier") == "Gold",
        "only Gold may be included in ranking",
        errors,
    )
    _require(
        policy.get("ranking_scope", {}).get("diagnostic_only_tiers") == ["Silver"],
        "Silver must be diagnostic only",
        errors,
    )
    matrix = policy.get("matrix", {})
    expected_matrix = {
        "case_families": 30,
        "variants_per_family": 3,
        "candidate_models": 3,
        "repeats_per_cell": 3,
        "expected_run_rows": 810,
    }
    for key, expected in expected_matrix.items():
        _require(matrix.get(key) == expected, f"matrix {key} must equal {expected}", errors)

    models = prereg.get("candidate_models", [])
    variants = prereg.get("variant_ids", [])
    families = prereg.get("case_families", [])
    _require(len(models) == 3 and len(set(models)) == 3, "exactly 3 unique models required", errors)
    _require(
        variants == ["baseline", "single_factor_stress", "missing_or_anomalous_diagnostic"],
        "variant ids must be the executed vocabulary of variant protocol v2",
        errors,
    )
    _require(len(families) == 30, "exactly 30 case families required", errors)
    family_ids = [item.get("id") for item in families if isinstance(item, dict)]
    _require(len(set(family_ids)) == 30, "case family ids must be unique", errors)
    family_track: dict[str, str] = {}
    for index, family in enumerate(families):
        if not isinstance(family, dict):
            errors.append(f"case_families/{index} must be an object")
            continue
        track = family.get("track")
        _require(track in tracks, f"{family.get('id')}: unknown track", errors)
        _require(bool(family.get("variant_axis")), f"{family.get('id')}: missing variant_axis", errors)
        family_track[str(family.get("id"))] = str(track)

    registry = prereg.get("recorded_pre_execution_changes", {}).get("case_tier_registry", {})
    cells = registry.get("cells", [])
    _require(len(cells) == 90, "case tier registry must hold exactly 90 cells", errors)
    seen_cells: set[tuple[str, str]] = set()
    gold_families: dict[str, set[str]] = defaultdict(set)
    gold_count = silver_count = 0
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            errors.append(f"case_tier_registry/cells/{index} must be an object")
            continue
        family_id = str(cell.get("family_id"))
        variant_id = cell.get("variant_id")
        tier = cell.get("tier")
        _require(family_id in family_track, f"cell {family_id}/{variant_id}: unregistered family", errors)
        _require(variant_id in variants, f"cell {family_id}/{variant_id}: unregistered variant", errors)
        _require(
            cell.get("track") == family_track.get(family_id),
            f"cell {family_id}/{variant_id}: track disagrees with family",
            errors,
        )
        _require(tier in {"Gold", "Silver"}, f"cell {family_id}/{variant_id}: unknown tier", errors)
        _require(
            not (variant_id == "missing_or_anomalous_diagnostic" and tier != "Silver"),
            f"cell {family_id}/{variant_id}: missing_or_anomalous must be Silver",
            errors,
        )
        key = (family_id, str(variant_id))
        _require(key not in seen_cells, f"cell {family_id}/{variant_id}: duplicate registry cell", errors)
        seen_cells.add(key)
        if tier == "Gold":
            gold_count += 1
            gold_families[str(cell.get("track"))].add(family_id)
        else:
            silver_count += 1
    _require(gold_count == 46, "case tier registry must hold exactly 46 Gold cells", errors)
    _require(silver_count == 44, "case tier registry must hold exactly 44 Silver cells", errors)
    cells_per_family: dict[str, int] = defaultdict(int)
    for cell in cells:
        if isinstance(cell, dict):
            cells_per_family[str(cell.get("family_id"))] += 1
    _require(
        all(cells_per_family.get(family_id) == 3 for family_id in family_track),
        "every family must register exactly 3 case tier cells",
        errors,
    )
    for track in tracks:
        _require(
            len(gold_families.get(track, set())) >= 10,
            f"{track}: fewer than 10 Gold families registered",
            errors,
        )

    loss_mapping = prereg.get("new_registrations", {}).get("loss_level_mapping", {})
    _require(
        set(loss_mapping.get("rules", {})) == ALLOWED_LOSSES,
        "loss_level_mapping must register all of L0..L4",
        errors,
    )
    _require(
        bool(prereg.get("new_registrations", {}).get("action_vocabulary_addendum")),
        "action vocabulary addendum must be registered",
        errors,
    )
    _require(
        bool(prereg.get("new_registrations", {}).get("single_factor_rule_derived_change_exemption", {}).get("clause")),
        "single_factor_rule derived-change exemption clause must be registered",
        errors,
    )

    _require(
        len(checklist.get("items", [])) >= 14,
        "Stage 4 checklist is incomplete",
        errors,
    )
    audit_areas = {item.get("area") for item in checklist.get("items", [])}
    required_areas = {
        "point_in_time", "contamination_leakage", "duplicate_cases",
        "single_factor_variants", "model_identity", "resource_fairness",
        "grader_correctness", "judge_bias", "exclusions", "statistics",
        "ranking_stability", "gold_silver_separation", "matrix_completeness",
        "freeze_integrity",
    }
    _require(required_areas <= audit_areas, "Stage 4 checklist misses required audit areas", errors)
    if errors:
        raise GraderValidationError(errors)
    return {"families": len(families), "models": len(models), "variants": len(variants)}


def verify_freeze() -> dict[str, Any]:
    """Verify each frozen file and the deterministic aggregate commitment."""

    manifest = load_json(MANIFEST_PATH)
    errors: list[str] = []
    commitments: list[str] = []
    for item in manifest.get("files", []):
        rel = item.get("path")
        expected = item.get("sha256")
        path = ROOT / str(rel)
        if not path.is_file():
            errors.append(f"missing frozen file: {rel}")
            continue
        actual = file_sha256(path)
        if actual != expected:
            errors.append(f"frozen file hash mismatch: {rel} expected {expected} got {actual}")
        commitments.append(f"{rel}\0{expected}\n")
    aggregate = hashlib.sha256("".join(commitments).encode("utf-8")).hexdigest()
    if aggregate != manifest.get("contract_bundle_sha256"):
        errors.append(
            "contract bundle commitment mismatch: "
            f"expected {manifest.get('contract_bundle_sha256')} got {aggregate}"
        )
    if manifest.get("supersedes", {}).get("sha256") != file_sha256(MANIFEST_V1_PATH):
        errors.append("v2 manifest supersedes commitment does not match the frozen v1 manifest file")
    if errors:
        raise GraderValidationError(errors)
    return {"files": len(commitments), "contract_bundle_sha256": aggregate}


def _parse_decimal(value: Any, path: str, errors: list[str]) -> Decimal | None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be a canonical non-negative decimal string")
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        errors.append(f"{path}: invalid decimal")
        return None
    if not parsed.is_finite() or parsed < 0 or str(parsed) != value:
        errors.append(f"{path}: must be a canonical non-negative finite decimal string")
        return None
    return parsed


def validate_results(bundle: Mapping[str, Any], *, require_complete: bool = True) -> list[dict[str, Any]]:
    """Validate result rows; complete mode enforces every frozen matrix cell once."""

    policy = load_json(POLICY_PATH)
    prereg = load_json(PREREG_PATH)
    errors: list[str] = []
    allowed_top_level = {
        "contract_version", "preregistration_sha256", "model_manifests", "runs"
    }
    _require(
        not (set(bundle) - allowed_top_level),
        f"unregistered top-level fields: {sorted(set(bundle) - allowed_top_level)}",
        errors,
    )
    _require(bundle.get("contract_version") == CONTRACT_VERSION, "unsupported result contract_version", errors)
    _require(
        bundle.get("preregistration_sha256") == file_sha256(PREREG_PATH),
        "preregistration_sha256 does not match the frozen preregistration v1.1",
        errors,
    )

    models = prereg["candidate_models"]
    manifests = bundle.get("model_manifests")
    if not isinstance(manifests, list):
        manifests = []
        errors.append("model_manifests must be an array")
    labels: list[Any] = []
    for index, manifest in enumerate(manifests):
        path = f"model_manifests/{index}"
        if not isinstance(manifest, dict):
            errors.append(f"{path}: must be an object")
            continue
        allowed_manifest_fields = {
            "logical_label", "requested_model_id", "response_model_id",
            "provider", "identity_verified",
        }
        _require(
            not (set(manifest) - allowed_manifest_fields),
            f"{path}: unregistered fields {sorted(set(manifest) - allowed_manifest_fields)}",
            errors,
        )
        label = manifest.get("logical_label")
        labels.append(label)
        _require(label in models, f"{path}: unregistered logical_label", errors)
        requested = manifest.get("requested_model_id")
        response = manifest.get("response_model_id")
        _require(bool(requested) and requested == response, f"{path}: model identity mismatch or fallback", errors)
        _require(manifest.get("identity_verified") is True, f"{path}: identity not verified", errors)
        _require(bool(manifest.get("provider")), f"{path}: provider required", errors)
    _require(sorted(labels) == sorted(models), "model manifests must cover each candidate exactly once", errors)

    family_lookup = {item["id"]: item for item in prereg["case_families"]}
    variants = prereg["variant_ids"]
    repeats = prereg["repeats_per_cell"]
    registry_cells = {
        (str(cell["family_id"]), str(cell["variant_id"])): cell
        for cell in prereg["recorded_pre_execution_changes"]["case_tier_registry"]["cells"]
    }
    allowed_invariants = set(policy["critical_success"]["allowed_invariants"])
    runs_value = bundle.get("runs")
    if not isinstance(runs_value, list):
        runs_value = []
        errors.append("runs must be an array")
    seen: set[tuple[str, str, str, int]] = set()
    normalized: list[dict[str, Any]] = []
    exclusion_by_family: dict[str, list[bool]] = defaultdict(list)
    exclusion_signatures: dict[str, set[tuple[Any, ...]]] = defaultdict(set)

    for index, raw in enumerate(runs_value):
        path = f"runs/{index}"
        if not isinstance(raw, dict):
            errors.append(f"{path}: must be an object")
            continue
        allowed_run_fields = {
            "family_id", "variant_id", "model_label", "repeat",
            "critical_invariants", "end_to_end_complete", "evidence_correct",
            "evidence_required", "expected_action", "actual_action",
            "max_loss_level", "total_cost_usd", "latency_ms", "excluded",
            "exclusion",
        }
        _require(
            not (set(raw) - allowed_run_fields),
            f"{path}: unregistered fields {sorted(set(raw) - allowed_run_fields)}",
            errors,
        )
        family_id = raw.get("family_id")
        variant_id = raw.get("variant_id")
        model = raw.get("model_label")
        repeat = raw.get("repeat")
        _require(family_id in family_lookup, f"{path}: unregistered family_id", errors)
        _require(variant_id in variants, f"{path}: unregistered variant_id", errors)
        _require(
            (str(family_id), str(variant_id)) in registry_cells,
            f"{path}: family/variant cell not in the case tier registry",
            errors,
        )
        _require(model in models, f"{path}: unregistered model_label", errors)
        _require(isinstance(repeat, int) and not isinstance(repeat, bool) and 1 <= repeat <= repeats, f"{path}: invalid repeat", errors)
        key = (str(family_id), str(variant_id), str(model), repeat if isinstance(repeat, int) else -1)
        _require(key not in seen, f"{path}: duplicate matrix cell {key}", errors)
        seen.add(key)

        invariants = raw.get("critical_invariants")
        if not isinstance(invariants, dict) or not invariants:
            errors.append(f"{path}: at least one critical invariant is required")
            invariants = {}
        else:
            unknown = set(invariants) - allowed_invariants
            _require(not unknown, f"{path}: unknown critical invariants {sorted(unknown)}", errors)
            _require(all(type(value) is bool for value in invariants.values()), f"{path}: invariant values must be boolean", errors)
        _require(type(raw.get("end_to_end_complete")) is bool, f"{path}: end_to_end_complete must be boolean", errors)
        correct = raw.get("evidence_correct")
        required = raw.get("evidence_required")
        _require(isinstance(correct, int) and not isinstance(correct, bool) and correct >= 0, f"{path}: invalid evidence_correct", errors)
        _require(isinstance(required, int) and not isinstance(required, bool) and required >= 0, f"{path}: invalid evidence_required", errors)
        if isinstance(correct, int) and isinstance(required, int):
            _require(correct <= required, f"{path}: evidence_correct exceeds evidence_required", errors)
        _require(raw.get("expected_action") in ALLOWED_ACTIONS, f"{path}: invalid expected_action", errors)
        actual = raw.get("actual_action")
        _require(actual is None or actual in ALLOWED_ACTIONS, f"{path}: invalid actual_action", errors)
        _require(raw.get("max_loss_level") in ALLOWED_LOSSES, f"{path}: invalid max_loss_level", errors)
        _parse_decimal(raw.get("total_cost_usd"), f"{path}/total_cost_usd", errors)
        latency = raw.get("latency_ms")
        _require(isinstance(latency, int) and not isinstance(latency, bool) and latency >= 0, f"{path}: invalid latency_ms", errors)
        excluded = raw.get("excluded")
        _require(type(excluded) is bool, f"{path}: excluded must be boolean", errors)
        exclusion_by_family[str(family_id)].append(excluded is True)
        if excluded is True:
            exclusion = raw.get("exclusion")
            if not isinstance(exclusion, dict):
                errors.append(f"{path}: excluded row requires exclusion object")
            else:
                allowed_exclusion_fields = {
                    "code", "decided_before_identity_unblinding",
                    "independent_reviewer", "evidence_sha256",
                }
                _require(
                    not (set(exclusion) - allowed_exclusion_fields),
                    f"{path}/exclusion: unregistered fields "
                    f"{sorted(set(exclusion) - allowed_exclusion_fields)}",
                    errors,
                )
                code = exclusion.get("code")
                blinded = exclusion.get("decided_before_identity_unblinding")
                reviewer = exclusion.get("independent_reviewer")
                evidence_hash = exclusion.get("evidence_sha256")
                _require(code in policy["exclusions"]["allowed_codes"], f"{path}: unregistered exclusion code", errors)
                _require(blinded is True, f"{path}: exclusion decision was not blind", errors)
                _require(bool(reviewer), f"{path}: independent exclusion reviewer required", errors)
                _require(isinstance(evidence_hash, str) and len(evidence_hash) == 64 and all(c in "0123456789abcdef" for c in evidence_hash), f"{path}: valid evidence_sha256 required", errors)
                exclusion_signatures[str(family_id)].add((code, reviewer, evidence_hash, blinded))
        normalized.append(dict(raw))

    if require_complete:
        expected = {
            (family, variant, model, repeat)
            for family in family_lookup
            for variant in variants
            for model in models
            for repeat in range(1, repeats + 1)
        }
        missing = expected - seen
        extra = seen - expected
        _require(not missing, f"incomplete matrix: {len(missing)} cells missing", errors)
        _require(not extra, f"matrix has {len(extra)} extra cells", errors)
        _require(len(normalized) == policy["matrix"]["expected_run_rows"], "result row count must be exactly 810", errors)
        expected_rows_per_family = len(variants) * len(models) * repeats
        for family_id in family_lookup:
            flags = exclusion_by_family.get(family_id, [])
            if any(flags):
                _require(len(flags) == expected_rows_per_family and all(flags), f"{family_id}: exclusion must apply to the whole family and every candidate", errors)
                _require(len(exclusion_signatures[family_id]) == 1, f"{family_id}: exclusion evidence must be identical across the family", errors)
    if errors:
        raise GraderValidationError(errors)
    return normalized


def _critical_success(run: Mapping[str, Any]) -> int:
    return int(bool(run["end_to_end_complete"]) and all(run["critical_invariants"].values()))


def _family_values(runs: Sequence[Mapping[str, Any]], model: str, family_id: str, gold_variants: Sequence[str]) -> dict[str, float]:
    rows = [row for row in runs if row["model_label"] == model and row["family_id"] == family_id]
    if not rows:
        raise GraderValidationError([f"no rows for {model}/{family_id}"])
    critical = [_critical_success(row) for row in rows]
    evidence = [
        (row["evidence_correct"] / row["evidence_required"])
        if row["evidence_required"] else 1.0
        for row in rows
    ]
    abstention_rows = [row for row in rows if row["expected_action"] != "answer"]
    answer_rows = [row for row in rows if row["expected_action"] == "answer"]
    pass3_values: list[int] = []
    for variant in gold_variants:
        repeated = sorted((row for row in rows if row["variant_id"] == variant), key=lambda row: row["repeat"])
        if repeated:
            pass3_values.append(math.prod(_critical_success(row) for row in repeated[:3]))
    return {
        "CSR": statistics.fmean(critical),
        "pass^3": statistics.fmean(pass3_values) if pass3_values else math.nan,
        "evidence_accuracy": statistics.fmean(evidence),
        "correct_abstention_rate": statistics.fmean(
            [row["actual_action"] == row["expected_action"] for row in abstention_rows]
        ) if abstention_rows else math.nan,
        "erroneous_abstention_rate": statistics.fmean(
            [row["actual_action"] != "answer" for row in answer_rows]
        ) if answer_rows else math.nan,
        "high_loss_error_rate_per_1000": 1000.0 * statistics.fmean(
            [row["max_loss_level"] in {"L3", "L4"} for row in rows]
        ),
        "L4_events": float(sum(row["max_loss_level"] == "L4" for row in rows)),
        "cost_usd": statistics.fmean(float(Decimal(row["total_cost_usd"])) for row in rows),
        "latency_ms": statistics.fmean(row["latency_ms"] for row in rows),
    }


def _nanmean(values: Sequence[float]) -> float:
    finite = [value for value in values if not math.isnan(value)]
    return statistics.fmean(finite) if finite else math.nan


def _aggregate_cached(
    family_cache: Mapping[str, Mapping[str, Mapping[str, float]]],
    model: str,
    family_samples: Mapping[str, Sequence[str]],
) -> dict[str, float]:
    track_results: dict[str, dict[str, float]] = {}
    for track, families in family_samples.items():
        values = [family_cache[model][family] for family in families]
        track_results[track] = {
            metric: _nanmean([value[metric] for value in values])
            for metric in values[0]
        }
    metrics = next(iter(track_results.values()))
    return {
        metric: _nanmean([track_results[track][metric] for track in sorted(track_results)])
        for metric in metrics
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, (key, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[key] = running
    return adjusted


def score_results(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Score a complete bundle using fixed Gold-only weights and family clustering."""

    runs = validate_results(bundle, require_complete=True)
    policy = load_json(POLICY_PATH)
    prereg = load_json(PREREG_PATH)
    excluded_families = {
        row["family_id"] for row in runs if row["excluded"] is True
    }
    registry_cells = prereg["recorded_pre_execution_changes"]["case_tier_registry"]["cells"]
    gold_cells = {
        (str(cell["family_id"]), str(cell["variant_id"]))
        for cell in registry_cells if cell["tier"] == "Gold"
    }
    gold_variants_by_family: dict[str, list[str]] = defaultdict(list)
    for variant in prereg["variant_ids"]:
        for family in prereg["case_families"]:
            if (str(family["id"]), str(variant)) in gold_cells:
                gold_variants_by_family[str(family["id"])].append(str(variant))
    gold_runs = [
        row for row in runs
        if (str(row["family_id"]), str(row["variant_id"])) in gold_cells
    ]
    family_track_lookup = {family["id"]: family["track"] for family in prereg["case_families"]}
    gold_by_track: dict[str, list[str]] = defaultdict(list)
    for row in gold_runs:
        if row["family_id"] in excluded_families:
            continue
        track = family_track_lookup[row["family_id"]]
        if row["family_id"] not in gold_by_track[track]:
            gold_by_track[track].append(row["family_id"])
    for families in gold_by_track.values():
        families.sort()
    if any(len(families) < 10 for families in gold_by_track.values()):
        raise GraderValidationError(["fewer than 10 valid Gold families remain in a track; ranking invalid"])

    models = prereg["candidate_models"]
    family_cache = {
        model: {
            family: _family_values(gold_runs, model, family, gold_variants_by_family[family])
            for families in gold_by_track.values()
            for family in families
        }
        for model in models
    }
    point = {
        model: _aggregate_cached(family_cache, model, gold_by_track)
        for model in models
    }
    stats = policy["statistics"]
    rng = random.Random(stats["bootstrap_seed"])
    replicate_count = stats["cluster_bootstrap_replicates"]
    boot: dict[str, dict[str, list[float]]] = {
        model: {metric: [] for metric in point[model]} for model in models
    }
    pair_diffs: dict[str, list[float]] = {
        f"{left}__vs__{right}": []
        for index, left in enumerate(models)
        for right in models[index + 1:]
    }
    top_counts = {model: 0 for model in models}
    for _ in range(replicate_count):
        sampled = {
            track: [rng.choice(families) for _ in families]
            for track, families in gold_by_track.items()
        }
        values = {
            model: _aggregate_cached(family_cache, model, sampled)
            for model in models
        }
        for model in models:
            for metric, value in values[model].items():
                boot[model][metric].append(value)
        for key in pair_diffs:
            left, right = key.split("__vs__")
            pair_diffs[key].append(values[left]["CSR"] - values[right]["CSR"])
        leader = sorted(models, key=lambda model: (-values[model]["CSR"], model))[0]
        top_counts[leader] += 1

    model_report: dict[str, Any] = {}
    for model in models:
        model_report[model] = {}
        for metric, value in point[model].items():
            finite_bootstrap = [
                sample for sample in boot[model][metric] if not math.isnan(sample)
            ]
            if math.isnan(value) or not finite_bootstrap:
                estimate = None
                interval = None
            else:
                estimate = round(value, 8)
                interval = [
                    round(_percentile(finite_bootstrap, 0.025), 8),
                    round(_percentile(finite_bootstrap, 0.975), 8),
                ]
            model_report[model][metric] = {
                "estimate": estimate,
                "ci95": interval,
            }
        model_report[model]["bootstrap_top_probability"] = round(
            top_counts[model] / replicate_count, 8
        )

    raw_p: dict[str, float] = {}
    pair_report: dict[str, Any] = {}
    for key, differences in pair_diffs.items():
        non_positive = sum(value <= 0 for value in differences)
        non_negative = sum(value >= 0 for value in differences)
        p_value = min(1.0, 2 * (min(non_positive, non_negative) + 1) / (replicate_count + 1))
        raw_p[key] = p_value
        left, right = key.split("__vs__")
        pair_report[key] = {
            "csr_difference": round(point[left]["CSR"] - point[right]["CSR"], 8),
            "ci95": [round(_percentile(differences, 0.025), 8), round(_percentile(differences, 0.975), 8)],
            "bootstrap_two_sided_p": round(p_value, 8),
        }
    adjusted = _holm_adjust(raw_p)
    for key in pair_report:
        pair_report[key]["holm_adjusted_p"] = round(adjusted[key], 8)

    point_leader = sorted(models, key=lambda model: (-point[model]["CSR"], model))[0]
    loo_matches = 0
    loo_total = 0
    for track, families in gold_by_track.items():
        for omitted in families:
            reduced = {name: list(ids) for name, ids in gold_by_track.items()}
            reduced[track].remove(omitted)
            values = {
                model: _aggregate_cached(family_cache, model, reduced)["CSR"]
                for model in models
            }
            leader = sorted(models, key=lambda model: (-values[model], model))[0]
            loo_matches += leader == point_leader
            loo_total += 1
    loo_agreement = loo_matches / loo_total

    gates = policy["ranking_stability"]
    stat_cfg = policy["statistics"]
    alpha = float(stat_cfg["familywise_alpha"])
    min_difference = float(stat_cfg["minimum_business_difference_csr"])
    comparisons: list[bool] = []
    for peer in models:
        if peer == point_leader:
            continue
        direct = f"{point_leader}__vs__{peer}"
        reverse = f"{peer}__vs__{point_leader}"
        if direct in pair_report:
            difference = pair_report[direct]["csr_difference"]
            lower = pair_report[direct]["ci95"][0]
            adjusted_p = pair_report[direct]["holm_adjusted_p"]
        else:
            difference = -pair_report[reverse]["csr_difference"]
            lower = -pair_report[reverse]["ci95"][1]
            adjusted_p = pair_report[reverse]["holm_adjusted_p"]
        comparisons.append(difference >= min_difference and lower > 0 and adjusted_p <= alpha)
    leader_pass3_not_reversed = all(
        point[point_leader]["pass^3"] >= point[peer]["pass^3"]
        for peer in models if peer != point_leader
    )
    gate_results = {
        "pairwise_statistical_and_business_significance": all(comparisons),
        "bootstrap_top_probability": model_report[point_leader]["bootstrap_top_probability"] >= float(gates["bootstrap_top_probability_min"]),
        "leave_one_family_out_agreement": loo_agreement >= float(gates["leave_one_family_out_leader_agreement_min"]),
        "pass3_not_reversed": leader_pass3_not_reversed,
        "leader_has_zero_L4": point[point_leader]["L4_events"] == 0,
    }
    reliable = all(gate_results.values())
    return {
        "contract_version": CONTRACT_VERSION,
        "preregistration_version": prereg["version"],
        "ranking_scope": "Gold only, case-level tier registry; Silver excluded from every reported estimate",
        "track_weights": policy["ranking_scope"]["tracks"],
        "cluster_unit": "case_family",
        "bootstrap_replicates": replicate_count,
        "excluded_families": sorted(excluded_families),
        "models": model_report,
        "pairwise_csr": pair_report,
        "provisional_leader": point_leader,
        "leave_one_family_out_leader_agreement": round(loo_agreement, 8),
        "leader_gates": gate_results,
        "ranking_reliable": reliable,
        "ranking_conclusion": (
            f"{point_leader} satisfies every preregistered leader gate"
            if reliable else "No reliable global leader may be claimed"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-freeze")
    subparsers.add_parser("verify-freeze")
    validate_parser = subparsers.add_parser("validate-results")
    validate_parser.add_argument("results")
    validate_parser.add_argument("--allow-partial", action="store_true")
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("results")
    score_parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-freeze":
            result = validate_frozen_contract()
        elif args.command == "verify-freeze":
            validate_frozen_contract()
            result = verify_freeze()
        elif args.command == "validate-results":
            rows = validate_results(load_json(args.results), require_complete=not args.allow_partial)
            result = {"valid": True, "rows": len(rows), "complete": not args.allow_partial}
        else:
            result = score_results(load_json(args.results))
            if args.output:
                pathlib.Path(args.output).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (GraderValidationError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
