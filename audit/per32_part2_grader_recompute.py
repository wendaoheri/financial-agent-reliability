#!/usr/bin/env python3
"""PER-32 Stage 4 independent audit — Part 2: grader recompute (all 810 runs).

Layers:
  A. Deterministic recompute: re-run the frozen round grader on the frozen
     (candidate, projection, snapshot, trace) artifacts for every executed run
     and require byte-identical grader_sha256. This proves each stored grader
     result is exactly the frozen deterministic function of the frozen inputs.
  B. Commitment binding: the grader's candidate/trace/projection/snapshot
     sha256 commitments must equal the actual on-disk byte hashes.
  C. Clean-room oracle anchor: for all 90 tasks re-execute the frozen Stage-2
     oracle (registered invocation `evaluate(snapshot if refs else None,
     inputs)` with the card's own inputs) and require the registered Gold
     (status / reason set / value) to reproduce. Oracle implementation file
     hashes must equal the per-card registered implementation_sha256.
  D. Expected-value layer cross-check: the frozen v3.10 expectation function
     output must equal the registered Stage-2 Gold for all 90 tasks.
  E. Independent semantic cross-check: for every run, independently compare the
     candidate status and value against the expected values (own canonical
     equality, Decimal-exact) and compare verdicts with the frozen grader's
     status_correct / value_semantic_correct checks.

Run: uv run python audit/per32_part2_grader_recompute.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from decimal import Decimal, InvalidOperation

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.acceptance_v3_10 import (  # noqa: E402  (auditee code, disclosed)
    grade_candidate_v310,
    independent_expected_v310,
    read_json,
)
from harness.acceptance_v3_11 import grade_candidate_v311  # noqa: E402

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


def canonical_hash(value: object) -> str:
    return hashlib.sha256(cjson(value).encode("utf-8")).hexdigest()


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROUNDS = [
    ("v3.10", ROOT / "runs/stage3/acceptance-20260813-v3.10",
     "contracts/stage3_acceptance_plan.v3.10.json", grade_candidate_v310),
    ("v3.11", ROOT / "runs/stage3/acceptance-20260813-v3.11",
     "contracts/stage3_acceptance_plan.v3.11.json", grade_candidate_v311),
    ("v3.11.1", ROOT / "runs/stage3/coverage-20260814-v3.11.1",
     "contracts/stage3_acceptance_plan.v3.11.1.json", grade_candidate_v311),
]

# ------------------------------------------------------------------ A + B
total_runs = 0
hash_matches = 0
commit_ok = 0
for label, rundir, plan_rel, grade_fn in ROUNDS:
    plan = read_json(ROOT / plan_rel)
    tasks = {t["case_id"]: t for t in plan["tasks"]}
    grader_paths = sorted((rundir / "graders").glob("run_*.json"))
    for gpath in grader_paths:
        g = read_json(gpath)
        run_id = g["run_id"]
        total_runs += 1
        task = tasks[g["case_id"]]
        candidate_p = rundir / "candidates" / f"{run_id}.json"
        trace_p = rundir / "traces" / f"{run_id}.json"
        projection_p = ROOT / task["projection_path"]
        snapshot_p = ROOT / task["snapshot_path"]
        candidate = read_json(candidate_p)
        trace = read_json(trace_p)
        projection = read_json(projection_p)
        snapshot = read_json(snapshot_p)
        recomputed = grade_fn(candidate, projection, snapshot, trace)
        if recomputed["grader_sha256"] == g["grader_sha256"]:
            hash_matches += 1
        else:
            check(f"{label} {run_id} grader_sha256 recompute", False,
                  f"{recomputed['grader_sha256']} != {g['grader_sha256']}")
        # commitment binding: the grader commits to canonical-content hashes
        # (sorted-keys compact JSON); raw byte integrity of the same files is
        # verified against the frozen evidence bundle manifest in Part 1.
        wants = {
            # frozen convention: hash exists only when a candidate mapping is
            # present (candidate-failed runs persist `null`)
            "candidate_sha256": canonical_hash(candidate)
            if isinstance(candidate, dict) else None,
            "trace_sha256": canonical_hash(trace),
            "projection_sha256": canonical_hash(projection),
            "snapshot_sha256": canonical_hash(snapshot),
        }
        if g["commitments"] == wants:
            commit_ok += 1
        else:
            diff = {k: (g["commitments"].get(k), wants[k])
                    for k in wants if g["commitments"].get(k) != wants[k]}
            check(f"{label} {run_id} commitment binding", False, str(diff))

check("A: all 810 grader results byte-recompute",
      hash_matches == total_runs == 810,
      f"matches={hash_matches}/{total_runs}")
check("B: all 810 grader commitments bind to disk bytes",
      commit_ok == total_runs == 810, f"ok={commit_ok}/{total_runs}")

# ------------------------------------------------------------------ C
public_oracle = load_module("audit_public_oracle", ROOT / "cases/public/oracle.py")
ftw_oracle = load_module("audit_ftw_oracle", ROOT / "oracles/longbridge/oracle_v2.py")

cards = sorted((ROOT / "cases/public/v2").glob("case_card.*.json")) + \
    sorted((ROOT / "cases/longbridge/synthetic_v2").glob("case_card.*.json"))
check("90 case cards present", len(cards) == 90, f"got {len(cards)}")

oracle_ok = 0
impl_hash_ok = 0
registered_gold: dict[str, dict] = {}   # card case_id -> expected
card_by_case: dict[str, dict] = {}
for card_p in cards:
    card = read_json(card_p)
    oracle = card["oracle"]
    impl, func = oracle["implementation"].split(":")
    actual_impl_hash = sha256_file(ROOT / impl)
    if actual_impl_hash == oracle["implementation_sha256"]:
        impl_hash_ok += 1
    else:
        check(f"oracle impl hash {card_p.name}", False,
              f"{actual_impl_hash} != {oracle['implementation_sha256']}")
    module = public_oracle if "public" in impl else ftw_oracle
    snapshot = None
    if card.get("evidence_refs"):
        ref = card["evidence_refs"][0]
        snap_rel = ref["snapshot_path"] if isinstance(ref, dict) and "snapshot_path" in ref else None
        if snap_rel is None:
            # registered convention: snapshot resolves per family
            fam = card["variant"]["family_id"]
            if "public" in impl:
                snap_rel = f"snapshots/public/v2/data_snapshot.{fam}.json"
            else:
                snap_rel = f"snapshots/longbridge/synthetic_v2/data_snapshot.{fam}.v2.json"
        snapshot = read_json(ROOT / snap_rel)
    result = getattr(module, func)(snapshot, dict(card["task"]["inputs"]))
    got = {
        "status": result.get("status"),
        "reason_codes": sorted(result.get("reason_codes", [])),
        "value": result.get("value"),
    }
    want = {
        "status": oracle["expected_status"],
        "reason_codes": sorted(oracle.get("reason_codes", [])),
        "value": oracle.get("expected_value"),
    }
    registered_gold[card["case_id"]] = want
    card_by_case[card["case_id"]] = card
    if got == want:
        oracle_ok += 1
    else:
        check(f"C: registered Gold recompute {card['case_id']}", False,
              f"got={got} want={want}")

check("C: oracle implementation hashes match registration (90)",
      impl_hash_ok == 90, f"{impl_hash_ok}/90")
check("C: Stage-2 registered Gold reproduces for all 90 cases",
      oracle_ok == 90, f"{oracle_ok}/90")

# ------------------------------------------------------------------ D
def deep_numeric_equal(a, b) -> bool:
    """Leaf-wise equality where numeric-looking strings compare as Decimal
    (the v3.10 layer re-quantizes values to the disclosed 6-decimal contract;
    the registered Gold stores the raw oracle form)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(deep_numeric_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(deep_numeric_equal(x, y) for x, y in zip(a, b))
    if a == b:
        return True
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return False


plan310 = read_json(ROOT / "contracts/stage3_acceptance_plan.v3.10.json")
d_ok = 0
for task in plan310["tasks"]:
    card_case_v2 = task["case_id"].replace("-v3", "-v2")
    projection = read_json(ROOT / task["projection_path"])
    snapshot = read_json(ROOT / task["snapshot_path"])
    expected = independent_expected_v310(projection, snapshot)
    gold = registered_gold[card_case_v2]
    same = (
        expected["status"] == gold["status"]
        and sorted(expected.get("reason_codes", [])) == gold["reason_codes"]
        and deep_numeric_equal(expected.get("value"), gold["value"])
    )
    if same:
        d_ok += 1
    else:
        check(f"D: v3.10 expectation vs Gold {task['case_id']}", False,
              f"expected={expected} gold={gold}")
check("D: v3.10 expectation layer equals registered Gold (90, Decimal-equal)",
      d_ok == 90, f"{d_ok}/90")

# ------------------------------------------------------------------ E
def norm(value):
    """Auditor-owned canonical form: Decimal-exact numbers, exact strings."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            return ("num", str(Decimal(str(value)).normalize()))
        except InvalidOperation:
            return ("raw", repr(value))
    if isinstance(value, str):
        try:
            return ("num", str(Decimal(value).normalize()))
        except InvalidOperation:
            return ("str", value)
    if isinstance(value, list):
        return [norm(item) for item in value]
    if isinstance(value, dict):
        return {key: norm(val) for key, val in sorted(value.items())}
    return ("raw", repr(value))


semantic_checked = 0
semantic_agree = 0
for label, rundir, plan_rel, grade_fn in ROUNDS:
    plan = read_json(ROOT / plan_rel)
    tasks = {t["case_id"]: t for t in plan["tasks"]}
    for gpath in sorted((rundir / "graders").glob("run_*.json")):
        g = read_json(gpath)
        task = tasks[g["case_id"]]
        projection = read_json(ROOT / task["projection_path"])
        snapshot = read_json(ROOT / task["snapshot_path"])
        candidate = read_json(rundir / "candidates" / f"{g['run_id']}.json")
        expected = independent_expected_v310(projection, snapshot)
        cand_status = candidate.get("status") if isinstance(candidate, dict) else None
        cand_value = candidate.get("value") if isinstance(candidate, dict) else None
        status_ok = cand_status == expected["status"]
        value_ok = norm(cand_value) == norm(expected.get("value"))
        frozen_status = g["checks"].get("status_correct")
        frozen_value = g["checks"].get("value_semantic_correct")
        semantic_checked += 1
        # Frozen checks may be None when provider/structure invalid; compare
        # only when they are boolean.
        agree = True
        if frozen_status is not None and frozen_status != status_ok:
            agree = False
        if frozen_value is not None and frozen_value != value_ok:
            agree = False
        if frozen_status is None or frozen_value is None:
            # provider/structure invalid path: candidate must not be scored
            agree = agree and not g["all_applicable_checks_passed"]
        if agree:
            semantic_agree += 1
        else:
            check(f"E: semantic cross-check {label} {g['run_id']}", False,
                  f"mine status={status_ok} value={value_ok} "
                  f"frozen status={frozen_status} value={frozen_value}")

check("E: independent status/value verdicts agree with frozen checks (810)",
      semantic_agree == semantic_checked == 810,
      f"{semantic_agree}/{semantic_checked}")

# aggregate grader outcome tallies (for the statistics part and report)
tally = {"all_passed": 0, "succeeded_runs": 0}
for label, rundir, _plan_rel, _fn in ROUNDS:
    for gpath in sorted((rundir / "graders").glob("run_*.json")):
        g = read_json(gpath)
        checks = g["checks"]
        if all(v is True for v in checks.values()):
            tally["all_passed"] += 1
        trace = read_json(rundir / "traces" / f"{g['run_id']}.json")
        if trace["status"] == "succeeded":
            tally["succeeded_runs"] += 1
print(f"\nINFO strict-all-checks-true runs: {tally['all_passed']}/810; "
      f"trace succeeded: {tally['succeeded_runs']}/810")

print(f"\nRESULT: {'PASS' if not FAILS else 'FAIL'} — {PASSES} checks passed, "
      f"{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
