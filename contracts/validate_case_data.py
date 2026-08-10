#!/usr/bin/env python3
"""Dependency-free validator for frozen case_card and data_snapshot v1 contracts."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CONFIG_PATH = ROOT / "case_data_validation_config.v1.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MIC_RE = re.compile(r"^[A-Z0-9]{4}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ContractValidationError(ValueError):
    """Raised with all discovered contract violations."""

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
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )


def load_config() -> dict[str, Any]:
    return load_json(CONFIG_PATH)


def _assert_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise ValueError(
            f"{path}: non-integer financial numbers must be canonical decimal strings"
        )
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_finite(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_finite(child, f"{path}/{index}")


def canonical_bytes(document: Mapping[str, Any], *, omit_content_hash: bool = True) -> bytes:
    """Serialize using the frozen v1 canonical JSON profile.

    The profile is UTF-8, NFC-preserving input, sorted object keys, no insignificant
    whitespace, JSON lowercase literals, integers only, and no ASCII escaping.
    Non-integer financial numbers are decimal strings, avoiding binary-float and
    cross-language number-rendering drift.
    Hashing omits only ``integrity.content_sha256`` to avoid a circular digest.
    """

    material = copy.deepcopy(document)
    if omit_content_hash and isinstance(material.get("integrity"), dict):
        material["integrity"].pop("content_sha256", None)
    _assert_finite(material)
    return json.dumps(
        material,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def file_sha256(path: str | pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _require_object(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return {}
    return value


def _require_list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return []
    return value


def _required(obj: Mapping[str, Any], keys: Iterable[str], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in obj:
            errors.append(f"{path}/{key}: required field is missing")


def _parse_time(value: Any, path: str, errors: list[str]) -> dt.datetime | None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be an RFC 3339 timestamp string")
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: invalid RFC 3339 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{path}: timezone offset is required")
        return None
    return parsed


def _check_hash(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        errors.append(f"{path}: must be a lowercase 64-character SHA-256 hex digest")


def _check_common_integrity(document: Mapping[str, Any], errors: list[str]) -> None:
    config = load_config()
    integrity = _require_object(document.get("integrity"), "$/integrity", errors)
    _required(integrity, ("canonicalization", "hash_algorithm", "content_sha256"), "$/integrity", errors)
    if integrity.get("canonicalization") != config["canonicalization"]:
        errors.append("$/integrity/canonicalization: unsupported canonicalization profile")
    if integrity.get("hash_algorithm") != config["hash_algorithm"]:
        errors.append("$/integrity/hash_algorithm: must be sha256")
    actual = integrity.get("content_sha256")
    _check_hash(actual, "$/integrity/content_sha256", errors)
    if isinstance(actual, str) and SHA256_RE.fullmatch(actual):
        expected = content_sha256(document)
        if actual != expected:
            errors.append(
                f"$/integrity/content_sha256: hash mismatch (expected {expected}, got {actual})"
            )


def _validate_subject(subject_value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    subject = _require_object(subject_value, path, errors)
    _required(subject, ("subject_type", "entity_name", "identifiers", "market", "currency", "units"), path, errors)
    identifiers = _require_list(subject.get("identifiers"), f"{path}/identifiers", errors)
    if not identifiers:
        errors.append(f"{path}/identifiers: at least one stable identifier is required")
    for index, item in enumerate(identifiers):
        identifier = _require_object(item, f"{path}/identifiers/{index}", errors)
        _required(identifier, ("scheme", "value"), f"{path}/identifiers/{index}", errors)
    market = _require_object(subject.get("market"), f"{path}/market", errors)
    _required(market, ("mic", "country", "timezone"), f"{path}/market", errors)
    if market.get("mic") is not None and (
        not isinstance(market.get("mic"), str) or not MIC_RE.fullmatch(market["mic"])
    ):
        errors.append(f"{path}/market/mic: must be a four-character ISO 10383 MIC")
    currency = _require_object(subject.get("currency"), f"{path}/currency", errors)
    _required(currency, ("code",), f"{path}/currency", errors)
    if currency.get("code") is not None and (
        not isinstance(currency.get("code"), str) or not CURRENCY_RE.fullmatch(currency["code"])
    ):
        errors.append(f"{path}/currency/code: must be an ISO 4217-style three-letter code")
    units = _require_object(subject.get("units"), f"{path}/units", errors)
    _required(units, ("amount_scale", "price_basis", "accounting_basis"), f"{path}/units", errors)
    return subject


def validate_data_snapshot(snapshot: Mapping[str, Any], *, raise_on_error: bool = True) -> list[str]:
    errors: list[str] = []
    config = load_config()
    _required(
        snapshot,
        (
            "contract_type",
            "contract_version",
            "snapshot_id",
            "revision",
            "status",
            "source",
            "access",
            "financial_subject",
            "temporal",
            "records",
            "lineage",
            "integrity",
        ),
        "$",
        errors,
    )
    if snapshot.get("contract_type") != "data_snapshot":
        errors.append("$/contract_type: must be data_snapshot")
    if snapshot.get("contract_version") != config["contract_versions"]["data_snapshot"]:
        errors.append("$/contract_version: unsupported data_snapshot version")
    if snapshot.get("status") != "frozen":
        errors.append("$/status: snapshots consumed by evaluation must be frozen")
    if not isinstance(snapshot.get("revision"), int) or snapshot.get("revision", 0) < 1:
        errors.append("$/revision: must be an integer >= 1")

    source = _require_object(snapshot.get("source"), "$/source", errors)
    _required(source, ("provider", "source_type", "dataset", "uri", "license"), "$/source", errors)
    license_obj = _require_object(source.get("license"), "$/source/license", errors)
    _required(license_obj, ("name", "url", "redistributable"), "$/source/license", errors)
    if not license_obj.get("name"):
        errors.append("$/source/license/name: source license must be explicit")

    access = _require_object(snapshot.get("access"), "$/access", errors)
    _required(access, ("mode", "query_name", "query_args", "prohibited_scopes"), "$/access", errors)
    provider = str(source.get("provider", "")).lower()
    if provider in config["public_read_only_providers"] and access.get("mode") != "public_read_only":
        errors.append("$/access/mode: Longbridge sources must use public_read_only")
    scopes = _require_list(access.get("prohibited_scopes"), "$/access/prohibited_scopes", errors)
    if provider in config["public_read_only_providers"]:
        missing = set(config["forbidden_data_scopes"]) - set(scopes)
        if missing:
            errors.append(
                "$/access/prohibited_scopes: Longbridge snapshot must prohibit "
                + ", ".join(sorted(missing))
            )
        query_blob = json.dumps(
            {"query_name": access.get("query_name"), "query_args": access.get("query_args")},
            ensure_ascii=False,
        ).lower()
        unsafe = sorted(scope for scope in config["forbidden_data_scopes"] if scope in query_blob)
        if unsafe:
            errors.append(
                "$/access: Longbridge query appears to request forbidden account/trading scope: "
                + ", ".join(unsafe)
            )

    _validate_subject(snapshot.get("financial_subject"), "$/financial_subject", errors)
    temporal = _require_object(snapshot.get("temporal"), "$/temporal", errors)
    _required(temporal, ("event_time", "as_of", "available_at", "retrieved_at"), "$/temporal", errors)
    event_time = _parse_time(temporal.get("event_time"), "$/temporal/event_time", errors)
    as_of = _parse_time(temporal.get("as_of"), "$/temporal/as_of", errors)
    available_at = _parse_time(temporal.get("available_at"), "$/temporal/available_at", errors)
    retrieved_at = _parse_time(temporal.get("retrieved_at"), "$/temporal/retrieved_at", errors)
    if event_time and available_at and event_time > available_at:
        errors.append("$/temporal: time inversion; event_time must not be after available_at")
    if available_at and retrieved_at and available_at > retrieved_at:
        errors.append("$/temporal: time inversion; available_at must not be after retrieved_at")
    if as_of and retrieved_at and as_of > retrieved_at:
        errors.append("$/temporal: time inversion; as_of must not be after retrieved_at")

    records = _require_list(snapshot.get("records"), "$/records", errors)
    if not records:
        errors.append("$/records: a frozen snapshot must contain at least one record")
    seen_records: set[str] = set()
    for index, item in enumerate(records):
        record = _require_object(item, f"$/records/{index}", errors)
        _required(record, ("record_id", "evidence_type", "source_locator", "payload"), f"$/records/{index}", errors)
        record_id = record.get("record_id")
        if record_id in seen_records:
            errors.append(f"$/records/{index}/record_id: duplicate record id")
        if isinstance(record_id, str):
            seen_records.add(record_id)

    lineage = _require_object(snapshot.get("lineage"), "$/lineage", errors)
    _required(
        lineage,
        ("collector", "collector_version", "schema_version", "query_args", "raw_response_sha256", "code_revision", "parent_snapshot_ids"),
        "$/lineage",
        errors,
    )
    _check_hash(lineage.get("raw_response_sha256"), "$/lineage/raw_response_sha256", errors)
    _check_common_integrity(snapshot, errors)
    if errors and raise_on_error:
        raise ContractValidationError(errors)
    return errors


def _pointer_get(document: Any, pointer: str) -> Any:
    value = document
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    for part in pointer[1:].split("/"):
        token = part.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _leaf_diffs(left: Any, right: Any, path: str = "") -> set[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        diffs: set[str] = set()
        for key in set(left) | set(right):
            child_path = f"{path}/{key.replace('~', '~0').replace('/', '~1')}"
            if key not in left or key not in right:
                diffs.add(child_path)
            else:
                diffs.update(_leaf_diffs(left[key], right[key], child_path))
        return diffs
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return {path}
        diffs: set[str] = set()
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            diffs.update(_leaf_diffs(left_item, right_item, f"{path}/{index}"))
        return diffs
    return set() if left == right else {path or "/"}


def validate_variant_relation(
    case_card: Mapping[str, Any], parent_case: Mapping[str, Any], *, raise_on_error: bool = True
) -> list[str]:
    errors: list[str] = []
    config = load_config()
    variant = _require_object(case_card.get("variant"), "$/variant", errors)
    if variant.get("kind") != "single_factor_perturbation":
        if errors and raise_on_error:
            raise ContractValidationError(errors)
        return errors
    if variant.get("parent_case_id") != parent_case.get("case_id"):
        errors.append("$/variant/parent_case_id: does not match supplied parent case")
    changed = _require_list(variant.get("changed_factors"), "$/variant/changed_factors", errors)
    if len(changed) != 1:
        errors.append("$/variant/changed_factors: single-factor variant must declare exactly one factor")
    elif isinstance(changed[0], str):
        factor = changed[0]
        if not any(factor == allowed or factor.startswith(allowed + "/") for allowed in config["single_factor_eligible_pointers"]):
            errors.append("$/variant/changed_factors/0: pointer is not an eligible perturbation factor")
        try:
            if _pointer_get(case_card, factor) == _pointer_get(parent_case, factor):
                errors.append("$/variant/changed_factors/0: declared factor did not change")
        except (KeyError, IndexError, TypeError, ValueError):
            errors.append("$/variant/changed_factors/0: JSON pointer does not resolve in both cases")
        ignored = tuple(config["semantic_diff_ignored_pointers"])
        diffs = {
            path
            for path in _leaf_diffs(parent_case, case_card)
            if not any(path == ignore or path.startswith(ignore + "/") for ignore in ignored)
        }
        outside = sorted(
            path for path in diffs if not (path == factor or path.startswith(factor + "/"))
        )
        if outside:
            errors.append(
                "$/variant: more than one key factor changed; undeclared semantic differences: "
                + ", ".join(outside)
            )
    if errors and raise_on_error:
        raise ContractValidationError(errors)
    return errors


def validate_case_card(
    case_card: Mapping[str, Any],
    *,
    snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    parent_case: Mapping[str, Any] | None = None,
    raise_on_error: bool = True,
) -> list[str]:
    errors: list[str] = []
    config = load_config()
    _required(
        case_card,
        (
            "contract_type",
            "contract_version",
            "case_id",
            "revision",
            "status",
            "source",
            "task",
            "financial_subject",
            "temporal",
            "risk",
            "quality",
            "evidence_policy",
            "evidence_refs",
            "variant",
            "oracle",
            "lineage",
            "integrity",
        ),
        "$",
        errors,
    )
    if case_card.get("contract_type") != "case_card":
        errors.append("$/contract_type: must be case_card")
    if case_card.get("contract_version") != config["contract_versions"]["case_card"]:
        errors.append("$/contract_version: unsupported case_card version")
    if case_card.get("status") != "frozen":
        errors.append("$/status: case cards consumed by evaluation must be frozen")
    if not isinstance(case_card.get("revision"), int) or case_card.get("revision", 0) < 1:
        errors.append("$/revision: must be an integer >= 1")

    source = _require_object(case_card.get("source"), "$/source", errors)
    _required(source, ("origin_type", "name", "uri", "license"), "$/source", errors)
    source_license = _require_object(source.get("license"), "$/source/license", errors)
    _required(source_license, ("name", "url", "redistributable"), "$/source/license", errors)
    if not source_license.get("name"):
        errors.append("$/source/license/name: source license must be explicit")

    task = _require_object(case_card.get("task"), "$/task", errors)
    _required(task, ("domain", "prompt", "inputs", "required_tools", "permissions", "initial_state"), "$/task", errors)
    case_subject = _validate_subject(case_card.get("financial_subject"), "$/financial_subject", errors)

    temporal = _require_object(case_card.get("temporal"), "$/temporal", errors)
    _required(temporal, ("event_time", "as_of", "available_at_cutoff"), "$/temporal", errors)
    event_time = _parse_time(temporal.get("event_time"), "$/temporal/event_time", errors)
    as_of = _parse_time(temporal.get("as_of"), "$/temporal/as_of", errors)
    cutoff = _parse_time(temporal.get("available_at_cutoff"), "$/temporal/available_at_cutoff", errors)
    if event_time and as_of and event_time > as_of:
        errors.append("$/temporal: time inversion; event_time must not be after as_of")
    if cutoff and as_of and cutoff > as_of:
        errors.append("$/temporal: time inversion; available_at_cutoff must not be after as_of")

    risk = _require_object(case_card.get("risk"), "$/risk", errors)
    _required(risk, ("level", "loss_class", "rationale"), "$/risk", errors)
    if risk.get("level") not in ("low", "medium", "high", "critical"):
        errors.append("$/risk/level: must be low, medium, high, or critical")

    quality = _require_object(case_card.get("quality"), "$/quality", errors)
    _required(quality, ("tier", "ranking_eligible", "independently_recomputable", "rationale"), "$/quality", errors)
    tier = quality.get("tier")
    if tier not in config["quality_tiers"]:
        errors.append("$/quality/tier: every case must be explicitly marked Gold or Silver")
    elif tier == "Gold":
        if quality.get("ranking_eligible") is not True:
            errors.append("$/quality/ranking_eligible: Gold cases must be ranking eligible")
        if quality.get("independently_recomputable") is not True:
            errors.append("$/quality/independently_recomputable: Gold cases must be independently recomputable")
    elif quality.get("ranking_eligible") is not False:
        errors.append("$/quality/ranking_eligible: Silver cases must be excluded from the main ranking")

    policy = _require_object(case_card.get("evidence_policy"), "$/evidence_policy", errors)
    _required(
        policy,
        ("minimum_evidence_count", "required_evidence_types", "future_information_prohibited"),
        "$/evidence_policy",
        errors,
    )
    if policy.get("future_information_prohibited") is not True:
        errors.append("$/evidence_policy/future_information_prohibited: must be true")
    minimum = policy.get("minimum_evidence_count")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        errors.append("$/evidence_policy/minimum_evidence_count: must be an integer >= 0")
        minimum = 0
    refs = _require_list(case_card.get("evidence_refs"), "$/evidence_refs", errors)
    if len(refs) < minimum:
        errors.append("$/evidence_refs: evidence minimum set is not satisfied")
    if tier == "Gold" and len(refs) < config["quality_tiers"]["Gold"]["minimum_evidence_count"]:
        errors.append("$/evidence_refs: Gold case requires at least one evidence reference")

    evidence_types: set[str] = set()
    for index, item in enumerate(refs):
        ref = _require_object(item, f"$/evidence_refs/{index}", errors)
        _required(ref, ("snapshot_id", "record_ids", "snapshot_sha256", "evidence_type"), f"$/evidence_refs/{index}", errors)
        _check_hash(ref.get("snapshot_sha256"), f"$/evidence_refs/{index}/snapshot_sha256", errors)
        if isinstance(ref.get("evidence_type"), str):
            evidence_types.add(ref["evidence_type"])
        if snapshots is not None and isinstance(ref.get("snapshot_id"), str):
            snapshot = snapshots.get(ref["snapshot_id"])
            if snapshot is None:
                errors.append(f"$/evidence_refs/{index}/snapshot_id: referenced snapshot not supplied")
                continue
            if ref.get("snapshot_sha256") != snapshot.get("integrity", {}).get("content_sha256"):
                errors.append(f"$/evidence_refs/{index}/snapshot_sha256: does not match referenced snapshot")
            snapshot_subject = snapshot.get("financial_subject")
            if isinstance(snapshot_subject, dict) and snapshot_subject != case_subject:
                errors.append(
                    f"$/evidence_refs/{index}: snapshot financial_subject does not match case financial_subject"
                )
            snapshot_records = {record.get("record_id") for record in snapshot.get("records", [])}
            for record_id in _require_list(ref.get("record_ids"), f"$/evidence_refs/{index}/record_ids", errors):
                if record_id not in snapshot_records:
                    errors.append(f"$/evidence_refs/{index}/record_ids: unknown record {record_id}")
            snapshot_available = _parse_time(
                snapshot.get("temporal", {}).get("available_at"),
                f"$/evidence_refs/{index}/snapshot.temporal.available_at",
                errors,
            )
            snapshot_as_of = _parse_time(
                snapshot.get("temporal", {}).get("as_of"),
                f"$/evidence_refs/{index}/snapshot.temporal.as_of",
                errors,
            )
            if snapshot_available and cutoff and snapshot_available > cutoff:
                errors.append(f"$/evidence_refs/{index}: future information; snapshot available_at exceeds case cutoff")
            if snapshot_as_of and as_of and snapshot_as_of > as_of:
                errors.append(f"$/evidence_refs/{index}: future information; snapshot as_of exceeds case as_of")
    required_types = set(_require_list(policy.get("required_evidence_types"), "$/evidence_policy/required_evidence_types", errors))
    if not required_types.issubset(evidence_types):
        errors.append("$/evidence_refs: required evidence types are not all present")

    variant = _require_object(case_card.get("variant"), "$/variant", errors)
    _required(variant, ("kind", "family_id", "parent_case_id", "changed_factors"), "$/variant", errors)
    kind = variant.get("kind")
    if kind not in config["variant_kinds"]:
        errors.append("$/variant/kind: unsupported variant kind")
    if kind == "normal" and (variant.get("parent_case_id") is not None or variant.get("changed_factors") != []):
        errors.append("$/variant: normal case must not declare a parent or changed factor")
    if kind != "normal" and not variant.get("parent_case_id"):
        errors.append("$/variant/parent_case_id: non-normal variant requires a parent")

    oracle = _require_object(case_card.get("oracle"), "$/oracle", errors)
    _required(
        oracle,
        ("spec_version", "implementation", "implementation_sha256", "expected_status", "expected_value", "reason_codes"),
        "$/oracle",
        errors,
    )
    _check_hash(oracle.get("implementation_sha256"), "$/oracle/implementation_sha256", errors)
    if tier == "Silver" and oracle.get("expected_status") != "abstain":
        errors.append("$/oracle/expected_status: Silver case must expect abstention")
    if kind == "missing_or_anomalous" and not refs and oracle.get("expected_status") != "abstain":
        errors.append("$/oracle/expected_status: missing-evidence case must expect abstention")

    lineage = _require_object(case_card.get("lineage"), "$/lineage", errors)
    _required(
        lineage,
        ("producer", "generator_version", "code_revision", "generated_at", "source_case_id", "parent_case_id"),
        "$/lineage",
        errors,
    )
    _parse_time(lineage.get("generated_at"), "$/lineage/generated_at", errors)
    _check_common_integrity(case_card, errors)

    if parent_case is not None:
        errors.extend(validate_variant_relation(case_card, parent_case, raise_on_error=False))
    if errors and raise_on_error:
        raise ContractValidationError(errors)
    return errors


def validate_bundle(fixtures_dir: str | pathlib.Path) -> dict[str, int]:
    fixtures = pathlib.Path(fixtures_dir)
    snapshots: dict[str, Mapping[str, Any]] = {}
    cases: dict[str, Mapping[str, Any]] = {}
    errors: list[str] = []
    for path in sorted(fixtures.glob("data_snapshot*.json")):
        snapshot = load_json(path)
        snapshot_errors = validate_data_snapshot(snapshot, raise_on_error=False)
        errors.extend(f"{path.name}: {error}" for error in snapshot_errors)
        if isinstance(snapshot.get("snapshot_id"), str):
            snapshots[snapshot["snapshot_id"]] = snapshot
    for path in sorted(fixtures.glob("case_card*.json")):
        case = load_json(path)
        if isinstance(case.get("case_id"), str):
            cases[case["case_id"]] = case
    for path in sorted(fixtures.glob("case_card*.json")):
        case = load_json(path)
        parent_id = case.get("variant", {}).get("parent_case_id")
        parent = cases.get(parent_id) if parent_id else None
        case_errors = validate_case_card(
            case,
            snapshots=snapshots,
            parent_case=parent,
            raise_on_error=False,
        )
        if parent_id and parent is None:
            case_errors.append("$/variant/parent_case_id: parent case not supplied in bundle")
        implementation = case.get("oracle", {}).get("implementation")
        implementation_hash = case.get("oracle", {}).get("implementation_sha256")
        if isinstance(implementation, str):
            implementation_path = (PROJECT_ROOT / implementation.split(":", 1)[0]).resolve()
            if not implementation_path.is_file():
                case_errors.append("$/oracle/implementation: implementation file does not exist")
            elif file_sha256(implementation_path) != implementation_hash:
                case_errors.append("$/oracle/implementation_sha256: implementation file hash mismatch")
        errors.extend(f"{path.name}: {error}" for error in case_errors)
    if errors:
        raise ContractValidationError(errors)
    return {"snapshots": len(snapshots), "cases": len(cases)}


def verify_manifest(path: str | pathlib.Path) -> None:
    manifest_path = pathlib.Path(path)
    manifest = load_json(manifest_path)
    errors: list[str] = []
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ContractValidationError(["$/files: must be an array"])
    bundle_lines: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append(f"$/files/{index}: path and sha256 are required")
            continue
        target = (manifest_path.parent / entry["path"]).resolve()
        actual = file_sha256(target) if target.is_file() else None
        if actual != entry.get("sha256"):
            errors.append(f"$/files/{index}: file hash mismatch for {entry['path']}")
        bundle_lines.append(f"{entry.get('sha256')}  {entry['path']}\n")
    expected_bundle = hashlib.sha256("".join(bundle_lines).encode("utf-8")).hexdigest()
    if manifest.get("contract_bundle_sha256") != expected_bundle:
        errors.append("$/contract_bundle_sha256: manifest bundle hash mismatch")
    if errors:
        raise ContractValidationError(errors)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bundle_parser = subparsers.add_parser("validate-bundle", help="validate fixture directory")
    bundle_parser.add_argument("fixtures_dir")
    hash_parser = subparsers.add_parser("hash", help="print canonical content hash for a JSON document")
    hash_parser.add_argument("document")
    manifest_parser = subparsers.add_parser("verify-manifest", help="verify a frozen manifest")
    manifest_parser.add_argument("manifest")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-bundle":
            counts = validate_bundle(args.fixtures_dir)
            print(json.dumps({"valid": True, **counts}, sort_keys=True))
        elif args.command == "hash":
            print(content_sha256(load_json(args.document)))
        elif args.command == "verify-manifest":
            verify_manifest(args.manifest)
            print(json.dumps({"valid": True}, sort_keys=True))
    except (ContractValidationError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
