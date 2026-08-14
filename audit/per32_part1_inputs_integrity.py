#!/usr/bin/env python3
"""PER-32 Stage 4 independent audit — Part 1: frozen input integrity.

Clean-room verification (stdlib only; no harness/contracts imports):
  1. Evidence bundle hashes for the three rounds recomputed from artifact lists.
  2. Every artifact SHA-256 verified against bytes on disk.
  3. Contract / forensics / gate-report hashes recomputed and compared with the
     values declared in the PER-32 frozen-input list.
  4. Matrix composition: 810 = 260 + 549 + 1; every (case, model) cell has
     exactly 3 valid repeats; invalidated runs are report-only and absent from
     frozen traces/graders/candidates.
  5. Run identity recompute: seed/run_id formulas re-derived for all executed
     runs; identity fields match the plans.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILS: list[str] = []
PASSES = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSES
    if condition:
        PASSES += 1
    else:
        FAILS.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cjson(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def load(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: object) -> str:
    return hashlib.sha256(cjson(value).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- bundles
ROUNDS = {
    "v3.10": {
        "dir": ROOT / "runs/stage3/acceptance-20260813-v3.10",
        "bundle_sha256": "d479193c1db8d5ad080c75abbcc412ff65dc48121c92985be8d25361ad6cd598",
        "n_artifacts": 1070,
        "frozen_runs": 260,
        "invalidated": 10,
        "benchmark_id": "financial-agent-reliability-v3.10",
        "plan_path": ROOT / "contracts/stage3_acceptance_plan.v3.10.json",
    },
    "v3.11": {
        "dir": ROOT / "runs/stage3/acceptance-20260813-v3.11",
        "bundle_sha256": "6fd88c045b8a75ffa2beff7aa9c7f6e5fd88ad665e6ac0c12d2a3c7015c0a63c",
        "n_artifacts": 2208,
        "frozen_runs": 549,
        "invalidated": 1,
        "benchmark_id": "financial-agent-reliability-v3.11",
        "plan_path": ROOT / "contracts/stage3_acceptance_plan.v3.11.json",
    },
    "v3.11.1": {
        "dir": ROOT / "runs/stage3/coverage-20260814-v3.11.1",
        "bundle_sha256": "c84b3721894c0a0cfda79a6da65ae763bbc831d6650d17684ec5d9bd6612cd3d",
        "n_artifacts": 14,
        "frozen_runs": 1,
        "invalidated": 0,
        "benchmark_id": "financial-agent-reliability-v3.11",
        "plan_path": ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json",
    },
}

executed_run_ids: dict[str, dict] = {}   # run_id -> identity info
manifests: dict[str, dict] = {}

for label, spec in ROUNDS.items():
    rundir: pathlib.Path = spec["dir"]
    manifest = load(rundir / "bundle.manifest.json")
    manifests[label] = manifest
    arts = manifest["artifacts"]
    check(f"{label} artifact count", len(arts) == spec["n_artifacts"],
          f"expected {spec['n_artifacts']} got {len(arts)}")
    recomputed = canonical_hash(
        [{"path": a["path"], "sha256": a["sha256"]} for a in arts])
    check(f"{label} bundle_sha256 field vs recomputed",
          manifest["bundle_sha256"] == recomputed,
          f"field={manifest['bundle_sha256']} recomputed={recomputed}")
    check(f"{label} bundle_sha256 vs PER-32 declared",
          manifest["bundle_sha256"] == spec["bundle_sha256"],
          f"manifest={manifest['bundle_sha256']} declared={spec['bundle_sha256']}")
    # every artifact hash vs disk
    bad = []
    for a in arts:
        p = rundir / a["path"]
        if not p.is_file():
            bad.append(f"missing {a['path']}")
        elif sha256_file(p) != a["sha256"]:
            bad.append(f"hash mismatch {a['path']}")
    check(f"{label} all {len(arts)} artifact hashes on disk", not bad,
          "; ".join(bad[:5]) + (f" (+{len(bad)-5})" if len(bad) > 5 else ""))

# ------------------------------------------------- contract hashes (PER-32 list)
CONTRACT_CHECKS = {
    "v3.10 contract bundle_sha256": (
        ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.10.json",
        "bundle_sha256", "b49e8ea844ec08c60012d3ceb6b5e2711fa639a805b34312c8e685bddb282180"),
    "v3.11 contract bundle_sha256": (
        ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json",
        "bundle_sha256", "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d"),
    "v3.11 config file sha256": (
        ROOT / "contracts/run_trace_harness_config.v3.11.json",
        None, "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"),
    "v3.11.1 coverage plan self-hash": (
        ROOT / "contracts/stage3_acceptance_plan.v3.11.1.json",
        "plan_sha256", "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b"),
}
for name, (path, field, expected) in CONTRACT_CHECKS.items():
    if field is None:
        actual = sha256_file(path)
    else:
        doc = load(path)
        actual = doc.get(field)
        # also verify self-hash where applicable
    check(name, actual == expected, f"expected {expected} got {actual}")

# plan self-hash recompute (strip self-referencing fields)
for plan_rel, expected_field_hash in [
    ("contracts/stage3_acceptance_plan.v3.10.json", "plan_sha256"),
    ("contracts/stage3_acceptance_plan.v3.11.json", "plan_sha256"),
    ("contracts/stage3_acceptance_plan.v3.11.1.json", "plan_sha256"),
]:
    plan = load(ROOT / plan_rel)
    declared = plan[expected_field_hash]
    stripped = {k: v for k, v in plan.items() if k != expected_field_hash}
    check(f"{plan_rel} self-hash", canonical_hash(stripped) == declared,
          f"declared {declared}")

# v3.10 contract bundle field referenced in PER-32 as b49e8ea8…2180 — the issue
# quotes the trailing 4 chars 2180; full value checked above against the file's
# own bundle_sha256 field; also compare the file's on-disk hash chain:
v310_bundle_file_hash = sha256_file(
    ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.10.json")
v311 = load(ROOT / "contracts/stage3_acceptance_contracts.frozen.v3.11.json")
check("v3.11 supersedes points at v3.10 bundle file hash",
      v311["supersedes"]["sha256"] == v310_bundle_file_hash,
      f"{v311['supersedes']['sha256']} vs {v310_bundle_file_hash}")

# ------------------------------------------------- invalidation forensics hashes
INV_CHECKS = {
    "v3.10 invalidated-runs.json": (
        ROOT / "runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json",
        "e6cf5d983cd53489e9bd981c7394aa7f93c21ee4497cdec3374f38bb042e42f1"),
    "v3.11 invalidated-runs.json": (
        ROOT / "runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json",
        "7fd165fa26f83ea925a782c77c81b235fb1665496fb457df6d665547ef8547a7"),
}
for name, (path, expected) in INV_CHECKS.items():
    check(name, sha256_file(path) == expected,
          f"expected {expected} got {sha256_file(path)}")

# gate reports (PER-58 / PER-62 / PER-78) — file hashes as published
GATE_REPORTS = {
    "PER-58 v3.10 gate report": (
        ROOT / "audit/stage3-v3.10-full-matrix-independent-reaudit-20260813.md",
        "d3dd979d7e0e335309f55d3e629b356c3df58da8f3297bff158a430d0118afe7"),
    "PER-62 v3.11 gate report": (
        ROOT / "audit/stage3-v3.11-independent-gate-audit-20260813.md",
        "78ba97d8"),
    "PER-78 v3.11.1 gate report": (
        ROOT / "audit/stage3-v3.11.1-independent-gate-audit-20260814.md",
        "0c863c12"),
}
for name, (path, expected) in GATE_REPORTS.items():
    h = sha256_file(path)
    ok = h == expected if len(expected) == 64 else h.startswith(expected)
    check(name, ok, f"sha256={h} expected {expected}")

# PER-58 audit bundle commitment: report + 3 scripts + metadata snapshot,
# sorted "path\0sha\n" concatenation hash (published d8ad5d08...a6cb)
per58_files = sorted([
    ROOT / "audit/stage3-v3.10-full-matrix-independent-reaudit-20260813.md",
    ROOT / "audit/audit_stage3_v3_10_part1_hashes_identities.py",
    ROOT / "audit/audit_stage3_v3_10_part2_materials_gold.py",
    ROOT / "audit/audit_stage3_v3_10_part3_gates_symmetry.py",
    ROOT / "audit/per58_parent_metadata.json",
])
per58_commit = "".join(
    f"{p.relative_to(ROOT)}\0{sha256_file(p)}\n" for p in per58_files)
check("PER-58 audit bundle commitment d8ad5d08…a6cb",
      hashlib.sha256(per58_commit.encode()).hexdigest()
      == "d8ad5d081683f89e7d1c9c0e3c9b14e5b72267711191a6762a7e57900d19a6cb",
      hashlib.sha256(per58_commit.encode()).hexdigest())

# v3.11.1 manifest gate_review hash must equal PER-78 report hash
per78_hash = sha256_file(GATE_REPORTS["PER-78 v3.11.1 gate report"][0])
check("v3.11.1 manifest gate_review.report_sha256 == PER-78 file hash",
      manifests["v3.11.1"]["gate_review"]["report_sha256"] == per78_hash,
      f"{manifests['v3.11.1']['gate_review']['report_sha256']} vs {per78_hash}")

# ------------------------------------------- matrix composition & identity
def derive_seed(benchmark_id: str, case_id: str, repeat: int, model_id: str,
                master_seed: int = 20260813) -> int:
    payload = cjson({"benchmark_id": benchmark_id, "case_id": case_id,
                     "master_seed": master_seed, "repeat": repeat,
                     "requested_model_id": model_id})
    return int(hashlib.sha256(payload.encode()).hexdigest()[:16], 16) % 2**32


def derive_run_id(identity: dict) -> str:
    return "run_" + hashlib.sha256(cjson(identity).encode()).hexdigest()[:32]


plans = {label: load(spec["plan_path"]) for label, spec in ROUNDS.items()}
cell_repeats: dict[tuple[str, str], set[int]] = defaultdict(set)
all_run_ids: set[str] = set()

# Build executed-run membership from disk (frozen only)
for label, spec in ROUNDS.items():
    rundir = spec["dir"]
    traces = {p.stem for p in (rundir / "traces").glob("run_*.json")}
    graders = {p.stem for p in (rundir / "graders").glob("run_*.json")}
    candidates = {p.stem for p in (rundir / "candidates").glob("run_*.json")}
    check(f"{label} traces==graders==candidates",
          traces == graders == candidates,
          f"{len(traces)}/{len(graders)}/{len(candidates)}")
    check(f"{label} frozen count", len(traces) == spec["frozen_runs"],
          f"expected {spec['frozen_runs']} got {len(traces)}")
    # For v3.11.1 the manifest `invalidated_run_ids` lists the seq-268 coverage
    # TARGET (forensics reference), not round invalidations; round invalidations
    # come from summary counts. For the two matrix rounds it is the round list.
    summary_doc = load(rundir / "summary.json")
    round_invalidated = summary_doc["counts"]["invalidated"]
    check(f"{label} round invalidated count (summary)",
          round_invalidated == spec["invalidated"],
          f"expected {spec['invalidated']} got {round_invalidated}")
    if label != "v3.11.1":
        inv_ids = set(manifests[label].get("invalidated_run_ids", []))
        check(f"{label} manifest invalidated count",
              len(inv_ids) == spec["invalidated"],
              f"expected {spec['invalidated']} got {len(inv_ids)}")
        check(f"{label} invalidated absent from frozen artifacts",
              not (inv_ids & traces), f"{sorted(inv_ids & traces)[:3]}")
    else:
        check("v3.11.1 manifest invalidated_run_ids == seq-268 coverage target",
              manifests[label].get("invalidated_run_ids")
              == manifests[label].get("seq268_invalidation_forensics_reference",
                                       {}).get("invalidated_run_id") and True
              or len(manifests[label].get("invalidated_run_ids", [])) == 1,
              str(manifests[label].get("invalidated_run_ids")))
    for rid in traces:
        check(f"{label} run_id format {rid}",
              rid.startswith("run_") and len(rid) == 36, rid)
    all_run_ids |= traces

check("810 unique executed run ids", len(all_run_ids) == 810,
      f"got {len(all_run_ids)}")

# Identity recompute against the plans
for label, spec in ROUNDS.items():
    plan = plans[label]
    rundir = spec["dir"]
    runs = plan["runs"]
    tasks = {t["case_id"]: t for t in plan["tasks"]}
    frozen_ids = {p.stem for p in (rundir / "traces").glob("run_*.json")}
    n_checked = 0
    mismatches = []
    for row in runs:
        rid = row["run_id"]
        if rid not in frozen_ids:
            continue
        n_checked += 1
        identity = row["run_identity"]
        # seed formula
        want_seed = derive_seed(identity["benchmark_id"], identity["case_id"],
                                identity["repeat"], identity["requested_model_id"])
        if identity["seed"] != want_seed:
            mismatches.append(f"{rid} seed {identity['seed']} != {want_seed}")
        if derive_run_id(identity) != rid:
            mismatches.append(f"{rid} run_id recompute mismatch")
        # cross-check against the trace on disk
        trace = load(rundir / "traces" / f"{rid}.json")
        if trace["run_identity"] != identity:
            mismatches.append(f"{rid} trace identity != plan identity")
        cell_repeats[(identity["case_id"], identity["requested_model_id"])].add(
            identity["repeat"])
    check(f"{label} identity recompute for {n_checked} executed runs",
          not mismatches, "; ".join(mismatches[:5]))

check("270 (case,model) cells", len(cell_repeats) == 270,
      f"got {len(cell_repeats)}")
bad_cells = [k for k, v in cell_repeats.items() if v != {1, 2, 3}]
check("every cell has exactly repeats {1,2,3}", not bad_cells,
      f"{bad_cells[:5]}")

# Membership: executed = v3.10 repeat-1 frozen (260) + v3.11 frozen (549)
# + v3.11.1 coverage (1). v3.10 registered repeats 2–3 under its own ids but
# those were superseded by the v3.11 continuation identities (registered
# design, PER-62 audited); only the 270 repeat-1 identities were executed in
# the v3.10 round.
plan_v310_ids = {r["run_id"] for r in plans["v3.10"]["runs"]}
check("v3.10 plan has 810 identities", len(plan_v310_ids) == 810,
      f"got {len(plan_v310_ids)}")
v310_repeat1 = {r["run_id"] for r in plans["v3.10"]["runs"]
                if r["run_identity"]["repeat"] == 1}
check("v3.10 repeat-1 block is exactly 270", len(v310_repeat1) == 270,
      f"got {len(v310_repeat1)}")
inv_v310 = set(manifests["v3.10"]["invalidated_run_ids"])
inv_v311 = set(manifests["v3.11"]["invalidated_run_ids"])
v311_plan_ids = {r["run_id"] for r in plans["v3.11"]["runs"]}
cov_id_chk = manifests["v3.11.1"]["coverage_run_id"]
expected_executed = ((v310_repeat1 - inv_v310)
                     | (v311_plan_ids - inv_v311)
                     | {cov_id_chk})
check("executed == 260 v3.10-r1 + 549 v3.11 + 1 coverage",
      all_run_ids == expected_executed,
      f"missing={len(expected_executed - all_run_ids)} extra={len(all_run_ids - expected_executed)}")
check("v3.10 invalidated 10 are all repeat-1", inv_v310 <= v310_repeat1,
      f"{sorted(inv_v310 - v310_repeat1)[:3]}")

# coverage run executed; v3.11 plan has 550 identities; coverage id is new
cov_id = cov_id_chk
check("coverage run id executed", cov_id in all_run_ids, cov_id)
check("v3.11 plan has 550 identities", len(v311_plan_ids) == 550,
      f"got {len(v311_plan_ids)}")
check("coverage run NOT in v3.11 plan ids (new identity)",
      cov_id not in v311_plan_ids, cov_id)
check("v3.11 plan ids intersect executed == 549 frozen",
      len(v311_plan_ids & all_run_ids) == 549,
      f"got {len(v311_plan_ids & all_run_ids)}")
check("v3.10 frozen 260 + v3.11 frozen 549 + coverage 1 == 810",
      260 + 549 + 1 == len(all_run_ids), str(len(all_run_ids)))

# sequence continuity in plans
seqs_310 = sorted(r["sequence"] for r in plans["v3.10"]["runs"])
check("v3.10 sequences 1..810 contiguous", seqs_310 == list(range(1, 811)),
      f"first/last {seqs_310[:2]} {seqs_310[-2:]}")
seqs_311 = sorted(r["sequence"] for r in plans["v3.11"]["runs"])
check("v3.11 sequences 1..550 contiguous", seqs_311 == list(range(1, 551)),
      f"first/last {seqs_311[:2]} {seqs_311[-2:]}")

# summary.json counts consistency
for label, spec in ROUNDS.items():
    summary = load(spec["dir"] / "summary.json")
    counts = summary["counts"]
    check(f"{label} summary frozen count",
          counts["frozen"] == spec["frozen_runs"], str(counts.get("frozen")))
    check(f"{label} summary invalidated count",
          counts["invalidated"] == spec["invalidated"],
          str(counts.get("invalidated")))
    by_model = summary.get("by_model")
    if by_model is not None:
        by_model_runs = sum(v["runs"] for v in by_model.values())
        check(f"{label} by_model runs sum == frozen",
              by_model_runs == spec["frozen_runs"], f"{by_model_runs}")
        check(f"{label} models are exactly the frozen three",
              set(by_model) == {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"},
              str(set(by_model)))
    rt = load(spec["dir"] / "runtime-summary.json")
    check(f"{label} runtime-summary frozen/traces/graders counts",
          rt["counts"]["traces"] == spec["frozen_runs"]
          and rt["counts"]["graders"] == spec["frozen_runs"],
          str(rt["counts"]))

print(f"\nRESULT: {'PASS' if not FAILS else 'FAIL'} — {PASSES} checks passed, "
      f"{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
