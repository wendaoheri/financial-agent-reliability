# Stage 3 v3.11.1 — Single-Unit Coverage Plan Preregistration (PER-77)

Date: 2026-08-14. Status: frozen offline; pending independent gate re-review.
No paid calls, no candidate/model requests, no preflight, no secret reads this round.

## Why

v3.11 continuation sequence 268 (`run_c0f58d3c0d9227585058c4e4872a468b`,
deepseek-v4-pro / case-synthetic-ftw-14-normal-v3 / repeat 2) was torn down by
the agent runtime (session teardown) mid-unit with only a `run_started`
checkpoint event. It was invalidated report-only under the frozen
`no_post_hoc_selection` policy. The unit therefore has only two valid records
(repeat 1 from the v3.10 round, repeat 3 from the v3.11 round); the v0.1
confirmed scope needs three for PER-32 `pass^3` and ranking stability.

## What moved, what did not

- Plan-only version bump: `contracts/stage3_acceptance_plan.v3.11.1.json`
  (plan_version 3.11.1, contract_version stays 3.11.0), `supersedes` → the
  v3.11 continuation plan.
- Contracts byte-exact: v3.11 bundle
  `b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d`, config
  `bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e`; no change
  to prompts, oracle, thresholds, reason semantics, or case materials; v3.5–v3.11
  frozen artifacts zero drift.
- The plan carries exactly ONE task/run: the invalidated unit at repeat 2.

## Frozen hashes

| Artifact | Hash |
|---|---|
| plan_sha256 (v3.11.1) | `64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b` |
| plan_core_sha256 (v3.11.1) | `c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b` |
| coverage run_id | `run_0e1e8f4400e16f22f6581e0bb0d9c54d` |
| coverage seed | `738396034` (equals seq 268 seed; formula and master_seed 20260813 unchanged) |

Identity separation from seq 268 comes exclusively from the new
`plan_core_sha256` commitment (single-task core: contract_version +
config_sha256 + models=[deepseek-v4-pro] + the one task_inputs entry). Seed,
case, model, repeat, variant, and config hash are all identical to seq 268 —
no post-hoc reselection. The coverage run id is disjoint from all 1540
historical v3.5–v3.11 plan run ids (checked) and never reuses the invalidated id.

## Invalidation forensics (preserved, never replaced)

- `runs/stage3/acceptance-20260813-v3.11/invalidated-runs.json`
  (file sha256 `7fd165fa…547a7`, report_sha256 `3a5189e7…68bda`)
- `runs/stage3/acceptance-20260813-v3.11/pending-invalidations.json`
  (`61c7baec…47946`)
- checkpoint residue `checkpoints/run_c0f58d3c….jsonl` (`68f0e738…85b6`)

`coverage_replaces_or_reexecutes_invalidation = false` everywhere (plan,
coverage_map, authorization). The seq 268 run id is explicitly in the
authorization's `denied_run_ids`.

## Authorization design (binds exactly 1 run id)

`runs/stage3/coverage-20260814-v3.11.1/authorization.run.json`
(kind `financial_acceptance_single_unit_coverage_run`, self-hash
`authorization_sha256`):

- `authorized_run_ids` = exactly `[run_0e1e8f44…]`; `authorized_run_count` 1;
  `maximum_runs` 1; `exact_model_ids` = `[deepseek-v4-pro]`.
- `out_of_scope_policy`: any run_id not exactly in `authorized_run_ids`
  (including all 1540 historical ids) must be rejected before any provider
  request; the seq 268 id is additionally in `denied_run_ids`.
- Binds `plan_sha256`, `plan_core_sha256`, the unchanged bundle/config hashes,
  and the carry-over `preflight_sha256`.
- Basis: owner standing scope `standing_all_paid_runs_owner_2026_08_12`
  (parent issue metadata), PER-77, 2026-08-14.
- `execution_gate`: independent gate review **pending**; delivery-owner
  dispatch required before the artifact may be consumed.

Preflight is a documented carry-over of the v3.11 preflight
(`a1abbba9…d19`, itself the PER-63 carry-over of v3.10 `669cbd04…ef3f`):
config byte-identical, coverage case tool-schema vector
`118f9266…` identical between the v3.11 and v3.11.1 plans, deepseek
parameter commitment `429e4c97…` equal to the config commitment. Zero paid
preflight calls.

## Reproduce

```
uv run python -m harness.acceptance_v3_11_1 verify-plan
uv run python -m harness.acceptance_v3_11_1 verify-contracts
uv run python audit/verify_v3_11_1_coverage_pre_execution.py
uv run python audit/build_stage3_v3_11_1_execution_artifacts.py   # idempotent rebuild
uv run python -m unittest discover -s tests                        # 239 tests
uv run python -m harness.acceptance_v3_11 verify-contracts
uv run python -m harness.acceptance_v3_11 verify-plan
node --test tests/integration/financial_acceptance_v3_11.test.mjs  # 13 tests
```

Files added this round: `harness/acceptance_v3_11_1.py`,
`contracts/stage3_acceptance_plan.v3.11.1.json`,
`audit/build_stage3_v3_11_1_execution_artifacts.py`,
`audit/verify_v3_11_1_coverage_pre_execution.py`,
`audit/v3_11_1_coverage_authorized_run_ids.json`,
`tests/test_financial_acceptance_v3_11_1.py`,
`runs/stage3/coverage-20260814-v3.11.1/` (plan/config/bundle frozen copies,
`preflight.json`, `authorization.run.json`). No existing frozen artifact was
modified.
