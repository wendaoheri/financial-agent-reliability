"""降级标注登记(口径 3.4 + Stage 1 差距报告 PER-318)。

每个标注包含:编号、严重度、受影响批次、是否影响结论用途、复现/核对
方式与最小修复建议。标注在复盘输出中逐批留痕,不得静默跳过。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DowngradeLabel:
    code: str
    severity: str  # high / medium / low
    affected_batches: tuple[str, ...]
    summary: str
    consequence: str  # 对结论用途的影响
    remediation: str


LABELS: tuple[DowngradeLabel, ...] = (
    DowngradeLabel(
        code="H1",
        severity="high",
        affected_batches=(
            "acceptance-v3", "acceptance-v3.1", "acceptance-v3.2",
            "acceptance-v3.3", "acceptance-v3.4",
        ),
        summary=(
            "v3–v3.4 无任何验收运行轨迹/grader/评分;按设计即无运行"
            "(v3.4 契约 acceptance_runs_authorized=false),属定性问题而非数据丢失。"
        ),
        consequence=(
            "这些批次只构成'模型身份与协议门'证据,不是'场景答题→评分'证据;"
            "任何验收评分结论不得引用这些批次。"
        ),
        remediation="如需验收评分证据,必须立新运行(新血缘),不回写旧批次。",
    ),
    DowngradeLabel(
        code="M1",
        severity="medium",
        affected_batches=("acceptance-v3.5",),
        summary=(
            "v3.5 付费调用授权记录缺失(authorization.run/preflight 均无);"
            "v3.8 的 authorization_basis 未追认 v3.5。"
        ),
        consequence=(
            "v3.5 评分链本身完整(36/36 grader↔trace 对账一致),但治理层"
            "授权节点缺失:该批次结论按'部分可追溯'标注,授权缺失不影响评分"
            "重算本身,影响的是执行合规性声明。"
        ),
        remediation="只能降级标注(v3.8 起授权机制已建立);不回补历史授权文书。",
    ),
    DowngradeLabel(
        code="M3",
        severity="medium",
        affected_batches=("acceptance-v3.10",),
        summary=(
            "v3.10 run_bba344e2 被验证器在持久化前拒绝,无 grading-failures "
            "转录;该次拒绝本身不可从取证复现,仅存 checkpoint 与作废记录。"
        ),
        consequence=(
            "孤立事件(1/270);作废记录本身即证据,该 run 不入结论。"
            "复盘按'孤立取证不可复现事件'显式标注,不影响其余 260 run。"
        ),
        remediation="显式标注 + 保留 checkpoint 取证链;无需修复。",
    ),
    DowngradeLabel(
        code="L1",
        severity="low",
        affected_batches=("*",),
        summary="cost_usd 全为 null(provider 响应不含成本);token 用量与请求次数完整。",
        consequence="金额口径不可复盘;以 token/请求次数为替代口径。",
        remediation="未来运行需价目表映射或账单归档(新增记录类,不回补历史)。",
    ),
    DowngradeLabel(
        code="L2",
        severity="low",
        affected_batches=(
            "acceptance-v3", "acceptance-v3.1", "acceptance-v3.2",
            "acceptance-v3.3", "acceptance-v3.4",
        ),
        summary="早期 preflight 不记录消费的 case_id(脱敏代价)。",
        consequence="早期 preflight 的用例级消费不可复盘;批次级结论不受影响。",
        remediation="未来运行新增 case_id 明文记录(非敏感字段)。",
    ),
    DowngradeLabel(
        code="L3",
        severity="low",
        affected_batches=(
            "acceptance-v3.5", "acceptance-v3.8", "acceptance-v3.9",
            "acceptance-v3.10", "acceptance-v3.11", "coverage-v3.11.1",
        ),
        summary="summary 无显式 ranking 字段。",
        consequence="无;可由 by_model/by_repeat 聚合推导导出(本工具 ranking 命令)。",
        remediation="推导即可,不新增记录。",
    ),
    DowngradeLabel(
        code="L4",
        severity="low",
        affected_batches=("acceptance-v3.9",),
        summary="v3.9 无 driver-console/driver-progress 日志(机制 v3.10 才引入)。",
        consequence="过程复盘以 checkpoints 哈希链 + trace usage/attempts 承载,无缺口。",
        remediation="推导即可。",
    ),
    DowngradeLabel(
        code="L5",
        severity="low",
        affected_batches=("acceptance-v3.10",),
        summary=(
            "v3.10 driver-progress.jsonl 中 run_invalidated 事件存在断点续跑"
            "重复落盘;复盘须按 run_id 去重。"
        ),
        consequence="去重后与 invalidated-runs.json 完全吻合(本工具 invalidation 命令复核)。",
        remediation="推导即可。",
    ),
    DowngradeLabel(
        code="L6",
        severity="low",
        affected_batches=("*",),
        summary=(
            "双哈希口径:规范化 c14n 哈希与整文件 sha256 并存;"
            "裸文件哈希复核会误判失配。"
        ),
        consequence="无;复盘工具内建口径区分(hashing.detect_bundle_aggregate 等)。",
        remediation="推导即可。",
    ),
    DowngradeLabel(
        code="L7",
        severity="low",
        affected_batches=(
            "acceptance-v3.5", "acceptance-v3.8", "acceptance-v3.9",
            "acceptance-v3.10", "acceptance-v3.11", "coverage-v3.11.1",
        ),
        summary=(
            "FTW 合成案例卡 evidence_refs=[]:卡级快照指针缺失,快照绑定仅在"
            "运行时投影哈希(trace/checkpoint/grader commitments)。"
        ),
        consequence=(
            "运行内链条完整(复盘按运行时锚点校验);卡级指针缺失按缺口记录,"
            "不影响本口径下的可追溯判定。"
        ),
        remediation="未来运行补齐卡级 evidence_refs 或书面确认运行时锚点口径(新增记录类)。",
    ),
    DowngradeLabel(
        code="L8",
        severity="low",
        affected_batches=("acceptance-v3.11",),
        summary=(
            "v3.11 无独立 authorization.preflight.json(carry-over 取代:"
            "源哈希 + 9 项等价校验 + PER-62/63 独立审计)。"
        ),
        consequence="链条闭合,不构成缺口;复盘按 carry-over 记录核对。",
        remediation="推导即可。",
    ),
    DowngradeLabel(
        code="L9",
        severity="low",
        affected_batches=("stage5-report",),
        summary=(
            "reports/stage5 无独立 artifact manifest,provenance 内嵌于"
            "report bundle/machine_readable_results。"
        ),
        consequence="外部可复核性弱于 runs bundle;REPRODUCE.md + build_stage5.py 重推路径存在。",
        remediation="推导即可(report-level 复盘复验该路径)。",
    ),
    DowngradeLabel(
        code="L10",
        severity="low",
        affected_batches=("acceptance-v3.5", "acceptance-v3.8"),
        summary="runs/stage3 的 v3.5/v3.8 目录是 symlink → evidence/stage3(无 drift 风险但无冗余)。",
        consequence="无;复盘工具 symlink 感知,以 evidence/stage3 为正本。",
        remediation="归档打包时解引用 symlink(新增规范类)。",
    ),
    DowngradeLabel(
        code="L11",
        severity="low",
        affected_batches=("acceptance-v3.8", "acceptance-v3.9", "acceptance-v3.10", "acceptance-v3.11", "coverage-v3.11.1"),
        summary="v3.8+ graders 不含 model_id(v3.5 含),模型归属须经 run_id 联结。",
        consequence="无;已验全部可联结(本工具经 plan.runs 联结并复核)。",
        remediation="推导即可。",
    ),
    DowngradeLabel(
        code="L12",
        severity="low",
        affected_batches=("acceptance-v3.11", "coverage-v3.11.1"),
        summary="批内部分文件权限 600(owner-only),他人复盘需注意读权限。",
        consequence="提示性;不影响本次复盘(同机同用户)。",
        remediation="归档打包规范说明(新增规范类)。",
    ),
    DowngradeLabel(
        code="L14",
        severity="low",
        affected_batches=("acceptance-v3.9", "acceptance-v3.10", "acceptance-v3.11", "coverage-v3.11.1"),
        summary=(
            "契约文件 paid_calls_authorized=false 与 authorization 文书的 true 并存"
            "(语义分层:契约不授权,授权来自 authorization_basis)。"
        ),
        consequence="表面不一致、语义正确;复盘按语义分层判读。",
        remediation="文档注明(Stage 4 规范固化承接)。",
    ),
)

LABEL_BY_CODE: dict[str, DowngradeLabel] = {label.code: label for label in LABELS}


def labels_for_batch(batch_id: str) -> tuple[DowngradeLabel, ...]:
    """返回登记到某批次的全部降级标注(``*`` 表示全批次通用)。"""
    return tuple(
        label
        for label in LABELS
        if batch_id in label.affected_batches or "*" in label.affected_batches
    )
