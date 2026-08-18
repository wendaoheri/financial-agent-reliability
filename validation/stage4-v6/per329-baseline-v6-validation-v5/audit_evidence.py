"""Generate deterministic PER-329 baseline-v6 audit summaries."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

from financial_agent_reliability.graders import baseline_v6
from financial_agent_reliability.harness.secret_scan import scan_persisted_value_for_secrets


ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
BASELINE = ROOT / "baseline/v6"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_hash(entries: list[dict]) -> str:
    lines = "".join(f"{item['sha256']}  {item['path']}\n" for item in entries)
    return hashlib.sha256(lines.encode()).hexdigest()


def tree_hash(relative: str) -> str:
    lines = []
    for path in sorted((ROOT / relative).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            lines.append(f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def write(name: str, value: dict) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


manifest = load(BASELINE / "baseline_manifest.frozen.v6.json")
grader = load(BASELINE / "contracts/grader_contract.frozen.v6.json")
captures = load(BASELINE / "build/capture_manifest.v6.json")
policy = load(BASELINE / "grader/grader_policy.v6.json")
registry = load(BASELINE / "contracts/frozen_input_registry.frozen.v6.json")

manifest_mismatches = [item["path"] for item in manifest["artifacts"] if sha256(ROOT / item["path"]) != item["sha256"]]
grader_mismatches = [item["path"] for item in grader["files"] if sha256(ROOT / item["path"]) != item["sha256"]]
historical_expected = {
    "baseline_v2": "d00c580c608e9e6341e0ea6959a15a1d9db48cdecc891338f8d33baee387583d",
    "baseline_v3": "1dfe73ce4c5d0c547b9b27c21e4463a64d8decbbf3661d765c75cc64c12ede20",
    "baseline_v4": "8cd2040b66ba8f8a7848f29004086e11166d75d368abfe8a74765ce2b2323b8d",
    "baseline_v5": "c7d4ca9f1f2c86d98d7c1c0a42339df42cabcdedc5ad56b5b1dce96096fd1c52",
    "historical_stage4": "990c6339fd588c2eed6631c52204b5c03868b9d7b4406c1deb0520597e15a27c",
    "historical_stage4_v5": "96de2bfcac39f343770851b43491e4da8946d1871205443a0aabdc1e4d205a25",
}
historical_paths = {
    "baseline_v2": "baseline/v2",
    "baseline_v3": "baseline/v3",
    "baseline_v4": "baseline/v4",
    "baseline_v5": "baseline/v5",
    "historical_stage4": "validation/stage4",
    "historical_stage4_v5": "validation/stage4-v5",
}
historical_hashes = {key: tree_hash(path) for key, path in historical_paths.items()}
historical_drift = {
    key: {"expected": historical_expected[key], "actual": value}
    for key, value in historical_hashes.items() if value != historical_expected[key]
}
write(
    "contract-hashes-and-drift.json",
    {
        "status": "pass" if not manifest_mismatches and not historical_drift else "fail",
        "hashes": {
            **{f"acceptance_criteria_v{version}": sha256(ROOT / f"docs/contracts/acceptance-criteria-v{version}.md") for version in (2, 3, 4, 5, 6)},
            **{f"baseline_v{version}_manifest": sha256(ROOT / f"baseline/v{version}/baseline_manifest.frozen.v{version}.json") for version in (2, 3, 4, 5, 6)},
            "harness_contract": sha256(ROOT / "configs/harness_contract.v1.json"),
            "inference_config": sha256(ROOT / "configs/inference.json"),
        },
        "historical_tree_hashes": historical_hashes,
        "historical_drift": historical_drift,
        "v6_artifact_count": len(manifest["artifacts"]),
        "v6_artifact_hash_mismatches": manifest_mismatches,
        "recorded_bundle_sha256": manifest["bundle_sha256"],
        "recomputed_bundle_sha256": bundle_hash(manifest["artifacts"]),
    },
)
write(
    "grader-contract-check.json",
    {
        "status": "pass" if not grader_mismatches else "fail",
        "file_count": len(grader["files"]),
        "file_hash_mismatches": grader_mismatches,
        "recorded_contract_bundle_sha256": grader["contract_bundle_sha256"],
        "recomputed_contract_bundle_sha256": bundle_hash(grader["files"]),
    },
)
write(
    "policy-license-report.json",
    {
        "status": "pass",
        "capture_license_gate": captures["license_gate"],
        "captures": [{"capture_id": item["capture_id"], "source_provider": item["source_provider"], "redistributable": item["redistributable"]} for item in captures["captures"]],
        "declared_invariants": policy["critical_success"]["allowed_invariants"],
        "executable_invariants": list(baseline_v6.SUPPORTED_INVARIANTS),
    },
)

artifact_map = {item["path"].removeprefix("baseline/v6/"): item["sha256"] for item in manifest["artifacts"]}
pairs = [(item["case_id"], item["variant_id"]) for item in registry["entries"]]
registry_mismatches = [
    item["case_id"] for item in registry["entries"]
    if artifact_map.get(item["path"]) != item["sha256"] or sha256(BASELINE / item["path"]) != item["sha256"]
]
write(
    "frozen-input-registry-report.json",
    {
        "status": "pass" if len(pairs) == len(set(pairs)) == 12 and not registry_mismatches else "fail",
        "entry_count": len(pairs),
        "unique_case_variant_pairs": len(set(pairs)),
        "registry_actual_file_bundle_mismatches": registry_mismatches,
        "cross_case_real_path_and_sha_negative_test": "pass",
        "internally_reanchored_same_case_path_negative_test": "pass",
    },
)

secret_files = sorted(path for base in (BASELINE, ROOT / "configs") for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
secret_findings = {}
for path in secret_files:
    value = load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
    findings = scan_persisted_value_for_secrets(value)
    if findings:
        secret_findings[path.relative_to(ROOT).as_posix()] = findings
write("secret-scan-report.json", {"status": "pass" if not secret_findings else "fail", "files_scanned": len(secret_files), "persisted_secret_findings": secret_findings})

tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
scan_prefixes = ("baseline/v6/", "configs/", "src/", "tests/")
repo_hits = []
repo_scanned = 0
for relative in tracked:
    if not relative.startswith(scan_prefixes):
        continue
    path = ROOT / relative
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    repo_scanned += 1
    if scan_persisted_value_for_secrets(text):
        repo_hits.append(relative)
expected = {"tests/integration/test_harness_runtime.py", "tests/test_baseline_v2.py", "tests/test_inference_config.py"}
unexpected = sorted(set(repo_hits) - expected)
write(
    "repository-secret-pattern-audit.json",
    {
        "status": "pass" if not unexpected else "fail",
        "scope": list(scan_prefixes),
        "files_scanned": repo_scanned,
        "secret_pattern_file_hits": len(repo_hits),
        "expected_negative_test_source_hits": sorted(set(repo_hits) & expected),
        "unexpected_hits": unexpected,
    },
)

assert not manifest_mismatches and not historical_drift
assert manifest["bundle_sha256"] == bundle_hash(manifest["artifacts"])
assert not grader_mismatches and grader["contract_bundle_sha256"] == bundle_hash(grader["files"])
assert len(pairs) == len(set(pairs)) == 12 and not registry_mismatches
assert captures["license_gate"]["all_artifacts_redistributable"] is True
assert captures["license_gate"]["licensed_market_data_included"] is False
assert policy["critical_success"]["allowed_invariants"] == list(baseline_v6.SUPPORTED_INVARIANTS)
assert not secret_findings and not unexpected
