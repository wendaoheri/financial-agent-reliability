"""Freeze the PER-59 v3.10 first-round evidence bundle manifest.

Deterministic, read-only over the completed run directory; writes
``bundle.manifest.json`` into it using the same content-hash scheme as the
v3.9 round (sorted relative path -> sha256 artifact list; bundle_sha256 =
canonical content hash of that list). Excludes the manifest itself and any
``*.partial`` leftovers.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from contracts.run_trace_validator_v3_8 import content_sha256, file_sha256

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED = {
    "plan_sha256": "009b1ea126b462bf873a555dbc7ced91b900d88728d94e5d208ee3a95c3ed4ec",
    "config_sha256": "fdac619573fbe7449e5db32d3a643f394f705c5e73b18ea8446f7aebcf4b511f",
    "contract_bundle_sha256": "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180",
}
AUTHORIZATION_BASIS = {
    "owner_comment_id": "6fdca2fb-0f86-473c-9269-5c71e7a470b3",
    "parent_issue_id": "45640133-7162-4832-aef6-94d0a3900bd6",
    "paid_authorization_scope": "standing_all_paid_runs_owner_2026_08_12",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).resolve()

    errors: list[str] = []
    for name, key in [("stage3_acceptance_plan.v3.10.json", "plan_sha256")]:
        plan = json.loads((run_dir / name).read_text(encoding="utf-8"))
        if plan.get("plan_sha256") != EXPECTED[key]:
            errors.append(f"frozen plan copy drifted:{name}")
    preflight = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
    invalidation_report = run_dir / "invalidated-runs.json"
    invalidated_ids: list[str] = []
    if invalidation_report.is_file():
        invalidated_ids = sorted(entry["run_id"] for entry in json.loads(invalidation_report.read_text(encoding="utf-8")).get("entries", []))

    artifacts = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "bundle.manifest.json" or path.suffix == ".partial":
            continue
        artifacts.append({"path": path.relative_to(run_dir).as_posix(), "sha256": file_sha256(path)})
    manifest = {
        "contract_type": "stage3_financial_acceptance_evidence_bundle",
        "contract_version": "3.10.0",
        "status": "frozen",
        "plan_sha256": EXPECTED["plan_sha256"],
        "config_sha256": EXPECTED["config_sha256"],
        "contract_bundle_sha256": EXPECTED["contract_bundle_sha256"],
        "preflight_sha256": preflight.get("preflight_sha256"),
        "authorization_basis": AUTHORIZATION_BASIS,
        "invalidated_run_ids": invalidated_ids,
        "invalidated_count": len(invalidated_ids),
        "artifacts": artifacts,
        "bundle_sha256": content_sha256(artifacts),
    }
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False))
        return 2
    output = run_dir / "bundle.manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": True, "artifacts": len(artifacts), "bundle_sha256": manifest["bundle_sha256"], "invalidated": len(invalidated_ids), "manifest": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
