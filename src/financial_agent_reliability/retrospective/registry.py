"""历史运行批次注册表(复盘对象清单)。

覆盖 Stage 1 差距报告(PER-318)批次覆盖矩阵中的全部批次。每个批次登记:

- ``batch_type``:复盘语义分组——
  ``acceptance``(验收评分批次)/ ``coverage``(补跑覆盖批次)/
  ``smoke``(冒烟批次)/ ``frozen_smoke_evidence``(冒烟冻结证据 bundle)/
  ``frozen_preflight_evidence``(预检冻结证据 bundle)/
  ``protocol_gate``(协议门批次:按设计无验收运行,差距项 H1)/
  ``diagnostic_session``(排障会话留存);
- 契约版本、批内 plan/config 文件名、配套校验器与冻结 reconcile 脚本;
- 差距报告登记的降级标注(在 labels.py 中细化)。

注册表本身是推导产物:路径/版本逐一取自盘上实物与冻结契约,不新增任何
冻结目录内容。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RUNS_STAGE3 = REPO_ROOT / "runs" / "stage3"
EVIDENCE_STAGE3 = REPO_ROOT / "evidence" / "stage3"
ARCHIVE_ROOT = REPO_ROOT / "runs" / "frozen-runtime-archive"

#: 候选模型固定 ID(密钥纪律:仅身份用途,不触达任何密钥)。
EXPECTED_MODELS: tuple[str, ...] = ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro")


@dataclass(frozen=True)
class BatchRecord:
    """一个历史批次的复盘入口信息。"""

    batch_id: str
    batch_type: str
    dir_name: str
    contract_version: str | None = None
    canonical_root: str = "runs/stage3"  # 相对仓库根的批次目录位置
    plan_file: str | None = None
    config_file: str | None = None
    has_manifest: bool = False
    has_candidates_dir: bool = False
    reconcile_script: str | None = None  # 相对仓库根的冻结 reconcile 脚本
    trace_validator: str | None = None  # 冻结校验器(版本配套)
    notes: tuple[str, ...] = ()

    @property
    def directory(self) -> pathlib.Path:
        return REPO_ROOT / self.canonical_root / self.dir_name


BATCHES: tuple[BatchRecord, ...] = (
    # ---- 协议门批次(v3–v3.4):按设计无验收运行(差距项 H1) ----
    BatchRecord(
        batch_id="acceptance-v3", batch_type="protocol_gate",
        dir_name="acceptance-20260811-v3", contract_version="3.0.0",
        notes=("H1:protocol-gate evidence only; no acceptance runs by design",),
    ),
    BatchRecord(
        batch_id="acceptance-v3.1", batch_type="protocol_gate",
        dir_name="acceptance-20260811-v3.1", contract_version="3.1.0",
        notes=("H1:protocol-gate evidence only; no acceptance runs by design",),
    ),
    BatchRecord(
        batch_id="acceptance-v3.2", batch_type="protocol_gate",
        dir_name="acceptance-20260811-v3.2", contract_version="3.2.0",
        notes=("H1:protocol-gate evidence only; no acceptance runs by design",),
    ),
    BatchRecord(
        batch_id="acceptance-v3.3", batch_type="protocol_gate",
        dir_name="acceptance-20260811-v3.3", contract_version="3.3.0",
        notes=(
            "H1:protocol-gate evidence only; no acceptance runs by design",
            "preflight three-piece set: auto_strict / forced_strict / sequence",
        ),
    ),
    BatchRecord(
        batch_id="acceptance-v3.4", batch_type="protocol_gate",
        dir_name="acceptance-20260812-v3.4", contract_version="3.4.0",
        notes=(
            "H1:protocol-gate evidence only; no acceptance runs by design",
            "v3.4 contract declares acceptance_runs_authorized=false",
        ),
    ),
    # ---- frozen-preflight-evidence v1–v4 ----
    BatchRecord(
        batch_id="frozen-preflight-evidence-v1", batch_type="frozen_preflight_evidence",
        dir_name="frozen-preflight-evidence-20260811", has_manifest=True,
        notes=("execution_decision=blocked(0/3 preflight)",),
    ),
    BatchRecord(
        batch_id="frozen-preflight-evidence-v2", batch_type="frozen_preflight_evidence",
        dir_name="frozen-preflight-evidence-20260811-v2", has_manifest=True,
        notes=("execution_decision=blocked(0/3 preflight)",),
    ),
    BatchRecord(
        batch_id="frozen-preflight-evidence-v3", batch_type="frozen_preflight_evidence",
        dir_name="frozen-preflight-evidence-20260811-v3", has_manifest=True,
        notes=("execution_decision=blocked;目录探测根因证据",),
    ),
    BatchRecord(
        batch_id="frozen-preflight-evidence-v4", batch_type="frozen_preflight_evidence",
        dir_name="frozen-preflight-evidence-20260811-v4", has_manifest=True,
        notes=("execution_decision=preflight_passed(修正 ID 后 3/3)",),
    ),
    # ---- 冒烟线 ----
    BatchRecord(
        batch_id="smoke-v1", batch_type="smoke",
        dir_name="smoke-20260811-v1", contract_version="2.0.0",
        notes=(
            "hard stop:harness 身份判定缺陷,3 run 全部作废",
            "权威取证在 frozen-smoke-evidence-20260811-v1",
        ),
    ),
    BatchRecord(
        batch_id="smoke-v2", batch_type="smoke",
        dir_name="smoke-20260811-v2", contract_version="2.0.0",
        notes=("纠正性续跑 36/36 成功;收官冻结在 frozen-smoke-evidence-v2",),
    ),
    BatchRecord(
        batch_id="frozen-smoke-evidence-v1", batch_type="frozen_smoke_evidence",
        dir_name="frozen-smoke-evidence-20260811-v1", has_manifest=True,
        notes=("hard-stop 取证冻结 bundle(自包含)",),
    ),
    BatchRecord(
        batch_id="frozen-smoke-evidence-v2", batch_type="frozen_smoke_evidence",
        dir_name="frozen-smoke-evidence-20260811-v2", has_manifest=True,
        notes=("收官冻结 bundle;tar.gz 与目录逐文件一致(Stage 1 抽样 7/7)",),
    ),
    # ---- 诊断会话 ----
    BatchRecord(
        batch_id="session-20260811", batch_type="diagnostic_session",
        dir_name="session-20260811",
        notes=("当日 preflight 排障会话留存;经哈希绑定 36 个冒烟 run(Stage 1 已验)",),
    ),
    # ---- 验收批次 ----
    BatchRecord(
        batch_id="acceptance-v3.5", batch_type="acceptance",
        dir_name="acceptance-20260812-v3.5", contract_version="3.5.0",
        canonical_root="evidence/stage3",
        plan_file="stage3_acceptance_plan.v3.5.json",
        has_manifest=True, has_candidates_dir=False,
        trace_validator="contracts.run_trace_validator_v3_5.validate_run_trace_v35",
        notes=(
            "M1:授权记录缺失(authorization.run/preflight 均无)——降级标注",
            "候选答案未外置(在 trace.result.structured_output 内,可推导)",
            "runs/stage3/acceptance-20260812-v3.5 为指向本目录的 symlink(L10)",
        ),
    ),
    BatchRecord(
        batch_id="acceptance-v3.8", batch_type="acceptance",
        dir_name="acceptance-20260812-v3.8", contract_version="3.8.0",
        canonical_root="evidence/stage3",
        plan_file="stage3_acceptance_plan.v3.8.json",
        config_file="run_trace_harness_config.v3.8.json",
        has_manifest=True, has_candidates_dir=True,
        reconcile_script="audit/reconcile_stage3_v3_8_execution.py",
        notes=("runs/stage3/acceptance-20260812-v3.8 为指向本目录的 symlink(L10)",),
    ),
    BatchRecord(
        batch_id="acceptance-v3.9", batch_type="acceptance",
        dir_name="acceptance-20260813-v3.9", contract_version="3.9.0",
        plan_file="stage3_acceptance_plan.v3.9.json",
        config_file="run_trace_harness_config.v3.9.json",
        has_manifest=True, has_candidates_dir=True,
        reconcile_script="audit/reconcile_stage3_v3_9_execution.py",
        notes=("L4:无 driver-console/driver-progress 日志(机制 v3.10 才引入)",),
    ),
    BatchRecord(
        batch_id="acceptance-v3.10", batch_type="acceptance",
        dir_name="acceptance-20260813-v3.10", contract_version="3.10.0",
        plan_file="stage3_acceptance_plan.v3.10.json",
        config_file="run_trace_harness_config.v3.10.json",
        has_manifest=True, has_candidates_dir=True,
        reconcile_script="audit/reconcile_stage3_v3_10_execution.py",
        notes=(
            "M3:run_bba344e2 验证器持久化前拒绝,孤立取证不可复现事件——显式标注",
            "L5:driver-progress run_invalidated 事件须按 run_id 去重对账",
        ),
    ),
    BatchRecord(
        batch_id="acceptance-v3.11", batch_type="acceptance",
        dir_name="acceptance-20260813-v3.11", contract_version="3.11.0",
        plan_file="stage3_acceptance_plan.v3.11.json",
        config_file="run_trace_harness_config.v3.11.json",
        has_manifest=True, has_candidates_dir=True,
        reconcile_script="audit/reconcile_stage3_v3_11_execution.py",
        notes=("L8:preflight 自 v3.10 carry-over(9 项等价校验,链条闭合)",),
    ),
    BatchRecord(
        batch_id="coverage-v3.11.1", batch_type="coverage",
        dir_name="coverage-20260814-v3.11.1", contract_version="3.11.1",
        plan_file="stage3_acceptance_plan.v3.11.1.json",
        config_file="run_trace_harness_config.v3.11.json",
        has_manifest=True, has_candidates_dir=True,
        reconcile_script="audit/reconcile_stage3_v3_11_1_coverage.py",
        notes=("独立补跑轮次;stage5 报告层并入 v3.10 r1 + v3.11 r3 合并单元",),
    ),
)

#: archive 副本(差距项 M2):frozen-runtime-archive 子集 → evidence 正本。
ARCHIVE_COPIES: tuple[tuple[str, str], ...] = (
    ("runs/frozen-runtime-archive/acceptance-20260812-v3.5",
     "evidence/stage3/acceptance-20260812-v3.5"),
    ("runs/frozen-runtime-archive/acceptance-20260812-v3.8",
     "evidence/stage3/acceptance-20260812-v3.8"),
)


def batch_by_id(batch_id: str) -> BatchRecord:
    for record in BATCHES:
        if record.batch_id == batch_id:
            return record
    raise KeyError(f"unknown batch_id: {batch_id}")


def acceptance_batches() -> tuple[BatchRecord, ...]:
    return tuple(b for b in BATCHES if b.batch_type in {"acceptance", "coverage"})
