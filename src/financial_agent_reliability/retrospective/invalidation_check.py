"""作废对账器(差距项 A3/L5:可从现有产物推导)。

v3.10 driver-progress.jsonl 中 ``run_invalidated`` 事件因断点续跑存在重复
落盘(55 条事件 / 10 个唯一 run_id)。对账规则:按 run_id 去重后,与
``invalidated-runs.json``、``summary.invalidated_runs``、bundle manifest
``invalidated_run_ids`` 四处逐一吻合。
"""

from __future__ import annotations

import json
from typing import Any

from financial_agent_reliability.retrospective.registry import BatchRecord


def reconcile_invalidations(batch: BatchRecord) -> dict[str, Any]:
    batch_dir = batch.directory
    result: dict[str, Any] = {"batch_id": batch.batch_id, "applicable": False}

    invalidation_path = batch_dir / "invalidated-runs.json"
    if not invalidation_path.is_file():
        result["note"] = "no invalidated-runs.json(批次无作废 run 或早期契约无此文书)"
        return result
    report = json.loads(invalidation_path.read_text(encoding="utf-8"))
    entries = report.get("entries", [])
    report_ids = sorted({str(entry.get("run_id")) for entry in entries})
    result["applicable"] = True
    result["invalidated_run_ids_in_report"] = report_ids
    result["entry_count"] = len(entries)

    problems: list[str] = []
    # F3:重复 run_id 检出须并入同一 problems 列表(此前的 setdefault 写入
    # 会被函数末尾的赋值覆盖丢弃)。
    if len(report_ids) != len(entries):
        problems.append("invalidation report has duplicate run_ids")

    # driver-progress 事件按 run_id 去重(L5)
    progress_path = batch_dir / "driver-progress.jsonl"
    if progress_path.is_file():
        event_ids: list[str] = []
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "run_invalidated":
                run_id = event.get("run_id") or (event.get("payload") or {}).get("run_id")
                if run_id:
                    event_ids.append(str(run_id))
        deduped = sorted(set(event_ids))
        result["progress_events_total"] = len(event_ids)
        result["progress_events_deduped"] = len(deduped)
        if deduped != report_ids:
            problems.append(
                f"driver-progress 去重后 {len(deduped)} 个 run_id 与 invalidated-runs.json 不符"
            )

    # summary.invalidated_runs
    summary_path = batch_dir / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_ids = sorted(
            str(item.get("run_id")) for item in summary.get("invalidated_runs", [])
        )
        if summary_ids and summary_ids != report_ids:
            problems.append("summary.invalidated_runs 与 invalidated-runs.json 不符")
        counts = summary.get("counts", {})
        if "invalidated" in counts and counts["invalidated"] != len(report_ids):
            problems.append("summary.counts.invalidated 与报告条数不符")

    # bundle manifest invalidated_run_ids
    manifest_path = batch_dir / "bundle.manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_ids = manifest.get("invalidated_run_ids")
        if manifest_ids is not None and sorted(str(r) for r in manifest_ids) != report_ids:
            problems.append("manifest.invalidated_run_ids 与 invalidated-runs.json 不符")
        if manifest.get("invalidated_count") not in (None, len(report_ids)):
            problems.append("manifest.invalidated_count 与报告条数不符")

    # report-only 纪律:作废 run 不得有 traces/graders/candidates 冻结件
    for run_id in report_ids:
        for sub in ("traces", "graders", "candidates"):
            if (batch_dir / sub / f"{run_id}.json").exists():
                problems.append(f"{run_id}: 作废 run 存在 {sub} 冻结件(违反 report-only)")

    result["problems"] = problems
    result["ok"] = not problems
    return result
