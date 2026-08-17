"""复盘编排与判定(口径 3.3 / 3.4 / 5)。

逐批次串联 A 组(证据链完整性)与 B 组(结论一致性)检查,按三档判定:

- ``traceable``:适用判定项全部通过,无缺失节点;
- ``partially_traceable``:完整性通过但个别判定项缺失/降级(点名标注);
- ``untraceable``:任一链锚断裂(哈希不符、缺件、重算不一致)。

缺失 ≠ 失败 ≠ 通过:协议门/诊断类批次按设计无验收评分节点,其判定只
针对该批次实际承载的结论(协议门/预检/冒烟),并以 scope_note 明示边界。
"""

from __future__ import annotations

import json
from typing import Any

from financial_agent_reliability.retrospective.labels import labels_for_batch
from financial_agent_reliability.retrospective.manifest_check import (
    check_bundle_manifest,
)
from financial_agent_reliability.retrospective.model import (
    DEGRADED,
    FAIL,
    NA,
    PARTIALLY_TRACEABLE,
    PASS,
    TRACEABLE,
    UNTRACEABLE,
    BatchRetrospection,
    CheckResult,
)
from financial_agent_reliability.retrospective.registry import (
    REPO_ROOT,
    BatchRecord,
)
from financial_agent_reliability.retrospective.run_checks import retrospect_runs
from financial_agent_reliability.retrospective.scenario_check import (
    check_scenario_inputs,
)
from financial_agent_reliability.retrospective.summary_check import (
    check_summary_recompute,
)


def _inventory_correspondence(batch: BatchRecord) -> CheckResult:
    """traces/graders/checkpoints 三类产物按 run_id 一一对应(冒烟类批次)。"""
    batch_dir = batch.directory
    stems: dict[str, set[str]] = {}
    for sub in ("traces", "graders", "checkpoints"):
        directory = batch_dir / sub
        stems[sub] = (
            {path.stem for path in directory.glob("*")} if directory.is_dir() else set()
        )
    if not any(stems.values()):
        return CheckResult(
            name="A3_run_inventory", status=NA,
            details=("no run artifact directories (protocol-gate/diagnostic batch)",),
        )
    union = set().union(*stems.values())
    problems = []
    for sub, ids in stems.items():
        missing = union - ids
        if missing:
            problems.append(f"{sub} 缺少 {len(missing)} 个 run_id")
    summary_path = batch_dir / "summary.json"
    counts: dict[str, Any] = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        counts = summary.get("counts", {})
        if counts and counts.get("completed") != len(stems.get("traces", set())):
            problems.append("summary.counts.completed 与盘上 traces 数不符")
    status = FAIL if problems else PASS
    return CheckResult(
        name="A3_run_inventory",
        status=status,
        details=tuple(problems) or ("run artifacts correspond 1:1",),
        metrics={sub: len(ids) for sub, ids in stems.items()},
    )


def _protocol_gate_check(batch: BatchRecord) -> CheckResult:
    """协议门批次:按设计无验收运行;复核'无运行'这一事实本身。"""
    batch_dir = batch.directory
    if not batch_dir.is_dir():
        return CheckResult(
            name="A_protocol_gate_scope", status=FAIL,
            details=(f"batch directory missing: {batch_dir}",),
        )
    stray = [
        sub for sub in ("traces", "graders", "candidates")
        if (batch_dir / sub).is_dir()
    ]
    artifacts = sorted(path.name for path in batch_dir.iterdir() if path.is_file())
    details = [f"protocol-gate artifacts on disk: {', '.join(artifacts) or '(none)'}"]
    if stray:
        return CheckResult(
            name="A_protocol_gate_scope", status=FAIL,
            details=(f"unexpected run artifact directories: {stray}",),
        )
    note = ""
    if batch.batch_id == "acceptance-v3.4":
        contract = json.loads(
            (REPO_ROOT / "contracts" / "stage3_acceptance_contracts.frozen.v3.4.json").read_text(
                encoding="utf-8"
            )
        )
        authorized = contract.get("preflight_execution", {}).get("acceptance_runs_authorized")
        note = f"contract preflight_execution.acceptance_runs_authorized={authorized}"
        if authorized is not False:
            return CheckResult(
                name="A_protocol_gate_scope", status=FAIL,
                details=("v3.4 contract no longer forbids acceptance runs",),
            )
    return CheckResult(
        name="A_protocol_gate_scope",
        status=PASS,
        details=tuple(details + ([note] if note else [])),
        metrics={"files": len(artifacts)},
    )


def _missing_governance_documents(batch: BatchRecord) -> tuple[str, ...]:
    """F2:治理文书缺失检测(M1 降级标注的导出依据)。

    M1 由批内目录的事实导出——``preflight.json`` / ``authorization.run.json``
    缺失即命中,不再按 ``batch_id`` 硬编码;任何验收/覆盖批次缺文书都会
    落入同一检测。返回缺失文书的短名(固定顺序,保证输出稳定)。
    """
    documents = (
        ("authorization.run.json", "authorization.run"),
        ("preflight.json", "preflight"),
    )
    return tuple(
        label for name, label in documents if not (batch.directory / name).is_file()
    )


def _governance_check(batch: BatchRecord, runs: Any) -> CheckResult:
    """治理节点(preflight/授权/冻结输入)汇总为单项检查。"""
    problems = list(runs.frozen_input_errors)
    degraded: list[str] = []
    preflight_problems = list(runs.preflight_errors)
    authorization_problems = list(runs.authorization_errors)

    missing_documents = _missing_governance_documents(batch)
    if missing_documents:
        # M1:治理文书缺失——由检测导出降级标注(而非按 batch_id 硬编码),
        # 按口径 3.4 降级而非失败。
        short_id = batch.batch_id.removeprefix("acceptance-").removeprefix("coverage-")
        degraded.append(
            f"M1:{short_id} 授权记录缺失({'/'.join(missing_documents)} 均无)"
        )
    problems.extend(preflight_problems)
    problems.extend(authorization_problems)
    problems.extend(runs.invalidation_notes)

    status = FAIL if problems else (PASS if not degraded else DEGRADED)
    resolved = list(runs.frozen_input_resolved)
    details = problems[:10] + degraded
    if resolved:
        details.append(
            "PER-85-D6 relocation 放行留痕(旧路径钉住按迁移映射解析):"
            + "; ".join(resolved[:6])
        )
    return CheckResult(
        name="A5_governance_freeze",
        status=status,
        details=tuple(details) or ("governance artifacts verify",),
        metrics={
            "frozen_input_errors": len(runs.frozen_input_errors),
            "frozen_pins_relocated": len(resolved),
            "preflight_errors": len(preflight_problems),
            "authorization_errors": len(authorization_problems),
            "invalidation_notes": len(runs.invalidation_notes),
            # M1(治理文书缺失)影响执行合规性声称 → 降级为部分可追溯。
            "downgrade_affects_conclusion": bool(missing_documents),
        },
    )


def _verdict_from_checks(
    checks: tuple[CheckResult, ...], scope_acceptance: bool
) -> tuple[str, str]:
    """判定规则(口径 3.4):

    - 任一 FAIL → untraceable;
    - 降级/缺失判定项**影响其声称结论** → partially_traceable(点名);
    - 降级标注但结论链不受影响(如 L7 卡级指针缺失而运行时锚点完整)
      → 保持 traceable,标注按 G5 留痕;受影响结论必须退出其声称用途。
    """
    fails = [c.name for c in checks if c.status == FAIL]
    degraded = [c.name for c in checks if c.status == DEGRADED]
    affecting = [
        c.name
        for c in checks
        if c.status == DEGRADED and c.metrics.get("downgrade_affects_conclusion")
    ]
    nas = [c.name for c in checks if c.status == NA]
    if fails:
        return UNTRACEABLE, "链锚断裂/完整性失败:" + ", ".join(fails)
    if scope_acceptance and (affecting or nas):
        return (
            PARTIALLY_TRACEABLE,
            "完整性通过但存在影响结论的降级/缺失节点:" + ", ".join(affecting + nas),
        )
    if scope_acceptance and degraded:
        return (
            TRACEABLE,
            "适用判定项全部通过;降级标注不留结论影响:" + ", ".join(degraded),
        )
    return TRACEABLE, "适用判定项全部通过"


def retrospect_batch(batch: BatchRecord) -> BatchRetrospection:
    """单批次复盘入口(只读、可重复、结果稳定)。"""
    checks: list[CheckResult] = []
    run_statistics: dict[str, Any] = {}
    scope_note = ""

    if batch.batch_type in {"acceptance", "coverage"}:
        checks.append(check_bundle_manifest(batch.directory))
        scenario = check_scenario_inputs(batch)
        checks.append(scenario)
        runs = retrospect_runs(batch)
        run_statistics = dict(runs.metrics)
        # F4:契约世代无 commitments/链锚字段时,anchor_problems=() 是 N/A
        # 而非"anchors hold"空转通过——详情文本显式注记。
        if runs.anchors_na:
            anchor_note = (
                "traces validate; grader recompute bit-equal; "
                "chain-anchor re-verification N/A(该契约世代无 commitments/链锚字段,"
                "anchor_problems=0 为不适用而非通过)"
            )
        else:
            anchor_note = "traces validate; grader recompute bit-equal; anchors hold"
        checks.append(
            CheckResult(
                name="A3_trace_and_B1_regrade",
                status=FAIL if (runs.run_errors or runs.anchor_problems) else PASS,
                details=tuple(list(runs.run_errors[:10]) + list(runs.anchor_problems[:10]))
                or (anchor_note,),
                metrics={
                    "runs": len(runs.records),
                    "run_errors": len(runs.run_errors),
                    "anchor_problems": len(runs.anchor_problems),
                    **{k: v for k, v in runs.metrics.items() if isinstance(v, (int, str))},
                },
            )
        )
        checks.append(_governance_check(batch, runs))
        checks.append(check_summary_recompute(batch, runs))
        scope_note = "验收评分批次:结论链 N0–N5 全量复盘"
    elif batch.batch_type in {"smoke", "frozen_smoke_evidence"}:
        checks.append(check_bundle_manifest(batch.directory))
        checks.append(_inventory_correspondence(batch))
        scope_note = "冒烟线批次:结论限于冒烟通过/硬停判定,非验收评分证据"
    elif batch.batch_type == "frozen_preflight_evidence":
        checks.append(check_bundle_manifest(batch.directory))
        decision_path = batch.directory / "execution_decision.json"
        checks.append(
            CheckResult(
                name="A_execution_decision",
                status=PASS if decision_path.is_file() else FAIL,
                details=(
                    ("execution_decision.json present",)
                    if decision_path.is_file()
                    else ("execution_decision.json missing",)
                ),
            )
        )
        scope_note = "预检证据 bundle:结论限于模型身份预检判定,非验收评分证据"
    elif batch.batch_type == "protocol_gate":
        checks.append(_protocol_gate_check(batch))
        scope_note = (
            "协议门批次(差距项 H1):按设计无验收运行,本批结论限于协议/身份门;"
            "缺失的轨迹/评分节点不可从现有产物推导(运行从未发生)"
        )
    else:  # diagnostic_session
        batch_dir = batch.directory
        files = sorted(path.name for path in batch_dir.iterdir() if path.is_file()) if batch_dir.is_dir() else []
        checks.append(
            CheckResult(
                name="A_session_inventory",
                status=PASS if files else FAIL,
                details=(f"diagnostic session files: {', '.join(files)}",)
                if files
                else ("session directory empty or missing",),
                metrics={"files": len(files)},
            )
        )
        scope_note = "诊断会话留存:仅过程排障证据,不构成任何评分结论"

    labels = tuple(label.code for label in labels_for_batch(batch.batch_id))
    verdict, basis = _verdict_from_checks(
        tuple(checks), scope_acceptance=batch.batch_type in {"acceptance", "coverage"}
    )
    return BatchRetrospection(
        batch_id=batch.batch_id,
        batch_type=batch.batch_type,
        directory=batch.directory.relative_to(REPO_ROOT).as_posix(),
        contract_version=batch.contract_version,
        verdict=verdict,
        verdict_basis=basis,
        checks=tuple(checks),
        labels=labels,
        run_statistics=run_statistics,
        scope_note=scope_note,
    )
