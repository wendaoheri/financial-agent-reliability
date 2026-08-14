"""PER-58 independent audit — Part 1: frozen hashes, supersedes chain, run identities.

Fully standalone: does NOT import any harness/contracts module. Every hash and
identity is recomputed from first principles using only the frozen artifacts on
disk and the declared derivation formulas.

Usage: python3 audit/audit_stage3_v3_10_part1_hashes_identities.py
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    tag = "OK  " if condition else "FAIL"
    if not condition:
        FAILURES.append(label)
    print(f"[{tag}] {label}")


def canonical(value) -> str:
    # financial-agent-c14n-json-v1 profile: sorted keys, compact separators, UTF-8 preserved
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csha(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fsha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


# declared values from PER-58 issue body + PER-57 declaration comment
DECLARED = {
    "v3_10_bundle": "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180",
    "v3_10_plan": "009b1ea126b462bf873a555dbc7ced91b900d88728d94e5d208ee3a95c3ed4ec",
    "v3_10_plan_core": "133ea34b60240f66660b4428f8c39aa2feba6b73a95c3fe71a8752eacf28076e",
    "v3_10_config": "fdac619573fbe7449e5db32d3a643f394f705c5e73b18ea8446f7aebcf4b511f",
}
# parent issue metadata baseline — loaded from the saved snapshot, never hand-typed
_META_RAW = json.loads((ROOT / "audit/per58_parent_metadata.json").read_text(encoding="utf-8"))
PARENT_META = {ver: _META_RAW[f"stage3_v{ver.replace('.', '_')}_contract_bundle_sha256"] for ver in ["3.6", "3.7", "3.8", "3.9"]}
PARENT_PLAN_META = {ver: _META_RAW[f"stage3_v{ver.replace('.', '_')}_plan_sha256"] for ver in ["3.6", "3.7", "3.8", "3.9"]}


def part_bundles() -> None:
    print("== Bundle hashes, artifact drift, supersedes chain ==")
    # v3.5 uses the combined-base commitment scheme
    doc = load("contracts/stage3_acceptance_contracts.frozen.v3.5.json")
    protocol = load("contracts/stage3_acceptance_contracts.frozen.v3.4.json")
    financial = load("contracts/stage3_acceptance_contracts.frozen.v3.json")
    inherited = {i["path"]: i for i in [*protocol["artifacts"], *financial["artifacts"]]}
    combined = [*inherited.values(), *doc["artifacts"]]
    commitments = sorted(f"{a['path']}\0{a['sha256']}\n" for a in combined)
    v35 = hashlib.sha256("".join(commitments).encode()).hexdigest()
    check(v35 == doc["bundle_sha256"], f"v3.5 bundle_sha256 recomputed (combined {len(combined)} artifacts)")
    drift = [a["path"] for a in combined if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
    check(not drift, f"v3.5 combined artifacts zero drift on disk ({len(drift)} bad)")

    prior_sha = doc["bundle_sha256"]
    for ver in ["3.6", "3.7", "3.8", "3.9", "3.10"]:
        p = f"contracts/stage3_acceptance_contracts.frozen.v{ver}.json"
        d = load(p)
        check(csha(d["artifacts"]) == d["bundle_sha256"], f"v{ver} bundle_sha256 == canonical(artifacts)")
        bad = [a["path"] for a in d["artifacts"] if not (ROOT / a["path"]).is_file() or fsha(ROOT / a["path"]) != a["sha256"]]
        check(not bad, f"v{ver} {len(d['artifacts'])} artifacts zero drift on disk")
        sup = d["supersedes"]
        check(sup["path"] == f"contracts/stage3_acceptance_contracts.frozen.v{'3.9' if ver == '3.10' else f'3.{int(ver[-1]) - 1}'}.json", f"v{ver} supersedes points to prior version")
        check(fsha(ROOT / sup["path"]) == sup["sha256"], f"v{ver} supersedes raw-file sha matches prior bundle file")
        prior_key = f"v{ver.replace('.', '_').replace('3_', '3_')}_bundle_sha256"
        prior_key = f"v{'3_9' if ver == '3.10' else '3_' + str(int(ver[-1]) - 1)}_bundle_sha256"
        check(sup.get(prior_key) == prior_sha, f"v{ver} supersedes.{prior_key} == recomputed prior bundle_sha256")
        # v3.6 carries the flag top-level; v3.7+ carry it in the preserved block
        flag = d.get("preserved", {}).get("retroactive_regrading", d.get("retroactive_regrading"))
        check(flag is False, f"v{ver} retroactive_regrading == false")
        check(d.get("paid_calls_authorized") is False, f"v{ver} paid_calls_authorized == false")
        prior_sha = d["bundle_sha256"]

    v310 = load("contracts/stage3_acceptance_contracts.frozen.v3.10.json")
    check(v310["bundle_sha256"] == DECLARED["v3_10_bundle"], "v3.10 bundle_sha256 == PER-58 declared value")
    check(len(v310["artifacts"]) == 111, "v3.10 bundle artifact count == 111")
    check(v310["preserved"]["v3_9_bundle_sha256"] == PARENT_META["3.9"], "v3.10 preserved v3.9 hash == parent metadata")
    for ver, meta in PARENT_META.items():
        key = f"v{ver.replace('.', '_')}_bundle_sha256"
        check(v310["preserved"][key] == meta, f"v3.10 preserved {key} == parent metadata")
        recomputed = load(f"contracts/stage3_acceptance_contracts.frozen.v{ver}.json")["bundle_sha256"]
        check(recomputed == meta, f"v{ver} on-disk bundle_sha256 == parent metadata (zero drift)")


def part_plans() -> None:
    print("== Plan hashes and chain ==")
    for ver in ["3.5", "3.6", "3.7", "3.8", "3.9"]:
        d = load(f"contracts/stage3_acceptance_plan.v{ver}.json")
        body = {k: v for k, v in d.items() if k != "plan_sha256"}
        check(csha(body) == d["plan_sha256"], f"v{ver} plan_sha256 == canonical(plan minus plan_sha256)")
        if ver in PARENT_PLAN_META:
            check(d["plan_sha256"] == PARENT_PLAN_META[ver], f"v{ver} plan_sha256 == parent metadata")
        check(len(d["runs"]) == 36, f"v{ver} plan run count == 36")

    plan = load("contracts/stage3_acceptance_plan.v3.10.json")
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    check(csha(body) == plan["plan_sha256"], "v3.10 plan_sha256 == canonical(plan minus plan_sha256)")
    check(plan["plan_sha256"] == DECLARED["v3_10_plan"], "v3.10 plan_sha256 == PER-58 declared value")

    # supersedes chain to v3.9 plan
    v39p = load("contracts/stage3_acceptance_plan.v3.9.json")
    check(plan["supersedes"]["path"] == "contracts/stage3_acceptance_plan.v3.9.json", "v3.10 plan supersedes v3.9 plan")
    check(fsha(ROOT / plan["supersedes"]["path"]) == plan["supersedes"]["sha256"], "v3.10 plan supersedes raw-file sha matches v3.9 plan file")
    check(plan["supersedes"]["plan_sha256"] == v39p["plan_sha256"], "v3.10 plan supersedes.plan_sha256 == v3.9 plan_sha256")

    # config binding
    cfg_path = ROOT / "contracts/run_trace_harness_config.v3.10.json"
    cfg_file_sha = fsha(cfg_path)
    check(cfg_file_sha == DECLARED["v3_10_config"], "v3.10 config file sha256 == PER-58 declared value")
    core = {
        "contract_version": plan["contract_version"],
        "config_sha256": cfg_file_sha,
        "models": plan["fairness"]["models"],
        "task_inputs": [
            {k: t[k] for k in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"]}
            for t in plan["tasks"]
        ],
    }
    check(csha(core) == plan["plan_core_sha256"], "v3.10 plan_core_sha256 recomputed from tasks+config+models")
    check(plan["plan_core_sha256"] == DECLARED["v3_10_plan_core"], "v3.10 plan_core_sha256 == PER-58 declared value")
    for t in plan["tasks"]:
        check_key = all(k in t for k in ["case_id", "source_case_sha256", "projection_sha256", "snapshot_sha256", "tool_schema_sha256"])
        if not check_key:
            check(False, f"task {t.get('case_id')} missing binding key")
            break
    else:
        check(True, "all 90 tasks carry case/source/projection/snapshot/tool-schema bindings")


def part_identities() -> None:
    print("== Run identity scheme (810 / 270) ==")
    plan = load("contracts/stage3_acceptance_plan.v3.10.json")
    rd = plan["replication_design"]
    master_seed = rd["master_seed"]
    benchmark_id = rd["benchmark_id"]
    check(master_seed == 20260813 and benchmark_id == "financial-agent-reliability-v3.10", "master_seed=20260813, benchmark_id as declared")
    check(rd["no_post_hoc_selection"] is True, "no_post_hoc_selection == true")
    check(plan["first_round_run_cap"] == 270 and plan["registered_total_run_cap"] == 810, "caps 270/810")

    runs = plan["runs"]
    check(len(runs) == 810, "810 registered runs")
    check(len(plan["tasks"]) == 90, "90 in-plan tasks")
    models = plan["fairness"]["models"]
    check(models == ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"], "3 declared models in fixed order")

    def derive_seed(case_id, model_id, repeat):
        identity = {"benchmark_id": benchmark_id, "case_id": case_id, "master_seed": master_seed, "repeat": repeat, "requested_model_id": model_id}
        return int(csha(identity)[:16], 16) % 2**32

    def derive_run_id(identity):
        return "run_" + csha(identity)[:32]

    bad_seed = bad_rid = bad_field = 0
    for row in runs:
        rid = row["run_identity"]
        want_seed = derive_seed(rid["case_id"], rid["requested_model_id"], rid["repeat"])
        if row["seed"] != want_seed or rid["seed"] != want_seed:
            bad_seed += 1
        if derive_run_id(rid) != row["run_id"]:
            bad_rid += 1
        if rid["repeat"] != row["repeat"] or rid["requested_model_id"] != row["model_id"]:
            bad_field += 1
        if rid["plan_core_sha256"] != plan["plan_core_sha256"] or rid["benchmark_id"] != benchmark_id:
            bad_field += 1
    check(bad_seed == 0, f"810/810 seeds match independent recomputation (bad={bad_seed})")
    check(bad_rid == 0, f"810/810 run_ids match independent recomputation (bad={bad_rid})")
    check(bad_field == 0, f"810/810 identity fields internally consistent (bad={bad_field})")

    ids = [row["run_id"] for row in runs]
    check(len(set(ids)) == 810, "810 run ids mutually distinct")

    first_round = [row for row in runs if row["repeat"] == 1]
    check(len(first_round) == 270, "first round repeat==1 has 270 runs")
    check([row["sequence"] for row in first_round] == list(range(1, 271)), "first round occupies sequences 1..270")
    check([row["sequence"] for row in runs] == list(range(1, 811)), "sequences contiguous 1..810, repeat-major")

    cells: dict[tuple, list] = {}
    for row in runs:
        cells.setdefault((row["run_identity"]["case_id"], row["model_id"]), []).append(row)
    check(len(cells) == 270, "270 (case, model) cells")
    check(all(sorted(r["repeat"] for r in rows) == [1, 2, 3] for rows in cells.values()), "each cell carries repeats 1,2,3 exactly once")
    check(all(len({r["seed"] for r in rows}) == 3 for rows in cells.values()), "each (case, model) cell has exactly 3 distinct seeds")

    blocks: dict[tuple, set] = {}
    task_ids = {t["case_id"] for t in plan["tasks"]}
    check(len(task_ids) == 90, "90 distinct task case_ids")
    for row in runs:
        blocks.setdefault((row["model_id"], row["repeat"]), set()).add(row["run_identity"]["case_id"])
    check(len(blocks) == 9, "9 (model, repeat) blocks")
    check(all(b == task_ids for b in blocks.values()), "every (model, repeat) block covers all 90 tasks exactly")

    # disjointness from the 180 historical run ids (v3.5-v3.9 plans, 36 each)
    historical: set[str] = set()
    for ver in ["3.5", "3.6", "3.7", "3.8", "3.9"]:
        old = load(f"contracts/stage3_acceptance_plan.v{ver}.json")
        historical |= {row["run_id"] for row in old["runs"]}
    check(len(historical) == 180, f"historical run id pool == 180 (found {len(historical)})")
    check(not (set(ids) & historical), "810 new run ids disjoint from all 180 historical ids")

    # seed order-independence: derivation is a pure function of the 5 identity
    # fields; verify a shuffled re-enumeration reproduces identical (run_id, seed)
    import random as _r
    shuffled = runs[:]
    _r.Random(1).shuffle(shuffled)
    remap = {derive_run_id({
        "benchmark_id": benchmark_id, "case_id": r["run_identity"]["case_id"],
        "harness_config_sha256": r["run_identity"]["harness_config_sha256"],
        "plan_core_sha256": plan["plan_core_sha256"], "repeat": r["repeat"],
        "requested_model_id": r["model_id"], "seed": derive_seed(r["run_identity"]["case_id"], r["model_id"], r["repeat"]),
        "variant_id": r["run_identity"]["variant_id"],
    }): derive_seed(r["run_identity"]["case_id"], r["model_id"], r["repeat"]) for r in shuffled}
    check(remap == {row["run_id"]: row["seed"] for row in runs}, "seed/run_id derivation independent of enumeration order")


def main() -> None:
    part_bundles()
    part_plans()
    part_identities()
    print()
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)} failures)")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("RESULT: PASS — all part-1 checks green")


if __name__ == "__main__":
    main()
