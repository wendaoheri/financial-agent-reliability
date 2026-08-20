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
- Record input, tool calls, output, errors, latency, token/cost estimates, task hash, and config hash
  in JSONL traces. Record Git state when the command runs inside a Git worktree; otherwise use null.
- Scores remain correctness 0–4, evidence 0–2, and safety 0/1 with a safety hard gate.
- Use synthetic/read-only fixtures by default. Never place secrets or private data in source,
  configs, tasks, traces, logs, or reports. Never perform real trades or production writes.
- Paid model calls and external-account use require explicit owner approval.

## Verification

```bash
uv sync --locked
npm ci
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
npm run test:pi
uv run bench validate --tasks tasks/dev/tasks.jsonl --config configs/mock.json
uv build
```
