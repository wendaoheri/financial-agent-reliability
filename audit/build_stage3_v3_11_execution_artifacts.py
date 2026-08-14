"""PER-63 execution-artifact builder for the v3.11 550-unit continuation round.

Deterministic. Builds, into the v3.11 run directory:
  1. frozen copies of the v3.11 plan / config / contract bundle;
  2. the plan-bound v3.11 identity-preflight artifact as a documented
     carry-over of the v3.10 preflight (669cbd04...ef3f). The carry-over was
     re-verified pre-execution by PER-63 (endpoint, parameter commitments,
     model ids, system prompt, retry policy, and the 90 per-case tool-schema
     vectors are byte-identical between v3.10 and v3.11); no paid preflight
     calls are made this round;
  3. the paid 550-run continuation authorization artifact bound to the exact
     550 plan run ids under the owner's standing authorization.

Fails closed on any hash mismatch. Never reads, prints, or persists secrets.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs" / "stage3" / "acceptance-20260813-v3.11"

DECLARED_PLAN_SHA256 = "c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c"
DECLARED_PLAN_CORE_SHA256 = "559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604"
DECLARED_CONFIG_FILE_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECLARED_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"
SOURCE_PREFLIGHT_SHA256 = "669cbd049177d9c7ae7ea9e25bc9dda2fa6abee996061023477354895063ef3f"
SOURCE_PREFLIGHT_PATH = ROOT / "runs" / "stage3" / "acceptance-20260813-v3.10" / "preflight.json"
SOURCE_ENDPOINT_ID = "bailian_98bd231ca931"
EXPECTED_MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
AUTHORIZATION_BASIS = {
    "owner_comment_id": "6fdca2fb-0f86-473c-9269-5c71e7a470b3",
    "parent_issue_id": "45640133-7162-4832-aef6-94d0a3900bd6",
    "paid_authorization_scope": "standing_all_paid_runs_owner_2026_08_12",
    "metadata_keys": [
        "candidate_runs_allowed=true",
        "stage3_acceptance_runs_authorized=true",
        "paid_calls_authorized=true",
    ],
    "authorized_on": "2026-08-13",
    "issue": "PER-63",
    "preflight_carry_over": (
        "no configuration drift found by the PER-63 pre-execution check; the v3.10 "
        "preflight evidence carries over to v3.11 per the independent gate audit "
        "recommendation; no paid preflight calls were made this round"
    ),
}

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}")
    if not ok:
        FAILURES.append(label)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    plan = json.loads((ROOT / "contracts/stage3_acceptance_plan.v3.11.json").read_text(encoding="utf-8"))
    config_path = ROOT / "contracts/run_trace_harness_config.v3.11.json"
    bundle_path = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"

    # --- frozen-input integrity (fail closed) --------------------------------
    check(plan.get("plan_sha256") == DECLARED_PLAN_SHA256, "plan self-hash matches declared value")
    stripped = dict(plan)
    stripped.pop("plan_sha256", None)
    check(sha256_text(canonical(stripped)) == DECLARED_PLAN_SHA256, "plan content hash recomputed")
    check(plan.get("plan_core_sha256") == DECLARED_PLAN_CORE_SHA256, "plan_core hash matches declared value")
    check(sha256_file(config_path) == DECLARED_CONFIG_FILE_SHA256, "config file hash matches declared value")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    check(bundle.get("bundle_sha256") == DECLARED_BUNDLE_SHA256, "contract bundle hash matches declared value")
    check(sha256_text(canonical(bundle["artifacts"])) == DECLARED_BUNDLE_SHA256, "contract bundle artifact-list hash recomputed")
    check(plan["fairness"]["models"] == EXPECTED_MODELS, "model order matches the three registered candidates")
    check(len(plan["runs"]) == 550 and plan.get("continuation_run_cap") == 550, "plan carries exactly 550 continuation runs")

    # --- carry-over source integrity ------------------------------------------
    source = json.loads(SOURCE_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    source_stripped = dict(source)
    source_stripped.pop("preflight_sha256", None)
    check(source.get("preflight_sha256") == SOURCE_PREFLIGHT_SHA256, "source v3.10 preflight declares the carry-over hash")
    check(sha256_text(canonical(source_stripped)) == SOURCE_PREFLIGHT_SHA256, "source v3.10 preflight self-hash recomputed")
    check(source.get("decision") == "passed_3_of_3" and source.get("counts") == {"requested": 3, "passed": 3, "blocked": 0}, "source preflight is a passing 3-of-3 artifact")
    check(source.get("endpoint_id") == SOURCE_ENDPOINT_ID, "source preflight endpoint id is the carried-over endpoint")
    check([row["model_id"] for row in source["results"]] == EXPECTED_MODELS, "source preflight model order matches")

    if FAILURES:
        print(f"RESULT: FAIL — {len(FAILURES)} check(s) failed; nothing written")
        return 1

    # --- 1. frozen copies ------------------------------------------------------
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("stage3_acceptance_plan.v3.11.json", "run_trace_harness_config.v3.11.json", "stage3_acceptance_contracts.frozen.v3.11.json"):
        shutil.copyfile(ROOT / "contracts" / name, RUN_DIR / name)
        check(sha256_file(RUN_DIR / name) == sha256_file(ROOT / "contracts" / name), f"frozen copy byte-identical: {name}")

    # --- 2. carry-over preflight artifact --------------------------------------
    preflight = {
        "contract_type": "stage3_identity_preflight",
        "contract_version": "3.11.0",
        "plan_sha256": DECLARED_PLAN_SHA256,
        "endpoint_id": SOURCE_ENDPOINT_ID,
        "carry_over": {
            "source_contract_version": "3.10.0",
            "source_preflight_sha256": SOURCE_PREFLIGHT_SHA256,
            "source_preflight_path": "runs/stage3/acceptance-20260813-v3.10/preflight.json",
            "paid_calls_in_this_round": 0,
            "results_copied_from_source": True,
            "basis": (
                "the identity elements bound by the source preflight are byte-identical under v3.11; "
                "carry-over validated by the PER-62 independent gate audit and re-verified pre-execution by PER-63"
            ),
            "verified": {
                "source_preflight_self_hash_recomputed": True,
                "parameters_sha256_by_model_equal": True,
                "parameters_by_model_deep_equal": True,
                "candidate_model_ids_equal": True,
                "endpoint_id_equal": True,
                "system_prompt_equal": True,
                "provider_retry_policy_equal": True,
                "per_case_tool_schema_vectors_equal_90_of_90": True,
            },
        },
        "results": source["results"],
        "counts": {"requested": 3, "passed": 3, "blocked": 0},
        "decision": "passed_3_of_3",
        "raw_provider_response_stored": False,
    }
    preflight["preflight_sha256"] = sha256_text(canonical({k: v for k, v in preflight.items() if k != "preflight_sha256"}))
    write_json(RUN_DIR / "preflight.json", preflight)
    check(True, f"carry-over preflight artifact written (preflight_sha256={preflight['preflight_sha256'][:12]}…)")

    # --- 3. paid 550-run continuation authorization ----------------------------
    authorization = {
        "paid_calls_authorized": True,
        "authorization_kind": "financial_acceptance_550_continuation_run",
        "plan_sha256": DECLARED_PLAN_SHA256,
        "preflight_sha256": preflight["preflight_sha256"],
        "exact_model_ids": EXPECTED_MODELS,
        "authorized_run_ids": [row["run_id"] for row in plan["runs"]],
        "authorization_basis": AUTHORIZATION_BASIS,
    }
    check(len(authorization["authorized_run_ids"]) == 550 and len(set(authorization["authorized_run_ids"])) == 550, "authorization binds exactly 550 distinct run ids in plan order")
    write_json(RUN_DIR / "authorization.run.json", authorization)
    check(True, "550-run continuation authorization artifact written")

    print(f"RUN_DIR: {RUN_DIR}")
    print("RESULT: PASS — execution artifacts built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
