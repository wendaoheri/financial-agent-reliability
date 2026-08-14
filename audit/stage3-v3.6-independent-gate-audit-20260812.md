## Independent gate decision

`fail`

v3.6 does not meet the technical gate for either a paid identity preflight or the
new 36-run. This decision does not grant or consume any paid-call authorization.
No candidate model call was made during this audit.

Evidence labels in this report are explicit: command results and frozen-file
inspection are **direct evidence**; gate consequences are **inferences** from
those results. No illustrative result is used as acceptance evidence.

## Integrity results (direct evidence)

- v3.5 combined contract bundle recomputed:
  `d24948f9f36639600fc3d206d83cedd98970b11317282fdfdb92ecbc9d2c9cb8`.
- v3.5 evidence bundle (112 artifacts) recomputed:
  `9f0123159f3e7018bfee423dd11d5bd902649ee0c0cfe01f3b921980acfa5532`;
  112/112 artifact hashes matched.
- v3.5 manifest file SHA-256:
  `8ff16f9c99ff967d1e950135a19296ebb728c391622b355958e8f53706b76191`.
- v3.6 bundle recomputed:
  `afd1a163d9d205449b8e90c15086b21b42b831571ac20c8066c916c31874c959`;
  33/33 artifact hashes matched.
- v3.6 config file SHA-256:
  `fc90c1f0f9bcd161e5d4037743c10239a0e482de71302c1e1f74803f2bae2653`.
- v3.6 plan canonical SHA-256:
  `7874bd77c0862a797bcde2f88851b89041ee12dd71e2dd50a1764dbd502844b1`;
  plan file SHA-256:
  `3eb65d69c4434c8b98f457f46667e928a8a11b400fa6aefa8d82e009e584e3ac`.
- v3.6 revision freeze SHA-256:
  `deddc53eaf7a10a3b81e95205b53d123339c565492eb5bda43171dd558774298`.
- v3.6 adjudication-ledger freeze SHA-256:
  `a7f20669344830461e498095d993e7b522cc3608d96bc217afe2b8ee04583f21`.
- All 12 source-case, projection, and snapshot hashes referenced by the plan
  matched. The plan contains 12 tasks, 36 unique run IDs, exactly 12 cells per
  exact model ID, one cell per case/model pair, and zero run-ID overlap with
  v3.5.
- Static leakage scan found no `oracle`, `expected_*`, answer-key, grader, or
  candidate/provider-failure fields in `cases/candidate_v3_6`. The published
  required/allowed reason sets are part of the prospectively frozen candidate
  contract, not a newly introduced hidden-output field.

## Positive controls (direct evidence, limited applicability)

- Decimal arithmetic uses base-10 precision 34, `ROUND_HALF_EVEN`, an exact
  unrounded threshold comparison, six-decimal lexical validation, and a separate
  absolute-tolerance check. Boundary tests passed.
- The static payload normalizer gives all three exact model IDs the same common
  controls and gives only `qwen3.8-max` the documented Bailian protocol flag
  `enable_thinking=false`; GLM and DeepSeek receive no Qwen-only flag.
- The static policy preregisters one provider retry, zero semantic retries,
  identical replay, capped Retry-After, no selective rerun, no imputation, and
  ranking withholding under asymmetric coverage. Unit fixtures distinguish
  empty/timeout/429 provider failures from a candidate parse failure.

These controls do not cure the blockers below because the v3.6 execution path
does not wire them into an executable run.

## Blocking findings

### B1 — Critical — v3.6 live harness is a successful no-op

**Direct evidence.** `harness/live_acceptance_v3_6.mjs` is 87 lines and exports
only schema/prompt/payload/retry helper functions. It has no CLI `main`, no
preflight, no run loop, no trace/grader/checkpoint writer, and no authorization
gate. Running it with the frozen plan exited 0, emitted nothing, and created no
output directory:

```text
node harness/live_acceptance_v3_6.mjs \
  --plan contracts/stage3_acceptance_plan.v3.6.json \
  --output-dir reports/_audit_should_not_exist
# exit 0; no stdout/stderr; no output directory
```

**Impact (inference).** Stage 4 cannot execute or prove a v3.6 preflight/36-run;
an operator can mistake a no-op exit 0 for success.

**Minimum repair.** In a new superseding frozen version, implement an executable
runner that binds the v3.6 prompt, tools, budget, provider retry state machine,
authorization/preflight gate, strict trace validation, independent grader, and
checkpoint/evidence output. Add a CLI integration test that requires 36
auditable outputs and rejects offline-only plans without new authorization.

### B2 — Critical — model identity and replay commitments are not enforced

**Direct evidence.** Three one-factor mutations of the baseline trace all
returned `status=succeeded`, `candidate_scored=true` from
`validate_run_trace_v36`:

- `provider.response_model_id="unexpected-fallback"`;
- `attempts[0].model_id="deepseek-v4-pro"` while the requested model is Qwen;
- invalid non-SHA values in `tool_schema_sha256` and `parameters_sha256`.

The validator checks the requested ID but not the response ID or each attempt's
ID, and validates neither commitment on a single-attempt success. It also does
not bind the run identity to membership in the frozen plan.

**Impact (inference).** Fallback/model substitution or tool/parameter drift can
enter the accepted 36 cells as a valid candidate result, invalidating fairness
and model attribution.

**Minimum repair.** Require response model ID and every attempt model ID to
equal the requested exact ID; validate 64-hex tool/parameter hashes against the
actual frozen request; bind run identity, case, seed, model, config/core hash,
and run ID to the frozen plan; add independent negative fixtures for each field.

### B3 — Critical — grader is not independent for evidence, PIT, structure, unit, method, or calculation

**Direct evidence.** The baseline candidate received all checks true although
its trace contains no `evidence_observations`; `evidence_sufficient` trusts only
candidate-claimed record IDs. Removing required candidate fields `uncertainty`
and `permission_boundary_claimed` still produced `structure_parsed=true` and
`all_applicable_checks_passed=true`. Changing either field also changed no
grader check. The check set contains no independent PIT, evidence provenance,
unit, method, or calculation check. The trace schema has no evidence-observation
or availability-at contract. Expected values are copied from the source card's
`oracle` (`harness/acceptance_v3_6.py:289-294`), with FKW-12 numbers hard-coded,
rather than recomputed from frozen evidence by an independent implementation.

**Impact (inference).** A candidate can claim unread evidence, omit required
wire fields, or be scored without time-basis provenance. Method/unit/calculation
errors collapse into one opaque semantic comparison and cannot be isolated or
audited as required.

**Minimum repair.** Validate candidate output against the frozen per-case wire
schema before semantic grading; add trace-bound evidence observations and
availability cutoffs; recompute Gold answers independently from frozen snapshots;
split PIT, evidence provenance/sufficiency, unit, method, calculation, lexical,
and numeric checks; add one-factor positive and negative fixtures for every
domain.

### B4 — Critical — the secret scanner exists but is not part of acceptance

**Direct evidence.** Injecting `Bearer synthetic-token-123` into a persisted
provider field produced `scan_persisted_value_for_secrets` finding
`$.provider.diagnostic`, while the trace validator still returned success and
the grader's `no_secret_leakage` check stayed true. The grader trusts the
trace's self-declared boolean instead of independently scanning persisted data.

**Impact (inference).** A persisted credential-like value can pass the security
gate, defeating the stated sensitive-information control.

**Minimum repair.** Invoke the scanner over the entire persisted trace,
checkpoint, grader, and summary before acceptance; reject forbidden keys and
secret patterns regardless of self-declared flags; add isolated leak fixtures
for every persisted container.

### B5 — High — retry trace cardinality conflicts with the resource budget

**Direct evidence.** The config allows up to 8 model requests and one provider
retry per failed request, while `run_trace.schema.v3.6.json` allows only 1-2
flat `attempts` total and has no logical request index. Tests cover a single
logical request only.

**Impact (inference).** A normal multi-turn/tool run cannot fully reconcile its
requests and retries to the frozen trace contract; infrastructure and candidate
failures can be conflated or omitted.

**Minimum repair.** Record logical requests with nested 1-2 provider attempts
(or explicit request/attempt indexes), reconcile them to model-request and token
budgets, and test multi-turn success plus failures at early and late turns.

### B6 — High — schemas and reason-code fixtures do not falsify the full contract

**Direct evidence.** The grader-result schema declares `checks` only as an
unconstrained object; the trace schema leaves run identity, provider, failure,
result, permission, environment, and redaction as unconstrained objects. The
reason vocabulary has 18 definitions, but the derivation function implements
only the 8 codes used by the current cases; tests exercise one exact-set fault
and do not cover all triggers, suppression, mutual exclusion, or allowed-status
rules.

**Impact (inference).** Structurally incomplete grader/trace documents can pass
schema validation, and ten frozen reason-code semantics have no executable
falsification evidence.

**Minimum repair.** Freeze strict nested schemas with exact required fields,
types, enums, and `additionalProperties=false`; validate generated artifacts
against them; implement and test all 18 reason-code triggers and precedence
rules, including required/allowed/exact-set and status compatibility.

### B7 — High — required full Python suite is not green

**Direct evidence.** The required command ran 144 tests: 143 passed and one
failed at `tests/test_financial_acceptance_v3_5.py:21` because
`harness/acceptance_v3_5.py:157` treats already frozen same-version run IDs as
historical overlap. Focused v3.6 Python tests were 11/11 and all Node integration
tests were 36/36.

**Impact (inference).** The repository does not meet its explicit handoff gate;
the known non-idempotent legacy test also prevents a clean independent replay.

**Minimum repair.** Resolve this through a new versioned historical-validation
contract that preserves v3.5 bytes and validates the frozen plan without
regenerating it against itself. Do not edit v3.5 in place or waive the failure
based on current model results.

## Reproduction commands

```text
uv run python -m harness.acceptance_v3_6 verify-contracts
uv run python -m harness.acceptance_v3_6 verify-plan
uv run python -m audit.build_stage3_v3_6_adjudication verify
uv run python -m unittest tests.test_financial_acceptance_v3_6 -v
uv run python -m unittest discover -s tests -v
node --test tests/integration/*.test.mjs
node harness/live_acceptance_v3_6.mjs --plan contracts/stage3_acceptance_plan.v3.6.json --output-dir reports/_audit_should_not_exist
```

The identity, grader, and secret counterexamples are deterministic one-factor
mutations of `tests/fixtures/acceptance_v3_6/grader.baseline.json`; their exact
inputs and observed outputs are described in B2-B4.

## Limits and next gate

- No external provider behavior, credentials, pricing, or live identity was
  tested; doing so is outside this issue and still lacks new paid authorization.
- Static prompt/tool/model symmetry and Qwen's provider-only flag are supported,
  but runtime symmetry is unverified because B1 leaves no v3.6 execution path.
- v3.6 must not enter paid preflight or 36-run. After the Stage 2 implementer
  publishes a new superseding frozen bundle and all focused/full tests pass, a
  new independent audit is required. This audit does not authorize Stage 4.
