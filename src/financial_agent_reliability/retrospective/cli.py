"""复盘工具 CLI(``fareli-retro``)。

命令(全部只读、离线、可重复):

- ``list``:列出注册表批次;
- ``run --batch <id> | --all``:执行批次复盘,输出 JSON;
- ``lineage`` / ``archive-map`` / ``invalidation`` / ``ranking`` /
  ``report-level``:差距报告推导件;
- ``evidence [--out DIR]``:全量复盘并把证据落盘(默认 docs/retrospectives/)。

退出码:0 = 全部批次可追溯/按口径闭合;2 = 存在 untraceable 判定或推导件失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from financial_agent_reliability.retrospective.archive_map import build_archive_map
from financial_agent_reliability.retrospective.engine import retrospect_batch
from financial_agent_reliability.retrospective.invalidation_check import (
    reconcile_invalidations,
)
from financial_agent_reliability.retrospective.lineage import build_lineage_index
from financial_agent_reliability.retrospective.registry import (
    BATCHES,
    REPO_ROOT,
    acceptance_batches,
    batch_by_id,
)
from financial_agent_reliability.retrospective.report import (
    run_full_retrospective,
    write_evidence,
)
from financial_agent_reliability.retrospective.report_level import (
    check_grader_bundle_freeze,
    check_report_bundle_freeze,
    export_ranking,
    recompute_report_level,
)
from financial_agent_reliability.retrospective.model import UNTRACEABLE


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fareli-retro", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list")

    run_parser = subparsers.add_parser("run")
    run_group = run_parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument("--batch")
    run_group.add_argument("--all", action="store_true")

    subparsers.add_parser("lineage")
    subparsers.add_parser("archive-map")
    subparsers.add_parser("invalidation")
    subparsers.add_parser("ranking")
    subparsers.add_parser("report-level")

    evidence_parser = subparsers.add_parser("evidence")
    evidence_parser.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command == "list":
        _emit(
            {
                "batches": [
                    {
                        "batch_id": batch.batch_id,
                        "batch_type": batch.batch_type,
                        "directory": batch.directory.relative_to(REPO_ROOT).as_posix(),
                        "contract_version": batch.contract_version,
                    }
                    for batch in BATCHES
                ]
            }
        )
        return 0

    if args.command == "run":
        if args.batch:
            result = retrospect_batch(batch_by_id(args.batch))
            _emit(result.to_dict())
            return 2 if result.verdict == UNTRACEABLE else 0
        index = run_full_retrospective()
        _emit(index)
        return 2 if index["verdict_counts"].get(UNTRACEABLE) else 0

    if args.command == "lineage":
        _emit(build_lineage_index())
        return 0
    if args.command == "archive-map":
        payload = build_archive_map()
        _emit(payload)
        return 0 if payload["all_ok"] else 2
    if args.command == "invalidation":
        payload = [
            reconcile_invalidations(batch) for batch in acceptance_batches()
        ]
        _emit(payload)
        return 0 if all(item.get("ok", True) for item in payload) else 2
    if args.command == "ranking":
        _emit(export_ranking())
        return 0
    if args.command == "report-level":
        payload = {
            "grader_bundle_freeze": check_grader_bundle_freeze(),
            "report_bundle_freeze": check_report_bundle_freeze(),
            "report_consistency": recompute_report_level(),
        }
        _emit(payload)
        ok = all(block.get("ok") for block in payload.values())
        return 0 if ok else 2

    if args.command == "evidence":
        try:
            written = write_evidence(args.out)
        except ValueError as exc:
            # F7:路径策略违规(仓外/无法解析)——明确报错,不崩溃栈。
            print(f"error: {exc}", file=sys.stderr)
            return 2
        _emit(written)
        index = run_full_retrospective()
        return 2 if index["verdict_counts"].get(UNTRACEABLE) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
