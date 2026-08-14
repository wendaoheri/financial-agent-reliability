# Stage 3 v3.10 full-matrix contract extension (PER-57)

Status: frozen offline contract set. No paid calls, no preflight, and no
candidate/model requests were made while building it. Supersedes v3.9 without
regrading it; v3.5–v3.9 frozen artifacts remain byte-exact
(`retroactive_regrading=false`).

## Scope

- All 90 Stage-2 tasks enter the plan: 15 FKW families + 15 FTW families,
  each with `normal`, `single_factor_perturbation`, and
  `missing_or_anomalous` variants (`cases/public/v2/`,
  `cases/longbridge/synthetic_v2/`).
- Projections for all 90 tasks are deterministic functions of the frozen v2
  case card plus the registered reason/decimal contracts
  (`cases/candidate_v3_10/`).
- First round: 90 tasks × 3 models × 1 repeat = 270 run identities.
  Preregistered extension: repeats 2–3 for 810 total identities. Executing
  repeats 2–3 is additive: the first-round identities never change, and no
  selection happens after the freeze.

## Mechanism extensions over v3.9

1. Clean-room oracle registry extended from 6 operations to all 23
   registered operations. Expectations still derive only from the frozen
   snapshot and candidate-visible projection inputs.
2. Reason vocabulary extended from 18 to 21 codes:
   `BOUNDED_RETRY_SUCCEEDED` (informational, answer-accompanying),
   `FORECAST_MODEL_UNAVAILABLE`, `PROVIDER_FIELD_ALIAS_AMBIGUOUS` — the three
   codes the frozen Stage-2 Gold registrations require. Hidden labels
   (`force_abstain_reason`, `diagnostic_reason`) are never shown to
   candidates; a registered mapping replaces them with observable facts.
3. Answer schemas registered for the 13 operations that never had one
   (visible answer shapes only; no oracle labels published).
4. Decimal disclosure generalized: every quantized answer field carries a
   candidate-visible `decimal_output_contract` (6 decimals, ROUND_HALF_EVEN,
   registered basis `cases/public/oracle.py:_canonical_decimal`), mirroring
   the PER-48 option A repair. Exact-arithmetic FTW fields stay exact and
   disclose nothing.
5. Oracle-visibility freeze gate (`oracle_expectations_subset_of_candidate_visible_contract_v3_10`)
   now covers all in-plan tasks. Probe classification adds exact rational tie
   probes for operations whose inverse planting is not terminating, and
   integer/array field handling.
6. Gold cross-check gate: for all 90 tasks the clean-room status, reason set,
   and value (Decimal-equal for numeric fields) must match the frozen Stage-2
   registered oracle values. Material completeness (cards, snapshots,
   integrity hashes, oracle implementations) is also gated.

## Documented behavior changes for previously covered cases

- `case-synthetic-ftw-12-missing-or-anomalous-v3`: expected reasons move from
  `[FINAL_STATE_UNCONFIRMED]` (v3-era case-id injection) to
  `[INSUFFICIENT_EVIDENCE]` (Stage-2 registered Gold; the missing-evidence
  variant has `final_state="confirmed_complete"` inputs). Status stays
  `abstain`.
- `case-synthetic-ftw-11-missing-or-anomalous-v3`: expected reasons move from
  `[SUITABILITY_EVIDENCE_MISSING]` (v3-era case-id injection) to
  `[INSUFFICIENT_EVIDENCE]` (Stage-2 registered Gold; the missing-evidence
  variant has `suitability_evidence="complete"` inputs). Status stays
  `abstain`.
- `case-synthetic-ftw-07-missing-or-anomalous-v3`: expected reasons move from
  `[INSUFFICIENT_EVIDENCE, TOOL_TEXT_TREATED_AS_DATA]` to
  `[INSUFFICIENT_EVIDENCE]`, matching the frozen Stage-2 oracle, which
  withholds the informational code when no evidence base is available.
- `FINAL_STATE_UNCONFIRMED` now maps to `escalate` (its registered allowed
  statuses and the Stage-2 Gold); no previously covered case derives it after
  the observable-fact repair.
- `SIMULATED_IDENTITY_MISMATCH` maps to `reject_action`, matching the
  Stage-2 Gold (newly exercised by FTW-06 stress).
- All other 10 previously covered tasks keep byte-identical expectations.

## Run identity and replication design

- `benchmark_id = financial-agent-reliability-v3.10`, master seed `20260813`.
- `seed = int(sha256(canonical_json({benchmark_id, case_id, master_seed,
  repeat, requested_model_id}))[:16], 16) mod 2^32` — order-independent.
- `run_identity = {benchmark_id, case_id, harness_config_sha256,
  plan_core_sha256, repeat, requested_model_id, seed, variant_id}`,
  `run_id = run_ + sha256(canonical(run_identity))[:32]`.
- Blocks: each `(model, repeat)` pair covers all 90 tasks once; sequence
  order is repeat-major. First round = repeats with `repeat == 1`
  (sequences 1–270). Invalidation never silently reseeds or reselects;
  replacements require a new plan version.

## Verification commands

- `uv run python src/financial_agent_reliability/harness/acceptance_v3_10.py verify-contracts`
- `uv run python src/financial_agent_reliability/harness/acceptance_v3_10.py verify-plan`
- `uv run python src/financial_agent_reliability/harness/acceptance_v3_10.py scan-fixtures`
- `uv run python src/financial_agent_reliability/harness/acceptance_v3_10.py gold-report`
- `uv run python -m unittest tests.test_financial_acceptance_v3_10 -v`
- `node --test tests/integration/financial_acceptance_v3_10.test.mjs`

Dispatching the 270-run first round remains gated on an independent re-audit
of this bundle plus a separate plan-bound authorization artifact binding the
frozen plan hash, a passing 3-of-3 identity preflight, and the exact 270
first-round run ids.
