#!/usr/bin/env python3
"""Dependency-free validator for the frozen baseline v6 bundle (PER-328).

Successor in role to ``contracts/validate_case_data.py`` (baseline v1,
removed per PER-323 cleanup list v1; recoverable via the contracts/
rollback index commit 077fcb56). Commands:

  validate-bundle <baseline_v6_root>
      Cross-object semantic validation of snapshots and case cards:
      c14n content hashes, temporal discipline, evidence references,
      Gold/Silver rules, single-factor variant discipline, access-scope
      prohibition, and oracle-implementation registration.

  verify-manifest <baseline_v6_root>
      Recompute every artifact hash registered in
      ``baseline_manifest.frozen.v6.json``, recompute the bundle hash, and
      flag any unregistered file under the baseline root.

  verify-trace <run_trace.json>
      Execute the production v8 validator with the frozen v6 registry: full
      JSON Schema, cross-block anchors, and external case/variant/path/SHA binding.

Exit status: 0 when all checks pass, 1 otherwise; violations are printed
one per line. No third-party imports; no network; no mutation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^run_[0-9a-f]{32}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
SECRET_KEYS = frozenset(
    {"api_key", "authorization", "bearer_token", "password", "client_secret", "access_token"}
)
SECRET_TEXT = re.compile(r"(?i)(Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})")
FORBIDDEN_DATA_SCOPES = (
    "account", "assets", "cash", "holdings", "orders", "positions", "portfolio", "trades",
)
ALLOWED_ACTIONS = ("answer", "abstain", "escalate", "reject_action")


class ValidationError(ValueError):
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


def load_json(path: pathlib.Path) -> Any:
    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )


def canonical_bytes(document: Mapping[str, Any], *, omit_content_hash: bool = True) -> bytes:
    clone = copy.deepcopy(dict(document))
    if omit_content_hash and isinstance(clone.get("integrity"), dict):
        clone["integrity"].pop("content_sha256", None)
    return json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _check_timestamps_ordered(
    label: str, errors: list[str], **fields: str | None
) -> None:
    for name, value in fields.items():
        _check(
            isinstance(value, str) and TIMESTAMP_RE.match(value) is not None,
            f"{label}: {name} must be an RFC3339 UTC timestamp",
            errors,
        )
    ordered = [(name, value) for name, value in fields.items() if isinstance(value, str)]
    for earlier, later in zip(ordered, ordered[1:]):
        _check(
            earlier[1] <= later[1],
            f"{label}: temporal ordering violated ({earlier[0]} <= {later[0]})",
            errors,
        )


def _scan_secrets(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in SECRET_KEYS:
                errors.append(f"{path}/{key}: secret key name in persisted content")
            _scan_secrets(child, f"{path}/{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_secrets(child, f"{path}/{index}", errors)
    elif isinstance(value, str):
        if SECRET_TEXT.search(value):
            errors.append(f"{path}: secret-like text pattern in persisted content")


# ---------------------------------------------------------------------------
# validate-bundle
# ---------------------------------------------------------------------------

def validate_bundle(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    root = pathlib.Path(root)
    snapshot_paths = sorted((root / "snapshots").glob("data_snapshot.*.json"))
    case_paths = sorted((root / "cases").glob("case-*.json"))
    _check(bool(snapshot_paths), "no snapshots found", errors)
    _check(bool(case_paths), "no case cards found", errors)

    snapshots: dict[str, tuple[dict[str, Any], pathlib.Path]] = {}
    for path in snapshot_paths:
        snapshot = load_json(path)
        snapshot_id = str(snapshot.get("snapshot_id", path.name))
        label = f"snapshot {snapshot_id}"
        _check(snapshot.get("contract_type") == "data_snapshot", f"{label}: contract_type", errors)
        _check(snapshot.get("contract_version") == "6.0.0", f"{label}: contract_version", errors)
        _check(snapshot.get("status") == "frozen", f"{label}: status must be frozen", errors)
        temporal = snapshot.get("temporal", {})
        _check_timestamps_ordered(
            label, errors,
            event_time=temporal.get("event_time"),
            available_at=temporal.get("available_at"),
            retrieved_at=temporal.get("retrieved_at"),
        )
        if isinstance(temporal.get("as_of"), str) and isinstance(temporal.get("retrieved_at"), str):
            _check(
                temporal["as_of"] <= temporal["retrieved_at"],
                f"{label}: as_of <= retrieved_at",
                errors,
            )
        access = snapshot.get("access", {})
        _check(access.get("mode") == "public_read_only", f"{label}: access.mode", errors)
        _check(
            set(access.get("prohibited_scopes", [])) >= set(FORBIDDEN_DATA_SCOPES),
            f"{label}: prohibited_scopes must cover all forbidden data scopes",
            errors,
        )
        source = snapshot.get("source", {})
        _check(
            source.get("provider") in {"sec_edgar", "project_synthetic"},
            f"{label}: only public-domain or project-synthetic providers are allowed",
            errors,
        )
        _check(
            source.get("license", {}).get("redistributable") is True,
            f"{label}: source must be explicitly redistributable",
            errors,
        )
        record_ids = {str(record.get("record_id")) for record in snapshot.get("records", [])}
        _check(
            len(record_ids) == len(snapshot.get("records", [])),
            f"{label}: record ids must be unique",
            errors,
        )
        for record in snapshot.get("records", []):
            for scope in FORBIDDEN_DATA_SCOPES:
                _check(
                    scope not in record.get("payload", {}),
                    f"{label}: record {record.get('record_id')} payload carries forbidden scope '{scope}'",
                    errors,
                )
        if not snapshot.get("records"):
            _check(
                bool(snapshot.get("lineage", {}).get("parent_snapshot_ids")),
                f"{label}: empty records allowed only for derived missing-evidence snapshots",
                errors,
            )
        expected_hash = hashlib.sha256(canonical_bytes(snapshot)).hexdigest()
        integrity = snapshot.get("integrity", {})
        _check(
            integrity.get("content_sha256") == expected_hash,
            f"{label}: content_sha256 mismatch",
            errors,
        )
        _check(
            SHA256_RE.match(str(snapshot.get("lineage", {}).get("raw_response_sha256", ""))) is not None,
            f"{label}: lineage.raw_response_sha256",
            errors,
        )
        _scan_secrets(snapshot, label, errors)
        snapshots[snapshot_id] = (snapshot, path)

    families: dict[str, list[dict[str, Any]]] = {}
    for path in case_paths:
        case = load_json(path)
        case_id = str(case.get("case_id", path.name))
        label = f"case {case_id}"
        _check(case.get("contract_type") == "case_card", f"{label}: contract_type", errors)
        _check(case.get("contract_version") == "6.0.0", f"{label}: contract_version", errors)
        _check(case.get("status") == "frozen", f"{label}: status must be frozen", errors)
        _check(case.get("future_information_prohibited") is True, f"{label}: future_information_prohibited", errors)
        _check(
            case.get("source", {}).get("license", {}).get("redistributable") is True,
            f"{label}: source must be explicitly redistributable",
            errors,
        )
        task = case.get("task", {})
        _check(isinstance(task.get("method_id"), str), f"{label}: task.method_id", errors)
        _check(
            bool(task.get("permissions", {}).get("allowed_operations")),
            f"{label}: task.permissions.allowed_operations",
            errors,
        )
        _check(
            isinstance(task.get("expected_final_environment_state"), Mapping),
            f"{label}: task.expected_final_environment_state",
            errors,
        )

        temporal = case.get("temporal", {})
        _check_timestamps_ordered(
            label, errors,
            event_time=temporal.get("event_time"),
            as_of=temporal.get("as_of"),
        )
        if isinstance(temporal.get("available_at_cutoff"), str) and isinstance(temporal.get("as_of"), str):
            _check(
                temporal["available_at_cutoff"] <= temporal["as_of"],
                f"{label}: available_at_cutoff <= as_of",
                errors,
            )
        task_inputs = case.get("task", {}).get("inputs", {})
        if "available_at_cutoff" in task_inputs:
            _check(
                str(task_inputs["available_at_cutoff"]) <= str(temporal.get("available_at_cutoff", "")),
                f"{label}: task.inputs.available_at_cutoff must not exceed the card horizon",
                errors,
            )

        quality = case.get("quality", {})
        tier = quality.get("tier")
        _check(tier in {"Gold", "Silver"}, f"{label}: tier", errors)
        variant = case.get("variant", {})
        kind = variant.get("kind")
        _check(
            kind in {"normal", "single_factor_perturbation", "missing_or_anomalous"},
            f"{label}: variant.kind",
            errors,
        )
        if kind == "missing_or_anomalous":
            _check(tier == "Silver", f"{label}: missing_or_anomalous must be Silver", errors)
            _check(quality.get("ranking_eligible") is False, f"{label}: Silver must not be ranking-eligible", errors)
            _check(
                case.get("oracle", {}).get("expected_status") in {"abstain", "escalate", "reject_action"},
                f"{label}: missing_or_anomalous must expect a non-answer",
                errors,
            )
        if tier == "Gold":
            _check(quality.get("ranking_eligible") is True, f"{label}: Gold must be ranking-eligible", errors)
            _check(
                quality.get("independently_recomputable") is True,
                f"{label}: Gold must be independently recomputable",
                errors,
            )

        oracle = case.get("oracle", {})
        _check(
            oracle.get("expected_status") in ALLOWED_ACTIONS,
            f"{label}: oracle.expected_status",
            errors,
        )
        if oracle.get("expected_status") == "answer":
            _check(oracle.get("expected_value") is not None, f"{label}: answer requires expected_value", errors)
        else:
            _check(oracle.get("expected_value") is None, f"{label}: non-answer requires null expected_value", errors)
            _check(bool(oracle.get("reason_codes")), f"{label}: non-answer requires reason codes", errors)
        for field in ("implementation_sha256", "reference_implementation_sha256"):
            _check(
                SHA256_RE.match(str(oracle.get(field, ""))) is not None,
                f"{label}: oracle.{field}",
                errors,
            )

        for ref in case.get("evidence_refs", []):
            snapshot_id = str(ref.get("snapshot_id"))
            _check(snapshot_id in snapshots, f"{label}: unknown snapshot {snapshot_id}", errors)
            if snapshot_id not in snapshots:
                continue
            snapshot, snapshot_path = snapshots[snapshot_id]
            _check(
                ref.get("snapshot_sha256") == file_sha256(snapshot_path),
                f"{label}: snapshot_sha256 mismatch for {snapshot_id}",
                errors,
            )
            available = set(str(r.get("record_id")) for r in snapshot.get("records", []))
            for record_id in ref.get("record_ids", []):
                _check(
                    record_id in available,
                    f"{label}: referenced record {record_id} missing from {snapshot_id}",
                    errors,
                )
            snap_temporal = snapshot.get("temporal", {})
            if isinstance(snap_temporal.get("available_at"), str):
                _check(
                    snap_temporal["available_at"] <= str(temporal.get("available_at_cutoff", "")),
                    f"{label}: snapshot.available_at <= case.available_at_cutoff ({snapshot_id})",
                    errors,
                )
            if isinstance(snap_temporal.get("as_of"), str):
                _check(
                    snap_temporal["as_of"] <= str(temporal.get("as_of", "")),
                    f"{label}: snapshot.as_of <= case.as_of ({snapshot_id})",
                    errors,
                )

        expected_hash = hashlib.sha256(canonical_bytes(case)).hexdigest()
        _check(
            case.get("integrity", {}).get("content_sha256") == expected_hash,
            f"{label}: content_sha256 mismatch",
            errors,
        )
        _scan_secrets(case, label, errors)
        families.setdefault(str(variant.get("family_id")), []).append(case)

    for family_id, members in families.items():
        kinds = {str(member.get("variant", {}).get("kind")) for member in members}
        _check(
            kinds == {"normal", "single_factor_perturbation", "missing_or_anomalous"},
            f"family {family_id}: must register exactly the three variant kinds",
            errors,
        )
        normals = [m for m in members if m.get("variant", {}).get("kind") == "normal"]
        if len(normals) == 1:
            normal = normals[0]
            for member in members:
                if member is normal:
                    continue
                _check(
                    member.get("variant", {}).get("parent_case_id") == normal.get("case_id"),
                    f"family {family_id}: variant parent must be the normal case",
                    errors,
                )
                if member.get("variant", {}).get("kind") == "single_factor_perturbation":
                    changed = member.get("variant", {}).get("changed_factors")
                    _check(
                        isinstance(changed, list) and len(changed) == 1,
                        f"family {family_id}: single-factor variant must declare exactly one changed factor",
                        errors,
                    )
                    _check(
                        member.get("family_key") == normal.get("family_key"),
                        f"family {family_id}: family_key must be variant-invariant",
                        errors,
                    )
    registry_path = root / "contracts/frozen_input_registry.frozen.v6.json"
    _check(registry_path.is_file(), "frozen input registry missing", errors)
    if registry_path.is_file():
        registry = load_json(registry_path)
        actual = {
            (str(item.get("case_id")), str(item.get("variant_id"))): (
                str(item.get("path")), str(item.get("sha256"))
            )
            for item in registry.get("entries", [])
        }
        expected = {
            (str(card["case_id"]), str(card["variant"]["kind"])): (
                path.relative_to(root).as_posix(), file_sha256(path)
            )
            for path in case_paths
            for card in [load_json(path)]
        }
        _check(len(actual) == len(registry.get("entries", [])), "frozen input registry has duplicate case/variant keys", errors)
        _check(actual == expected, "frozen input registry does not exactly match case/variant/path/sha256 set", errors)
    return errors


# ---------------------------------------------------------------------------
# verify-manifest
# ---------------------------------------------------------------------------

def verify_manifest(root: pathlib.Path) -> list[str]:
    errors: list[str] = []
    root = pathlib.Path(root)
    manifest_path = root / "baseline_manifest.frozen.v6.json"
    _check(manifest_path.is_file(), "baseline_manifest.frozen.v6.json missing", errors)
    if errors:
        return errors
    manifest = load_json(manifest_path)
    entries = list(manifest.get("artifacts", []))
    seen: set[str] = set()
    for entry in entries:
        relative = str(entry.get("path"))
        expected = str(entry.get("sha256"))
        _check(relative not in seen, f"manifest: duplicate path {relative}", errors)
        seen.add(relative)
        path = root.parent.parent / relative
        _check(path.is_file(), f"manifest: missing artifact {relative}", errors)
        if path.is_file():
            _check(
                file_sha256(path) == expected,
                f"manifest: hash mismatch {relative}",
                errors,
            )
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        if "__pycache__" in path.parts:
            continue  # gitignored interpreter bytecode noise, not a baseline artifact
        relative = path.relative_to(root.parent.parent).as_posix()
        _check(relative in seen, f"manifest: unregistered file {relative}", errors)
    lines = "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries)
    bundle = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    _check(
        bundle == manifest.get("bundle_sha256"),
        "manifest: bundle_sha256 mismatch",
        errors,
    )
    return errors


# ---------------------------------------------------------------------------
# verify-trace
# ---------------------------------------------------------------------------

def load_frozen_input_registry(
    registry_path: pathlib.Path,
) -> tuple[dict[tuple[str, str], Any], list[str]]:
    """Preserve path+SHA commitments while binding them to actual case files."""

    from financial_agent_reliability.harness.run_trace_validator_v8 import (
        load_frozen_input_registry as load_v8_registry,
    )

    return load_v8_registry(pathlib.Path(registry_path))

def verify_trace(
    trace_path: pathlib.Path,
    *,
    registered_inputs: Mapping[tuple[str, str], Any] | None = None,
    registry_path: pathlib.Path | None = None,
    inference_config_path: pathlib.Path | None = None,
) -> list[str]:
    from financial_agent_reliability.harness.run_trace_validator_v8 import (
        verify_trace as verify_v8_trace,
    )

    return verify_v8_trace(
        pathlib.Path(trace_path),
        registered_inputs=registered_inputs,
        registry_path=(
            registry_path
            or pathlib.Path(__file__).resolve().parent
            / "contracts/frozen_input_registry.frozen.v6.json"
        ),
        inference_config_path=inference_config_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bundle = subparsers.add_parser("validate-bundle")
    bundle.add_argument("root", type=pathlib.Path)
    manifest = subparsers.add_parser("verify-manifest")
    manifest.add_argument("root", type=pathlib.Path)
    trace = subparsers.add_parser("verify-trace")
    trace.add_argument("trace", type=pathlib.Path)
    trace.add_argument("--registry", type=pathlib.Path)
    trace.add_argument("--inference-config", type=pathlib.Path)
    args = parser.parse_args(argv)

    if args.command == "validate-bundle":
        errors = validate_bundle(args.root)
    elif args.command == "verify-manifest":
        errors = verify_manifest(args.root)
    else:
        errors = verify_trace(args.trace, registry_path=args.registry, inference_config_path=args.inference_config)
    if errors:
        print(f"{args.command}: {len(errors)} violation(s)", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"{args.command}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
