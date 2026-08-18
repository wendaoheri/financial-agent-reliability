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
- trace schema 版本（当前 `0.1.0`）。

任务集后续遵循 dev → pilot → eval 生命周期；v0.1 仅提供合成 mock smoke，未引入
真实金融数据、外部账户或网络调用。

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

`run` 以追加方式写 JSONL，每条记录包含输入、工具调用、输出、错误、延迟、token/
成本估计、Git commit/dirty 状态和完整候选配置。`compare` 只读原始 trace；报告写入
独立文件。测试会在 compare 前后重算原始 trace SHA-256。

## 安全门

v0.1 只接受 `adapter: "mock"`，不读取 API key，不产生付费请求，不执行工具或交易。
任何 live adapter、付费模型调用、预算、外部账号和对外发布都需要项目所有者另行
明确确认，并应在新版本中实现显式预检门。
