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

## Offline pi Agent Phase 0

Install the exact-pinned Node runtime once, then execute the six-cell dev selection:

```bash
npm ci
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/pi-offline.json
uv run bench run --tasks tasks/dev/tasks.jsonl --config configs/pi-offline.json \
  --slice fundamentals --slice news_filings --slice portfolio \
  --output runs/pi-phase0.jsonl --run-id pi-phase0
uv run bench compare runs/pi-phase0.jsonl --output runs/pi-phase0-report.json
```

The adapter executes the real `pi-agent-core@0.73.1` `Agent.prompt()` lifecycle and one sequential
read-only tool call per task. Its faux model transport is deterministic and has zero provider cost.
The three model names are logical future-pilot coordinates, not claims that those live models ran.
Each trace records compact Agent lifecycle events plus the Python and Node lock hashes. A live pi
pilot remains out of scope until separately approved.

The deterministic failure-signature control is independently reproducible:

```bash
uv run bench run --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-offline-negative-control.json \
  --slice portfolio --variant analyze_weight \
  --output runs/pi-phase0-negative.jsonl --run-id pi-phase0-negative
```

This command intentionally exits 1 after writing a `WRONG_ANSWER` trace; that exit is the expected
negative-control result.

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
