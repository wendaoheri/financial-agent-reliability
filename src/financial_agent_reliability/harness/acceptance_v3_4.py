"""Freeze and verify the v3.4 Bailian-compatible split-submission contract."""

from __future__ import annotations

import argparse
import json
import pathlib

from contracts.run_trace_validator import build_bundle_sha256, file_sha256


ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = ROOT / "contracts" / "run_trace_harness_config.v3.4.json"
BASE_CONFIG = ROOT / "contracts" / "run_trace_harness_config.v3.3.json"
BASE_BUNDLE = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.3.json"
OUTPUT = ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.4.json"


def build_contract_manifest() -> dict:
    paths = [
        CONFIG,
        ROOT / "contracts" / "candidate_submission_wire_contract.v3.4.json",
        ROOT / "contracts" / "run_trace.schema.v3.4.json",
        ROOT / "docs" / "contracts" / "bailian-function-calling-v3.4.md",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "pi_runtime_v3_4.mjs",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "live_acceptance_v3_4.mjs",
        ROOT / "src" / "financial_agent_reliability" / "harness" / "acceptance_v3_4.py",
        ROOT / "tests" / "integration" / "acceptance_v3_4.test.mjs",
        ROOT / "tests" / "test_acceptance_v3_4.py",
    ]
    artifacts = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": file_sha256(path)}
        for path in paths
    ]
    base = json.loads(BASE_BUNDLE.read_text(encoding="utf-8"))
    return {
        "contract_type": "stage3_acceptance_contract_correction_bundle",
        "contract_version": "3.4.0",
        "status": "frozen_before_preflight",
        "base_bundle": {
            "path": BASE_BUNDLE.relative_to(ROOT).as_posix(),
            "sha256": file_sha256(BASE_BUNDLE),
            "bundle_sha256": base["bundle_sha256"],
        },
        "rationale": (
            "use Bailian Qwen thinking controls explicitly, remove the invalid forced-tool diagnostic, "
            "and replace the model-facing nullable union with split answer/non-answer functions"
        ),
        "preflight_execution": {
            "variants": ["auto_split_submission"],
            "maximum_model_units": 3,
            "acceptance_runs_authorized": False,
        },
        "artifacts": artifacts,
        "bundle_sha256": build_bundle_sha256([*base["artifacts"], *artifacts]),
        "candidate_visible_model_specific_changes": False,
        "provider_adapter_model_specific_controls": True,
        "retroactive_regrading": False,
    }


def verify_manifest(manifest: dict) -> list[str]:
    errors: list[str] = []
    if manifest.get("contract_version") != "3.4.0":
        errors.append("contract_version must be 3.4.0")
    if manifest.get("candidate_visible_model_specific_changes") is not False:
        errors.append("candidate_visible_model_specific_changes must be false")
    if manifest.get("retroactive_regrading") is not False:
        errors.append("retroactive_regrading must be false")
    if manifest.get("preflight_execution", {}).get("maximum_model_units") != 3:
        errors.append("maximum_model_units must be 3")
    for artifact in manifest.get("artifacts", []):
        path = ROOT / artifact["path"]
        if not path.is_file():
            errors.append(f"missing artifact: {artifact['path']}")
        elif file_sha256(path) != artifact["sha256"]:
            errors.append(f"hash mismatch: {artifact['path']}")
    base = json.loads(BASE_BUNDLE.read_text(encoding="utf-8"))
    expected = build_bundle_sha256([*base["artifacts"], *manifest.get("artifacts", [])])
    if manifest.get("bundle_sha256") != expected:
        errors.append("bundle_sha256 mismatch")
    return errors


def freeze_contracts() -> pathlib.Path:
    manifest = build_contract_manifest()
    errors = verify_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze-contracts", "verify-contracts"])
    args = parser.parse_args()
    if args.command == "freeze-contracts":
        result = freeze_contracts()
        print(json.dumps({"path": result.relative_to(ROOT).as_posix(), "sha256": file_sha256(result)}))
    else:
        manifest = json.loads(OUTPUT.read_text(encoding="utf-8"))
        errors = verify_manifest(manifest)
        print(json.dumps({"valid": not errors, "errors": errors}))
        raise SystemExit(0 if not errors else 2)
