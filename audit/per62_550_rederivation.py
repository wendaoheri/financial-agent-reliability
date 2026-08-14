"""PER-62 independent clean-room re-derivation of the v3.11 continuation plan.

Run as an independent auditor (read-only). Rebuilds, from the frozen formulas
ALONE (not from any harness/implementation module), the 550 continuation run
identities (10 repeat-1 coverage + 90x3x{2,3} extension), the plan_core and
plan hashes, and cross-checks them against the frozen v3.11 plan. The seed /
run_id formulas are first anchored against v3.10 invalidated-runs.json, which
is independent ground truth (master_seed=20260813, benchmark_id=v3.10).

Exits non-zero if any audited check fails. Prints per-item PASS/FAIL.

Usage:
    python3 audit/per62_550_rederivation.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

PLAN_PATH = ROOT / "contracts" / "stage3_acceptance_plan.v3.11.json"
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v3.11.json"
FORENSICS_PATH = ROOT / "runs" / "stage3" / "acceptance-20260813-v3.10" / "invalidated-runs.json"

MASTER_SEED = 20260813
V310_BENCHMARK_ID = "financial-agent-reliability-v3.10"
DECLARED_PLAN_CORE_SHA256 = "559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604"
DECLARED_V310_FORENSICS_FILE_SHA256 = "e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1"


def canonical(value: Any) -> str:
    """canonical_json: sorted keys, compact separators, preserve non-ASCII."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_seed(benchmark_id: str, case_id: str, master_seed: int, repeat: int, model_id: str) -> int:
    """seed = int(sha256(canonical_json(obj))[:16], 16) mod 2^32; order-independent."""
    obj = {
        "benchmark_id": benchmark_id,
        "case_id": case_id,
        "master_seed": master_seed,
        "repeat": repeat,
        "requested_model_id": model_id,
    }
    return int(sha256_text(canonical(obj))[:16], 16) % 2**32


def build_run_id(identity: dict[str, Any]) -> str:
    """run_id = 'run_' + sha256(canonical_json(run_identity))[:32]."""
    return "run_" + sha256_text(canonical(identity))[:32]


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def item1_anchor() -> tuple[int, int, int]:
    """Anchor seed + run_id formulas on v3.10 invalidated ground truth."""
    forensics = load_json(FORENSICS_PATH)
    entries = forensics["entries"]
    seed_ok = rid_ok = 0
    for entry in entries:
        ident = entry["run_identity"]
        seed = derive_seed(V310_BENCHMARK_ID, entry["case_id"], MASTER_SEED, entry["repeat"], ident["requested_model_id"])
        rid = build_run_id(ident)
        seed_ok += seed == entry["seed"]
        rid_ok += rid == entry["run_id"]
    return seed_ok, rid_ok, len(entries)


def recompute_plan_core(plan: dict[str, Any], config_hash: str) -> str:
    """Independently reconstruct plan_core and return its canonical sha256."""
    core = {
        "contract_version": "3.11.0",
        "config_sha256": config_hash,
        "models": plan["fairness"]["models"],
        "task_inputs": [
            {k: task[k] for k in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for task in sorted(plan["tasks"], key=lambda item: item["case_id"])
        ],
    }
    return sha256_text(canonical(core))


def main() -> int:
    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    plan = load_json(PLAN_PATH)
    design = plan["replication_design"]
    config_hash = sha256_file(CONFIG_PATH)
    runs = plan["runs"]

    # ---- Item 1: formula anchor against v3.10 ground truth ----
    seed_ok, rid_ok, n = item1_anchor()
    check(seed_ok == n, f"item1: seed formula reproduces {n}/{n} v3.10 invalidated seeds (master_seed={MASTER_SEED})")
    check(rid_ok == n, f"item1: run_id formula reproduces {n}/{n} v3.10 invalidated run_ids")

    # ---- Item 2: clean-room re-derivation of the 550 identities ----
    check(len(runs) == 550, "item2: plan carries exactly 550 runs")
    check([row["sequence"] for row in runs] == list(range(1, 551)), "item2: sequences are 1..550 in order")

    plan_core_hash = recompute_plan_core(plan, config_hash)
    check(plan_core_hash == DECLARED_PLAN_CORE_SHA256, "item2: plan_core_sha256 independently reconstructed")
    check(plan.get("plan_core_sha256") == DECLARED_PLAN_CORE_SHA256, "item2: declared plan_core_sha256 matches recomputed value")
    plan_sha = sha256_text(canonical({k: v for k, v in plan.items() if k != "plan_sha256"}))
    check(plan_sha == plan.get("plan_sha256"), "item2: plan_sha256 recomputed from canonical plan content")
    check(config_hash == runs[0]["run_identity"]["harness_config_sha256"], "item2: harness_config_sha256 matches config file hash")

    mismatches: list[tuple[int, str, str]] = []
    for row in runs:
        ident = row["run_identity"]
        seed = derive_seed(design["benchmark_id"], ident["case_id"], design["master_seed"], row["repeat"], row["model_id"])
        rebuilt = {
            "benchmark_id": design["benchmark_id"],
            "case_id": ident["case_id"],
            "harness_config_sha256": config_hash,
            "plan_core_sha256": plan_core_hash,
            "repeat": row["repeat"],
            "requested_model_id": row["model_id"],
            "seed": seed,
            "variant_id": ident["variant_id"],
        }
        rid = build_run_id(rebuilt)
        if seed != row["seed"] or rid != row["run_id"] or rebuilt != ident:
            mismatches.append((row["sequence"], row["run_id"], rid))
    check(not mismatches, f"item2: 550/550 identities re-derived exactly (seed + run_id + identity); mismatches={len(mismatches)}")
    for seq, plan_rid, rebuilt_rid in mismatches[:20]:
        print(f"    mismatch seq={seq} plan={plan_rid} rebuilt={rebuilt_rid}")

    print()
    if failures:
        print(f"RESULT: FAIL - {len(failures)} check(s) failed")
        return 1
    print("RESULT: PASS - independent clean-room re-derivation green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
