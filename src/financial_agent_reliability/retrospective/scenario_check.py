"""R2 / A2:场景输入重建校验(case_card + data_snapshot + 运行构成件)。

- 批内 plan 自哈希与 contracts/ 正本一致性;
- plan.tasks 对 case/projection/snapshot 的逐件 sha256 钉住复核;
- case/snapshot 的 ``integrity.content_sha256``(c14n 口径)复核;
- case 卡 ``evidence_refs[].snapshot_sha256`` 与快照一致性(L7:合成卡
  evidence_refs 为空时按缺口记录,不判失败);
- 冻结校验器 ``contracts/validate_case_data.py`` 的时点与结构纪律复核。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from contracts.validate_case_data import (
    content_sha256 as _case_c14n,
    validate_case_card,
    validate_data_snapshot,
)
from financial_agent_reliability.retrospective.hashing import (
    content_sha256,
    file_sha256,
)
from financial_agent_reliability.retrospective.model import (
    DEGRADED,
    FAIL,
    NA,
    PASS,
    CheckResult,
)
from financial_agent_reliability.retrospective.registry import REPO_ROOT, BatchRecord


def load_batch_plan(batch: BatchRecord) -> dict[str, Any] | None:
    if not batch.plan_file:
        return None
    plan_path = batch.directory / batch.plan_file
    if not plan_path.is_file():
        return None
    return json.loads(plan_path.read_text(encoding="utf-8"))


def plan_self_hash_ok(plan: Mapping[str, Any]) -> bool:
    """plan.plan_sha256 == c14n(plan 去掉 plan_sha256 自身)。"""
    claimed = plan.get("plan_sha256")
    if not isinstance(claimed, str):
        return False
    stripped = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return content_sha256(stripped) == claimed


def check_scenario_inputs(batch: BatchRecord) -> CheckResult:
    if batch.batch_type not in {"acceptance", "coverage"}:
        return CheckResult(
            name="A2_scenario_inputs",
            status=NA,
            details=(f"batch_type={batch.batch_type}: 场景输入节点按设计不适用",),
        )
    plan = load_batch_plan(batch)
    if plan is None:
        return CheckResult(
            name="A2_scenario_inputs",
            status=FAIL,
            details=(f"plan file missing: {batch.plan_file}",),
        )

    problems: list[str] = []
    degraded_notes: list[str] = []

    if not plan_self_hash_ok(plan):
        problems.append("plan.plan_sha256 self hash mismatch")
    canonical_plan = REPO_ROOT / "contracts" / str(batch.plan_file)
    if canonical_plan.is_file():
        in_batch = batch.directory / str(batch.plan_file)
        if file_sha256(in_batch) != file_sha256(canonical_plan):
            problems.append("in-batch plan differs from contracts/ canonical plan")
    else:
        degraded_notes.append("canonical contracts/ plan copy not found for comparison")

    tasks = plan.get("tasks", [])
    if not tasks:
        problems.append("plan has no tasks")
    validator_errors: list[str] = []
    empty_evidence_refs = 0
    checked_cases = 0
    snapshot_cache: dict[str, Mapping[str, Any]] = {}

    for task in tasks:
        case_id = str(task.get("case_id"))
        # 投影件与快照件的整文件钉住(plan 口径)
        for key in ("projection_path", "snapshot_path", "source_case_path"):
            rel = task.get(key)
            sha_key = {
                "projection_path": "projection_sha256",
                "snapshot_path": "snapshot_sha256",
                "source_case_path": "source_case_sha256",
            }[key]
            if not rel:
                continue
            expected = task.get(sha_key)
            path = REPO_ROOT / str(rel)
            if not path.is_file():
                problems.append(f"{case_id}: {key} missing on disk: {rel}")
                continue
            if isinstance(expected, str) and file_sha256(path) != expected:
                problems.append(f"{case_id}: {key} hash drift: {rel}")

        # 快照内容哈希(c14n)+ 冻结校验器
        snap_rel = task.get("snapshot_path")
        snapshot = None
        if snap_rel:
            snap_path = REPO_ROOT / str(snap_rel)
            if snap_path.is_file():
                snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
                snapshot_cache[str(snapshot.get("snapshot_id"))] = snapshot
                integrity = snapshot.get("integrity", {})
                claimed = integrity.get("content_sha256") if isinstance(integrity, Mapping) else None
                if isinstance(claimed, str) and _case_c14n(snapshot) != claimed:
                    problems.append(f"{case_id}: snapshot content_sha256 drift")
                validator_errors.extend(
                    f"{case_id}: snapshot: {item}"
                    for item in validate_data_snapshot(snapshot, raise_on_error=False)
                )

        # case 卡内容哈希 + 冻结校验器 + evidence_refs 交叉校验
        case_rel = task.get("source_case_path")
        if case_rel:
            card_path = REPO_ROOT / str(case_rel)
            if card_path.is_file():
                card = json.loads(card_path.read_text(encoding="utf-8"))
                checked_cases += 1
                integrity = card.get("integrity", {})
                claimed = integrity.get("content_sha256") if isinstance(integrity, Mapping) else None
                if isinstance(claimed, str) and _case_c14n(card) != claimed:
                    problems.append(f"{case_id}: case card content_sha256 drift")
                validator_errors.extend(
                    f"{case_id}: case_card: {item}"
                    for item in validate_case_card(
                        card, snapshots=snapshot_cache, raise_on_error=False
                    )
                )
                refs = card.get("evidence_refs") or []
                if not refs:
                    empty_evidence_refs += 1  # L7:合成案例卡卡级指针缺失
                for ref in refs:
                    ref_sha = ref.get("snapshot_sha256")
                    snap = snapshot_cache.get(str(ref.get("snapshot_id")))
                    if isinstance(ref_sha, str) and snap is not None:
                        snap_integrity = snap.get("integrity", {})
                        snap_claimed = (
                            snap_integrity.get("content_sha256")
                            if isinstance(snap_integrity, Mapping)
                            else None
                        )
                        if snap_claimed != ref_sha:
                            problems.append(
                                f"{case_id}: evidence_refs snapshot_sha256 mismatch"
                            )

    problems.extend(validator_errors[:10])
    if empty_evidence_refs:
        degraded_notes.append(
            f"L7:{empty_evidence_refs} 张案例卡 evidence_refs 为空"
            "(卡级快照指针缺失;运行内投影哈希链完整)"
        )

    status = FAIL if problems else (DEGRADED if degraded_notes else PASS)
    return CheckResult(
        name="A2_scenario_inputs",
        status=status,
        details=tuple(problems[:20] + degraded_notes) or ("scenario inputs rebuild verified",),
        metrics={
            "tasks": len(tasks),
            "case_cards_checked": checked_cases,
            "snapshots_cached": len(snapshot_cache),
            "empty_evidence_refs_cards": empty_evidence_refs,
            "validator_errors": len(validator_errors),
            "plan_self_hash_ok": plan_self_hash_ok(plan),
            # L7 属证据字段缺口:结论链经运行时投影哈希完整承载,无结论受影响。
            "downgrade_affects_conclusion": False,
        },
    )
