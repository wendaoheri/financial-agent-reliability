# Financial Agent Eval Lab Working Agreement

These rules apply to every agent working in this repository. The auto-managed Multica runtime instructions remain authoritative for platform operations.

## Project purpose

This repository is a lightweight financial-agent evaluation lab. Its job is to produce small, reproducible experiments that explain differences between base models and Agent implementations. It is not a compliance archive, a global leaderboard, or an append-only baseline factory.

Keep two experiment axes explicit:

- same Agent, different model: isolate model capability;
- same model, different Agent: isolate planning, memory, tool orchestration, and recovery;
- a combined product track may exist, but do not mix it into the two isolation tracks.

## Active and legacy paths

- Active code lives under `src/financial_agent_reliability/`.
- Lightweight tasks, fixtures, candidate examples, and runner contracts live under `examples/bench/` and `src/financial_agent_reliability/bench/`.
- `docs/runner-mvp.md` and `docs/task-contract-v0.1.md` define the v0.1 execution path.
- Historical baseline, contract, validation, and audit trees are legacy evidence. Preserve them until a dedicated cleanup change removes them, but do not extend them with a new baseline generation or make their per-file hashes a gate for lightweight benchmark work.
- The `legacy-heavy-governance-v6` Git tag is the rollback point for the previous heavy-governance line.

## Versioning and evidence

Define a benchmark run with:

- Git commit or release tag;
- dependency lock files;
- candidate configuration;
- task ID and seed;
- append-only JSONL trace.

The runner should record input, tool calls, output, errors, latency, token/cost estimate, Git version, and candidate configuration automatically. Do not require people to maintain per-artifact hashes, clone a full baseline generation for a small task edit, or archive clean-room logs for routine development.

## Task and scoring protocol

- Task cards use the v0.1 schema and stay within the ten-field contract documented in `docs/task-contract-v0.1.md`.
- Prefer paired variants that change one meaningful factor and state whether the expected signal belongs to the model or Agent axis.
- Tasks move through `dev` → `pilot` → `eval`. A task enters `eval` only after pilot evidence shows useful separation without leakage.
- Score correctness 0–4, evidence quality 0–2, and safety 0/1 as a hard gate. Report cost and latency separately.
- Report at least overall, slice, and variant differences. Diagnose important failures with: symptom, trigger, attribution hypothesis, reproduction evidence, and next test.
- Never tune a task, Gold answer, or grader after seeing a named candidate's result without recording the change and returning the task to pilot.

## Engineering conventions

- Use `uv` for Python environments, dependencies, locking, and commands. Do not use pip, Poetry, or Conda directly for this project.
- Keep reusable Python in `src/financial_agent_reliability/`, tests in `tests/`, synthetic fixtures in `examples/bench/fixtures/` or `tests/fixtures/`, and human-readable design notes in `docs/`.
- Keep model and Agent adapters thin; task definitions must not depend on one provider implementation.
- Prefer the smallest CLI and file protocol that solves the current experiment. Do not add a service, database, dashboard, or governance layer without demonstrated reuse.
- Do not rewrite unrelated legacy files during lightweight benchmark work.

## Verification

Run focused tests first, then the relevant full checks before handoff:

```bash
uv run python -m unittest discover -s tests -v
npm run test:runtime
uv run bench validate --tasks examples/bench/mock-tasks.jsonl --candidates examples/bench/mock-candidates.json
```

For runner changes, also run an offline/mock `bench run` and `bench compare`, then report trace count, errors, and cost estimate. Never claim candidate quality from mock or `dev` data.

## Safety and cost boundaries

- Use synthetic, historical, read-only, or mock data by default.
- Never place an order, move money, or mutate a production financial system.
- Secrets come only from environment or platform secret facilities and must not enter source, fixtures, task cards, traces, logs, or reports.
- Paid model calls, new external accounts, additional budget, and external publication require separate explicit approval from the project owner.
- Preserve permission, prompt-injection, secret-scan, and no-real-transaction tests as hard safety gates.

## Git, PR, and Multica handoff

- Start work from the latest intended base and use a branch or PR containing the relevant `PER-XXX` key.
- If one change depends on another branch, run them serially or combine them into one integration branch; do not place dependent branches in the same parallel stage.
- A Stage child is complete only after its change is integrated and acceptance evidence is recorded. `in_review` and `blocked` are not terminal and do not close a Multica Stage.
- When a child becomes `blocked` or `in_review`, explicitly hand it back to the parent/Squad Leader for integration or acceptance; do not assume the stage barrier will wake the Leader.
- After integration and verification, the responsible reviewer moves the child to `done`; only then may the Leader promote the next stage.
- Keep changes focused, report exact commands and results, link the real PR, and state unverified areas plainly.
