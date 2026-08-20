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

## Live pi Agent Phase 1 readiness

Calculate the full Phase 1 ceiling without loading credentials or making a network request:

```bash
uv run bench plan-live --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-pilot.json \
  --slice fundamentals --slice news_filings --slice portfolio
```

The current six-task, four-model plan is capped at four one-turn identity preflights plus 24
two-turn pi Agent cells: 52 provider requests total, with provider retries disabled. The planned
input contract is 74,624 tokens and the hard output cap is 24,832 tokens. Input tokenization and
the token-plan's USD price are not provider-verifiable before an approved preflight, so the plan
reports `cost_usd_upper_bound: null` instead of claiming zero cost.

After explicit approval, run exact-identity preflight first:

```bash
uv run bench preflight --config configs/pi-bailian-pilot.json \
  --output runs/pi-live-preflight.json
```

Only a passed report whose config hash and all four exact response model IDs match can be bound to
the pilot. The pilot uses the same slice filters as `plan-live`. It inherits only
`BENCH_BAILIAN_API_KEY`; the key never enters subprocess input, command arguments, config, trace, or
report. No live command is part of the default verification suite.

Phase 1.1 uses a new output contract rather than changing or rescoring the Phase 1 trace. It fixes
the reason-code ontology, records only a redaction-safe invalid-output classification/length/hash,
and runs each model independently so one model's safety hard stop cannot suppress evidence from a
different model. Calculate the approved eight-cell calibration without network access:

```bash
uv run bench plan-live --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-calibration-v2.json \
  --slice fundamentals --slice portfolio \
  --variant positive_earnings --variant execute_trade
```

After one four-model exact-identity preflight, execute four separate filtered runs with the same
bound preflight. Each run orders the normal calculation before the safety case and preserves the
per-model hard stop. Phase 1 and Phase 1.1 traces must not be concatenated into one ranking.

Contract/call calibration 2.1 is configured separately in
`configs/pi-bailian-calibration-v3.json`. It explicitly requires null values for abstentions and
refusals, and uses provider JSON Object mode only on the second (final) turn. Plan it offline with
the same two calibration cells before seeking approval for any new live calls:

```bash
uv run bench plan-live --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-calibration-v3.json \
  --slice fundamentals --slice portfolio \
  --variant positive_earnings --variant execute_trade
```

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

The preflight is bound to the run-config hash and exact returned model identities. The legacy
`bailian-live` path is plain-agent only. The `pi-agent-live` path uses the pinned Agent lifecycle,
one simulated/read-only fixture tool, sequential execution, a two-turn ceiling, and zero automatic
provider retries. Neither path can perform transactions.

## Durable long-horizon qualification

`bench soak` runs one filtered synthetic task as a durable sequence. A 50-step run executes 100
provider turns and 50 simulated read-only tool calls per candidate. It writes one atomically
committed step record plus a checkpoint and summary under the candidate directory. Re-running the
same command resumes from committed steps; a task/config/lock/preflight fingerprint mismatch is
rejected before another provider call.

```bash
uv run bench soak --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-calibration-v3.json \
  --slice portfolio --variant analyze_weight \
  --preflight runs/phase2/preflight.json \
  --steps 50 --experiment-id phase2-long-horizon-v1 \
  --output-dir runs/phase2/long-horizon-v1
```

Provider retries remain zero. A cancel-file passed with `--cancel-file` yields `cancelled` before
the next step. Provider errors yield `incomplete`; neither terminal state enters the completed
aggregate. Exact identity failure, fallback, a non-read tool call, duplicate tool execution, or a
persisted-secret finding is a hard stop. This qualification measures workflow durability and
provider binding, not task quality or model ranking.
