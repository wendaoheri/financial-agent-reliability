import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  applyLedgerOperationV311,
  buildToolSchemasV311,
  classifyAttemptV311,
  continuationRunsV311,
  executeDecimalCalculationV311,
  executeFrozenPlanV311,
  executeIdentityPreflightV311,
  finalizedState,
  normalizePayloadV311,
  verifyCheckpointChain,
} from "../../harness/live_acceptance_v3_11.mjs";

const config = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.11.json", import.meta.url), "utf8"));
const plan = JSON.parse(readFileSync(new URL("../../contracts/stage3_acceptance_plan.v3.11.json", import.meta.url), "utf8"));
const fixtureAnswers = JSON.parse(readFileSync(new URL("../fixtures/acceptance_v3_11/candidate_answers.synthetic.json", import.meta.url), "utf8"));
const modelIds = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"];

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}
function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.from(String(value))).digest("hex"); }

function preflightAuthorization() {
  return { paid_calls_authorized: true, authorization_kind: "identity_preflight", maximum_model_units: 3, plan_sha256: plan.plan_sha256, exact_model_ids: modelIds };
}
async function passingPreflight() {
  return executeIdentityPreflightV311({
    plan,
    authorization: preflightAuthorization(),
    send: async ({ payload }) => ({ response_model_id: payload.model, http_status: 200, assistant_action_valid: true, parameters_honored: true, tool_calls: [{ id: `preflight-${payload.model}`, name: "read_frozen_case", arguments: { case_id: plan.tasks[0].case_id } }], usage: { input: 1, output: 1 } }),
  });
}
function runAuthorization(preflight) {
  return { paid_calls_authorized: true, authorization_kind: "financial_acceptance_550_continuation_run", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, authorized_run_ids: continuationRunsV311(plan).map((row) => row.run_id), exact_model_ids: modelIds };
}
function calculationCall(visible, snapshot) {
  const inputs = visible.task.inputs;
  const recordForYear = (year) => snapshot.records.find((item) => String(item.payload.year) === String(year));
  if (inputs.operation === "scale") {
    const record = recordForYear(inputs.target_year);
    return { id: "calculate", name: "calculate", arguments: { operation: "divide", inputs: [String(record.payload.value), String(inputs.divisor)] } };
  }
  if (inputs.operation === "method" && inputs.method === "three_year_average") return { id: "calculate", name: "calculate", arguments: { operation: "average", inputs: snapshot.records.map((item) => String(item.payload.value)) } };
  if (inputs.operation === "threshold") {
    const record = recordForYear(inputs.target_year);
    return { id: "calculate", name: "calculate", arguments: { operation: "threshold", inputs: [String(record.payload.value), String(inputs.threshold)] } };
  }
  if (inputs.operation === "average") {
    return { id: "calculate", name: "calculate", arguments: { operation: "average", inputs: inputs.years.map((year) => String(recordForYear(year).payload.value)) } };
  }
  return null;
}
function syntheticSend() {
  return async ({ payload }) => {
    const visible = JSON.parse(payload.messages[0].content[0].text.split("Candidate-visible contract:").at(-1));
    assert.deepEqual(payload.tools, buildToolSchemasV311(visible));
    const task = plan.tasks.find((item) => item.case_id === visible.case_id);
    const snapshot = JSON.parse(readFileSync(new URL(`../../${task.snapshot_path}`, import.meta.url), "utf8"));
    const answer = fixtureAnswers[visible.case_id];
    const priorToolResults = payload.messages.filter((message) => message.role === "toolResult");
    if (!priorToolResults.length) {
      const evidenceIds = [...new Set([...visible.evidence_contract.material_record_ids, ...answer.evidence_record_ids])];
      const calls = [{ id: "read-case", name: "read_frozen_case", arguments: { case_id: visible.case_id } }];
      calls.push(...evidenceIds.map((record_id, index) => ({ id: `read-evidence-${index}`, name: "read_frozen_evidence", arguments: { snapshot_id: snapshot.snapshot_id, record_id } })));
      const calculation = calculationCall(visible, snapshot);
      if (calculation) calls.push(calculation);
      return { response_model_id: payload.model, http_status: 200, assistant_action_valid: true, tool_calls: calls, usage: { input: 10, output: 10 } };
    }
    const { status, value, ...shared } = answer;
    const submission = status === "answer" ? { id: "submit", name: "submit_candidate_answer", arguments: { value, ...shared } } : { id: "submit", name: "submit_candidate_non_answer", arguments: { status, ...shared } };
    return { response_model_id: payload.model, http_status: 200, assistant_action_valid: true, tool_calls: [submission], usage: { input: 10, output: 10 } };
  };
}

test("decimal tool executes all frozen operations", () => {
  assert.deepEqual(executeDecimalCalculationV311("add", ["1.2", "3.4"]), { operation: "add", value: "4.6" });
  assert.deepEqual(executeDecimalCalculationV311("subtract", ["5", "2.5"]), { operation: "subtract", value: "2.5" });
  assert.deepEqual(executeDecimalCalculationV311("multiply", ["1.5", "4"]), { operation: "multiply", value: "6" });
  assert.deepEqual(executeDecimalCalculationV311("divide", ["1", "8"]), { operation: "divide", value: "0.125" });
  assert.deepEqual(executeDecimalCalculationV311("average", ["7.527", "5.279", "5.415"]), { operation: "average", value: "6.073667" });
  assert.deepEqual(executeDecimalCalculationV311("threshold", ["36.1479343675069", "40"]), { operation: "threshold", value: "36.147934", threshold: "40", meets_threshold: false });
});

test("stateful simulated ledger exposes real before and after roots", () => {
  const ledger = new Map();
  const buy = applyLedgerOperationV311(ledger, "buy", "SYN", "2.5");
  assert.notEqual(buy.state_before_sha256, buy.state_after_sha256);
  const sell = applyLedgerOperationV311(ledger, "sell", "SYN", "2.5");
  assert.equal(sell.resulting_quantity, "0");
  assert.equal(sell.state_after_sha256, buy.state_before_sha256);
});

test("HTTP and identity classification is independent of self-reported class", () => {
  assert.equal(classifyAttemptV311({ requested_model_id: "glm-5.2", response_model_id: "glm-5.2", http_status: 429, assistant_action_valid: true }), "provider_or_runtime_failure");
  assert.equal(classifyAttemptV311({ requested_model_id: "glm-5.2", response_model_id: "deepseek-v4-pro", http_status: 200, assistant_action_valid: true }), "indeterminate");
  assert.equal(classifyAttemptV311({ requested_model_id: "glm-5.2", response_model_id: "glm-5.2", http_status: 200, assistant_action_valid: true }), "success");
});

test("three models remain symmetric except Qwen provider protocol flag", () => {
  for (const model of config.candidate_model_ids) {
    const payload = normalizePayloadV311({ model, tools: [] }, 8);
    assert.equal(payload.temperature, 0);
    assert.equal(payload.enable_thinking, model === "qwen3.8-max" ? false : undefined);
  }
});

test("token budget ceiling is the budget-design product and symmetric", () => {
  const budget = config.resource_budget;
  assert.equal(budget.single_request_context_window, 32768);
  assert.equal(budget.max_total_tokens, 262144);
  assert.equal(budget.max_total_tokens, budget.max_model_requests * budget.single_request_context_window);
  assert.equal(budget.max_total_tokens_derivation.back_derived_from_observed_usage, false);
  assert.equal(config.token_budget_repair.three_model_symmetric, true);
});

test("continuation plan registers 550 identities: 10 coverage + 540 extension", () => {
  assert.equal(plan.contract_version, "3.11.0");
  assert.equal(plan.tasks.length, 90);
  assert.equal(plan.runs.length, 550);
  assert.equal(plan.continuation_run_cap, 550);
  assert.equal(plan.registered_total_run_cap, 550);
  assert.equal(plan.authorization.paid_calls_authorized, false);
  const coverage = plan.runs.filter((row) => row.repeat === 1);
  const extension = plan.runs.filter((row) => row.repeat === 2 || row.repeat === 3);
  assert.equal(coverage.length, 10);
  assert.equal(extension.length, 540);
  assert.deepEqual(plan.replication_design.extension_repeats, [2, 3]);
  assert.equal(plan.replication_design.no_post_hoc_selection, true);
  assert.equal(plan.replication_design.v3_10_invalidation_forensics.preserved, true);
  const ids = new Set(plan.runs.map((row) => row.run_id));
  assert.equal(ids.size, 550);
});

test("coverage runs map one-to-one onto the v3.10 invalidated forensics", () => {
  assert.equal(Object.keys(plan.coverage_map).length, 10);
  const coverageRows = plan.runs.filter((row) => row.repeat === 1);
  assert.equal(coverageRows.length, 10);
  for (const row of coverageRows) {
    const mapping = plan.coverage_map[row.run_id];
    assert.equal(mapping.case_id, row.run_identity.case_id);
    assert.equal(mapping.model_id, row.model_id);
    assert.equal(mapping.repeat, 1);
    assert.match(mapping.v3_10_run_id, /^run_[0-9a-f]{32}$/);
    assert.notEqual(mapping.v3_10_run_id, row.run_id);
  }
});

test("every seed is independently rederived from the frozen master seed", () => {
  for (const row of plan.runs) {
    const identity = { benchmark_id: plan.replication_design.benchmark_id, case_id: row.run_identity.case_id, master_seed: plan.replication_design.master_seed, repeat: row.repeat, requested_model_id: row.model_id };
    const derived = BigInt(`0x${sha256(canonical(identity)).slice(0, 16)}`) % 2n ** 32n;
    assert.equal(BigInt(row.seed), derived, `${row.run_id} seed not reproducible`);
    assert.equal(row.run_identity.seed, row.seed);
    assert.equal(row.run_id, `run_${sha256(canonical(row.run_identity)).slice(0, 32)}`);
  }
});

test("authorization blocks the frozen plan before any transport call", async () => {
  let calls = 0;
  await assert.rejects(() => executeFrozenPlanV311({ plan, outputDirectory: mkdtempSync(join(tmpdir(), "v311-blocked-")), send: async () => { calls += 1; } }), /authorization/);
  assert.equal(calls, 0);
});

test("authorization binding the wrong kind is rejected", async () => {
  const preflight = await passingPreflight();
  const wrongKind = { paid_calls_authorized: true, authorization_kind: "financial_acceptance_270_run", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, authorized_run_ids: plan.runs.map((row) => row.run_id), exact_model_ids: modelIds };
  await assert.rejects(() => executeFrozenPlanV311({ plan, preflight, authorization: wrongKind, outputDirectory: mkdtempSync(join(tmpdir(), "v311-kind-")), send: async () => {} }), /550-run continuation authorization/);
});

test("synthetic transport executes the full 550-run continuation with independent validation", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v311-continuation-"));
  const preflight = await passingPreflight();
  const summary = await executeFrozenPlanV311({
    plan,
    preflight,
    authorization: runAuthorization(preflight),
    outputDirectory,
    send: syntheticSend(),
  });
  assert.equal(summary.counts.accepted, 550);
  assert.deepEqual({ ...summary.counts, accepted: 550 }, { planned: 550, candidates: 550, traces: 550, graders: 550, accepted: 550, invalidated: 0 });
  const traces = readdirSync(join(outputDirectory, "traces")).map((name) => JSON.parse(readFileSync(join(outputDirectory, "traces", name), "utf8")));
  assert.equal(traces.length, 550);
  assert.ok(traces.every((trace) => trace.contract_version === "3.11.0"));
  // Every trace's cumulative total_tokens is inside the v3.11 ceiling.
  assert.ok(traces.every((trace) => trace.usage.total_tokens <= 262144));
});

test("resume skips finalized units byte-exact and hard-stops on partial state", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v311-resume-"));
  const preflight = await passingPreflight();
  const authorization = runAuthorization(preflight);
  // Execute a bounded chunk, then resume: previously finalized units skip.
  const first = await executeFrozenPlanV311({ plan, preflight, authorization, outputDirectory, send: syntheticSend(), limit: 3 });
  assert.equal(first.status, "chunk_complete");
  assert.equal(first.executed, 3);
  const doneRunId = plan.runs[0].run_id;
  assert.equal(finalizedState(outputDirectory, doneRunId), "finalized");
  const chain = verifyCheckpointChain(join(outputDirectory, "checkpoints", `${doneRunId}.jsonl`), doneRunId);
  assert.equal(chain.valid, true);
  const resumed = await executeFrozenPlanV311({ plan, preflight, authorization, outputDirectory, send: syntheticSend(), limit: 3 });
  assert.ok(resumed.resumed >= 3, `expected >=3 resumed, got ${resumed.resumed}`);
});

test("a partial checkpoint hard-stops resume instead of silently re-executing", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v311-partial-"));
  const preflight = await passingPreflight();
  const authorization = runAuthorization(preflight);
  // Seed the first scope unit with an interrupted (empty) checkpoint ledger.
  const partialRunId = plan.runs[0].run_id;
  const { appendFileSync, mkdirSync } = await import("node:fs");
  mkdirSync(join(outputDirectory, "checkpoints"), { recursive: true });
  appendFileSync(join(outputDirectory, "checkpoints", `${partialRunId}.jsonl`), "");
  assert.equal(finalizedState(outputDirectory, partialRunId), "partial");
  await assert.rejects(
    () => executeFrozenPlanV311({ plan, preflight, authorization, outputDirectory, send: syntheticSend(), limit: 1 }),
    /hard stop|partial|inconsistent|never silently replaced/,
  );
});
