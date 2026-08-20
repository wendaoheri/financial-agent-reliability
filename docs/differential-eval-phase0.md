# 金融 Agent 差异化评测 Phase 0

本实验只产出诊断，不产出模型排名。模型轴与 Agent 工程轴分开：A0 是单轮无工具对照，A1 是最多四次模型请求的最小只读 Agent。Phase 0 只运行合成 mock，不访问模型提供商。

## 任务与判定门

任务集位于 `configs/differential_eval_phase0.v1.json`，共 8 个家族、16 张卡。每个家族只有 normal/challenge 两个变体，fixture 只改变一个登记因素。D1–D8 是不可互相抵消的门；R1–R5 只用于失败归因。

Gold 由 `experiments/oracle.py` 与 `experiments/oracle_reference.py` 两个独立实现重算。两者不一致、与任务卡登记不一致、单因素扰动不成立、引用记录不存在或密钥扫描命中时，Phase 0 直接失败。

## 运行

```bash
uv run python -m financial_agent_reliability.experiments.phase0 --validate-only
uv run python -m financial_agent_reliability.experiments.phase0 \
  --output runs/phase0/differential-dev-v1
uv run fareli-harness preflight \
  --output runs/phase0/differential-dev-v1/live-preflight.json
uv run python -m financial_agent_reliability.experiments.phase0 \
  --output runs/phase0/differential-dev-v1 \
  --preflight runs/phase0/differential-dev-v1/live-preflight.json
```

第二条命令生成：

- `phase0.validation.json`：16 卡、8 对单因素变体、双 Oracle 和密钥门结果；
- `trace.jsonl`：32 条合成 A0/A1 trace；
- `aggregate.json`：总体、slice、variant 三层聚合；
- `failure_signatures.json`：合成负对照的失败签名。
- `pilot.admission.json`：离线准入、三模型身份门和配置哈希的联合判定。

合成负对照只验证评测链路能检测差异，不是任何真实模型的结果。只有 Phase 0 全部门通过，才允许进入 3 模型 × A0/A1 × 8 张 pilot 卡的 48 单元 Phase 1。

## Phase 1 边界

Phase 1 仅包含 `EVID-01`、`METHOD-01`、`SAFE-01`、`SUIT-01`。每格运行一次，因此只能报告探索性诊断；至少两个家族出现方向一致且非格式检查主导的分离信号后，才可另行预注册重复验证。真实交易、生产写入、对外发布和模型身份回退始终禁止。
