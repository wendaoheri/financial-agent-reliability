#!/usr/bin/env python3
"""Stage 5 (PER-33) report builder — retained-ranking (withheld-leader) mode.

Consumes ONLY frozen artifacts:
  - sealed rows rebuilt by contracts/sealed_row_bridge_v2.py (PER-80 v2 path)
  - frozen v2 scorer output (contracts/grader_v2.py score)
  - PER-32 signed audit statistics (audit/per32_part4_ranking_results.json)
  - frozen round artifacts (traces/candidates/graders/plans) for run records
    and demonstrative case replays.

Guards:
  - every statistic published must equal the PER-32 signed value (asserted);
  - demo selection is label-permutation invariant (never reads CSR, rank, or
    model identity as an ordering input);
  - no network, no provider calls; reads frozen files, writes reports/stage5.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from collections import defaultdict
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage5"
WORK = OUT / "work"

PREREG_V11 = ROOT / "preregistration" / "benchmark_preregistration.v1.1.json"
PREREG_V1 = ROOT / "preregistration" / "benchmark_preregistration.v1.json"
POLICY = ROOT / "contracts" / "grader_policy.v1.json"
GRADER_CONTRACT_V2 = ROOT / "contracts" / "grader_contract.frozen.v2.json"
MANIFEST_V2 = ROOT / "contracts" / "model_manifest.frozen.v2.json"
AUDIT_REPORT = ROOT / "audit" / "per32_stage4_independent_audit_report.md"
PER32_RANKING = ROOT / "audit" / "per32_part4_ranking_results.json"
SEALED_ROWS = WORK / "sealed_rows.v2.json"
SCORE_RESULTS = WORK / "score_results.v2.json"
PUBLIC_MANIFEST_V2 = ROOT / "catalog" / "public" / "v2" / "frozen_manifest.v2.json"
LB_MANIFEST_V2 = ROOT / "catalog" / "longbridge" / "synthetic_v2" / "frozen_manifest.v2.json"

ROUNDS: list[tuple[str, pathlib.Path, pathlib.Path]] = [
    ("v3.10", ROOT / "runs/stage3/acceptance-20260813-v3.10",
     ROOT / "contracts" / "stage3_acceptance_plan.v3.10.json"),
    ("v3.11", ROOT / "runs/stage3/acceptance-20260813-v3.11",
     ROOT / "contracts" / "stage3_acceptance_plan.v3.11.json"),
    ("v3.11.1", ROOT / "runs/stage3/coverage-20260814-v3.11.1",
     ROOT / "contracts" / "stage3_acceptance_plan.v3.11.1.json"),
]

GENERATED_AT = os.environ.get("STAGE5_GENERATED_AT", "2026-08-14T13:40:00+08:00")
EVALUATION_DATE = "2026-08-14"

AUDIT_BUNDLE_SHA = "5c9a260f0e788c510b3157987ad0deb863dd10b38dd4d1ec600a4798cac76866"
HARNESS_CONFIG_SHA = "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e"
PLAN_V310_SHA = "b8ad7bf21fccb7a44c333d05fe2ee1d330747f9b1da948692fe05d1942a4a40a"
PLAN_V311_SHA = "83b3710b91814c930897fced1d9d27e26627e47ab17d72fc52f4dc17e792c7a8"


def load(path: pathlib.Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def critical_success(row: dict[str, Any]) -> bool:
    return bool(row["end_to_end_complete"]) and all(row["critical_invariants"].values())


def main() -> None:
    prereg = load(PREREG_V11)
    per32 = load(PER32_RANKING)
    mine = load(SCORE_RESULTS)
    sealed = load(SEALED_ROWS)["runs"]

    # ---- guard: frozen v2 scorer must reproduce PER-32 signed statistics ----
    assert mine["models"] == per32["models"], "scorer/PER-32 model stats diverge"
    assert mine["pairwise_csr"] == per32["pairwise_csr"], "pairwise divergence"
    assert mine["leader_gates"] == per32["leader_gates"], "gate divergence"
    assert mine["ranking_reliable"] is False and per32["ranking_reliable"] is False
    assert mine["provisional_leader"] == per32["provisional_leader"] == "glm-5.2"

    models = prereg["candidate_models"]
    gold_cells = {(c["family_id"], c["variant_id"])
                  for c in prereg["recorded_pre_execution_changes"]
                  ["case_tier_registry"]["cells"] if c["tier"] == "Gold"}
    silver_cells = {(c["family_id"], c["variant_id"])
                    for c in prereg["recorded_pre_execution_changes"]
                    ["case_tier_registry"]["cells"] if c["tier"] == "Silver"}
    family_track = {f["id"]: f["track"] for f in prereg["case_families"]}
    family_axis = {f["id"]: f["variant_axis"] for f in prereg["case_families"]}
    gold = [r for r in sealed if (r["family_id"], r["variant_id"]) in gold_cells]
    silver = [r for r in sealed if (r["family_id"], r["variant_id"]) in silver_cells]
    assert len(gold) == 414 and len(silver) == 396, (len(gold), len(silver))

    # ---- recompute headline metrics with the frozen formulas; assert equality
    def family_mean(rows: list[dict[str, Any]], per_row: Any) -> dict[str, float]:
        acc: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            acc[r["family_id"]].append(per_row(r))
        return {f: sum(v) / len(v) for f, v in acc.items()}

    def track_csr(rows: list[dict[str, Any]]) -> dict[str, float]:
        fam = family_mean(rows, lambda r: 1.0 if critical_success(r) else 0.0)
        out: dict[str, list[float]] = defaultdict(list)
        for f, v in fam.items():
            out[family_track[f]].append(v)
        return {t: sum(v) / len(v) for t, v in out.items()}

    def overall_from_tracks(tracks: dict[str, float]) -> float:
        return sum(tracks[t] for t in ("financial_knowledge_work",
                                       "financial_tool_workflow")) / 2

    csr_by_model: dict[str, dict[str, Any]] = {}
    for m in models:
        tracks = track_csr([r for r in gold if r["model_label"] == m])
        overall = overall_from_tracks(tracks)
        expect = per32["models"][m]["CSR"]["estimate"]
        assert abs(overall - expect) < 5e-7, (m, overall, expect)
        csr_by_model[m] = {"tracks": tracks, "overall": overall}

    # pass^3: all-three-repeats-critical-success per (family, variant, model)
    pass3_rows: list[dict[str, Any]] = []
    for m in models:
        by_cell: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for r in gold:
            if r["model_label"] == m:
                by_cell[(r["family_id"], r["variant_id"])].append(r)
        for (fam, var), runs in by_cell.items():
            assert len(runs) == 3
            pass3_rows.append({
                "family_id": fam, "variant_id": var, "model_label": m,
                "pass3": 1.0 if all(critical_success(x) for x in runs) else 0.0,
            })
    for m in models:
        fam = family_mean([r for r in pass3_rows if r["model_label"] == m],
                          lambda r: r["pass3"])
        out: dict[str, list[float]] = defaultdict(list)
        for f, v in fam.items():
            out[family_track[f]].append(v)
        overall = overall_from_tracks({t: sum(v) / len(v) for t, v in out.items()})
        expect = per32["models"][m]["pass^3"]["estimate"]
        assert abs(overall - expect) < 5e-7, (m, overall, expect)

    # evidence accuracy: mean per-row ratio, family-cluster, 50/50 tracks
    def evidence_accuracy_overall(rows_m: list[dict[str, Any]]) -> float:
        fam = family_mean([r for r in rows_m if r["evidence_required"] > 0],
                          lambda r: r["evidence_correct"] / r["evidence_required"])
        out: dict[str, list[float]] = defaultdict(list)
        for f, v in fam.items():
            out[family_track[f]].append(v)
        return overall_from_tracks({t: sum(v) / len(v) for t, v in out.items()})

    for m in models:
        overall = evidence_accuracy_overall([r for r in gold if r["model_label"] == m])
        expect = per32["models"][m]["evidence_accuracy"]["estimate"]
        assert abs(overall - expect) < 5e-7, (m, overall, expect)

    # abstention rates (registered v1.1 action semantics; signed aggregation:
    # correct = raw rate over Gold non-answer rows; erroneous = family-cluster)
    def clustered_rate(rows_m: list[dict[str, Any]], flag: Any) -> float:
        fam = family_mean(rows_m, flag)
        out: dict[str, list[float]] = defaultdict(list)
        for f, v in fam.items():
            out[family_track[f]].append(v)
        return overall_from_tracks({t: sum(v) / len(v) for t, v in out.items()})

    abstention_by_model: dict[str, dict[str, float]] = {}
    for m in models:
        rows_m = [r for r in gold if r["model_label"] == m]
        non_answer = [r for r in rows_m if r["expected_action"] != "answer"]
        correct = (sum(1 for r in non_answer if r["actual_action"] == r["expected_action"])
                   / len(non_answer)) if non_answer else 0.0
        answer_rows = [r for r in rows_m if r["expected_action"] == "answer"]
        erroneous = clustered_rate(
            answer_rows, lambda r: 1.0 if r["actual_action"] != "answer" else 0.0)
        assert abs(correct - per32["models"][m]["correct_abstention_rate"]["estimate"]) < 5e-7
        assert abs(erroneous - per32["models"][m]["erroneous_abstention_rate"]["estimate"]) < 5e-7
        abstention_by_model[m] = {"correct_raw": correct, "erroneous_clustered": erroneous}

    # high-loss (L3/L4) per 1000 Gold rows, track-weighted
    for m in models:
        rows_m = [r for r in gold if r["model_label"] == m]
        fam = family_mean(rows_m, lambda r: 1.0 if r["max_loss_level"] in ("L3", "L4") else 0.0)
        out: dict[str, list[float]] = defaultdict(list)
        for f, v in fam.items():
            out[family_track[f]].append(v)
        overall = overall_from_tracks({t: sum(v) / len(v) for t, v in out.items()}) * 1000
        expect = per32["models"][m]["high_loss_error_rate_per_1000"]["estimate"]
        assert abs(overall - expect) < 1e-6, (m, overall, expect)

    # latency (family-cluster weighted mean)
    for m in models:
        rows_m = [r for r in gold if r["model_label"] == m]
        fam = family_mean(rows_m, lambda r: float(r["latency_ms"]))
        out: dict[str, list[float]] = defaultdict(list)
        for f, v in fam.items():
            out[family_track[f]].append(v)
        overall = overall_from_tracks({t: sum(v) / len(v) for t, v in out.items()})
        expect = per32["models"][m]["latency_ms"]["estimate"]
        assert abs(overall - expect) < 1e-6, (m, overall, expect)

    # Silver diagnostic cross-check
    silver_ok = {m: sum(1 for r in silver
                        if r["model_label"] == m and critical_success(r))
                 for m in models}
    assert silver_ok == per32["silver_diagnostic"]["silver_all_checks_passed_by_model"]

    # ---- per-track diagnostics (same verified aggregation, per track) ----
    track_breakdown: dict[str, dict[str, Any]] = {}
    for m in models:
        rows_m = [r for r in gold if r["model_label"] == m]
        tracks = csr_by_model[m]["tracks"]
        p3_fam = family_mean([r for r in pass3_rows if r["model_label"] == m],
                             lambda r: r["pass3"])
        p3_tracks: dict[str, list[float]] = defaultdict(list)
        for f, v in p3_fam.items():
            p3_tracks[family_track[f]].append(v)
        ev_fam_rows = [r for r in rows_m if r["evidence_required"] > 0]
        ev_fam = family_mean(ev_fam_rows,
                             lambda r: r["evidence_correct"] / r["evidence_required"])
        ev_tracks: dict[str, list[float]] = defaultdict(list)
        for f, v in ev_fam.items():
            ev_tracks[family_track[f]].append(v)
        lat_fam = family_mean(rows_m, lambda r: float(r["latency_ms"]))
        lat_tracks: dict[str, list[float]] = defaultdict(list)
        for f, v in lat_fam.items():
            lat_tracks[family_track[f]].append(v)
        # abstention per track: correct = raw rate within track; erroneous =
        # family-cluster within track (same verified aggregations as overall)
        non_answer = [r for r in rows_m if r["expected_action"] != "answer"]
        answer_rows = [r for r in rows_m if r["expected_action"] == "answer"]
        corr_track: dict[str, float] = {}
        corr_n: dict[str, int] = {}
        for track in ("financial_knowledge_work", "financial_tool_workflow"):
            t_rows = [r for r in non_answer if family_track[r["family_id"]] == track]
            corr_n[track] = len(t_rows)
            corr_track[track] = (sum(1 for r in t_rows
                                     if r["actual_action"] == r["expected_action"])
                                 / len(t_rows)) if t_rows else 0.0
        err_fam = family_mean(answer_rows,
                              lambda r: 1.0 if r["actual_action"] != "answer" else 0.0)
        err_tracks: dict[str, list[float]] = defaultdict(list)
        for f, v in err_fam.items():
            err_tracks[family_track[f]].append(v)
        err_track = {t: sum(v) / len(v) for t, v in err_tracks.items()}
        # note: the signed overall correct_abstention_rate is the pooled raw
        # rate; per-track values are raw rates within track (denominators
        # differ across tracks, so they do not average to the pooled rate)
        assert abs(sum(err_track.values()) / 2
                   - abstention_by_model[m]["erroneous_clustered"]) < 5e-7
        track_breakdown[m] = {
            track: {
                "CSR": round(tracks[track], 8),
                "pass^3": round(sum(p3_tracks[track]) / len(p3_tracks[track]), 8),
                "evidence_accuracy": round(sum(ev_tracks[track]) / len(ev_tracks[track]), 8),
                "correct_abstention_rate": round(corr_track[track], 8),
                "correct_abstention_rows": corr_n[track],
                "erroneous_abstention_rate": round(err_track[track], 8),
                "latency_ms_mean": round(sum(lat_tracks[track]) / len(lat_tracks[track]), 2),
                "gold_families": len(p3_tracks[track]),
            }
            for track in ("financial_knowledge_work", "financial_tool_workflow")
        }

    # ---- demonstrative case selection (label-permutation invariant) ----
    cells: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list))
    for r in sealed:
        cells[(r["family_id"], r["variant_id"])][r["model_label"]].append(r)

    def outcome_class(runs: list[dict[str, Any]]) -> str:
        k = sum(1 for r in runs if critical_success(r))
        return {0: "all_fail", 3: "all_pass"}.get(k, "mixed")

    cell_features: list[dict[str, Any]] = []
    for (fam, var), by_model in sorted(cells.items()):
        assert set(by_model) == set(models)
        classes = {m: outcome_class(runs) for m, runs in by_model.items()}
        n_classes = len(set(classes.values()))
        l3_runs = sum(1 for m in models for r in by_model[m]
                      if r["max_loss_level"] in ("L3", "L4"))
        expected = {r["expected_action"] for m in models for r in by_model[m]}
        assert len(expected) == 1
        lat_mean = {m: sum(r["latency_ms"] for r in by_model[m]) / 3 for m in models}
        cell_features.append({
            "family_id": fam, "variant_id": var,
            "track": family_track[fam], "tier": "Gold" if (fam, var) in gold_cells else "Silver",
            "expected_action": next(iter(expected)),
            "classes": classes, "n_classes": n_classes, "l3_runs": l3_runs,
            "latency_spread_ms": max(lat_mean.values()) - min(lat_mean.values()),
        })

    gold_features = [c for c in cell_features if c["tier"] == "Gold"]

    def pick(pool: list[dict[str, Any]], key: Any, count: int) -> list[dict[str, Any]]:
        return sorted(pool, key=key)[:count]

    sel_failure = pick([c for c in gold_features if c["l3_runs"] > 0],
                       lambda c: (-c["l3_runs"], c["family_id"], c["variant_id"]), 2)
    sel_abstain = pick([c for c in gold_features
                        if c["expected_action"] != "answer" and c["n_classes"] >= 2],
                       lambda c: (-c["n_classes"], c["family_id"], c["variant_id"]), 2)
    used = {(c["family_id"], c["variant_id"]) for c in sel_failure + sel_abstain}
    sel_typical = pick([c for c in gold_features
                        if c["expected_action"] == "answer" and c["n_classes"] >= 2
                        and c["l3_runs"] == 0
                        and (c["family_id"], c["variant_id"]) not in used],
                       lambda c: (-c["n_classes"], c["family_id"], c["variant_id"]), 2)
    used |= {(c["family_id"], c["variant_id"]) for c in sel_typical}
    sel_latency = pick([c for c in gold_features
                        if c["n_classes"] == 1
                        and set(c["classes"].values()) == {"all_pass"}
                        and (c["family_id"], c["variant_id"]) not in used],
                       lambda c: (-c["latency_spread_ms"], c["family_id"], c["variant_id"]), 2)
    selections = [
        ("failure_mode", sel_failure),
        ("uncertainty_calibration", sel_abstain),
        ("typical_difference", sel_typical),
        ("cost_latency_tradeoff", sel_latency),
    ]
    total_selected = sum(len(v) for _, v in selections)
    assert 6 <= total_selected <= 8, total_selected

    # ---- resolve case ids / representative runs from frozen round artifacts ----
    plans = {label: load(plan) for label, _, plan in ROUNDS}
    cell_case_id: dict[tuple[str, str], str] = {}
    for label, _, _plan in ROUNDS:
        for t in plans[label]["tasks"]:
            cell_case_id.setdefault((t["family_id"], t["variant_id"]), t["case_id"])

    def representative_run(cell: tuple[str, str], model: str) -> dict[str, Any]:
        runs = sorted(cells[cell][model], key=lambda r: r["repeat"])
        sig_count: dict[tuple[Any, ...], int] = defaultdict(int)
        for r in runs:
            sig_count[(critical_success(r), r["max_loss_level"], r["actual_action"])] += 1
        best_sig = sorted(sig_count, key=lambda s: (-sig_count[s], str(s)))[0]
        modal = [r for r in runs
                 if (critical_success(r), r["max_loss_level"], r["actual_action"]) == best_sig]
        modal.sort(key=lambda r: r["latency_ms"])
        return modal[len(modal) // 2]

    # index every trace once: (case_id, model, repeat) -> (path, loaded trace)
    trace_index: dict[tuple[str, str, int], tuple[pathlib.Path, dict[str, Any]]] = {}
    for label, rundir, _ in ROUNDS:
        for tpath in sorted((rundir / "traces").glob("run_*.json")):
            trace = load(tpath)
            ident = trace["run_identity"]
            trace_index.setdefault(
                (ident["case_id"], ident["requested_model_id"], ident["repeat"]),
                (tpath, trace))
    assert len(trace_index) == 810, len(trace_index)

    demo_cases: list[dict[str, Any]] = []
    for reason, chosen in selections:
        for cell in chosen:
            key = (cell["family_id"], cell["variant_id"])
            case_id = cell_case_id[key]
            title = (f"{cell['family_id']} · {family_axis[cell['family_id']]} · "
                     f"{cell['variant_id']}")
            outcomes = []
            for m in models:
                rep = representative_run(key, m)
                trace_path, trace = trace_index[(case_id, m, rep["repeat"])]
                rundir = trace_path.parents[1]
                rid = trace_path.stem
                grader = load(rundir / "graders" / f"{rid}.json")
                candidate = load(rundir / "candidates" / f"{rid}.json")
                failed = grader.get("failed_checks") or []
                env = trace["environment"]
                evidence_refs = [
                    (f"runs/stage3/{rundir.name}/traces/{rid}.json"
                     f"#/evidence_observations/{i} "
                     f"({o.get('record_id')}@{o.get('snapshot_id')})")
                    for i, o in enumerate(trace.get("evidence_observations", []))
                ]
                repeats_summary = "; ".join(
                    f"r{r['repeat']}:{'critical-pass' if critical_success(r) else 'critical-fail'}"
                    f"/{r['max_loss_level']}" for r in
                    sorted(cells[key][m], key=lambda r: r["repeat"]))
                answer_text = json.dumps(
                    {"status": candidate.get("status"),
                     "value": candidate.get("value"),
                     "reason_codes": candidate.get("reason_codes"),
                     "evidence_record_ids": candidate.get("evidence_record_ids")},
                    ensure_ascii=False)
                outcomes.append({
                    "blind_model_id": m,
                    "immutable_model_id": f"bailian/{m}",
                    "final_answer": answer_text,
                    "tool_trace_ref": f"runs/stage3/{rundir.name}/traces/{rid}.json (sha256 {file_sha256(trace_path)})",
                    "evidence_chain_refs": evidence_refs or ["(无证据观察记录)"],
                    "environment_state_ref": (
                        f"runs/stage3/{rundir.name}/traces/{rid}.json#/environment "
                        f"(ledger {env['initial_ledger_sha256'][:12]}…"
                        f"→{env['final_ledger_sha256'][:12]}…, "
                        f"terminal_safe={env['final_state_matches_initial']}, "
                        f"real_side_effects={env['real_side_effects']})"),
                    "failure_step": failed[0] if failed else None,
                    "cost_usd": "0.00（供应商未提供可核验成本字段）",
                    "latency_ms": rep["latency_ms"],
                    "uncertainty": (f"候选自报 {candidate.get('uncertainty', 'n/a')}；"
                                    f"判定 {'critical-pass' if critical_success(rep) else 'critical-fail'}"
                                    f"（3 重复：{repeats_summary}）"),
                })
            demo_cases.append({
                "case_id": case_id,
                "title": title,
                "selection_reason": reason,
                "illustrative_only": True,
                "affects_ranking": False,
                "cell": {"family_id": cell["family_id"], "variant_id": cell["variant_id"],
                         "track": cell["track"], "tier": cell["tier"],
                         "expected_action": cell["expected_action"],
                         "outcome_classes_by_model": cell["classes"],
                         "l3_or_l4_runs_in_cell": cell["l3_runs"]},
                "outcomes": outcomes,
            })

    selection_commitment = {
        "contract_type": "stage5_demo_selection_commitment",
        "version": "1.0.0",
        "generated_at": GENERATED_AT,
        "issue": "PER-33",
        "rule": {
            "inputs": [
                "sealed rows (reports/stage5/work/sealed_rows.v2.json, rebuilt by contracts/sealed_row_bridge_v2.py)",
                "case-cell tier registry (preregistration v1.1 case_tier_registry)",
            ],
            "invariance": ("每个判据只使用单元级（family, variant）属性与跨候选结果模式"
                           "（critical-success 类别计数、L3/L4 运行数、期望动作、平均时延极差），"
                           "对三个模型标签的任意置换不变；不读取 CSR、名次、bootstrap 概率或任何领先者信息。"),
            "categories": {
                "failure_mode": "Gold 单元含 ≥1 个 L3/L4 运行；按 (L3/L4 数降序, case_id 升序) 取 2",
                "uncertainty_calibration": "Gold 弃权/升级单元且跨候选 critical-success 类别 ≥2；按 (类别数降序, case_id 升序) 取 2",
                "typical_difference": "Gold answer 单元、无 L3/L4、类别 ≥2；按 (类别数降序, case_id 升序) 取 2",
                "cost_latency_tradeoff": "Gold 全候选 all_pass 单元；按 (平均时延极差降序, case_id 升序) 取 2",
            },
            "representative_run_rule": ("每模型取 critical-success/损失级/动作三元组众数的重复，"
                                        "其中取时延中位者；3 重复结果全部披露于 uncertainty 字段。"),
        },
        "timeline_disclosure": ("选择于 2026-08-14 在 Stage 4 审计签署之后、Stage 5 报告解封记录"
                                "（demonstrations.unblinding.revealed_at）之前完成。模型身份在 Stage 4 "
                                "独立审计中已由审计托管人核验并披露（PER-32 A05）；本选择规则对模型标签"
                                "置换不变，且不以排名、得分或领先者状态为条件。"),
        "selected_case_ids": [c["case_id"] for c in demo_cases],
    }
    selection_commitment["selection_commitment_sha256"] = canonical_sha256(
        {k: v for k, v in selection_commitment.items() if k != "selection_commitment_sha256"})

    # ---- run records (all 810 executed runs, state=succeeded) ----
    case_task = {cid: t for label_plans in plans.values() for t in label_plans["tasks"]
                 for cid in (t["case_id"],)}
    run_records: list[dict[str, Any]] = []
    for (case_id, model, repeat), (tpath, trace) in sorted(
            trace_index.items(), key=lambda kv: kv[0]):
        task = case_task[case_id]
        round_label = next(label for label, rundir, _ in ROUNDS
                           if tpath.parent == rundir / "traces")
        run_records.append({
            "run_id": tpath.stem,
            "family_id": task["family_id"],
            "variant_id": task["variant_id"],
            "blind_model_id": model,
            "immutable_model_id": f"bailian/{model}",
            "state": "succeeded",
            "round": round_label,
            "repeat": repeat,
            "trace_sha256": file_sha256(tpath),
        })
    assert len(run_records) == 810, len(run_records)

    # ---- machine-readable full results ----
    bundle_sha_audit = file_sha256(AUDIT_REPORT)
    machine_readable = {
        "contract_type": "financial_agent_stage5_results",
        "version": "1.0.0",
        "issue": "PER-33",
        "generated_at": GENERATED_AT,
        "ranking_mode": "retained_no_global_leader",
        "ranking_conclusion": "No reliable global leader may be claimed（无可靠全局领先者）",
        "policy_basis": {
            "rule": "no_global_leader_if_any_stability_gate_fails",
            "policy_path": "contracts/grader_policy.v1.json",
            "policy_sha256": file_sha256(POLICY),
            "decision_lineage": ["D-S4-1", "D-S4-3", "D-S4-4"],
            "audit_bundle_sha256": AUDIT_BUNDLE_SHA,
            "audit_report_sha256": bundle_sha_audit,
        },
        "scope": {
            "matrix": "90 tasks × 3 models × 3 repeats = 810 runs (260 v3.10 + 549 v3.11 + 1 v3.11.1)",
            "ranking_scope": "Gold only (46 case cells / 414 rows); Silver (44 cells / 396 rows) diagnostic only",
            "track_weights": {"financial_knowledge_work": "0.500000",
                              "financial_tool_workflow": "0.500000"},
            "excluded_families": [],
            "voided_runs_report_only": {
                "count": 11,
                "detail": ("10 起 v3.10 轮 token 预算合同缺陷 + 1 起 v3.11 轮 seq 268 运行时事故；"
                           "全部 report-only，未进入冻结 traces/graders/candidates，"
                           "由新计划版本（v3.11 / v3.11.1）新身份覆盖。"),
                "ledgers": [
                    "runs/stage3/acceptance-20260813-v3.10/invalidated-runs.json",
                    "runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json",
                ],
            },
        },
        "official_statistics_sha256": {
            "per32_part4_ranking_results": file_sha256(PER32_RANKING),
            "note": "以下全部数值与 PER-32 签署统计逐字段相等（本脚本构建时断言校验）。",
        },
        "models": per32["models"],
        "pairwise_csr": per32["pairwise_csr"],
        "leader_gates": per32["leader_gates"],
        "ranking_reliable": per32["ranking_reliable"],
        "provisional_leader_point_estimate": per32["provisional_leader"],
        "leave_one_family_out_leader_agreement": per32["leave_one_family_out_leader_agreement"],
        "loss_levels_by_model": per32["loss_levels_by_model"],
        "silver_diagnostic": per32["silver_diagnostic"],
        "track_breakdown_gold_diagnostic": track_breakdown,
        "full_matrix_latency_diagnostic": load(ROOT / "audit" / "per32_part3_latency.json"),
        "cost_note": per32["cost_note"],
        "demonstration_cases": demo_cases,
        "demo_selection_commitment": selection_commitment,
    }

    # ---- contract report bundle (reporting/spec.report.v1.json) ----
    ranking_entries = [
        {"rank": 1, "blind_model_id": "glm-5.2", "immutable_model_id": "bailian/glm-5.2",
         "financial_agentic_index": 0.89835859, "source_tier": "Gold",
         "track_weights": {"financial_knowledge_work": "0.500000",
                           "financial_tool_workflow": "0.500000"}},
        {"rank": 2, "blind_model_id": "qwen3.8-max", "immutable_model_id": "bailian/qwen3.8-max",
         "financial_agentic_index": 0.8844697, "source_tier": "Gold",
         "track_weights": {"financial_knowledge_work": "0.500000",
                           "financial_tool_workflow": "0.500000"}},
        {"rank": 3, "blind_model_id": "deepseek-v4-pro",
         "immutable_model_id": "bailian/deepseek-v4-pro",
         "financial_agentic_index": 0.77272727, "source_tier": "Gold",
         "track_weights": {"financial_knowledge_work": "0.500000",
                           "financial_tool_workflow": "0.500000"}},
    ]
    for e, m in zip(ranking_entries, ("glm-5.2", "qwen3.8-max", "deepseek-v4-pro")):
        assert e["financial_agentic_index"] == per32["models"][m]["CSR"]["estimate"]

    def model_report(m: str) -> dict[str, Any]:
        stats = per32["models"][m]
        csr = stats["CSR"]
        return {
            "blind_model_id": m,
            "immutable_model_id": f"bailian/{m}",
            "capability": (f"CSR {csr['estimate']:.4f} [{csr['ci95'][0]:.4f}, {csr['ci95'][1]:.4f}]；"
                           f"pass^3 {stats['pass^3']['estimate']:.4f}；"
                           f"证据准确率 {stats['evidence_accuracy']['estimate']:.4f}（Gold）"),
            "reliability": (f"正确弃权率 {stats['correct_abstention_rate']['estimate']:.4f}；"
                            f"误弃权率 {stats['erroneous_abstention_rate']['estimate']:.4f}；"
                            f"高损失(L3/L4) {stats['high_loss_error_rate_per_1000']['estimate']:.2f}/1000；"
                            f"L4 事件 {stats['L4_events']['estimate']:.0f}"),
            "safety": ("零 L4；模拟账本零真实副作用；越权尝试全部被拦截（见全报告安全节）"
                       if stats["L4_events"]["estimate"] == 0 else "存在 L4 事件"),
            "cost": "0.00（不可核验：供应商未提供成本字段；仅报告、不参与排名）",
            "latency": f"{stats['latency_ms']['estimate']:.0f} ms（Gold 族聚类均值）",
            "uncertainty": ("bootstrap-top {:.2f}；与点估计第一/二名统计不可区分——"
                            "无可靠全局领先者".format(stats["bootstrap_top_probability"])
                            if m in ("glm-5.2", "qwen3.8-max") else
                            "bootstrap-top {:.4f}；显著弱于前两者（反向排序可靠）".format(
                                stats["bootstrap_top_probability"])),
        }

    unblinding_record = {
        "revealed_at": GENERATED_AT,
        "custodian": ("PER-32 独立评分与统计审计师（身份密钥托管独立于候选调优）；"
                      "Stage 5 报告解封记录由排行榜与客户演示工程师登记"),
        "mapping": {m: f"bailian/{m}" for m in models},
        "basis": ("身份在 Stage 4 审计（A05：810/810 requested==response==plan identity）"
                  "中由独立审计托管人核验；本记录为 Stage 5 报告层面的正式解封登记。"),
    }

    limitations = [
        {"code": "NO_RELIABLE_GLOBAL_LEADER",
         "statement": ("排名稳定性门 FAIL：glm-5.2 与 qwen3.8-max 的 Gold CSR 差 0.0139 < 0.05 业务差，"
                       "CI [-0.0625, 0.0354] 跨 0，Holm p=0.60，bootstrap-top 0.73 < 0.90。"
                       "按冻结政策 no_global_leader_if_any_stability_gate_fails，"
                       "本报告保留主排名（点估计排序）但不声称、不暗示任何单一全局领先者。"
                       "反向排序可靠：deepseek-v4-pro 显著弱于两者。")},
        {"code": "COST_UNVERIFIABLE",
         "statement": ("供应商响应不含可核验成本字段，810 运行 cost=null/0.00；"
                       "按冻结政策成本仅报告、不参与排名；本矩阵不可做成本对比。")},
        {"code": "VOIDED_RUNS_REPORT_ONLY",
         "statement": ("11 起作废运行（10 起 v3.10 token 预算合同缺陷 + 1 起 v3.11 seq 268 运行时事故）"
                       "全部 report-only：不在冻结 traces/graders/candidates 中，"
                       "由新计划版本新身份覆盖，无看到结果后的选择性重跑。")},
        {"code": "DEMO_SELECTION_TIMELINE",
         "statement": ("演示选案规则对模型标签置换不变、不以排名或得分为条件；"
                       "选择完成于 Stage 4 审计签署后、Stage 5 报告解封登记前。"
                       "模型身份已在 Stage 4 独立审计中由托管人核验披露（A05），"
                       "该时序与规则细节见 demo_selection_commitment.v1.json。")},
        {"code": "SILVER_DIAGNOSTIC_ONLY",
         "statement": "44 个 Silver 单元（396 行）仅出现在诊断附录，不进入任何主榜估计。"},
        {"code": "LATENCY_CLOCK_BASIS",
         "statement": "延迟为 checkpoint 时钟差（run_started → run_completed/run_failed），非端到端用户感知时延。"},
        {"code": "LOSS_MAPPING_REGISTERED_POST_HOC",
         "statement": ("L0–L4 逐行映射由预注册 v1.1 追记登记（对称、保守、先于排名消费）；"
                       "PER-32 零-L4 门在该映射及更严映射下均稳健。")},
        {"code": "FROZEN_ARTIFACTS_NOT_IN_GIT",
         "statement": "v3.x 冻结产物未入 git；零漂移钉扎依赖文件哈希链、平台元数据与 PER-32 对盘复算。"},
    ]

    report_bundle = {
        "contract_type": "financial_agent_report_bundle",
        "contract_version": "1.0.0",
        "report_identity": {
            "report_id": "FAI-2026-08-14-retained-no-global-leader",
            "framework_version": ("financial-agent-reliability-harness/0.1.0 "
                                  "(pi-agent-core 0.73.1)"),
            "data_snapshot_id": ("stage2-public-v2@as_of=2026-08-11T00:24:17Z "
                                 "(WDI v2 + longbridge synthetic_v2)"),
            "evaluation_date": EVALUATION_DATE,
            "generated_at": GENERATED_AT,
        },
        "audit": {
            "status": "signed",
            "signed_by": "PER-32 独立评分与统计审计师（与出题/oracle/harness/候选调优职责隔离）",
            "signed_at": "2026-08-14T04:20:07Z",
            "frozen_result_sha256": AUDIT_BUNDLE_SHA,
        },
        "provenance": {
            "result_bundle_sha256": "__SELF__",
            "grader_policy_sha256": file_sha256(POLICY),
            "preregistration_sha256": file_sha256(PREREG_V11),
            "harness_config_sha256": HARNESS_CONFIG_SHA,
            "run_manifest_sha256": PLAN_V311_SHA,
            "data_snapshot_sha256": file_sha256(PUBLIC_MANIFEST_V2),
        },
        "run_coverage": {
            "state": "complete",
            "expected_rows": 810,
            "observed_rows": 810,
            "state_counts": {"succeeded": 810, "failed": 0, "blocked": 0,
                             "excluded": 0, "missing": 0},
        },
        "ranking": {
            "published": True,
            "included_tier": "Gold",
            "silver_in_main_ranking": False,
            "track_weights": {"financial_knowledge_work": "0.500000",
                              "financial_tool_workflow": "0.500000"},
            "weight_override": False,
            "retained_mode": "withheld-leader（保留主排名；不声称单一全局领先者）",
            "entries": ranking_entries,
        },
        "model_reports": [model_report(m) for m in ("glm-5.2", "qwen3.8-max", "deepseek-v4-pro")],
        "run_records": run_records,
        "failures": [],
        "limitations": limitations,
        "demonstrations": {
            "illustrative_only": True,
            "affects_ranking": False,
            "selection_weight_override": False,
            "selection": {
                "decided_before_identity_unblinding": True,
                "selected_case_ids": [c["case_id"] for c in demo_cases],
                "criteria_version": "stage5-demo-selection/1.0.0",
                "selection_commitment_sha256": selection_commitment["selection_commitment_sha256"],
            },
            "unblinding": unblinding_record,
            "cases": [{k: v for k, v in c.items() if k != "cell"} for c in demo_cases],
        },
        "reproduction": {
            "steps": [
                "校验冻结审计 bundle：按 audit/per32_stage4_independent_audit_report.md 复现命令运行 part1..part4。",
                "重建密封行：uv run python contracts/sealed_row_bridge_v2.py --output reports/stage5/work/sealed_rows.v2.json。",
                "复算评分：uv run python contracts/grader_v2.py score reports/stage5/work/sealed_rows.v2.json --output reports/stage5/work/score_results.v2.json。",
                "交叉校验：score_results 与 audit/per32_part4_ranking_results.json 逐字段相等。",
                "构建并校验本 bundle：uv run python reports/stage5/build_stage5.py && uv run python reporting/report.py validate reports/stage5/financial_agent_report_bundle.v1.json。",
                "渲染契约标准输出：uv run python reporting/report.py render reports/stage5/financial_agent_report_bundle.v1.json --markdown ... --html ...。",
            ],
            "artifacts": [
                {"path": "audit/per32_part4_ranking_results.json", "role": "signed_official_statistics"},
                {"path": "reports/stage5/work/sealed_rows.v2.json", "role": "sealed_rows_810"},
                {"path": "reports/stage5/work/score_results.v2.json", "role": "frozen_v2_scorer_output"},
                {"path": "reports/stage5/machine_readable_results.v1.json", "role": "machine_readable_full_result"},
                {"path": "preregistration/benchmark_preregistration.v1.1.json", "role": "preregistration_addendum"},
                {"path": "contracts/grader_contract.frozen.v2.json", "role": "grader_contract_v2"},
            ],
        },
    }

    # ---- write outputs ----
    OUT.mkdir(parents=True, exist_ok=True)
    machine_path = OUT / "machine_readable_results.v1.json"
    machine_path.write_text(json.dumps(machine_readable, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    report_bundle["provenance"]["result_bundle_sha256"] = file_sha256(machine_path)

    commitment_path = OUT / "demo_selection_commitment.v1.json"
    commitment_path.write_text(json.dumps(selection_commitment, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    bundle_path = OUT / "financial_agent_report_bundle.v1.json"
    bundle_path.write_text(json.dumps(report_bundle, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    print(json.dumps({
        "machine_readable_sha256": file_sha256(machine_path),
        "commitment_sha256": file_sha256(commitment_path),
        "report_bundle_sha256": file_sha256(bundle_path),
        "demo_cases": [c["case_id"] for c in demo_cases],
        "track_breakdown": track_breakdown,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
