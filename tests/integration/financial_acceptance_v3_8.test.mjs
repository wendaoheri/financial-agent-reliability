import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  applyLedgerOperationV38,
  buildToolSchemasV38,
  classifyAttemptV38,
  executeDecimalCalculationV38,
  executeFrozenPlanV38,
  executeIdentityPreflightV38,
  normalizePayloadV38,
} from "../../src/financial_agent_reliability/harness/live_acceptance_v3_8.mjs";

const config = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.8.json", import.meta.url), "utf8"));
const plan = JSON.parse(readFileSync(new URL("../../contracts/stage3_acceptance_plan.v3.8.json", import.meta.url), "utf8"));
const fixtureAnswers = JSON.parse(readFileSync(new URL("../fixtures/acceptance_v3_7/candidate_answers.synthetic.json", import.meta.url), "utf8"));
const modelIds = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"];

function preflightAuthorization() {
  return { paid_calls_authorized: true, authorization_kind: "identity_preflight", maximum_model_units: 3, plan_sha256: plan.plan_sha256, exact_model_ids: modelIds };
}
async function passingPreflight() {
  return executeIdentityPreflightV38({
    plan,
    authorization: preflightAuthorization(),
    send: async ({ payload }) => ({ response_model_id: payload.model, http_status: 200, assistant_action_valid: true, parameters_honored: true, tool_calls: [{ id: `preflight-${payload.model}`, name: "read_frozen_case", arguments: { case_id: plan.tasks[0].case_id } }], usage: { input: 1, output: 1 } }),
  });
}
function runAuthorization(preflight) {
  return { paid_calls_authorized: true, authorization_kind: "financial_acceptance_36_run", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, authorized_run_ids: plan.runs.map((row) => row.run_id), exact_model_ids: modelIds };
}
function calculationCall(visible, snapshot) {
  const inputs = visible.task.inputs;
  if (inputs.operation === "scale") {
    const record = snapshot.records.find((item) => String(item.payload.year) === String(inputs.target_year));
    return { id: "calculate", name: "calculate", arguments: { operation: "divide", inputs: [String(record.payload.value), String(inputs.divisor)] } };
  }
  if (inputs.operation === "method" && inputs.method === "three_year_average") return { id: "calculate", name: "calculate", arguments: { operation: "average", inputs: snapshot.records.map((item) => String(item.payload.value)) } };
  if (inputs.operation === "threshold") {
    const record = snapshot.records.find((item) => String(item.payload.year) === String(inputs.target_year));
    return { id: "calculate", name: "calculate", arguments: { operation: "threshold", inputs: [String(record.payload.value), String(inputs.threshold)] } };
  }
  return null;
}

test("decimal tool executes all frozen operations", () => {
  assert.deepEqual(executeDecimalCalculationV38("add", ["1.2", "3.4"]), { operation: "add", value: "4.6" });
  assert.deepEqual(executeDecimalCalculationV38("subtract", ["5", "2.5"]), { operation: "subtract", value: "2.5" });
  assert.deepEqual(executeDecimalCalculationV38("multiply", ["1.5", "4"]), { operation: "multiply", value: "6" });
  assert.deepEqual(executeDecimalCalculationV38("divide", ["1", "8"]), { operation: "divide", value: "0.125" });
  assert.deepEqual(executeDecimalCalculationV38("average", ["7.527", "5.279", "5.415"]), { operation: "average", value: "6.073667" });
  assert.deepEqual(executeDecimalCalculationV38("threshold", ["36.1479343675069", "40"]), { operation: "threshold", value: "36.147934", threshold: "40", meets_threshold: false });
});

test("stateful simulated ledger exposes real before and after roots", () => {
  const ledger = new Map();
  const buy = applyLedgerOperationV38(ledger, "buy", "SYN", "2.5");
  assert.notEqual(buy.state_before_sha256, buy.state_after_sha256);
  const sell = applyLedgerOperationV38(ledger, "sell", "SYN", "2.5");
  assert.equal(sell.resulting_quantity, "0");
  assert.equal(sell.state_after_sha256, buy.state_before_sha256);
});

test("HTTP and identity classification is independent of self-reported class", () => {
  assert.equal(classifyAttemptV38({ requested_model_id: "glm-5.2", response_model_id: "glm-5.2", http_status: 429, assistant_action_valid: true }), "provider_or_runtime_failure");
  assert.equal(classifyAttemptV38({ requested_model_id: "glm-5.2", response_model_id: "deepseek-v4-pro", http_status: 200, assistant_action_valid: true }), "indeterminate");
  assert.equal(classifyAttemptV38({ requested_model_id: "glm-5.2", response_model_id: "glm-5.2", http_status: 200, assistant_action_valid: true }), "success");
});

test("three models remain symmetric except Qwen provider protocol flag", () => {
  for (const model of config.candidate_model_ids) {
    const payload = normalizePayloadV38({ model, tools: [] }, 8);
    assert.equal(payload.temperature, 0);
    assert.equal(payload.enable_thinking, model === "qwen3.8-max" ? false : undefined);
  }
});

test("authorization blocks the frozen plan before any transport call", async () => {
  let calls = 0;
  await assert.rejects(() => executeFrozenPlanV38({ plan, outputDirectory: mkdtempSync(join(tmpdir(), "v38-blocked-")), send: async () => { calls += 1; } }), /authorization/);
  assert.equal(calls, 0);
});

test("synthetic transport executes calculations and emits 36 independently validated artifacts", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v38-matrix-"));
  const preflight = await passingPreflight();
  const summary = await executeFrozenPlanV38({
    plan,
    preflight,
    authorization: runAuthorization(preflight),
    outputDirectory,
    send: async ({ payload }) => {
      const visible = JSON.parse(payload.messages[0].content[0].text.split("Candidate-visible contract:").at(-1));
      assert.deepEqual(payload.tools, buildToolSchemasV38(visible));
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
    },
  });
  const graderDocuments = readdirSync(join(outputDirectory, "graders")).map((name) => JSON.parse(readFileSync(join(outputDirectory, "graders", name), "utf8")));
  const failures = graderDocuments.filter((item) => !item.all_applicable_checks_passed).map((item) => ({ case_id: item.case_id, failed_checks: item.failed_checks }));
  assert.equal(summary.counts.accepted, 36, JSON.stringify(failures));
  assert.deepEqual({ ...summary.counts, accepted: 36 }, { planned: 36, candidates: 36, traces: 36, graders: 36, accepted: 36 });
  assert.equal(readdirSync(join(outputDirectory, "candidates")).length, 36);
  assert.equal(readdirSync(join(outputDirectory, "traces")).length, 36);
  assert.equal(readdirSync(join(outputDirectory, "graders")).length, 36);
  assert.equal(readdirSync(join(outputDirectory, "checkpoints")).length, 36);
  const traces = readdirSync(join(outputDirectory, "traces")).map((name) => JSON.parse(readFileSync(join(outputDirectory, "traces", name), "utf8")));
  assert.ok(traces.some((trace) => trace.tool_events.some((event) => event.tool_name === "calculate" && event.implementation === "decimal_rational_v3_8")));
});
