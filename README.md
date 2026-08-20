# Financial Agent Evaluation Lab

一个轻量、离线优先的金融 model × agent 差异化评测 MVP。它读取任务集和单份运行配置，
顺序执行受限矩阵，输出 JSONL trace，并分别报告正确性、证据质量、安全性、延迟和
token。它不是交易系统，也不把 dev/mock 结果解释为模型排名。

## 快速开始

```bash
uv sync --locked
npm ci
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/mock.json
uv run bench run \
  --tasks tasks/dev/tasks.jsonl \
  --config configs/mock.json \
  --candidate mock-small__tool-agent \
  --slice market_data --variant valid_book \
  --output runs/mock.jsonl \
  --run-id mock
uv run bench compare runs/mock.jsonl --output runs/mock-report.json
```

真实 pi Agent 循环的零费用 Phase 0 基线：

```bash
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/pi-offline.json
uv run bench run --tasks tasks/dev/tasks.jsonl --config configs/pi-offline.json \
  --slice fundamentals --slice news_filings --slice portfolio \
  --output runs/pi-phase0.jsonl --run-id pi-phase0
uv run bench compare runs/pi-phase0.jsonl --output runs/pi-phase0-report.json
```

该命令执行 3 个逻辑模型标识 × 1 个固定 pi agent × 6 个 dev 变体，共 18 个离线 cell。
模型响应来自确定性 fixture transport，仅验证 harness、工具循环、trace 与评分链，不能解释
为三个真实模型的能力差异。

Phase 1 的零调用准备入口：

```bash
uv run bench plan-live --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-pilot.json \
  --slice fundamentals --slice news_filings --slice portfolio
```

该命令只计算请求与 token 上限，不读取密钥、不访问 provider。真实 preflight 和 pilot 仍需
分别获得付费/外部账号授权；`cost_usd_upper_bound: null` 表示 token-plan 配置没有可核验的
美元单价，不能把它解释为零费用。

已获授权的长程 harness 资格验证使用可恢复的 `soak` 状态机。以下命令把一个合成只读
任务重复执行 50 个持久化步骤；每步是一次两轮 pi 工具循环，因此每模型合计 100 个
provider turns 和 50 次工具调用：

```bash
uv run bench soak --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-calibration-v3.json \
  --slice portfolio --variant analyze_weight \
  --preflight runs/phase2/preflight.json \
  --steps 50 --experiment-id phase2-long-horizon-v1 \
  --output-dir runs/phase2/long-horizon-v1
```

每步写入独立原子文件；同版本重启会跳过已提交步骤，配置、任务、锁文件或 preflight
指纹变化时拒绝续跑。`incomplete`/`cancelled` 不进入完成聚合，模型身份漂移和非只读工具
调用是全局硬停止。

`configs/` 是唯一的用户运行配置目录；`tasks/` 只保存任务和合成 fixture；运行输出只写入
被忽略的 `runs/`。当前只有一个 CLI：`bench`。命令和 live provider 边界见
[`docs/usage.md`](docs/usage.md)，代码边界见 [`docs/architecture.md`](docs/architecture.md)。

## 验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
npm run test:pi
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/mock.json
uv build
```

所有任务数据均为合成只读数据。密钥只能通过环境变量提供，严禁进入配置、任务、trace、
日志或提交。真实模型调用、真实工具、生产写入和交易均不在默认授权范围内。
