"""PER-61 programmatic diff: v3.11 superseding contracts vs v3.10.

Produces a machine-readable, key-level diff demonstrating that the v3.11 change
scope is minimal and confined to:
  1. the cumulative total_tokens ceiling (config resource_budget + schema maximum),
  2. the run_identity repeat enum (1 -> {1,2,3}) so the continuation can execute,
  3. version tags / supersedes / plan-continuation metadata,
while prompts, oracle expectations, scoring thresholds, reason semantics, and case
materials are byte-identical. Run: uv run python audit/build_stage3_v3_11_diff.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def deep_diff(old, new, path="$"):
    """Return a list of (path, kind, old, new) leaf differences."""
    diffs = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            child = f"{path}.{key}"
            if key not in old:
                diffs.append((child, "added", None, new[key]))
            elif key not in new:
                diffs.append((child, "removed", old[key], None))
            else:
                diffs.extend(deep_diff(old[key], new[key], child))
    elif isinstance(old, list) and isinstance(new, list):
        if old != new:
            diffs.append((path, "changed", old, new))
    else:
        if old != new:
            diffs.append((path, "changed", old, new))
    return diffs


def summarize(pairs):
    return [{"path": p, "kind": k, "old": o, "new": n} for p, k, o, n in pairs]


def main() -> int:
    report = {"contract_transition": "v3.10 -> v3.11", "issue": "PER-61", "files": {}}

    # --- harness config ---
    cfg_old, cfg_new = load("contracts/run_trace_harness_config.v3.10.json"), load("contracts/run_trace_harness_config.v3.11.json")
    report["files"]["run_trace_harness_config"] = summarize(deep_diff(cfg_old, cfg_new))

    # --- run trace schema ---
    sch_old, sch_new = load("contracts/run_trace.schema.v3.10.json"), load("contracts/run_trace.schema.v3.11.json")
    report["files"]["run_trace.schema"] = summarize(deep_diff(sch_old, sch_new))

    # --- reason codes (content must be identical except version/supersedes) ---
    rc_old, rc_new = load("contracts/reason_codes.v3.10.json"), load("contracts/reason_codes.v3.11.json")
    report["files"]["reason_codes"] = summarize(deep_diff(rc_old, rc_new))

    # --- candidate output + wire contracts ---
    report["files"]["candidate_output_contracts"] = summarize(deep_diff(load("contracts/candidate_output_contracts.v3.10.json"), load("contracts/candidate_output_contracts.v3.11.json")))
    report["files"]["candidate_submission_wire_contract"] = summarize(deep_diff(load("contracts/candidate_submission_wire_contract.v3.10.json"), load("contracts/candidate_submission_wire_contract.v3.11.json")))
    report["files"]["stage3_independent_grader_result.schema"] = summarize(deep_diff(load("contracts/stage3_independent_grader_result.schema.v3.10.json"), load("contracts/stage3_independent_grader_result.schema.v3.11.json")))

    # --- projections: all 90 must differ only in contract_version/supersedes ---
    projection_diff_kinds = set()
    projection_nonversion_diffs = []
    for case_file in sorted((ROOT / "cases/candidate_v3_10").glob("*.json")):
        case_id = case_file.name
        old = load(f"cases/candidate_v3_10/{case_id}")
        new = load(f"cases/candidate_v3_11/{case_id}")
        for path, kind, old_v, new_v in deep_diff(old, new):
            top = path.split(".")[1] if "." in path else path
            projection_diff_kinds.add(top)
            if top not in {"contract_version", "supersedes"}:
                projection_nonversion_diffs.append({"case": case_id, "path": path, "kind": kind})
    report["projection_diff_top_level_fields"] = sorted(projection_diff_kinds)
    report["projection_non_version_diff_count"] = len(projection_nonversion_diffs)
    report["projection_non_version_diffs_sample"] = projection_nonversion_diffs[:5]

    out = ROOT / "audit" / "stage3_v3_11_v3_10_programmatic_diff.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # --- console summary ---
    print(f"wrote {out.relative_to(ROOT)}")
    for name, diffs in report["files"].items():
        changed_paths = [d["path"] for d in diffs]
        print(f"\n[{name}] {len(diffs)} leaf difference(s):")
        for cp in changed_paths:
            print(f"    {cp}")
    print(f"\nprojection top-level changed fields: {report['projection_diff_top_level_fields']}")
    print(f"projection non-version diffs: {report['projection_non_version_diff_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
