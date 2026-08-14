"""PER-79 delivery-owner dispatch of the v3.11.1 single-unit coverage run.

Deterministic. Flips the coverage authorization artifact's execution gate from
``pending`` to dispatched/authorized, recording the dispatch basis: the PER-78
scoped gate-review report (SHA-256 0c863c12...) that judged v3.11.1 to satisfy
the "single-unit coverage run" technical gate, and the owner's standing paid
authorization (parent issue comment 6fdca2fb..., metadata key
paid_authorization_scope=standing_all_paid_runs_owner_2026_08_12). All other
binding fields are left untouched and the authorization self-hash is recomputed
so the artifact stays re-verifiable. Never reads, prints, or persists secrets.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs" / "stage3" / "coverage-20260814-v3.11.1"
AUTH_PATH = RUN_DIR / "authorization.run.json"

# Fail-closed commitments (must match the frozen artifact before flipping).
DECLARED_PLAN_SHA256 = "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b"
DECLARED_PLAN_CORE_SHA256 = "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b"
DECLARED_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"
DECLARED_CONFIG_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECLARED_COVERAGE_RUN_ID = "run_0e1e8f4400e16f22f6581e0bb0d9c54d"
DECLARED_INVALIDATED_RUN_ID = "run_c0f58d3c0d9227585058c4e4872a468b"
GATE_REPORT_SHA256 = "0c863c1213c62724bec0e016f2bb36d955bbd0a884dd5e9df55413f062b37b58"
DISPATCHED_ON = "2026-08-14"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def self_hash(authorization: dict) -> str:
    return sha256_text(canonical({k: v for k, v in authorization.items() if k != "authorization_sha256"}))


def dispatched_gate() -> dict:
    return {
        "independent_gate_review_required": True,
        "independent_gate_review_status": "passed",
        "independent_gate_review_issue": "PER-78",
        "independent_gate_review_result": "pass",
        "independent_gate_review_report_sha256": GATE_REPORT_SHA256,
        "independent_gate_review_checks": "100/100 clean-room recomputation",
        "delivery_owner_dispatch_required": True,
        "delivery_owner_dispatch_status": "authorized",
        "dispatched_by_issue": "PER-79",
        "dispatched_on": DISPATCHED_ON,
        "dispatch_basis": {
            "gate_review_issue": "PER-78",
            "gate_review_report_sha256": GATE_REPORT_SHA256,
            "gate_review_result": "pass",
            "paid_authorization_scope": "standing_all_paid_runs_owner_2026_08_12",
            "standing_authorization_source": "parent issue comment 6fdca2fb-0f86-473c-9269-5c71e7a470b3; parent issue metadata key paid_authorization_scope",
            "parent_issue_id": "45640133-7162-4832-aef6-94d0a3900bd6",
        },
        "issue": "PER-77",
    }


def main() -> int:
    authorization = json.loads(AUTH_PATH.read_text(encoding="utf-8"))

    # Pre-flip integrity: the artifact must be exactly the frozen pending one.
    failures: list[str] = []
    if authorization.get("authorization_sha256") != self_hash(authorization):
        failures.append("authorization self-hash does not verify before dispatch")
    if authorization.get("authorization_kind") != "financial_acceptance_single_unit_coverage_run":
        failures.append("authorization kind wrong")
    if authorization.get("plan_sha256") != DECLARED_PLAN_SHA256 or authorization.get("plan_core_sha256") != DECLARED_PLAN_CORE_SHA256:
        failures.append("authorization plan binding drift")
    if authorization.get("contract_bundle_sha256") != DECLARED_BUNDLE_SHA256 or authorization.get("harness_config_sha256") != DECLARED_CONFIG_SHA256:
        failures.append("authorization contract binding drift")
    if authorization.get("authorized_run_ids") != [DECLARED_COVERAGE_RUN_ID] or authorization.get("denied_run_ids") != [DECLARED_INVALIDATED_RUN_ID]:
        failures.append("authorization run-id scope drift")
    if authorization.get("maximum_runs") != 1 or authorization.get("authorized_run_count") != 1:
        failures.append("authorization run caps drift")

    gate = authorization.get("execution_gate", {})
    already = gate.get("delivery_owner_dispatch_status") == "authorized" and gate.get("independent_gate_review_status") == "passed"
    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        return 1
    if already:
        print(json.dumps({"status": "already_dispatched", "authorization_sha256": authorization["authorization_sha256"], "path": str(AUTH_PATH)}, ensure_ascii=False))
        return 0
    if gate.get("independent_gate_review_status") != "pending":
        print(f"[FAIL] execution gate is in an unexpected state before dispatch: {gate.get('independent_gate_review_status')}")
        return 1

    # Flip the gate; keep every other binding field untouched.
    authorization["execution_gate"] = dispatched_gate()
    authorization["authorization_sha256"] = self_hash(authorization)
    partial = AUTH_PATH.with_suffix(".json.partial")
    partial.write_text(json.dumps(authorization, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(AUTH_PATH)
    print(json.dumps({
        "status": "dispatched",
        "execution_gate_status": "authorized",
        "gate_review_report_sha256": GATE_REPORT_SHA256,
        "authorized_run_ids": authorization["authorized_run_ids"],
        "maximum_runs": authorization["maximum_runs"],
        "authorization_sha256": authorization["authorization_sha256"],
        "path": str(AUTH_PATH),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
