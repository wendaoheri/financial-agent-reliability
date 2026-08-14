import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  buildAnswerSchemaV36,
  buildNonAnswerSchemaV36,
  buildRunPromptV36,
  classifyProviderAttemptV36,
  executeWithProviderRetryV36,
  normalizePayloadV36,
  shouldRetryProviderAttemptV36,
} from "../../src/financial_agent_reliability/harness/live_acceptance_v3_6.mjs";


const config = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.6.json", import.meta.url), "utf8"));
const projection = JSON.parse(readFileSync(new URL("../../cases/candidate_v3_6/case-public-fkw-12-normal-v3.json", import.meta.url), "utf8"));


test("v3.6 exposes one model-neutral contract with frozen reason and decimal semantics", () => {
  assert.deepEqual(config.candidate_model_ids, ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]);
  assert.equal(config.context_contract.same_prompt_tools_budget_retry_grader_for_all_models, true);
  assert.equal(config.execution.paid_calls_authorized, false);
  assert.equal(projection.decimal_output_contract.value_decimal_places, 6);
  assert.deepEqual(projection.reason_code_contract.required, []);
  const prompt = buildRunPromptV36(projection);
  assert.match(prompt, /decimal_output_contract/);
  assert.match(prompt, /reason_code_contract/);
  assert.doesNotMatch(prompt, /expected_value|qwen|glm|deepseek/i);
});


test("answer and non-answer tool schemas stay disjoint and union-free", () => {
  const answer = buildAnswerSchemaV36(projection);
  const nonAnswer = buildNonAnswerSchemaV36(projection);
  assert.equal(JSON.stringify(answer).match(/anyOf|oneOf/g), null);
  assert.equal(answer.properties.value.type, "object");
  assert.equal(answer.properties.status, undefined);
  assert.equal(nonAnswer.properties.value, undefined);
  assert.deepEqual(nonAnswer.properties.status.enum, ["abstain", "escalate", "reject_action"]);
});


test("Bailian controls and Qwen-only thinking flag remain exact", () => {
  const source = { model: "qwen3.8-max", tools: config.tool_names.map((name) => ({ type: "function", function: { name, description: name, parameters: { type: "object", properties: {} }, strict: true } })) };
  const qwen = normalizePayloadV36(source, 7);
  assert.equal(qwen.enable_thinking, false);
  assert.equal(qwen.tool_choice, "auto");
  assert.equal(qwen.tool_stream, false);
  assert.equal(qwen.parallel_tool_calls, false);
  for (const model of ["glm-5.2", "deepseek-v4-pro"]) {
    const payload = normalizePayloadV36({ ...source, model }, 7);
    assert.equal(payload.enable_thinking, undefined);
    assert.equal(payload.tool_choice, "auto");
    assert.equal(payload.tool_stream, false);
    assert.equal(payload.parallel_tool_calls, false);
  }
});


test("retry state machine only retries provider/runtime failures once", () => {
  const base = { http_status: 429, no_response: false, provider_error_class: "rate_limit", stream_termination_reason: "provider_error", content_bytes: 0, tool_call_bytes: 0 };
  assert.equal(classifyProviderAttemptV36(base), "provider_or_runtime_failure");
  assert.equal(shouldRetryProviderAttemptV36(base, 0), true);
  assert.equal(shouldRetryProviderAttemptV36(base, 1), false);
  const semantic = { http_status: 200, no_response: false, provider_error_class: null, stream_termination_reason: "stop", content_bytes: 32, tool_call_bytes: 0, valid_assistant_action: true, valid_submission: false };
  assert.equal(classifyProviderAttemptV36(semantic), "candidate_failure");
  assert.equal(shouldRetryProviderAttemptV36(semantic, 0), false);
});


test("retry executor replays an identical payload and accepts the first valid response", async () => {
  const observed = [];
  const waits = [];
  const responses = [
    { http_status: 429, no_response: false, provider_error_class: "rate_limit", stream_termination_reason: "provider_error", content_bytes: 0, tool_call_bytes: 0, valid_assistant_action: false, valid_submission: false },
    { http_status: 200, no_response: false, provider_error_class: null, stream_termination_reason: "tool_use", content_bytes: 0, tool_call_bytes: 32, valid_assistant_action: true, valid_submission: true },
  ];
  const result = await executeWithProviderRetryV36({
    payload: { model: "glm-5.2", seed: 7, tools: [{ name: "x" }] },
    send: async (payload, retryIndex) => { observed.push(JSON.stringify(payload)); return responses[retryIndex]; },
    sleep: async (milliseconds) => { waits.push(milliseconds); },
  });
  assert.equal(result.classification, "success");
  assert.equal(result.firstValidResponseAccepted, true);
  assert.deepEqual(observed, [observed[0], observed[0]]);
  assert.deepEqual(waits, [2000]);
});
