"""Freeze the PER-79 v3.11.1 single-unit coverage evidence bundle manifest.

Deterministic, read-only over the completed coverage run directory; writes
``bundle.manifest.json`` into it using the same content-hash scheme as the
v3.9/v3.10/v3.11 rounds (sorted relative path -> sha256 artifact list;
bundle_sha256 = canonical content hash of that list). Excludes the manifest
itself and any ``*.partial`` leftovers. The seq 268 invalidation forensics are
referenced by their frozen hashes (they live in the v3.11 round directory and
are preserved, never moved, modified, or replaced).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from contracts.run_trace_validator_v3_8 import content_sha256, file_sha256

ROOT = pathlib.Path(__file__).resolve().parents[1]
V311_RUN_DIR = ROOT / "runs/stage3/acceptance-20260813-v3.11"

EXPECTED = {
    "plan_sha256": "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b",
    "plan_core_sha256": "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b",
    "config_sha256": "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e",
    "contract_bundle_sha256": "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d",
    "gate_report_sha256": "0c863c1213c62724bec0e016f2bb36d955bbd0a884dd5e9df55413f062b37b58",
    "coverage_run_id": "run_0e1e8f4400e16f22f6581e0bb0d9c54d",
    "invalidated_run_id": "run_c0f58d3c0d9227585058c4e4872a468b",
}
FORENSICS = {
    "invalidated_runs_path": "runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json",
    "invalidated_runs_file_sha256": "7fd165fa26f83ea925a782c77c81b235fb1665496fb457df6d665547ef8547a7",
    "invalidation_report_sha256": "3a5189e7ffb4ad093b6508fcb6319bc68248a21de9a70c019685db5849868bda",
    "pending_invalidations_path": "runs/stage3/acceptance-20260813-v3.11/pending-invalidations.json",
    "pending_invalidations_file_sha256": "61c7baecab626a5559702bd8e77a4c2f700dbbd6cdff17102a30fe83fb147946",
    "checkpoint_residue_path": "runs/stage3/acceptance-20260813-v3.11/checkpoints/run_c0f58d3c0d9227585058c4e4872a468b.jsonl",
    "checkpoint_residue_sha256": "68f0e73854ae6341fe829037eaf2ff1a2b560dcbd2b9cfbca8f302e4d28c85b6",
}
AUTHORIZATION_BASIS = {
    "owner_comment_id": "6fdca2fb-0f86-473c-9269-5c71e7a470b3",
    "parent_issue_id": "45640133-7162-4832-aef6-94d0a3900bd6",
    "paid_authorization_scope": "standing_all_paid_runs_owner_2026_08_12",
    "gate_review_issue": "PER-78",
    "gate_review_report_sha256": EXPECTED["gate_report_sha256"],
    "dispatch_issue": "PER-79",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).resolve()

    errors: list[str] = []
    plan = json.loads((run_dir / "stage3_acceptance_plan.v3.11.1.json").read_text(encoding="utf-8"))
    if plan.get("plan_sha256") != EXPECTED["plan_sha256"]:
        errors.append("frozen coverage plan copy drifted")
    preflight = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
    authorization = json.loads((run_dir / "authorization.run.json").read_text(encoding="utf-8"))
    auth_stripped = {k: v for k, v in authorization.items() if k != "authorization_sha256"}
    if authorization.get("authorization_sha256") != content_sha256(auth_stripped):
        errors.append("authorization self-hash no longer verifies")
    if authorization.get("execution_gate", {}).get("delivery_owner_dispatch_status") != "authorized":
        errors.append("authorization gate not dispatched-authorized; refusing to freeze")

    # seq 268 forensics must still verify in the v3.11 round directory (referenced, not moved).
    forensics_ok = (
        file_sha256(V311_RUN_DIR / "invalidated-runs.json") == FORENSICS["invalidated_runs_file_sha256"]
        and file_sha256(V311_RUN_DIR / "pending-invalidations.json") == FORENSICS["pending_invalidations_file_sha256"]
        and file_sha256(V311_RUN_DIR / "checkpoints" / f"{EXPECTED['invalidated_run_id']}.jsonl") == FORENSICS["checkpoint_residue_sha256"]
    )
    if not forensics_ok:
        errors.append("seq 268 invalidation forensics no longer verify in the v3.11 round directory")

    artifacts = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "bundle.manifest.json" or path.suffix == ".partial":
            continue
        artifacts.append({"path": path.relative_to(run_dir).as_posix(), "sha256": file_sha256(path)})
    manifest = {
        "contract_type": "stage3_financial_acceptance_evidence_bundle",
        "contract_version": "3.11.0",
        "plan_kind": "single_unit_coverage",
        "status": "frozen",
        "plan_sha256": EXPECTED["plan_sha256"],
        "plan_core_sha256": EXPECTED["plan_core_sha256"],
        "config_sha256": EXPECTED["config_sha256"],
        "contract_bundle_sha256": EXPECTED["contract_bundle_sha256"],
        "preflight_sha256": preflight.get("preflight_sha256"),
        "preflight_carry_over_source_sha256": preflight.get("carry_over", {}).get("source_preflight_sha256"),
        "authorization_sha256": authorization.get("authorization_sha256"),
        "gate_review": {"issue": "PER-78", "report_sha256": EXPECTED["gate_report_sha256"], "result": "pass"},
        "authorization_basis": AUTHORIZATION_BASIS,
        "coverage_run_id": EXPECTED["coverage_run_id"],
        "coverage_replaces_or_reexecutes_invalidation": False,
        "seq268_invalidation_forensics_reference": FORENSICS,
        "invalidated_run_ids": [EXPECTED["invalidated_run_id"]],
        "invalidated_count": 1,
        "artifacts": artifacts,
        "bundle_sha256": content_sha256(artifacts),
    }
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False))
        return 2
    output = run_dir / "bundle.manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": True, "artifacts": len(artifacts), "bundle_sha256": manifest["bundle_sha256"], "manifest": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
