"""复盘证据落盘(口径 R6:产物落 audit/ 之外的非冻结工作目录)。

输出位于 ``docs/retrospectives/``(非冻结目录;不向 contracts/、evidence/、
runs/、audit/、reports/ 等冻结目录新增任何文件):

- ``retrospective-index.v1.json``:机器可读总索引(逐批次判定 + 降级标注);
- ``batches/<batch_id>.v1.json``:逐批次检查明细;
- ``retrospective-report.v1.md``:人读复盘记录;
- ``lineage-index.v1.json``、``archive-map.v1.json``、``ranking.v1.json``、
  ``invalidation-recon.v1.json``、``report-level.v1.json``:推导件。

输出不含墙钟时间戳,只含 git 提交锚点,保证可重复运行且结果稳定。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any

from financial_agent_reliability.retrospective.archive_map import build_archive_map
from financial_agent_reliability.retrospective.engine import retrospect_batch
from financial_agent_reliability.retrospective.invalidation_check import (
    reconcile_invalidations,
)
from financial_agent_reliability.retrospective.labels import LABELS
from financial_agent_reliability.retrospective.lineage import build_lineage_index
from financial_agent_reliability.retrospective.registry import BATCHES, REPO_ROOT
from financial_agent_reliability.retrospective.report_level import (
    check_grader_bundle_freeze,
    check_report_bundle_freeze,
    export_ranking,
    recompute_report_level,
)
from financial_agent_reliability.retrospective.model import BatchRetrospection

OUTPUT_DIR = REPO_ROOT / "docs" / "retrospectives"

CRITERIA_PATH = "docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md"
GAP_REPORT_PATH = "docs/stage1-historical-trace-inventory-gap-report.v1.md"

#: PER-320 审计 P1 表述纠正:runs/ 为 .gitignore 排除对象,git 不覆盖该目录,
#: 其完整性不能以 git 验证主张;依据为 bundle manifest 逐件 sha256 自证
#: (A1_manifest_integrity)+ 独立重算。git 零改动验证仅对 tracked 目录主张。
RUNS_INTEGRITY_BASIS = (
    "runs/ 为 .gitignore 排除对象,git 不覆盖该目录:其完整性由 bundle manifest "
    "逐件 sha256 自证(A1_manifest_integrity)+ 独立重算承担;git 零改动验证仅对 "
    "tracked 目录主张(contracts/、evidence/、audit/、reports/、snapshots/、"
    "cases/、catalog/、preregistration/)"
)


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_full_retrospective() -> dict[str, Any]:
    """对注册表全部批次执行复盘,返回机器可读总索引(纯读,不落盘)。"""
    retrospections = [retrospect_batch(batch) for batch in BATCHES]
    return {
        "contract_type": "stage3_historical_run_retrospective_index",
        "index_version": "1.0.0",
        "criteria_document": CRITERIA_PATH,
        "criteria_version": "1.0.0",
        "gap_report": GAP_REPORT_PATH,
        "git_commit": _git_head(),
        "offline": True,
        "runs_integrity_basis": RUNS_INTEGRITY_BASIS,
        "batches": [item.to_dict() for item in retrospections],
        "verdict_counts": _verdict_counts(retrospections),
        "labels_registry": [
            {
                "code": label.code,
                "severity": label.severity,
                "affected_batches": list(label.affected_batches),
                "summary": label.summary,
                "consequence": label.consequence,
                "remediation": label.remediation,
            }
            for label in LABELS
        ],
    }


def _verdict_counts(items: list[BatchRetrospection]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.verdict] = counts.get(item.verdict, 0) + 1
    return counts


def resolve_evidence_output_dir(
    output_dir: pathlib.Path | str | None,
) -> pathlib.Path:
    """F7:``evidence --out`` 路径策略。

    相对路径按仓库根解析(与调用方 CWD 无关);最终路径必须落在仓库内
    (证据是仓库内交付物,仓外路径也无法以仓库根相对路径登记),否则抛
    ``ValueError`` 并给出明确错误——不再让下游 ``relative_to`` 崩溃。
    """
    if output_dir is None:
        return OUTPUT_DIR
    candidate = pathlib.Path(str(output_dir)).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    repo_root = REPO_ROOT.resolve()
    if resolved != repo_root and repo_root not in resolved.parents:
        raise ValueError(
            "evidence --out must stay inside the repository "
            f"({repo_root}): got {resolved}"
        )
    return resolved


def write_evidence(
    output_dir: pathlib.Path | str | None = None,
) -> dict[str, str]:
    """执行全量复盘 + 全部推导件,落盘并返回输出路径清单。"""
    out = resolve_evidence_output_dir(output_dir)
    repo_root = REPO_ROOT.resolve()

    def _repo_relative(path: pathlib.Path) -> str:
        return path.resolve().relative_to(repo_root).as_posix()

    index = run_full_retrospective()
    written: dict[str, str] = {}

    index_path = out / "retrospective-index.v1.json"
    _write_json(index_path, index)
    written["index"] = _repo_relative(index_path)

    for item in index["batches"]:
        batch_path = out / "batches" / f"{item['batch_id']}.v1.json"
        _write_json(batch_path, item)
        written[f"batch:{item['batch_id']}"] = _repo_relative(batch_path)

    derived = {
        "lineage": build_lineage_index(),
        "archive_map": build_archive_map(),
        "ranking": export_ranking(),
        "report_level": {
            "grader_bundle_freeze": check_grader_bundle_freeze(),
            "report_bundle_freeze": check_report_bundle_freeze(),
            "report_consistency": recompute_report_level(),
        },
        "invalidation_recon": [
            reconcile_invalidations(batch)
            for batch in BATCHES
            if batch.batch_type in {"acceptance", "coverage"}
        ],
    }
    names = {
        "lineage": "lineage-index.v1.json",
        "archive_map": "archive-map.v1.json",
        "ranking": "ranking.v1.json",
        "report_level": "report-level.v1.json",
        "invalidation_recon": "invalidation-recon.v1.json",
    }
    for key, payload in derived.items():
        path = out / names[key]
        _write_json(path, payload)
        written[key] = _repo_relative(path)

    report_path = out / "retrospective-report.v1.md"
    report_path.write_text(render_markdown(index, derived), encoding="utf-8")
    written["report"] = _repo_relative(report_path)
    return written


def render_markdown(index: dict[str, Any], derived: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 历史运行复盘记录(Stage 2,PER-319)")
    lines.append("")
    lines.append(f"- 依据口径:`{CRITERIA_PATH}`(v1,PER-317 冻结)")
    lines.append(f"- 差距报告:`{GAP_REPORT_PATH}`(PER-318)")
    lines.append(f"- git 锚点:`{index['git_commit']}`")
    lines.append("- 复盘方式:完全离线;只读冻结/本地产物;无模型调用、无网络、无交易")
    lines.append(f"- runs/ 完整性依据:{RUNS_INTEGRITY_BASIS}(PER-320 审计 P1 纠正)")
    counts = index["verdict_counts"]
    lines.append(
        "- 判定汇总:" + ";".join(f"{key} × {value}" for key, value in sorted(counts.items()))
    )
    lines.append("")
    lines.append("## 逐批次判定")
    lines.append("")
    lines.append("| 批次 | 类型 | 契约版本 | 判定 | 降级标注 | 依据 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in index["batches"]:
        labels = ",".join(item["labels"]) or "—"
        lines.append(
            f"| `{item['batch_id']}` | {item['batch_type']} | "
            f"{item['contract_version'] or '—'} | **{item['verdict']}** | {labels} | "
            f"{item['verdict_basis']}"
            + (f"({item['scope_note']})" if item["scope_note"] else "")
            + " |"
        )
    lines.append("")
    lines.append("## 报告层(stage5 合并口径)")
    lines.append("")
    report_level = derived["report_level"]
    for key, block in report_level.items():
        ok = block.get("ok")
        lines.append(f"- `{key}`: {'通过' if ok else '未通过'}")
        for problem in block.get("problems", []):
            lines.append(f"  - {problem}")
    consistency = report_level.get("report_consistency", {})
    lines.append(
        f"- 密封行重建: {consistency.get('sealed_rows')} 行;"
        f"provisional_leader={consistency.get('provisional_leader')};"
        f"ranking_reliable={consistency.get('ranking_reliable')}"
    )
    lines.append("")
    lines.append("## 推导件")
    lines.append("")
    lines.append(f"- 血缘索引:`lineage-index.v1.json`({len(derived['lineage']['batches'])} 批次)")
    archive_ok = derived["archive_map"]["all_ok"]
    lines.append(f"- archive↔evidence 映射:`archive-map.v1.json`(一致:{archive_ok})")
    invalidations = derived["invalidation_recon"]
    lines.append(
        "- 作废对账:`invalidation-recon.v1.json`("
        + ";".join(
            f"{item['batch_id']}={'ok' if item.get('ok') else 'PROBLEM'}"
            for item in invalidations
            if item.get("applicable")
        )
        + ")"
    )
    ranking = derived["ranking"]
    lines.append(f"- 排名导出:`ranking.v1.json`(ranking_reliable={ranking['ranking_reliable']})")
    lines.append("")
    lines.append("## 降级标注登记")
    lines.append("")
    for label in index["labels_registry"]:
        lines.append(
            f"- **{label['code']}**({label['severity']}):{label['summary']} "
            f"影响:{label['consequence']}"
        )
    lines.append("")
    lines.append("## 复现命令")
    lines.append("")
    lines.append("```bash")
    lines.append("uv run fareli-retro run --all")
    lines.append("uv run fareli-retro evidence   # 重生成本目录全部证据")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)
