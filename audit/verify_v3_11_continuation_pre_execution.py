"""PER-61 pre-execution identity check (clean-room, independent of harness code).

Re-derives, from the frozen formulas alone, the 550 continuation run identities
(10 repeat-1 coverage + 90x3 repeat 2-3 extension) and verifies them against the
frozen v3.11 plan; recomputes plan_core; confirms the 10 coverage units map
one-to-one onto the v3.10 invalidation forensics; and checks disjointness against
all historical run ids from the v3.5-v3.10 plans. Fails closed on any mismatch.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

DECLARED_PLAN_SHA256 = "c688ca7d7cbb86d24f37812a192c29fd3b37280bc4be77ba8a6e40450c03cf6c"
DECLARED_PLAN_CORE_SHA256 = "559ad5eb4d6b45bb01ffe6db7ba4a06d0599cde681d4bfeba42a85a80a215604"
DECLARED_CONFIG_FILE_SHA256 = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
DECLARED_BUNDLE_SHA256 = "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"
DECLARED_V310_INVALIDATED_FILE_SHA256 = "e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1"
EXPECTED_MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]

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


def derive_seed(benchmark_id: str, case_id: str, master_seed: int, repeat: int, model_id: str) -> int:
    identity = {
        "benchmark_id": benchmark_id,
        "case_id": case_id,
        "master_seed": master_seed,
        "repeat": repeat,
        "requested_model_id": model_id,
    }
    return int(sha256_text(canonical(identity))[:16], 16) % 2**32


def main() -> int:
    plan = json.loads((ROOT / "contracts/stage3_acceptance_plan.v3.11.json").read_text(encoding="utf-8"))
    config_path = ROOT / "contracts/run_trace_harness_config.v3.11.json"
    bundle_path = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json"

    # 1. frozen input hashes
    check(plan.get("plan_sha256") == DECLARED_PLAN_SHA256, "plan_sha256 matches declared value")
    plan_core = dict(plan)
    plan_core.pop("plan_sha256", None)
    check(sha256_text(canonical(plan_core)) == DECLARED_PLAN_SHA256, "plan_sha256 recomputed from canonical content")
    check(plan.get("plan_core_sha256") == DECLARED_PLAN_CORE_SHA256, "plan_core_sha256 matches declared value")
    check(sha256_file(config_path) == DECLARED_CONFIG_FILE_SHA256, "config file hash matches declared value")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    check(bundle.get("bundle_sha256") == DECLARED_BUNDLE_SHA256, "bundle_sha256 matches declared value")
    check(sha256_text(canonical(bundle["artifacts"])) == DECLARED_BUNDLE_SHA256, "bundle_sha256 recomputed from artifact list")

    # 2. plan_core clean-room reconstruction
    design = plan["replication_design"]
    core = {
        "contract_version": "3.11.0",
        "config_sha256": sha256_file(config_path),
        "models": plan["fairness"]["models"],
        "task_inputs": [
            {key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for task in sorted(plan["tasks"], key=lambda item: item["case_id"])
        ],
    }
    check(sha256_text(canonical(core)) == DECLARED_PLAN_CORE_SHA256, "plan_core independently reconstructed")
    check(plan["fairness"]["models"] == EXPECTED_MODELS, "model order matches the three registered candidates")

    # 3. re-derive all 550 continuation identities
    runs = plan["runs"]
    check(len(runs) == 550, "exactly 550 continuation runs")
    check([row["sequence"] for row in runs] == list(range(1, 551)), "continuation occupies sequences 1..550")
    coverage = [row for row in runs if row["repeat"] == 1]
    extension = [row for row in runs if row["repeat"] in (2, 3)]
    check(len(coverage) == 10, "exactly 10 repeat-1 coverage runs")
    check(len(extension) == 540, "exactly 540 repeat 2-3 extension runs")
    check([row["sequence"] for row in coverage] == list(range(1, 11)), "coverage occupies sequences 1..10")

    bad = 0
    for row in runs:
        identity = row["run_identity"]
        seed = derive_seed(design["benchmark_id"], identity["case_id"], design["master_seed"], row["repeat"], row["model_id"])
        rebuilt_identity = {
            "benchmark_id": design["benchmark_id"],
            "case_id": identity["case_id"],
            "harness_config_sha256": sha256_file(config_path),
            "plan_core_sha256": DECLARED_PLAN_CORE_SHA256,
            "repeat": row["repeat"],
            "requested_model_id": row["model_id"],
            "seed": seed,
            "variant_id": identity["variant_id"],
        }
        run_id = "run_" + sha256_text(canonical(rebuilt_identity))[:32]
        if run_id != row["run_id"] or seed != row["seed"] or rebuilt_identity != identity:
            bad += 1
            print(f"  mismatch at sequence {row['sequence']}: plan={row['run_id']} rebuilt={run_id}")
    check(bad == 0, "550/550 continuation identities re-derived exactly (seed + run_id + identity)")

    # 4. coverage maps one-to-one onto the v3.10 invalidation forensics
    forensics_path = ROOT / "runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json"
    check(sha256_file(forensics_path) == DECLARED_V310_INVALIDATED_FILE_SHA256, "v3.10 invalidated-runs.json forensics hash preserved")
    forensics = json.loads(forensics_path.read_text(encoding="utf-8"))
    forensics_by_run = {entry["run_id"]: entry for entry in forensics["entries"]}
    check(len(forensics_by_run) == 10, "forensics record exactly 10 invalidated units")
    coverage_map = plan["coverage_map"]
    check(len(coverage_map) == 10, "coverage_map has 10 entries")
    mapped = 0
    for row in coverage:
        mapping = coverage_map.get(row["run_id"])
        if mapping is None:
            continue
        source = forensics_by_run.get(mapping["v3_10_run_id"])
        if (
            source is not None
            and source["case_id"] == row["run_identity"]["case_id"] == mapping["case_id"]
            and source["model_id"] == row["model_id"] == mapping["model_id"]
            and source["sequence"] == mapping["v3_10_sequence"]
            and source["repeat"] == 1 == mapping["repeat"]
            and source["replaced_or_reexecuted"] is False
            and mapping["v3_10_run_id"] != row["run_id"]
        ):
            mapped += 1
    check(mapped == 10, "10/10 coverage runs map exactly onto the invalidated forensics without replacement")

    # 5. disjointness against all historical run ids (v3.5-v3.10 plans)
    historical: set[str] = set()
    for version in ["3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]:
        old = json.loads((ROOT / f"contracts/stage3_acceptance_plan.v{version}.json").read_text(encoding="utf-8"))
        historical.update(row["run_id"] for row in old["runs"])
    new_ids = {row["run_id"] for row in runs}
    check(len(new_ids) == 550, "550 new run ids mutually distinct")
    check(not (new_ids & historical), f"550 new ids disjoint from all {len(historical)} historical plan ids")

    # 6. authorization scope template: the exact 550 ids the run artifact must cover
    authorized = [row["run_id"] for row in runs]
    out = ROOT / "audit" / "v3_11_continuation_550_authorized_run_ids.json"
    out.write_text(json.dumps(authorized, indent=0) + "\n", encoding="utf-8")
    check(len(authorized) == 550 and len(set(authorized)) == 550, "550 unique authorized run ids exported for artifact binding")

    print()
    if FAILURES:
        print(f"RESULT: FAIL — {len(FAILURES)} check(s) failed")
        return 1
    print("RESULT: PASS — pre-execution continuation identity verification green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
