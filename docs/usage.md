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

## Framework qualification

Run the preregistered known-answer and fault-injection matrix through the normal task loader,
candidate boundary, A0/A1 adapter paths, read-only tool trace, JSONL writer, grader, aggregate,
failure-signature, secret-scan, and manifest path:

```bash
uv run bench qualify --tasks tasks/dev/tasks.jsonl \
  --config configs/framework-qualification.json \
  --slice market_data --variant valid_book \
  --output-dir runs/framework-qualification --run-id framework-qualification
uv run bench qualify-replay --tasks tasks/dev/tasks.jsonl \
  --config configs/framework-qualification.json \
  --slice market_data --variant valid_book \
  --bundle runs/framework-qualification
```

The matrix changes only action, value, reason code, citation, safety, or runtime state per control.
It reports `candidate_success`, `candidate_failure`, and `invalid_run`. Protocol, provider, adapter,
and tool failures are invalid runs: they are excluded from CSR and never emit model-failure
signatures. Safety violations remain candidate failures with a failed hard gate. The replay command
verifies every registered SHA-256 before deterministically regrading the persisted trace.

## Frozen PER-420 evaluation pack

Validate the eight dimensions, 16 task cards, synthetic fixtures, citations, family protocols,
single-factor pairs, and two independent Oracles without loading credentials:

```bash
uv run bench eval-validate --pack tasks/per420
uv run bench eval-run --pack tasks/per420 \
  --output-dir runs/per420-offline
uv run bench eval-replay --pack tasks/per420 \
  --bundle runs/per420-offline
```

The run emits deterministic success, candidate-failure, and protocol-invalid controls through the
shared protocol, grading, and outcome gates. Invalid runs are excluded from CSR and their raw
invalid output is not persisted. Replay verifies the bundle hashes and regrades every trace against
the same assets. Framework source, Git state, dependency locks, and engineering environment are not
written to traces and do not enter the Eval Pack ID. `runner_protocol_version` records experiment
protocol semantics only. The candidate and harness JSON files in this pack are frozen provenance,
not active runtime configuration.

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
Each trace records compact Agent lifecycle events plus task, candidate-config, trace-schema, and
experiment-protocol coordinates. It contains no framework source or dependency-lock coordinates. A
live pi pilot remains out of scope until separately approved.

The deterministic failure-signature control is independently reproducible:

```bash
uv run bench run --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-offline-negative-control.json \
  --slice portfolio --variant analyze_weight \
  --output runs/pi-phase0-negative.jsonl --run-id pi-phase0-negative
```

This command intentionally exits 1 after writing a `WRONG_ANSWER` trace; that exit is the expected
negative-control result.

## Live pi Agent readiness

The sole current pi live configuration uses output contract 2.1. It requires a non-null scalar for
answers, null for abstentions/refusals, a redaction-safe invalid-output diagnostic, and provider JSON
Object mode only on the second and final turn. Calculate its full ceiling without loading credentials
or making a network request:

```bash
uv run bench plan-live --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-live.json \
  --slice fundamentals --slice news_filings --slice portfolio
```

The current six-task, four-model plan is capped at four one-turn identity preflights plus 24
two-turn pi Agent cells: 52 provider requests total, with provider retries disabled. The planned
input contract is 74,624 tokens and the hard output cap is 24,832 tokens. Input tokenization and
the token-plan's USD price are not provider-verifiable before an approved preflight, so the plan
reports `cost_usd_upper_bound: null` instead of claiming zero cost.

After separate explicit approval, run exact-identity preflight first:

```bash
uv run bench preflight --config configs/pi-bailian-live.json \
  --output runs/pi-live-preflight.json
```

Only a passed report whose config hash and all four exact response model IDs match can be bound to
the run. The run uses the same slice filters as `plan-live`. It inherits only
`BENCH_BAILIAN_API_KEY`; the key never enters subprocess input, command arguments, config, trace, or
report. No live command is part of the default verification suite.

For an isolated eight-cell dev calibration, filter the same current config explicitly:

```bash
uv run bench plan-live --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-live.json \
  --slice fundamentals --slice portfolio \
  --variant positive_earnings --variant execute_trade
```

After one four-model exact-identity preflight, execute separate candidate-filtered runs with the same
bound preflight so one model's hard stop cannot suppress another model's evidence.

## Live workflow

Live calls require explicit approval and `BENCH_BAILIAN_API_KEY` in the environment:

```bash
uv run bench preflight --config configs/plain-bailian-live.json \
  --output runs/live-preflight.json
uv run bench run --tasks tasks/dev/tasks.jsonl \
  --config configs/plain-bailian-live.json \
  --preflight runs/live-preflight.json \
  --output runs/live.jsonl --run-id live
```

The preflight is bound to the run-config hash and exact returned model identities. The
`bailian-live` path is the retained plain-agent comparison axis. The `pi-agent-live` path uses the
pinned Agent lifecycle, one simulated/read-only fixture tool, sequential execution, a two-turn
ceiling, and zero automatic provider retries. Neither path can perform transactions.

## Durable long-horizon qualification

`bench soak` runs one filtered synthetic task as a durable sequence. A 50-step run executes 100
provider turns and 50 simulated read-only tool calls per candidate. It writes one atomically
committed step record plus a checkpoint and summary under the candidate directory. Re-running the
same command resumes from committed steps; a task/config/protocol/preflight fingerprint mismatch
is rejected before another provider call. Git or framework dependency changes are outside this
experiment fingerprint.

```bash
uv run bench soak --tasks tasks/dev/tasks.jsonl \
  --config configs/pi-bailian-live.json \
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
