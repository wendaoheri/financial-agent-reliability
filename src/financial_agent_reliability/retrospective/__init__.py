"""历史运行复盘工具链(PER-319, Stage 2)。

按《场景与结论可复现可追溯验收口径(历史轨迹日志复盘)》v1
(``docs/contracts/scenario-conclusion-reproducibility-criteria.v1.md``,
PER-317 冻结)对历史运行批次执行离线复盘:

- R1/A1 证据 bundle manifest 完整性;
- R2/A2 场景输入(case_card + data_snapshot)重建校验;
- R3/A3 运行轨迹(run_trace + checkpoint 链)配套版本校验;
- R4/A4 链锚回验(run_identity / 候选输出 / grader commitments);
- R5/B1-B2 grader 确定性重算与批级统计重算;
- B3/A5 报告层一致性(stage5 + grader 捆扎 + 报告捆扎);
- R6/3.4 判定与降级标注(traceable / partially_traceable / untraceable)。

并承载 Stage 1 差距报告(PER-318)判定为"可从现有产物推导"的补齐项:
批次血缘索引、排名导出、作废对账、archive↔evidence 映射、双哈希口径
区分与降级标注。复盘默认完全离线:只读冻结/本地产物,不做任何模型
调用、网络访问或真实交易。

复盘产物不得写入任何冻结目录;本包生成的证据落在 ``docs/retrospectives/``。
"""

from __future__ import annotations

from financial_agent_reliability.retrospective.registry import (
    BATCHES,
    BatchRecord,
    batch_by_id,
)
from financial_agent_reliability.retrospective.engine import (
    BatchRetrospection,
    retrospect_batch,
)

__all__ = [
    "BATCHES",
    "BatchRecord",
    "BatchRetrospection",
    "batch_by_id",
    "retrospect_batch",
]
