import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  buildAnswerSchemaV35,
  buildNonAnswerSchemaV35,
  buildRunPromptV35,
  normalizePayloadV35,
} from "../../harness/live_acceptance_v3_5.mjs";


const config = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.5.json", import.meta.url), "utf8"));
const projection = JSON.parse(readFileSync(new URL("../../cases/candidate_v3/case-public-fkw-01-normal-v3.json", import.meta.url), "utf8"));


test("v3.5 puts all candidates on one visible financial contract", () => {
  assert.deepEqual(config.candidate_model_ids, ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]);
  assert.deepEqual(config.tool_names, [
    "read_frozen_case", "read_frozen_evidence", "calculate", "simulated_ledger",
    "submit_candidate_answer", "submit_candidate_non_answer",
  ]);
  assert.equal(config.context_contract.same_prompt_tools_budget_retry_for_all_models, true);
  assert.equal(config.candidate_visible_model_specific_changes, false);
  assert.equal(config.execution.authorized_run_cap, 36);
  assert.equal(config.execution.full_810_matrix_authorized, false);
});


test("answer and non-answer schemas are disjoint and union-free", () => {
  const answer = buildAnswerSchemaV35(projection);
  const nonAnswer = buildNonAnswerSchemaV35(projection);
  assert.equal(JSON.stringify(answer).includes("anyOf"), false);
  assert.equal(JSON.stringify(nonAnswer).includes("anyOf"), false);
  assert.equal(answer.properties.value.type, "object");
  assert.equal(answer.properties.status, undefined);
  assert.equal(nonAnswer.properties.value, undefined);
  assert.deepEqual(nonAnswer.properties.status.enum, ["abstain", "escalate", "reject_action"]);
});


test("financial prompt exposes shape not oracle and explains split submission", () => {
  const prompt = buildRunPromptV35(projection);
  assert.match(prompt, /submit_candidate_answer/);
  assert.match(prompt, /submit_candidate_non_answer/);
  assert.match(prompt, /answer_value_schema/);
  assert.doesNotMatch(prompt, /27811517000000|expected_status|force_abstain_reason|diagnostic_reason/);
  assert.doesNotMatch(prompt, /qwen|glm|deepseek/i);
});


test("Bailian payload controls are common except the required Qwen extension", () => {
  const source = { model: "qwen3.8-max", tools: config.tool_names.map((name) => ({ type: "function", function: { name, description: name, parameters: { type: "object", properties: {} }, strict: true } })) };
  const qwen = normalizePayloadV35(source, 1);
  assert.equal(qwen.enable_thinking, false);
  assert.equal(qwen.tool_choice, "auto");
  assert.equal(qwen.tool_stream, false);
  assert.equal(qwen.parallel_tool_calls, false);
  assert.equal(qwen.tools.every((item) => item.function.strict === undefined), true);
  for (const model of ["glm-5.2", "deepseek-v4-pro"]) {
    const other = normalizePayloadV35({ ...source, model }, 1);
    assert.equal(other.enable_thinking, undefined);
    assert.equal(other.tool_choice, "auto");
    assert.equal(other.tool_stream, false);
  }
});
