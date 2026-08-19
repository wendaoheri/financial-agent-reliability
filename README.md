# Financial Agent Evaluation Lab

一个轻量、离线优先的金融 Agent 差异化评测实验室。当前主路径用同一任务集分别改变
`model` 与 `agent`，自动生成 JSONL trace，并从正确性、证据质量和安全性三个层面解释
差异。它不是生产交易系统，也不把 mock/dev 结果当作真实模型排名。

v0.1 内部收口结论、证据坐标和边界见
[`docs/internal-v0.1-report.md`](docs/internal-v0.1-report.md)。

## 快速开始

环境基线为 Python 3.11；Python 命令统一通过 `uv` 执行。以下流程完全离线、零付费：

```bash
uv sync
npm ci
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

`bench run` 在发现诊断签名时返回 1，但仍会完整写出 trace；输入或契约错误返回 2。
命令、trace 字段和退出码详见 [`docs/runner-mvp.md`](docs/runner-mvp.md)；任务卡、
Gold/Oracle 和评分契约位于 `docs/` 的 v0.1 任务契约说明中。

## 活跃目录

| 路径 | 用途 |
| --- | --- |
| `src/financial_agent_reliability/bench/` | `validate`、`run`、`compare`、adapter、独立 grader 与 trace 协议 |
| `src/financial_agent_reliability/bench/contracts/` | 轻量 trace、任务、评分和推理配置 schema |
| `examples/bench/` | 8 个金融 slice、16 个成对变体、合成 fixture、mock 与负控候选 |
| `tests/test_bench_mvp.py` | Gold 隔离、工具轴、评分、配对差异、负控和 trace 回归测试 |
| `docs/runner-mvp.md` | v0.1 Runner 使用与解释边界 |
| `docs/` 的 v0.1 任务契约说明 | 十字段以内任务卡与 `dev → pilot → eval` 生命周期 |
| `runs/` | 本地运行产物；不作为 Git 跟踪内容 |

其他 `harness`、`baseline/v2`、v2 冻结验证和历史复盘材料是 legacy 证据或兼容路径，
不是日常轻量实验入口。失败的 baseline v3–v6 及其配套代码已从工作树清理；完整重型
治理线仍可从 Git tag `legacy-heavy-governance-v6`（`7d36f9e`）回溯。

## 当前能力与边界

- 任务集：8 个 slice、每个 2 个成对变体，当前全部为 `dev`。
- 候选轴：同 Agent 比 model、同 model 比 Agent；无可观察变化时输出
  `non_identifiable`。
- trace：记录输入、候选配置、工具调用、输出、错误、延迟、token/成本估计和 Git 版本。
- 评分：correctness 0–4、evidence 0–2、safety 0/1 硬门；成本和延迟单列。
- 工具：当前仅验证 Runner-owned 合成只读工具；禁止真实交易和生产写入。
- 权限：付费模型、外部账号、额外预算和对外发布都需项目所有者另行明确批准。

PER-390 已批准一次百炼 token-plan 四模型内部 MVP。受控入口为
`examples/bench/bailian-token-plan-candidates.v0.1.json`；它只支持 plain-agent，要求
先运行 `bench preflight` 并把通过报告传给 `bench run --preflight`，总请求数最多
4 次预检 + 64 个矩阵单元。完整命令与边界见 `docs/runner-mvp.md`。该授权不扩展到
真实工具、交易、生产写入或对外发布。

## 验证

```bash
uv run python -m unittest tests.test_bench_mvp -v
uv run python -m unittest discover -s tests -v
npm run test:runtime
uv run bench validate \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/mock-candidates.json
uv run bench validate \
  --tasks examples/bench/mock-tasks.jsonl \
  --candidates examples/bench/negative-control-candidates.json
```

凭据只能通过环境或平台密钥能力注入，严禁进入源码、fixture、task card、trace、日志
或报告。`configs/` 只保留被 baseline v2 钉住的历史兼容配置；轻量路径的推理配置实例
放在 `examples/bench/`，其 schema 与加载器分别位于 `bench/contracts/` 和 `bench/`。
