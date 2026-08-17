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

# PER-323 Stage 2:复盘模块的批次表与哈希口径仍绑定基线 v1(含已删除的
# ``contracts`` 校验器导入)。基线空窗期内不在模块顶层导入它们,保证
# ``fareli-retro`` 任何子命令都能先走到显式的 baseline_gap 门,而不是在
# import 期崩溃。baseline v3 只重建最小评测基线、未重建历史运行血缘，故该门继续生效。


#: Compatibility name retained from Stage 2. It can become False only after a
#: future version actually rebuilds the historical batch registry and lineage
#: roots; baseline v3 intentionally does not do so.
BASELINE_V2_PENDING = True


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

    if BASELINE_V2_PENDING:
        # PER-323 Stage 2(cleanup list M2):baseline v1 的血缘根目录
        # (runs/ evidence/ reports/ audit/)已按冻结清单删除,复盘工具链的批次表
        # 与根路径绑定该基线；baseline v3 未重建历史运行证据，故仍处于空窗期。
        # 显式报「基线空窗」而不是静默失败或误报 untraceable。
        _emit(
            {
                "status": "baseline_gap",
                "command": args.command,
                "reason": (
                    "baseline v1 lineage roots (runs/, evidence/, reports/, audit/) were "
                    "removed by the PER-323 frozen cleanup list; baseline v3 rebuilds "
                    "evaluation inputs and contracts only and does not "
                    "rebuild historical run evidence"
                ),
                "exit_code": 2,
            }
        )
        return 2

    return _dispatch(args)


def _dispatch(args: argparse.Namespace) -> int:
    """未来历史运行血缘重建后的真实分派;当前不可达(见 BASELINE_V2_PENDING)。

    导入全部延迟到此处:这些模块仍绑定基线 v1(含已删除的 contracts
    校验器),顶层导入会在空窗期直接崩溃。
    """
    from financial_agent_reliability.retrospective.archive_map import build_archive_map
    from financial_agent_reliability.retrospective.engine import retrospect_batch
    from financial_agent_reliability.retrospective.invalidation_check import (
        reconcile_invalidations,
    )
    from financial_agent_reliability.retrospective.lineage import build_lineage_index
    from financial_agent_reliability.retrospective.model import UNTRACEABLE
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
