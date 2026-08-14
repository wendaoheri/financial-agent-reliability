"""PER-59 pre-execution identity check (clean-room, independent of harness code).

Re-derives, from the frozen formulas alone, the 270 first-round run identities
(repeat==1) and verifies them against the frozen v3.10 plan, recomputes
plan_core, and checks disjointness against the 180 historical run ids from the
v3.5-v3.9 plans. Fails closed on any mismatch.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

DECLARED_PLAN_SHA256 = "009b1ea126b462bf873a555dbc7ced91b900d88728d94e5d208ee3a95c3ed4ec"
DECLARED_PLAN_CORE_SHA256 = "133ea34b60240f66660b4428f8c39aa2feba6b73a95c3fe71a8752eacf28076e"
DECLARED_CONFIG_FILE_SHA256 = "fdac619573fbe7449e5db32d3a643f394f705c5e73b18ea8446f7aebcf4b511f"
DECLARED_BUNDLE_SHA256 = "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180"
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
    plan = json.loads((ROOT / "contracts/stage3_acceptance_plan.v3.10.json").read_text(encoding="utf-8"))
    config_path = ROOT / "contracts/run_trace_harness_config.v3.10.json"
    bundle_path = ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.10.json"

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
        "contract_version": "3.10.0",
        "config_sha256": sha256_file(config_path),
        "models": plan["fairness"]["models"],
        "task_inputs": [
            {key: task[key] for key in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for task in sorted(plan["tasks"], key=lambda item: item["case_id"])
        ],
    }
    check(sha256_text(canonical(core)) == DECLARED_PLAN_CORE_SHA256, "plan_core independently reconstructed")

    # 3. re-derive all 270 first-round identities (repeat == 1)
    runs = plan["runs"]
    first_round = [row for row in runs if row["repeat"] == design["first_round_repeats"][0]]
    check(len(first_round) == 270, "exactly 270 repeat==1 runs")
    check([row["sequence"] for row in first_round] == list(range(1, 271)), "first round occupies sequences 1..270")
    check(plan["fairness"]["models"] == EXPECTED_MODELS, "model order matches the three registered candidates")

    bad = 0
    for row in first_round:
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
    check(bad == 0, "270/270 first-round identities re-derived exactly (seed + run_id + identity)")

    # 4. disjointness against the 180 historical run ids (v3.5-v3.9 plans)
    historical: set[str] = set()
    for version in ["3.5", "3.6", "3.7", "3.8", "3.9"]:
        old = json.loads((ROOT / f"contracts/stage3_acceptance_plan.v{version}.json").read_text(encoding="utf-8"))
        historical.update(row["run_id"] for row in old["runs"])
    check(len(historical) == 180, f"historical run id pool == 180 (found {len(historical)})")
    new_ids = {row["run_id"] for row in runs}
    check(len(new_ids) == 810, "810 preregistered run ids mutually distinct")
    check(not (new_ids & historical), "810 new ids disjoint from all 180 historical ids")

    # 5. authorization scope template: the exact 270 ids the run artifact must cover
    authorized = [row["run_id"] for row in first_round]
    out = ROOT / "audit" / "v3_10_first270_authorized_run_ids.json"
    out.write_text(json.dumps(authorized, indent=0) + "\n", encoding="utf-8")
    check(len(authorized) == 270 and len(set(authorized)) == 270, "270 unique authorized run ids exported for artifact binding")

    print()
    if FAILURES:
        print(f"RESULT: FAIL — {len(FAILURES)} check(s) failed")
        return 1
    print("RESULT: PASS — pre-execution identity verification green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
