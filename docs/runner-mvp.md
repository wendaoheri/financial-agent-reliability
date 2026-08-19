# 轻量 Runner MVP（v0.1）

本路径用于区分基础模型差异和 Agent 工程差异，不延续 baseline v2–v6 的逐文件
冻结治理作为日常主执行路径。旧材料完整保留；legacy 回退点为 Git tag
`legacy-heavy-governance-v6`，指向提交 `7d36f9e`。

## 版本和双轴

一次候选由 `model` 与 `agent` 两个独立字段定义，`candidate.id` 只负责稳定引用。
实验版本由以下证据共同确定：

- Git commit（自动写入每条 trace）；
- Python/Node 锁文件；
- 候选 `config` 的规范化 SHA-256；
- 任务集与候选清单文件 SHA-256；
- trace schema 版本（当前 `0.2.0`；读取器继续兼容 `0.1.0`）。

任务集遵循 dev → pilot → eval 生命周期；任务字段、评分硬门、Oracle 和首批 4-slice
合成 smoke 见 `docs/task-contract-v0.1.md`。v0.1 未引入真实金融数据、外部账户或
网络调用。

## 单命令工作流

```bash
uv sync
uv run bench validate \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json
uv run bench run \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json \
  --output runs/bench/mock-smoke.jsonl \
  --run-id mock-smoke
uv run bench compare runs/bench/mock-smoke.jsonl \
  --output runs/bench/mock-smoke-report.json
```

默认示例清单提供 2 个 mock model × 2 个 mock agent 的完整笛卡尔矩阵。候选行只声明
`model`、`agent`、`adapter` 和 adapter 自有 `config`；Runner 不读取任务语义来选择
候选，任务卡也不引用候选配置。可重复传入 `--slice`、`--variant`、`--candidate` 只跑
目标单元，例如：

```bash
uv run bench run --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json \
  --output runs/bench/portfolio-refusal.jsonl --run-id portfolio-refusal \
  --slice portfolio --variant execute_trade --candidate mock-small__plain-agent
```

`run` 以追加方式写 JSONL，每条记录包含输入、工具调用、输出、错误、延迟、token/
成本估计、Git commit/dirty 状态、任务集/候选/锁文件哈希和完整候选配置。`compare`
只读原始 trace；报告写入独立文件，并输出 overall、slice、variant 三层结果及 model、
agent、candidate 三种轴向视图；成本与延迟位于 `operational_metrics`，不进入质量分。
测试会在 compare 前后重算原始 trace SHA-256。

mock adapter 支持 `failure`、`timeout`、`tool_error`、`missing_evidence`、
`safety_violation` 故障注入。失败 trace 照常落盘并带失败签名；存在任一失败签名时
`bench run` 返回 1，输入/契约错误返回 2。缺证会保留结构化低分，但不伪装
成执行异常。此适配器不模拟 provider 协议、真实 token 计费或网络尾延迟。

`validate` 对正式任务卡执行 JSON Schema、fixture 元数据与引用闭包、成对变体及
确定性 Gold/Oracle 重算校验。为方便从 Runner MVP 迁移，加载器暂时仍接受旧的
`task_id` / `input` 简版行；新任务不得再使用该兼容格式。

## 安全门

v0.1 只接受 `adapter: "mock"`，不读取 API key，不产生付费请求，不执行工具或交易。
任何 live adapter、付费模型调用、预算、外部账号和对外发布都需要项目所有者另行
明确确认，并应在新版本中实现显式预检门。
