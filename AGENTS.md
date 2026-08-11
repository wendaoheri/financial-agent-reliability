
# Project Working Agreement

These rules apply to every agent working in this directory. The auto-managed
Multica runtime block above remains authoritative for platform operations.

## Project Purpose

- Treat `金融Agent系统性失效问题研究报告.html` as the research starting point,
  not as a frozen standard or implementation template.
- Optimize for detecting and controlling high-loss failures, correlated errors,
  unsafe execution, and responsibility gaps in financial-agent systems.
- Keep research evidence, evidence-based financial inference, and illustrative
  examples explicitly separated.

## Python and Environment Management

- Use `uv` exclusively for Python versions, virtual environments, dependency
  changes, locking, and command execution.
- The supported Python baseline is 3.11, pinned in `.python-version`; the local
  environment lives in `.venv`.
- Run project commands as `uv run <command>`. Add or remove dependencies with
  `uv add` and `uv remove`; do not use `pip`, Poetry, Conda, or hand-edit the
  resolved `uv.lock` file.
- After dependency changes, commit both `pyproject.toml` and `uv.lock` when the
  directory is placed under version control.

## Research and Data Discipline

- Record a source, publication date, access date when relevant, jurisdiction or
  market, and applicability limits for factual claims.
- Label conclusions as direct evidence, inference, or illustration. Preserve
  counterevidence and uncertainty instead of smoothing disagreements away.
- Never place credentials, private account data, licensed datasets, or material
  non-public information in source files, fixtures, logs, reports, or prompts.
- Use only synthetic or explicitly approved data for tests. No test or example
  may place a real order, move money, or mutate a production financial system.

## Implementation Conventions

- Keep executable validation logic deterministic. Freeze versioned contracts,
  schemas, preregistrations, and expected outputs before candidate evaluation;
  do not modify them after seeing candidate results without a new version and a
  documented rationale.
- Put reusable code in importable modules, tests in `tests/`, fixtures under
  `tests/fixtures/`, and human-readable design or contract notes under `docs/`.
- Preserve traceability from raw input and data snapshot through tool calls,
  intermediate decisions, grader output, and the final report.
- Prefer small, reviewable changes. Do not rewrite unrelated files or silently
  change frozen artifacts.

## Verification and Handoff

- Run the relevant focused test first, then the full suite with
  `uv run python -m unittest discover -s tests -v` before handoff.
- Validate generated JSON and reports against their schemas or deterministic
  expected outputs. Report the exact commands run and any unverified areas.
- A successful average score is not sufficient acceptance evidence: verify
  high-loss cases, abstention and escalation behavior, identity and time-basis
  checks, provenance, permission boundaries, and independent validation where
  the affected contract requires them.
