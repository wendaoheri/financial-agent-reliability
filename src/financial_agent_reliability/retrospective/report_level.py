"""B3 / A5:报告层结论一致性与冻结捆扎复核(stage5 合并口径)。

复盘链(全部只读、纯函数重算,不写任何冻结目录):

1. grader 捆扎冻结复核:``contracts.grader_v2.validate_frozen_contract`` +
   ``verify_freeze``(A5);
2. 报告捆扎冻结复核:``financial_agent_reliability.reporting.report.verify_freeze``;
3. 密封行重建:``contracts.sealed_row_bridge_v2.build_bundle`` 从三轮冻结
   round 产物(v3.10 r1 + v3.11 r2-3 + v3.11.1 覆盖单元)重建 810 行;
4. 结论重算:``contracts.grader_v2.score_results`` 对密封行束重新评分,
   与落盘 ``reports/stage5/work/score_results.v2.json``、PER-32 签署统计
   ``audit/per32_part4_ranking_results.json`` 逐字段比对(逐位相等);
5. 排名导出(差距项 L3/A2):由重算结果导出显式 Gold CSR 排名。
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from financial_agent_reliability.retrospective.registry import REPO_ROOT
from financial_agent_reliability.retrospective.hashing import file_sha256


def _load_module(name: str, relative: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def check_grader_bundle_freeze() -> dict[str, Any]:
    """A5:grader 捆扎 + 预注册/政策一致性(冻结 grader_v2 原样执行)。"""
    from contracts.grader_v2 import validate_frozen_contract, verify_freeze

    problems: list[str] = []
    try:
        validate_frozen_contract()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"validate_frozen_contract: {exc}")
    try:
        freeze = verify_freeze()
    except Exception as exc:  # noqa: BLE001
        freeze = {}
        problems.append(f"verify_freeze: {exc}")
    return {"ok": not problems, "problems": problems, "freeze": freeze}


def check_report_bundle_freeze() -> dict[str, Any]:
    """A5:报告捆扎(report_contract.frozen.v1.json)冻结复核。"""
    from financial_agent_reliability.reporting.report import verify_freeze

    problems: list[str] = []
    try:
        freeze = verify_freeze()
    except Exception as exc:  # noqa: BLE001
        freeze = {}
        problems.append(f"report verify_freeze: {exc}")
    return {"ok": not problems, "problems": problems, "freeze": freeze}


def recompute_report_level() -> dict[str, Any]:
    """B3:重建密封行 + 重评分 + 与落盘统计逐字段比对。"""
    bridge = _load_module("retrospective_sealed_bridge", "contracts/sealed_row_bridge_v2.py")
    from contracts.grader_v2 import score_results

    problems: list[str] = []
    bundle = bridge.build_bundle()
    sealed_path = REPO_ROOT / "reports" / "stage5" / "work" / "sealed_rows.v2.json"
    persisted_sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    if bundle != persisted_sealed:
        problems.append("sealed rows rebuild != persisted reports/stage5/work/sealed_rows.v2.json")

    score = score_results(bundle)
    score_path = REPO_ROOT / "reports" / "stage5" / "work" / "score_results.v2.json"
    persisted_score = json.loads(score_path.read_text(encoding="utf-8"))
    if score != persisted_score:
        problems.append("score_results recompute != persisted score_results.v2.json")

    per32_path = REPO_ROOT / "audit" / "per32_part4_ranking_results.json"
    per32 = json.loads(per32_path.read_text(encoding="utf-8"))
    for key in ("models", "pairwise_csr", "leader_gates", "ranking_reliable", "provisional_leader"):
        ours = score.get(key)
        theirs = per32.get(key)
        if key == "models":
            ours, theirs = score.get("models"), per32.get("models")
        if ours != theirs:
            problems.append(f"recomputed {key} != PER-32 signed statistics")

    machine_path = REPO_ROOT / "reports" / "stage5" / "machine_readable_results.v1.json"
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    if machine.get("ranking_reliable") != score.get("ranking_reliable"):
        problems.append("published ranking_reliable != recomputed")
    if machine.get("leader_gates") != score.get("leader_gates"):
        problems.append("published leader_gates != recomputed")
    if machine.get("pairwise_csr") != score.get("pairwise_csr"):
        problems.append("published pairwise_csr != recomputed")
    leader_point = machine.get("provisional_leader_point_estimate", {})
    if isinstance(leader_point, dict) and leader_point.get("model") != score.get("provisional_leader"):
        problems.append("published provisional leader != recomputed")

    return {
        "ok": not problems,
        "problems": problems,
        "sealed_rows": len(bundle.get("runs", [])),
        "provisional_leader": score.get("provisional_leader"),
        "ranking_reliable": score.get("ranking_reliable"),
        "machine_readable_sha256": file_sha256(machine_path),
        "score_results_sha256": file_sha256(score_path),
        "sealed_rows_sha256": file_sha256(sealed_path),
    }


def export_ranking() -> dict[str, Any]:
    """差距项 L3/A2:由重算统计导出显式排名(仅 Gold,诊断 Silver 不入榜)。"""
    bridge = _load_module("retrospective_sealed_bridge", "contracts/sealed_row_bridge_v2.py")
    from contracts.grader_v2 import score_results

    score = score_results(bridge.build_bundle())
    entries = []
    for model, metrics in score.get("models", {}).items():
        csr = metrics.get("CSR", {})
        entries.append({
            "model": model,
            "gold_csr_estimate": csr.get("estimate"),
            "gold_csr_ci95": csr.get("ci95"),
            "pass3_estimate": metrics.get("pass^3", {}).get("estimate"),
            "correct_abstention_rate": metrics.get("correct_abstention_rate", {}).get("estimate"),
            "high_loss_error_rate_per_1000": metrics.get("high_loss_error_rate_per_1000", {}).get("estimate"),
            "l4_events": metrics.get("L4_events", {}).get("estimate"),
            "bootstrap_top_probability": metrics.get("bootstrap_top_probability"),
        })
    entries.sort(key=lambda item: (-(item["gold_csr_estimate"] or -1.0), item["model"]))
    for rank, item in enumerate(entries, start=1):
        item["gold_csr_rank"] = rank
    return {
        "contract_type": "retrospective_ranking_export",
        "ranking_scope": score.get("ranking_scope"),
        "ranking_reliable": score.get("ranking_reliable"),
        "ranking_conclusion": score.get("ranking_conclusion"),
        "provisional_leader": score.get("provisional_leader"),
        "leader_gates": score.get("leader_gates"),
        "excluded_families": score.get("excluded_families"),
        "entries": entries,
    }
