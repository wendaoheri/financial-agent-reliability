import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { fauxAssistantMessage, fauxToolCall, registerFauxProvider } from "@mariozechner/pi-ai";

import {
  buildAnswerSchemaV34,
  buildPreflightPromptV34,
  createDiagnosticRecorderV34,
  normalizePayloadV34,
  preflightProjectionV34,
} from "../../harness/live_acceptance_v3_4.mjs";
import { createPinnedAgentV34 } from "../../harness/pi_runtime_v3_4.mjs";


const config = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.4.json", import.meta.url), "utf8"));
const wire = JSON.parse(readFileSync(new URL("../../contracts/candidate_submission_wire_contract.v3.4.json", import.meta.url), "utf8"));


test("v3.4 limits paid protocol validation to one auto unit per model", () => {
  assert.equal(config.contract_version, "3.4.0");
  assert.deepEqual(config.candidate_model_ids, ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]);
  assert.equal(config.preflight.variant.id, "auto_split_submission");
  assert.equal(config.preflight.variant.tool_choice, "auto");
  assert.equal(config.preflight.maximum_model_units, 3);
  assert.equal(config.preflight.acceptance_runs_authorized, false);
  assert.equal(config.candidate_visible_model_specific_changes, false);
});


test("split submission wire contract removes nullable unions", () => {
  const schema = buildAnswerSchemaV34(preflightProjectionV34());
  assert.equal(JSON.stringify(schema).includes("anyOf"), false);
  assert.equal(JSON.stringify(schema).includes("oneOf"), false);
  assert.equal(schema.properties.value.type, "object");
  assert.equal(schema.properties.value.properties.protocol_ok.type, "boolean");
  assert.equal(schema.properties.status, undefined);
  assert.equal(wire.tools.non_answer.required_fields.includes("value"), false);
  assert.match(schema.properties.value.description, /case-visible answer_value_schema/i);
  for (const field of schema.required) assert.equal(typeof schema.properties[field].description, "string");
});


test("Bailian payload explicitly controls Qwen thinking and complex tool streaming", () => {
  const source = {
    model: "qwen3.8-max",
    max_completion_tokens: 99,
    tools: [{ type: "function", function: { name: "x", description: "x", parameters: { type: "object", properties: {} }, strict: true } }],
  };
  const payload = normalizePayloadV34(source, 17);
  assert.equal(payload.tool_choice, "auto");
  assert.equal(payload.tool_stream, false);
  assert.equal(payload.parallel_tool_calls, false);
  assert.equal(payload.enable_thinking, false);
  assert.equal(payload.max_tokens, config.resource_budget.max_output_tokens);
  assert.equal(payload.tools[0].function.strict, undefined);
  assert.equal(payload.reasoning_effort, undefined);

  for (const model of ["glm-5.2", "deepseek-v4-pro"]) {
    const other = normalizePayloadV34({ ...source, model }, 17);
    assert.equal(other.tool_choice, "auto");
    assert.equal(other.tool_stream, false);
    assert.equal(other.parallel_tool_calls, false);
    assert.equal(other.enable_thinking, undefined);
  }
});


test("provider normalization rejects identity drift", () => {
  assert.throws(() => normalizePayloadV34({ model: "qwen-3.8-max", tools: [] }, 1), /identity/);
});


test("diagnostic trace stores known types but no values or unknown field names", async () => {
  const recorder = createDiagnosticRecorderV34();
  await recorder.onEvent({
    type: "tool_execution_start",
    toolCallId: "call-1",
    toolName: "submit_candidate_answer",
    args: {
      value: { protocol_ok: "secret-value", unknown_secret_key: "must-not-persist" },
      reason_codes: [],
      evidence_record_ids: [],
      uncertainty: "low",
      permission_boundary_claimed: true,
      another_secret_key: "must-not-persist",
    },
  });
  const serialized = JSON.stringify(recorder.events);
  assert.doesNotMatch(serialized, /secret-value|must-not-persist|unknown_secret_key|another_secret_key/);
  assert.match(serialized, /arguments_sha256/);
  assert.match(serialized, /\/value\/protocol_ok/);
  assert.match(serialized, /"type":"string"/);
  assert.match(serialized, /unknown_field_count/);
});


test("read trace recognizes case_id without persisting its value", async () => {
  const recorder = createDiagnosticRecorderV34();
  await recorder.onEvent({ type: "tool_execution_start", toolCallId: "call-read", toolName: "read_frozen_case", args: { case_id: "PREFLIGHT-V3.4" } });
  const serialized = JSON.stringify(recorder.events);
  assert.doesNotMatch(serialized, /PREFLIGHT-V3\.4/);
  assert.match(serialized, /\/case_id/);
  assert.equal(recorder.events[0].unknown_field_count, 0);
});


test("protocol prompt and pinned loop stay model-neutral and bounded", async () => {
  const projection = preflightProjectionV34();
  const prompt = buildPreflightPromptV34(projection);
  assert.doesNotMatch(prompt, /qwen|glm|deepseek|calculate|arithmetic/i);
  assert.match(prompt, /submit_candidate_answer/);

  const faux = registerFauxProvider({ models: [{ id: "qwen3.8-max", name: "fixture" }] });
  try {
    faux.setResponses([
      fauxAssistantMessage(fauxToolCall("read_frozen_case", { case_id: "PREFLIGHT-V3.4" }), { stopReason: "toolUse" }),
      fauxAssistantMessage("must remain queued"),
    ]);
    const tools = [
      { name: "read_frozen_case", parameters: { type: "object", required: ["case_id"], properties: { case_id: { type: "string" } } } },
      { name: "submit_candidate_answer", parameters: { type: "object", properties: {} } },
    ].map((item) => ({ ...item, label: item.name, description: item.name, executionMode: "sequential", execute: async () => ({ content: [], details: {} }) }));
    const agent = createPinnedAgentV34({ model: faux.models[0], tools, shouldStopAfterTurn: async () => true });
    await agent.prompt("fixture");
    assert.equal(faux.state.callCount, 1);
    assert.equal(faux.getPendingResponseCount(), 1);
  } finally {
    faux.unregister();
  }
});
