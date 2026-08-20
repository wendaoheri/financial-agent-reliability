# Usage

## Offline workflow

```bash
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/mock.json
uv run bench run --tasks tasks/dev/tasks.jsonl --config configs/mock.json \
  --candidate mock-small__tool-agent --slice market_data --variant valid_book \
  --output runs/mock.jsonl --run-id mock
uv run bench compare runs/mock.jsonl --output runs/mock-report.json
```

`bench run` exits 0 when all cells pass, 1 when it writes traces containing diagnostic failure
signatures, and 2 for invalid input or configuration.

## Live workflow

Live calls require explicit approval and `BENCH_BAILIAN_API_KEY` in the environment:

```bash
uv run bench preflight --config configs/bailian-token-plan.json \
  --output runs/live-preflight.json
uv run bench run --tasks tasks/dev/tasks.jsonl \
  --config configs/bailian-token-plan.json \
  --preflight runs/live-preflight.json \
  --output runs/live.jsonl --run-id live
```

The preflight is bound to the run-config hash and exact returned model identities. Live execution
is plain-agent only, sequential, capped at four preflight requests and 64 matrix cells, and cannot
invoke tools or perform transactions.
