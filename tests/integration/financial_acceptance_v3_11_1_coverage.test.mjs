import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  assertRunInScope,
  executeCoverageRun,
  historicalPlanRunIds,
  identityDriftErrors,
  validateAuthorizationCoverage,
  validatePreflightCoverage,
  verifyFrozenInputsCoverage,
} from "../../audit/driver_v3_11_1_coverage.mjs";
import { verifyCheckpointChain } from "../../harness/live_acceptance_v3_11.mjs";

const plan = JSON.parse(readFileSync(new URL("../../contracts/stage3_acceptance_plan.v3.11.1.json", import.meta.url), "utf8"));
const preflight = JSON.parse(readFileSync(new URL("../../runs/stage3/coverage-20260814-v3.11.1/preflight.json", import.meta.url), "utf8"));
const fixtureAnswers = JSON.parse(readFileSync(new URL("../fixtures/acceptance_v3_11/candidate_answers.synthetic.json", import.meta.url), "utf8"));

const DECLARED = {
  plan_sha256: "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b",
  plan_core_sha256: "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b",
  config_sha256: "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e",
  bundle_sha256: "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d",
  coverage_run_id: "run_0e1e8f4400e16f22f6581e0bb0d9c54d",
  invalidated_run_id: "run_c0f58d3c0d9227585058c4e4872a468b",
  gate_report_sha256: "0c863c1213c62724bec0e016f2bb36d955bbd0a884dd5e9df55413f062b37b58",
};

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}
function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.from(String(value))).digest("hex"); }

// Build the coverage authorization exactly as the dispatch step produces it:
// single-unit coverage kind, gate review passed (PER-78 report hash) and
// delivery-owner dispatch authorized.
function dispatchedAuthorization(overrides = {}) {
  const authorization = {
    contract_type: "stage3_run_authorization",
    authorization_kind: "financial_acceptance_single_unit_coverage_run",
    paid_calls_authorized: true,
    execution_gate: {
      independent_gate_review_required: true,
      independent_gate_review_status: "passed",
      independent_gate_review_issue: "PER-78",
      independent_gate_review_report_sha256: DECLARED.gate_report_sha256,
      delivery_owner_dispatch_required: true,
      delivery_owner_dispatch_status: "authorized",
      dispatched_by_issue: "PER-79",
      issue: "PER-77",
    },
    execution_round_dir: "runs/stage3/coverage-20260814-v3.11.1",
    plan_path: "contracts/stage3_acceptance_plan.v3.11.1.json",
    plan_sha256: DECLARED.plan_sha256,
    plan_core_sha256: DECLARED.plan_core_sha256,
    contract_bundle_path: "contracts/stage3_acceptance_contracts.frozen.v3.11.json",
    contract_bundle_sha256: DECLARED.bundle_sha256,
    harness_config_path: "contracts/run_trace_harness_config.v3.11.json",
    harness_config_sha256: DECLARED.config_sha256,
    preflight_path: "runs/stage3/coverage-20260814-v3.11.1/preflight.json",
    preflight_sha256: preflight.preflight_sha256,
    exact_model_ids: ["deepseek-v4-pro"],
    authorized_run_ids: [DECLARED.coverage_run_id],
    authorized_run_count: 1,
    authorized_unit: { case_id: "case-synthetic-ftw-14-normal-v3", requested_model_id: "deepseek-v4-pro", repeat: 2, seed: 738396034 },
    denied_run_ids: [DECLARED.invalidated_run_id],
    coverage_replaces_or_reexecutes_invalidation: false,
    maximum_runs: 1,
    maximum_model_requests_per_run: 8,
    out_of_scope_policy: "any run_id not exactly in authorized_run_ids — including all historical v3.5-v3.11 plan run ids and every denied id — must be rejected by the execution driver before any provider request",
  };
  return { ...authorization, ...overrides };
}

function coverageSend() {
  return async ({ payload }) => {
    const visible = JSON.parse(payload.messages[0].content[0].text.split("Candidate-visible contract:").at(-1));
    assert.equal(visible.case_id, "case-synthetic-ftw-14-normal-v3");
    const task = plan.tasks.find((item) => item.case_id === visible.case_id);
    const snapshot = JSON.parse(readFileSync(new URL(`../../${task.snapshot_path}`, import.meta.url), "utf8"));
    const answer = fixtureAnswers[visible.case_id];
    const priorToolResults = payload.messages.filter((message) => message.role === "toolResult");
    if (!priorToolResults.length) {
      const evidenceIds = [...new Set([...visible.evidence_contract.material_record_ids, ...answer.evidence_record_ids])];
      const calls = [{ id: "read-case", name: "read_frozen_case", arguments: { case_id: visible.case_id } }];
      calls.push(...evidenceIds.map((record_id, index) => ({ id: `read-evidence-${index}`, name: "read_frozen_evidence", arguments: { snapshot_id: snapshot.snapshot_id, record_id } })));
      return { response_model_id: payload.model, http_status: 200, assistant_action_valid: true, tool_calls: calls, usage: { input: 10, output: 10 } };
    }
    const { status, value, ...shared } = answer;
    const submission = status === "answer" ? { id: "submit", name: "submit_candidate_answer", arguments: { value, ...shared } } : { id: "submit", name: "submit_candidate_non_answer", arguments: { status, ...shared } };
    return { response_model_id: payload.model, http_status: 200, assistant_action_valid: true, tool_calls: [submission], usage: { input: 10, output: 10 } };
  };
}

test("frozen inputs verify before any provider request", () => {
  assert.equal(verifyFrozenInputsCoverage(), true);
});

test("coverage preflight is a passing 1-of-1 carry-over bound to the coverage plan", () => {
  assert.equal(validatePreflightCoverage(plan, preflight), true);
});

test("dispatched coverage authorization validates; pending gate is rejected", () => {
  assert.equal(validateAuthorizationCoverage(plan, dispatchedAuthorization(), preflight), true);
  const pending = dispatchedAuthorization();
  pending.execution_gate = { ...pending.execution_gate, delivery_owner_dispatch_status: "pending", independent_gate_review_status: "pending" };
  assert.throws(() => validateAuthorizationCoverage(plan, pending, preflight), /gate review|dispatch/);
});

test("out_of_scope_policy rejects denied, historical, and unknown run ids before any provider request", () => {
  const authorization = dispatchedAuthorization();
  assert.equal(assertRunInScope(authorization, DECLARED.coverage_run_id), true);
  assert.throws(() => assertRunInScope(authorization, DECLARED.invalidated_run_id), /out_of_scope_policy/);
  assert.throws(() => assertRunInScope(authorization, "run_00000000000000000000000000000000"), /out_of_scope_policy/);
  const historical = historicalPlanRunIds();
  assert.equal(historical.size, 1540);
  for (const id of [...historical].slice(0, 25)) assert.throws(() => assertRunInScope(authorization, id), /out_of_scope_policy/);
});

test("single coverage run executes, freezes, and reconciles with byte-exact identity", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v3111-coverage-"));
  const { summary, trace, grader } = await executeCoverageRun({
    plan,
    authorization: dispatchedAuthorization(),
    preflight,
    outputDirectory,
    send: coverageSend(),
    endpointId: "bailian_000000000000",
  });
  assert.equal(summary.counts.executed, 1);
  assert.equal(summary.coverage_run_id, DECLARED.coverage_run_id);
  assert.equal(trace.run_id, DECLARED.coverage_run_id);
  assert.equal(trace.status, "succeeded");
  assert.deepEqual(trace.run_identity, plan.runs[0].run_identity);
  assert.equal(identityDriftErrors(trace, plan.runs[0]).length, 0);
  // abstain case: candidate submitted a non-answer, structured output valid
  assert.equal(trace.result.structured_output_valid, true);
  assert.equal(trace.environment.real_side_effects, false);
  assert.equal(trace.environment.final_state_matches_initial, true);
  // exactly 1 trace / 1 grader / 1 checkpoint, chain verifies
  const chain = verifyCheckpointChain(join(outputDirectory, "checkpoints", `${DECLARED.coverage_run_id}.jsonl`), DECLARED.coverage_run_id);
  assert.equal(chain.valid, true);
  assert.equal(chain.events[0].event_type, "run_started");
  assert.equal(chain.events.at(-1).event_type, "run_completed");
  assert.equal(trace.checkpoint.event_count, chain.events.length);
  assert.equal(trace.checkpoint.final_event_sha256, chain.events.at(-1).event_sha256);
  for (const sub of ["traces", "graders", "candidates"]) assert.equal(existsSync(join(outputDirectory, sub, `${DECLARED.coverage_run_id}.json`)), true);
  // grader is deterministic and reports the abstention semantics
  assert.equal(typeof grader.all_applicable_checks_passed, "boolean");
  assert.equal(grader.contract_version, "3.11.0");
  assert.equal(summary.counts.planned, 1);
  assert.equal(summary.maximum_runs, 1);
});

test("a second execution of the same immutable run is refused (no re-run)", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v3111-coverage-rerun-"));
  await executeCoverageRun({ plan, authorization: dispatchedAuthorization(), preflight, outputDirectory, send: coverageSend(), endpointId: "bailian_000000000000" });
  await assert.rejects(
    executeCoverageRun({ plan, authorization: dispatchedAuthorization(), preflight, outputDirectory, send: coverageSend(), endpointId: "bailian_000000000000" }),
    /already has checkpoint/,
  );
});
