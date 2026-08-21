# Project Working Agreement

## Scope

- This repository contains one Python MVP: an offline-first financial model × agent benchmark.
- Keep runtime configuration only in `configs/`, task data only in `tasks/`, package code in
  `src/financial_agent_reliability/`, and tests in `tests/`.
- Do not add baseline, snapshot, evidence-freeze, migration, retrospective, report archive,
  compatibility alias, or version-copy directories. Git history is the archive. The sole Node
  boundary is the exact-version pi agent adapter declared in `package.json`; `bench` remains the
  only user-facing CLI.

## Python

- Use Python 3.11 and `uv` for environments, locking, dependencies, builds, and commands.
- Keep one console entry point: `bench = financial_agent_reliability.cli:main`.
- Load package resources with `importlib.resources`; package code must not infer a repository root,
  mutate `sys.path`, or install import aliases.
- Put all tool configuration in `pyproject.toml`. Run Ruff and unittest before handoff.

## Evaluation and safety

- Keep model and agent as separate axes. Tasks use `dev`, `pilot`, or `eval` lifecycle labels.
- Evaluation provenance covers evaluation assets and experiment records only. Record experiment
  input, tool calls, output, errors, latency, token/cost estimates, task hash, and config hash in
  JSONL traces.
- Treat the evaluation framework as replaceable engineering infrastructure. Source commits,
  dependency locks, operating-system details, clean/dirty state, source hashes, and framework
  release status must not become Eval Pack identity, Run Record evidence, Claim evidence, or an
  experiment admission gate. Manage them only through the repository's normal Git, PR, test, and
  build workflow. Any future framework-level replay requirement is a separate scope that needs
  explicit owner approval.
- Use `runner_protocol_version` only for the semantic compatibility of experiment inputs, outputs,
  tools, and scoring. It is not a framework code version and requires no commit mapping.
- `tasks/per420/` is the authoritative PER-420 asset pack. Its task, fixture, and scoring contracts
  define the evaluation; its candidate and harness contracts preserve historical experiment
  coordinates and are not executable live configuration.
- Keep `bench` as the only user-facing entry point. Do not recreate an `experiments` package,
  phase-specific Runner, alternate CLI, direct provider loop, or parallel grading path.
- Classify framework, provider, adapter, tool, and protocol failures as `invalid_run`; exclude them
  from candidate success rates and failure signatures. For protocol-invalid output, retain only the
  classification, length, and digest, never the raw content.
- For public-frozen or synthetic read-only tasks, an explicitly enabled research trace may retain
  the exact final assistant text after the JSON and top-level protocol are valid, including for
  `candidate_failure`. Bind it to the bundle hash and replay. Never retain raw reasoning, provider
  headers, credentials, or protocol-invalid content; retain only their approved metadata/digests.
- Scores remain correctness 0–4, evidence 0–2, and safety 0/1 with a safety hard gate.
- Use synthetic/read-only fixtures by default. Never place secrets or private data in source,
  configs, tasks, traces, logs, or reports. Never perform real trades or production writes.
- Paid model calls and external-account use require explicit owner approval.
- `bench plan-live` is the required zero-network budget evidence before a live pi preflight. Never
  infer approval for `bench preflight` or a live `bench run` from approval to implement the adapter.

## Verification

```bash
uv sync --locked
npm ci
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
npm run test:pi
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/mock.json
uv run bench eval-validate --pack tasks/per420
uv run bench eval-run --pack tasks/per420 --output-dir runs/per420-offline
uv run bench eval-replay --pack tasks/per420 --bundle runs/per420-offline
uv run bench plan-live --tasks tasks/dev/tasks.jsonl --config configs/pi-bailian-live.json \
  --slice fundamentals --slice news_filings --slice portfolio
uv build
```
