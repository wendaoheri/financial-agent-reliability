"""PER-62 independent audit of the v3.11 continuation plan (items 3-6 + caps).

Read-only. Covers:
  item3 coverage_map <-> v3.10 invalidation forensics exact 1:1 correspondence
        (+ ordering by v3.10 sequence, forensics file hash, report_sha256).
  item4 zero intersection of the 550 new run_ids vs all v3.5-v3.10 plan ids,
        plus internal uniqueness of the 550.
  item5 plan field semantics + on-disk existence of forensics artifacts.
  item6 coverage completeness of the extension (90x3x{2,3}) and of the 10
        coverage units (== the 10 invalidated units).
  caps  reconciliation of continuation_run_cap / registered_total_run_cap /
        planned_run_cap / first_round_run_cap and 550 = 10 + 540.

Usage:
    python3 audit/per62_plan_audit.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
V310_DIR = ROOT / "runs" / "stage3" / "acceptance-20260813-v3.10"

PLAN_PATH = CONTRACTS / "stage3_acceptance_plan.v3.11.json"
FORENSICS_PATH = V310_DIR / "invalidated-runs.json"
MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
HIST_VERSIONS = ["v3.5", "v3.6", "v3.7", "v3.8", "v3.9", "v3.10"]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    plan = load_json(PLAN_PATH)
    runs = plan["runs"]
    forensics = load_json(FORENSICS_PATH)
    entries = forensics["entries"]
    entries_by_seq = sorted(entries, key=lambda e: e["sequence"])
    coverage = [row for row in runs if row["repeat"] == 1]
    extension = [row for row in runs if row["repeat"] in (2, 3)]

    # ---- item3: coverage_map exact correspondence ----
    covmap = plan["coverage_map"]
    check(len(covmap) == 10, "item3: coverage_map has exactly 10 entries")
    check(len(entries) == 10, "item3: forensics record exactly 10 invalidated units")
    check(set(covmap) == {row["run_id"] for row in coverage}, "item3: coverage_map keys == the 10 coverage run_ids")

    mapped = 0
    order_ok = True
    for idx, row in enumerate(coverage):
        mapping = covmap.get(row["run_id"])
        source = entries_by_seq[idx]
        exact = (
            mapping is not None
            and mapping["v3_10_run_id"] == source["run_id"]
            and mapping["v3_10_sequence"] == source["sequence"]
            and mapping["case_id"] == source["case_id"] == row["run_identity"]["case_id"]
            and mapping["model_id"] == source["model_id"] == row["model_id"]
            and mapping["repeat"] == 1 == source["repeat"] == row["repeat"]
            and source["replaced_or_reexecuted"] is False
            and row["run_id"] != source["run_id"]
        )
        mapped += exact
        if mapping is not None and mapping["v3_10_sequence"] != source["sequence"]:
            order_ok = False
    check(mapped == 10, f"item3: {mapped}/10 coverage runs map exactly onto invalidated forensics (case/model/repeat/run_id/sequence)")
    check(order_ok, "item3: coverage sequences 1..10 follow ascending v3.10 sequence order")
    check(sha256_file(FORENSICS_PATH) == plan["replication_design"]["v3_10_invalidation_forensics"]["invalidated_runs_file_sha256"],
          "item3: invalidated-runs.json SHA-256 == declared e6cf5d98... forensics hash")
    check(plan["replication_design"]["v3_10_invalidation_forensics"]["invalidation_report_sha256"] == forensics["report_sha256"],
          "item3: invalidation_report_sha256 == file report_sha256")
    check(sha256_text(canonical({k: v for k, v in forensics.items() if k != "report_sha256"})) == forensics["report_sha256"],
          "item3: report_sha256 self-consistent (sha of canonical doc minus the field)")

    # ---- item4: zero intersection + internal uniqueness ----
    historical: set[str] = set()
    for ver in HIST_VERSIONS:
        historical.update(row["run_id"] for row in load_json(CONTRACTS / f"stage3_acceptance_plan.{ver}.json")["runs"])
    new_ids = [row["run_id"] for row in runs]
    new_set = set(new_ids)
    check(len(historical) == 990, f"item4: historical v3.5-v3.10 distinct run_ids == 990 (actual {len(historical)})")
    check(len(new_set) == 550, "item4: 550 new run_ids mutually distinct")
    check(not (new_set & historical), f"item4: intersection with {len(historical)} historical ids is empty")

    # ---- item5: field semantics + existence ----
    fx = plan["replication_design"]["v3_10_invalidation_forensics"]
    check(plan["continuation_run_cap"] == 550, "item5: continuation_run_cap == 550")
    check(fx["coverage_replaces_or_reexecutes_invalidation"] is False,
          "item5: coverage_replaces_or_reexecutes_invalidation == false")
    check(plan["replication_design"]["invalidation_policy"] != "", "item5: invalidation_policy present")
    check((V310_DIR / "grading-failures").is_dir(), "item5: grading-failures/ directory exists")
    check(FORENSICS_PATH.is_file(), "item5: invalidated-runs.json exists")

    # ---- item6: coverage completeness ----
    cells = Counter((row["run_identity"]["case_id"], row["model_id"], row["repeat"]) for row in extension)
    case_ids = {task["case_id"] for task in plan["tasks"]}
    expected = {(cid, model, rep) for cid in case_ids for model in MODELS for rep in (2, 3)}
    check(len(extension) == 540, "item6: extension block has 540 runs")
    check(set(cells) == expected and max(cells.values()) == 1, "item6: extension == 90 cases x 3 models x repeats{2,3} each exactly once")
    model_rank = {m: i for i, m in enumerate(MODELS)}
    ext_keys = [(row["repeat"], row["run_identity"]["case_id"], model_rank[row["model_id"]]) for row in extension]
    check(ext_keys == sorted(ext_keys), "item6: extension ordered repeat-major, then case_id, then fixed model order")
    cov_units = {(row["run_identity"]["case_id"], row["model_id"]) for row in coverage}
    inv_units = {(e["case_id"], e["model_id"]) for e in entries}
    check(cov_units == inv_units, "item6: 10 coverage (case,model) units == the 10 invalidated units")
    check(Counter(row["model_id"] for row in coverage) == Counter(e["model_id"] for e in entries),
          "item6: coverage model split matches invalidated (glm-5.2 x9, deepseek-v4-pro x1)")

    # ---- caps reconciliation ----
    hc = load_json(CONTRACTS / "run_trace_harness_config.v3.11.json")["execution"]
    hc10 = load_json(CONTRACTS / "run_trace_harness_config.v3.10.json")["execution"]
    p10 = load_json(CONTRACTS / "stage3_acceptance_plan.v3.10.json")
    n_cases = hc["case_count"]
    n_models = hc["models_per_case"]
    check(hc["planned_run_cap"] == 550 and hc10["planned_run_cap"] == 810, "caps: planned_run_cap 810(v3.10) -> 550(v3.11)")
    check(hc["first_round_run_cap"] == 270 == n_cases * n_models, "caps: first_round_run_cap == 270 == 90x3")
    check(plan["registered_total_run_cap"] == len(runs) == 550, "caps: registered_total_run_cap == len(runs) == 550 (v3.11)")
    check(p10["registered_total_run_cap"] == len(p10["runs"]) == 810, "caps: v3.10 registered_total_run_cap == len(its runs) == 810 (per-version semantics)")
    check(550 == 10 + 540 and 540 == n_cases * n_models * 2 and 810 == n_cases * n_models * 3, "caps: 550 == 10+540; 540 == 90x3x2; 810 == 90x3x3")

    print()
    if failures:
        print(f"RESULT: FAIL - {len(failures)} check(s) failed")
        return 1
    print("RESULT: PASS - items 3-6 and caps reconciliation green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
