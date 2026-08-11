"""Build the preregistered, deterministically randomized run matrix."""

from __future__ import annotations

import hashlib
import json
import pathlib
import random
from typing import Any

from contracts.run_trace_validator import build_run_id, file_sha256


BASE_SEED = 20260811
VARIANT_PROTOCOL_RELATIVE_PATH = pathlib.Path(
    "catalog/public/preregistration_variant_protocol.v2.json"
)
REQUIRED_VARIANT_PROTOCOL_VERSION = "2.0.0"
REQUIRED_EXECUTION_VARIANTS = (
    ("baseline", "normal"),
    ("single_factor_stress", "single_factor_perturbation"),
    ("missing_or_anomalous_diagnostic", "missing_or_anomalous"),
)
LEGACY_CONTROL_ID = "single_factor_control"
PUBLIC_MANIFEST_RELATIVE_PATH = pathlib.Path("catalog/public/v2/frozen_manifest.v2.json")
PUBLIC_CATALOG_RELATIVE_PATH = pathlib.Path("catalog/public/v2/seed_catalog.v2.json")
PUBLIC_COLLECTION_RELATIVE_PATH = pathlib.Path(
    "snapshots/public/v2/raw/collection_session.v2.json"
)
SYNTHETIC_MANIFEST_RELATIVE_PATH = pathlib.Path(
    "catalog/longbridge/synthetic_v2/frozen_manifest.v2.json"
)
SYNTHETIC_CATALOG_RELATIVE_PATH = pathlib.Path(
    "catalog/longbridge/synthetic_v2/seed_catalog.v2.json"
)
SYNTHETIC_POLICY_RELATIVE_PATH = pathlib.Path(
    "catalog/longbridge/synthetic_v2/stage3_input_policy.v2.json"
)
SYNTHETIC_SOURCE_SPEC_RELATIVE_PATH = pathlib.Path(
    "catalog/longbridge/synthetic_v2/source_spec.v2.json"
)

PUBLIC_V2_BUNDLE_SHA256 = "e3067d7a7cdb66694052e1a959a80120f7ccfbfa43b0525192b40acee942d62c"
PUBLIC_V2_MANIFEST_SHA256 = "42de93195e805391367b507c8a08ac4410551d882d095eba99878bbadc502334"
PUBLIC_V2_CATALOG_SHA256 = "7bb84ac20999ee10a5fd63d6b9c44f04829e9fac9759ed0497dbd890eee6eed3"
PUBLIC_V2_COLLECTION_SHA256 = "07eeb057b61da934ae4d462be786ab183a7cebb9be5213ae27f22d3fa8478f30"
PUBLIC_V2_PROTOCOL_SHA256 = "f7ea69077d4fc28e226d4b541859c234e6e9d74da1a7f1329701e934c325deeb"
REVOKED_PUBLIC_V1_BUNDLE_SHA256 = (
    "7a05f78739f6751778cac31cde031bf56721fa7429a68ce8aa6b1ff576de87a7"
)
SYNTHETIC_V2_CONTRACT_BUNDLE_SHA256 = (
    "29610ac66bc19cc40eb4eb1bf33ed479d17cb6cd9f232d94568ab55479d596c5"
)
SYNTHETIC_V2_STAGE3_BUNDLE_SHA256 = (
    "62511d582702c8019201c16f18e22a36bb0b8632d8c2ac39b3c9b8a8e49118e8"
)
SYNTHETIC_V2_MANIFEST_SHA256 = (
    "d49ee7f5d420e3c495587ba9ba051b57fe4502b48bbfeae536df52700cf41062"
)
SYNTHETIC_V2_POLICY_SHA256 = (
    "a0e287722842e66a58edaab227910818848a7ba7e4384d744d8c573ab757256c"
)
SYNTHETIC_V2_CATALOG_SHA256 = (
    "481a5b6055003513d67af03b9289503ac1a3a0ad168e403f3daa03419cabe42e"
)
SYNTHETIC_V2_SOURCE_SPEC_SHA256 = (
    "2b870e8fd69da0d172d94ebde04beb69fe4fa94ba78d32d4ef8eee92de381be6"
)
ISOLATED_LONGBRIDGE_V1_BUNDLE_SHA256 = (
    "d862b41b9e03a8e6d478e3515c1ce5c8613994527bd6bdd577082222dcc37c77"
)


def _load(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _bundle_commitments(root: pathlib.Path) -> list[dict[str, str]]:
    paths = [
        root / "contracts" / "run_trace_harness_config.v2.json",
        root / "contracts" / "model_manifest.frozen.v2.json",
        root / "contracts" / "model_manifest.schema.v2.json",
        root / "contracts" / "run_trace.schema.v2.json",
        root / "contracts" / "run_trace_validator_v2.py",
        root / "docs" / "contracts" / "harness-run-trace-v2.md",
        root / "preregistration" / "benchmark_preregistration.v1.json",
        root / VARIANT_PROTOCOL_RELATIVE_PATH,
        root / PUBLIC_MANIFEST_RELATIVE_PATH,
        root / PUBLIC_CATALOG_RELATIVE_PATH,
        root / PUBLIC_COLLECTION_RELATIVE_PATH,
        root / SYNTHETIC_MANIFEST_RELATIVE_PATH,
        root / SYNTHETIC_CATALOG_RELATIVE_PATH,
        root / SYNTHETIC_POLICY_RELATIVE_PATH,
        root / SYNTHETIC_SOURCE_SPEC_RELATIVE_PATH,
    ]
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in sorted(paths)
    ]


def _bundle_hash(commitments: list[dict[str, str]]) -> str:
    rendered = "".join(
        f"{item['path']}\0{item['sha256']}\n" for item in commitments
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _verify_frozen_manifest(
    root: pathlib.Path,
    relative_path: pathlib.Path,
    expected_manifest_sha256: str,
    expected_bundle_sha256: str,
) -> dict[str, Any]:
    manifest_path = root / relative_path
    if not manifest_path.is_file():
        raise ValueError(f"required input manifest is missing: {relative_path.as_posix()}")
    manifest = _load(manifest_path)
    if file_sha256(manifest_path) != expected_manifest_sha256:
        raise ValueError(f"input hash drift: {relative_path.as_posix()}")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"input manifest has no files: {relative_path.as_posix()}")
    root_resolved = root.resolve()
    commitment_lines: list[str] = []
    for entry in entries:
        listed_path = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(listed_path, str) or not isinstance(expected, str):
            raise ValueError(f"invalid input commitment: {relative_path.as_posix()}")
        artifact = (manifest_path.parent / listed_path).resolve()
        if not artifact.is_relative_to(root_resolved):
            raise ValueError(f"input commitment escapes project root: {listed_path}")
        if not artifact.is_file() or file_sha256(artifact) != expected:
            raise ValueError(f"input hash drift: {listed_path}")
        commitment_lines.append(f"{expected}  {listed_path}\n")
    actual_bundle = hashlib.sha256("".join(commitment_lines).encode("utf-8")).hexdigest()
    if (
        actual_bundle != expected_bundle_sha256
        or manifest.get("contract_bundle_sha256") != expected_bundle_sha256
    ):
        raise ValueError(f"input bundle hash drift: {relative_path.as_posix()}")
    return manifest


def _verify_selected_artifacts(
    root: pathlib.Path, entries: Any, expected_bundle_sha256: str
) -> None:
    if not isinstance(entries, list) or not entries:
        raise ValueError("synthetic Stage 3 input collection is empty")
    lines: list[str] = []
    for entry in entries:
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("invalid synthetic Stage 3 input commitment")
        if (
            not relative.startswith(
                ("cases/longbridge/synthetic_v2/", "snapshots/longbridge/synthetic_v2/")
            )
            or "/raw/" in relative
        ):
            raise ValueError("isolated Longbridge v1 input is prohibited")
        artifact = root / relative
        if not artifact.is_file() or file_sha256(artifact) != expected:
            raise ValueError(f"input hash drift: {relative}")
        lines.append(f"{expected}  {relative}\n")
    actual = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    if actual != expected_bundle_sha256:
        raise ValueError("synthetic Stage 3 input bundle hash drift")


def _case_inventory(root: pathlib.Path) -> dict[str, Any]:
    groups = (
        (
            "public_v2",
            root / "cases/public/v2",
            "case_card.FKW-*.json",
            {f"FKW-{index:02d}" for index in range(1, 16)},
        ),
        (
            "synthetic_workflow_v2",
            root / "cases/longbridge/synthetic_v2",
            "case_card.FTW-*.v2.json",
            {f"FTW-{index:02d}" for index in range(1, 16)},
        ),
    )
    expected_variants = {item[1] for item in REQUIRED_EXECUTION_VARIANTS}
    totals = {"families": 0, "cases": 0, "gold": 0, "silver": 0}
    for label, directory, pattern, expected_families in groups:
        cards = [_load(path) for path in sorted(directory.glob(pattern))]
        families: dict[str, set[str]] = {}
        for card in cards:
            family_id = card.get("variant", {}).get("family_id")
            kind = card.get("variant", {}).get("kind")
            tier = card.get("quality", {}).get("tier")
            if tier not in ("Gold", "Silver"):
                raise ValueError(f"{label} case has invalid quality tier")
            families.setdefault(str(family_id), set()).add(str(kind))
            totals[tier.lower()] += 1
        if set(families) != expected_families or any(
            variants != expected_variants for variants in families.values()
        ):
            raise ValueError(f"{label} family or variant allocation changed")
        totals["families"] += len(families)
        totals["cases"] += len(cards)
    if totals != {"families": 30, "cases": 90, "gold": 46, "silver": 44}:
        raise ValueError("frozen 30-family 46-Gold/44-Silver allocation changed")
    return {
        **totals,
        "track_weights": {
            "financial_knowledge_work": "50_percent",
            "financial_tool_workflow": "50_percent",
        },
    }


def _load_and_validate_input_bundles(root: pathlib.Path) -> dict[str, Any]:
    public_manifest_path = root / PUBLIC_MANIFEST_RELATIVE_PATH
    synthetic_policy_path = root / SYNTHETIC_POLICY_RELATIVE_PATH
    if not public_manifest_path.is_file() or not synthetic_policy_path.is_file():
        raise ValueError("public v2 and synthetic workflow v2 inputs are required")
    public_preview = _load(public_manifest_path)
    if public_preview.get("contract_bundle_sha256") == REVOKED_PUBLIC_V1_BUNDLE_SHA256:
        raise ValueError("revoked public v1 input is prohibited")
    synthetic_policy = _load(synthetic_policy_path)
    if (
        synthetic_policy.get("stage3_input_bundle_sha256")
        == ISOLATED_LONGBRIDGE_V1_BUNDLE_SHA256
    ):
        raise ValueError("isolated Longbridge v1 input is prohibited")

    public_manifest = _verify_frozen_manifest(
        root,
        PUBLIC_MANIFEST_RELATIVE_PATH,
        PUBLIC_V2_MANIFEST_SHA256,
        PUBLIC_V2_BUNDLE_SHA256,
    )
    synthetic_manifest = _verify_frozen_manifest(
        root,
        SYNTHETIC_MANIFEST_RELATIVE_PATH,
        SYNTHETIC_V2_MANIFEST_SHA256,
        SYNTHETIC_V2_CONTRACT_BUNDLE_SHA256,
    )
    if (
        public_manifest.get("version") != "2.0.0"
        or public_manifest.get("status") != "frozen_supersedes_v1"
        or public_manifest.get("superseded_bundle_sha256")
        != REVOKED_PUBLIC_V1_BUNDLE_SHA256
    ):
        raise ValueError("required public v2 bundle selection is invalid")
    if (
        synthetic_manifest.get("version") != "2.0.0"
        or synthetic_manifest.get("status") != "frozen_pending_independent_audit"
    ):
        raise ValueError("required synthetic workflow v2 bundle selection is invalid")

    expected_file_hashes = {
        PUBLIC_CATALOG_RELATIVE_PATH: PUBLIC_V2_CATALOG_SHA256,
        PUBLIC_COLLECTION_RELATIVE_PATH: PUBLIC_V2_COLLECTION_SHA256,
        VARIANT_PROTOCOL_RELATIVE_PATH: PUBLIC_V2_PROTOCOL_SHA256,
        SYNTHETIC_CATALOG_RELATIVE_PATH: SYNTHETIC_V2_CATALOG_SHA256,
        SYNTHETIC_POLICY_RELATIVE_PATH: SYNTHETIC_V2_POLICY_SHA256,
        SYNTHETIC_SOURCE_SPEC_RELATIVE_PATH: SYNTHETIC_V2_SOURCE_SPEC_SHA256,
    }
    for relative, expected in expected_file_hashes.items():
        if file_sha256(root / relative) != expected:
            raise ValueError(f"input hash drift: {relative.as_posix()}")

    public_catalog = _load(root / PUBLIC_CATALOG_RELATIVE_PATH)
    public_acceptance = _load(root / "catalog/public/v2/acceptance_report.v2.json")
    if (
        public_catalog.get("release", {}).get("candidate_runs_allowed") is not False
        or public_catalog.get("supersedes", {}).get("status") != "revoked"
        or public_catalog.get("supersedes", {}).get("bundle_sha256")
        != REVOKED_PUBLIC_V1_BUNDLE_SHA256
        or public_catalog.get("collection", {}).get("session_sha256")
        != PUBLIC_V2_COLLECTION_SHA256
        or public_acceptance.get("release", {}).get("candidate_runs_allowed") is not False
    ):
        raise ValueError("public v2 release or revocation gate changed")

    synthetic_catalog = _load(root / SYNTHETIC_CATALOG_RELATIVE_PATH)
    if (
        synthetic_policy.get("version") != "2.0.0"
        or synthetic_policy.get("status") != "frozen_pending_independent_audit"
        or synthetic_policy.get("candidate_runs_allowed") is not False
        or synthetic_policy.get("stage3_input_bundle_sha256")
        != SYNTHETIC_V2_STAGE3_BUNDLE_SHA256
        or synthetic_catalog.get("release", {}).get("candidate_runs_allowed") is not False
        or synthetic_catalog.get("supersedes", {}).get("status")
        != "retired_and_isolated_not_stage3_eligible"
        or synthetic_catalog.get("supersedes", {}).get("contract_bundle_sha256")
        != ISOLATED_LONGBRIDGE_V1_BUNDLE_SHA256
    ):
        raise ValueError("synthetic workflow v2 release or isolation gate changed")
    _verify_selected_artifacts(
        root,
        synthetic_policy.get("included_artifacts"),
        SYNTHETIC_V2_STAGE3_BUNDLE_SHA256,
    )
    allocation = _case_inventory(root)
    return {
        "public_v2": {
            "contract_bundle_sha256": PUBLIC_V2_BUNDLE_SHA256,
            "manifest": {
                "path": PUBLIC_MANIFEST_RELATIVE_PATH.as_posix(),
                "sha256": PUBLIC_V2_MANIFEST_SHA256,
            },
            "collection": {
                "path": PUBLIC_COLLECTION_RELATIVE_PATH.as_posix(),
                "sha256": PUBLIC_V2_COLLECTION_SHA256,
            },
            "catalog": {
                "path": PUBLIC_CATALOG_RELATIVE_PATH.as_posix(),
                "sha256": PUBLIC_V2_CATALOG_SHA256,
            },
            "protocol": {
                "path": VARIANT_PROTOCOL_RELATIVE_PATH.as_posix(),
                "sha256": PUBLIC_V2_PROTOCOL_SHA256,
            },
            "revoked_v1_bundle_sha256": REVOKED_PUBLIC_V1_BUNDLE_SHA256,
        },
        "synthetic_workflow_v2": {
            "contract_bundle_sha256": SYNTHETIC_V2_CONTRACT_BUNDLE_SHA256,
            "stage3_input_bundle_sha256": SYNTHETIC_V2_STAGE3_BUNDLE_SHA256,
            "manifest": {
                "path": SYNTHETIC_MANIFEST_RELATIVE_PATH.as_posix(),
                "sha256": SYNTHETIC_V2_MANIFEST_SHA256,
            },
            "collection_policy": {
                "path": SYNTHETIC_POLICY_RELATIVE_PATH.as_posix(),
                "sha256": SYNTHETIC_V2_POLICY_SHA256,
            },
            "catalog": {
                "path": SYNTHETIC_CATALOG_RELATIVE_PATH.as_posix(),
                "sha256": SYNTHETIC_V2_CATALOG_SHA256,
            },
            "source_protocol": {
                "path": SYNTHETIC_SOURCE_SPEC_RELATIVE_PATH.as_posix(),
                "sha256": SYNTHETIC_V2_SOURCE_SPEC_SHA256,
            },
            "isolated_v1_bundle_sha256": ISOLATED_LONGBRIDGE_V1_BUNDLE_SHA256,
        },
        "frozen_allocation": allocation,
    }


def _load_and_validate_variant_protocol(
    root: pathlib.Path, prereg: dict[str, Any]
) -> tuple[dict[str, Any], pathlib.Path]:
    protocol_path = root / VARIANT_PROTOCOL_RELATIVE_PATH
    if not protocol_path.is_file():
        raise ValueError(
            f"variant protocol v2 is required: {VARIANT_PROTOCOL_RELATIVE_PATH.as_posix()}"
        )
    protocol = _load(protocol_path)
    if protocol.get("version") != REQUIRED_VARIANT_PROTOCOL_VERSION:
        raise ValueError(
            f"required variant protocol version {REQUIRED_VARIANT_PROTOCOL_VERSION}"
        )
    if protocol.get("status") != "frozen_before_candidate_runs":
        raise ValueError("variant protocol must be frozen before candidate runs")

    base = protocol.get("base_preregistration", {})
    if (
        base.get("path") != "preregistration/benchmark_preregistration.v1.json"
        or base.get("version") != prereg.get("version")
        or base.get("preserved_unchanged") is not True
    ):
        raise ValueError("variant protocol base preregistration does not match")

    canonical = protocol.get("canonical_execution_variants")
    if not isinstance(canonical, list):
        raise ValueError("canonical execution variants are required")
    execution_ids = [item.get("execution_id") for item in canonical]
    if LEGACY_CONTROL_ID in execution_ids:
        raise ValueError(f"legacy variant id {LEGACY_CONTROL_ID} is prohibited")
    actual_pairs = tuple(
        (item.get("execution_id"), item.get("case_card_kind")) for item in canonical
    )
    if actual_pairs != REQUIRED_EXECUTION_VARIANTS:
        raise ValueError("canonical execution variants do not match protocol v2")

    harness_contract = protocol.get("harness_contract", {})
    required_ids = harness_contract.get("required_execution_ids")
    if LEGACY_CONTROL_ID in (required_ids or []):
        raise ValueError(f"legacy variant id {LEGACY_CONTROL_ID} is prohibited")
    if (
        harness_contract.get("required_protocol_version")
        != REQUIRED_VARIANT_PROTOCOL_VERSION
        or required_ids != [item[0] for item in REQUIRED_EXECUTION_VARIANTS]
        or harness_contract.get("reject_legacy_single_factor_control") is not True
        or harness_contract.get("case_count_per_family") != 3
        or harness_contract.get("family_count") != 30
        or harness_contract.get("total_case_count") != 90
        or harness_contract.get("missing_or_anomalous_must_be_silver") is not True
        or harness_contract.get("missing_or_anomalous_main_ranking_eligible") is not False
    ):
        raise ValueError("variant protocol harness contract is invalid")

    legacy = protocol.get("legacy_v1_crosswalk")
    if not isinstance(legacy, list):
        raise ValueError("legacy crosswalk is required")
    legacy_control = next(
        (item for item in legacy if item.get("legacy_id") == LEGACY_CONTROL_ID), None
    )
    if (
        legacy_control is None
        or legacy_control.get("case_card_kind") is not None
        or legacy_control.get("mapping_status") != "retired_unmapped"
    ):
        raise ValueError(f"legacy variant id {LEGACY_CONTROL_ID} must remain retired")
    assertions = protocol.get("non_equivalence_assertions")
    if not isinstance(assertions, list) or not any(
        item.get("left") == LEGACY_CONTROL_ID
        and item.get("right") == "missing_or_anomalous"
        and item.get("equivalent") is False
        and item.get("silent_mapping_prohibited") is True
        for item in assertions
    ):
        raise ValueError("legacy control non-equivalence assertion is required")

    # The Stage 1 file is intentionally preserved as historical input. Its
    # legacy ids are validated here but never materialized into executable rows.
    if prereg.get("variant_ids") != [
        "baseline",
        "single_factor_stress",
        LEGACY_CONTROL_ID,
    ]:
        raise ValueError("base preregistration legacy variant set changed")
    return protocol, protocol_path


def build_run_manifest(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root)
    config_path = root / "contracts" / "run_trace_harness_config.v2.json"
    prereg_path = root / "preregistration" / "benchmark_preregistration.v1.json"
    config = _load(config_path)
    prereg = _load(prereg_path)
    protocol, protocol_path = _load_and_validate_variant_protocol(root, prereg)
    selected_input_bundles = _load_and_validate_input_bundles(root)
    models = list(config["candidate_model_ids"])
    registered = list(prereg["candidate_models"])
    # PER-24 froze abstract candidate slots before PER-25 froze the executable
    # Bailian identities. Preserve the registered matrix cardinality, but take
    # executable IDs only from the later exact identity contract.
    if len(registered) != len(models) or len(set(registered)) != len(models):
        raise ValueError("preregistration candidate-slot cardinality changed")
    config_hash = file_sha256(config_path)
    protocol_hash = file_sha256(protocol_path)
    bundle_commitments = _bundle_commitments(root)
    bundle_hash = _bundle_hash(bundle_commitments)
    execution_ids = [item[0] for item in REQUIRED_EXECUTION_VARIANTS]
    blocks: list[tuple[str, str, int]] = [
        (str(family["id"]), str(variant), repeat)
        for family in prereg["case_families"]
        for variant in execution_ids
        for repeat in range(1, int(prereg["repeats_per_cell"]) + 1)
    ]
    block_random = random.Random(BASE_SEED)
    block_random.shuffle(blocks)
    runs: list[dict[str, Any]] = []
    for block_index, (family_id, variant_id, repeat) in enumerate(blocks):
        ordered_models = list(models)
        model_random = random.Random(BASE_SEED + block_index * 7919)
        model_random.shuffle(ordered_models)
        if ordered_models == models:
            ordered_models = ordered_models[1:] + ordered_models[:1]
        for order_in_block, model_id in enumerate(ordered_models):
            seed_material = f"{BASE_SEED}:{family_id}:{variant_id}:{repeat}:{model_id}"
            seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:8], 16)
            identity = {
                "benchmark_id": "financial-agent-reliability-v1",
                "case_id": family_id,
                "variant_id": variant_id,
                "requested_model_id": model_id,
                "repeat": repeat,
                "seed": seed,
                "harness_config_sha256": config_hash,
                "immutable_bundle_sha256": bundle_hash,
            }
            runs.append(
                {
                    "sequence": len(runs) + 1,
                    "block": block_index + 1,
                    "order_in_block": order_in_block + 1,
                    "family_id": family_id,
                    "variant_id": variant_id,
                    "model_id": model_id,
                    "repeat": repeat,
                    "seed": seed,
                    "run_id": build_run_id(identity),
                    "run_identity": identity,
                }
            )
    if len(runs) != 810 or len({row["run_id"] for row in runs}) != 810:
        raise ValueError("run matrix must contain exactly 810 unique rows")
    manifest_core = {
        "contract_type": "benchmark_run_manifest",
        "contract_version": "4.0.0",
        "randomization": "family_variant_repeat_blocks_seeded_then_model_order_seeded",
        "randomization_seed": BASE_SEED,
        "config_sha256": config_hash,
        "immutable_bundle_sha256": bundle_hash,
        "immutable_bundle_artifacts": bundle_commitments,
        "variant_protocol": {
            "path": VARIANT_PROTOCOL_RELATIVE_PATH.as_posix(),
            "version": protocol["version"],
            "sha256": protocol_hash,
        },
        "selected_input_bundles": selected_input_bundles,
        "full_paid_matrix_runs_allowed": False,
        "runs": runs,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest_core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return dict(manifest_core, manifest_sha256=manifest_hash)
