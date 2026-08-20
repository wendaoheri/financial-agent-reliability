# Financial Agent Evaluation Lab

一个轻量、离线优先的金融 model × agent 差异化评测 MVP。它读取任务集和单份运行配置，
顺序执行受限矩阵，输出 JSONL trace，并分别报告正确性、证据质量、安全性、延迟和
token。它不是交易系统，也不把 dev/mock 结果解释为模型排名。

## 快速开始

```bash
uv sync --locked
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

`configs/` 是唯一的用户运行配置目录；`tasks/` 只保存任务和合成 fixture；运行输出只写入
被忽略的 `runs/`。当前只有一个 CLI：`bench`。命令和 live provider 边界见
[`docs/usage.md`](docs/usage.md)，代码边界见 [`docs/architecture.md`](docs/architecture.md)。

## 验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/mock.json
uv build
```

所有任务数据均为合成只读数据。密钥只能通过环境变量提供，严禁进入配置、任务、trace、
日志或提交。真实模型调用、真实工具、生产写入和交易均不在默认授权范围内。
