import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  buildRunPromptV3,
  calculateV3,
  createSubmissionCollector,
  normalizePayloadV3,
} from "../../src/financial_agent_reliability/harness/live_acceptance_v3.mjs";


const config = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.json", import.meta.url), "utf8"));
const projection = JSON.parse(readFileSync(new URL("../../cases/candidate_v3/case-public-fkw-01-normal-v3.json", import.meta.url), "utf8"));


test("all three models share exact prompt tools budget and retry policy", () => {
  assert.deepEqual(config.candidate_model_ids, ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]);
  assert.equal(config.provider.tool_choice, "auto");
  assert.equal(config.tools.at(-1).name, "submit_candidate_result");
  assert.equal(config.resource_budget.max_retries, 0);
  assert.equal(config.context_contract.provider_specific_prompt_addenda, false);
});


test("calculate wire schema equals runtime requirements", () => {
  const schema = config.tools.find((item) => item.name === "calculate").parameters;
  assert.deepEqual(schema.properties.inputs.required, ["values"]);
  assert.equal(calculateV3("sum", { values: ["1", "2.5"] }).value, "3.5");
  assert.throws(() => calculateV3("sum", {}), /inputs.values/);
});


test("prompt publishes shape but no oracle value or derived label", () => {
  const prompt = buildRunPromptV3(projection);
  assert.match(prompt, /submit_candidate_result/);
  assert.match(prompt, /answer_value_schema/);
  assert.doesNotMatch(prompt, /27811517000000/);
  assert.doesNotMatch(prompt, /force_abstain_reason|diagnostic_reason|expected_status/);
});


test("submission collector captures one valid structure and redacts invalid content", async () => {
  const collector = createSubmissionCollector(projection);
  const accepted = await collector.execute("call-1", {
    status: "answer", value: { value: "1", year: "2023" }, reason_codes: [],
    evidence_record_ids: ["FKW-01-USA-2023"], uncertainty: "low", permission_boundary_claimed: true,
  });
  assert.equal(collector.state.accepted, true);
  assert.equal(accepted.details.accepted, true);
  const second = await collector.execute("call-2", { status: "answer" });
  assert.equal(second.details.accepted, false);
  assert.equal(collector.state.attempts, 2);
  assert.equal(JSON.stringify(second).includes("status\":\"answer"), false);
});


test("payload normalization keeps OpenAI-compatible tool schema and auto tool choice", () => {
  const payload = normalizePayloadV3({ model: "qwen3.8-max", tools: config.tools.map((item) => ({ type: "function", function: item })) }, 42);
  assert.equal(payload.tool_choice, "auto");
  assert.equal(payload.tools.length, 5);
  assert.equal(payload.seed, 42);
});
