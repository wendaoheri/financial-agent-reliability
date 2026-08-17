"""Generate deterministic PER-329 baseline-v4 audit summaries."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

from financial_agent_reliability.graders import baseline_v4
from financial_agent_reliability.harness.secret_scan import (
    scan_persisted_value_for_secrets,
)


ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
BASELINE = ROOT / "baseline/v4"


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle_hash(entries: list[dict]) -> str:
    lines = "".join(f"{item['sha256']}  {item['path']}\n" for item in entries)
    return hashlib.sha256(lines.encode()).hexdigest()


def write(name: str, value: dict) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


manifest = load(BASELINE / "baseline_manifest.frozen.v4.json")
grader = load(BASELINE / "contracts/grader_contract.frozen.v4.json")
captures = load(BASELINE / "build/capture_manifest.v4.json")
policy = load(BASELINE / "grader/grader_policy.v4.json")

manifest_mismatches = [
    item["path"]
    for item in manifest["artifacts"]
    if sha256(ROOT / item["path"]) != item["sha256"]
]
grader_mismatches = [
    item["path"]
    for item in grader["files"]
    if sha256(ROOT / item["path"]) != item["sha256"]
]
write(
    "contract-hashes-and-drift.json",
    {
        "status": "pass" if not manifest_mismatches else "fail",
        "hashes": {
            "acceptance_criteria_v2": sha256(ROOT / "docs/contracts/acceptance-criteria-v2.md"),
            "acceptance_criteria_v3": sha256(ROOT / "docs/contracts/acceptance-criteria-v3.md"),
            "acceptance_criteria_v4": sha256(ROOT / "docs/contracts/acceptance-criteria-v4.md"),
            "baseline_v2_manifest": sha256(ROOT / "baseline/v2/baseline_manifest.frozen.v2.json"),
            "baseline_v3_manifest": sha256(ROOT / "baseline/v3/baseline_manifest.frozen.v3.json"),
            "baseline_v4_manifest": sha256(BASELINE / "baseline_manifest.frozen.v4.json"),
            "harness_contract": sha256(ROOT / "configs/harness_contract.v1.json"),
            "inference_config": sha256(ROOT / "configs/inference.json"),
        },
        "v4_artifact_count": len(manifest["artifacts"]),
        "v4_artifact_hash_mismatches": manifest_mismatches,
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
        "captures": [
            {
                "capture_id": item["capture_id"],
                "source_provider": item["source_provider"],
                "redistributable": item["redistributable"],
            }
            for item in captures["captures"]
        ],
        "declared_invariants": policy["critical_success"]["allowed_invariants"],
        "executable_invariants": list(baseline_v4.SUPPORTED_INVARIANTS),
    },
)

secret_files = sorted(
    path
    for base in (BASELINE, ROOT / "configs")
    for path in base.rglob("*")
    if path.is_file() and "__pycache__" not in path.parts
)
secret_findings = {}
for path in secret_files:
    value = load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
    findings = scan_persisted_value_for_secrets(value)
    if findings:
        secret_findings[path.relative_to(ROOT).as_posix()] = findings
write(
    "secret-scan-report.json",
    {
        "status": "pass" if not secret_findings else "fail",
        "files_scanned": len(secret_files),
        "persisted_secret_findings": secret_findings,
    },
)

tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
scan_prefixes = ("baseline/v4/", "configs/", "src/", "tests/")
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
expected = {
    "tests/integration/test_harness_runtime.py",
    "tests/test_baseline_v2.py",
    "tests/test_inference_config.py",
}
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

assert not manifest_mismatches
assert manifest["bundle_sha256"] == bundle_hash(manifest["artifacts"])
assert not grader_mismatches
assert grader["contract_bundle_sha256"] == bundle_hash(grader["files"])
assert captures["license_gate"]["all_artifacts_redistributable"] is True
assert captures["license_gate"]["licensed_market_data_included"] is False
assert policy["critical_success"]["allowed_invariants"] == list(baseline_v4.SUPPORTED_INVARIANTS)
assert not secret_findings
assert not unexpected
