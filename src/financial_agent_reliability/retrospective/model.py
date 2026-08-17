"""复盘结果数据模型(只读、不可变)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 判定档位(口径 3.4)。
TRACEABLE = "traceable"
PARTIALLY_TRACEABLE = "partially_traceable"
UNTRACEABLE = "untraceable"

#: 单项检查状态。
PASS = "pass"
FAIL = "fail"
DEGRADED = "degraded"  # 通过但带降级标注
NA = "not_applicable"  # 按设计不适用(须说明理由)


@dataclass(frozen=True)
class CheckResult:
    """一项检查的结论。

    ``status`` 取值见上;``details`` 记录逐项证据(最多截断保留),
    ``metrics`` 记录可复核的计数/哈希等机器可读指标。
    """

    name: str
    status: str
    details: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchRetrospection:
    """单批次复盘结论。"""

    batch_id: str
    batch_type: str
    directory: str
    contract_version: str | None
    verdict: str  # TRACEABLE / PARTIALLY_TRACEABLE / UNTRACEABLE
    verdict_basis: str  # 判定依据一句话
    checks: tuple[CheckResult, ...]
    labels: tuple[str, ...]  # 命中的降级标注编号
    run_statistics: dict[str, Any] = field(default_factory=dict)
    scope_note: str = ""  # 该批次结论的适用边界(如协议门证据)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "batch_type": self.batch_type,
            "directory": self.directory,
            "contract_version": self.contract_version,
            "verdict": self.verdict,
            "verdict_basis": self.verdict_basis,
            "scope_note": self.scope_note,
            "labels": list(self.labels),
            "checks": [
                {
                    "name": check.name,
                    "status": check.status,
                    "details": list(check.details),
                    "metrics": check.metrics,
                }
                for check in self.checks
            ],
            "run_statistics": self.run_statistics,
        }
