import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { fauxAssistantMessage, fauxToolCall, registerFauxProvider } from "@mariozechner/pi-ai";

import {
  buildPreflightPromptV33,
  buildToolChoiceV33,
  createDiagnosticRecorderV33,
  preflightProjectionV33,
} from "../../harness/live_acceptance_v3_3.mjs";
import { createPinnedAgentV33 } from "../../harness/pi_runtime_v3_3.mjs";


const config = JSON.parse(
  readFileSync(new URL("../../contracts/run_trace_harness_config.v3.3.json", import.meta.url), "utf8"),
);


test("v3.3 freezes a sequential model-neutral A/B diagnostic", () => {
  assert.equal(config.contract_version, "3.3.0");
  assert.deepEqual(config.candidate_model_ids, ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]);
  assert.deepEqual(config.preflight.variants.map((item) => item.id), ["auto_strict", "forced_strict"]);
  assert.equal(config.preflight.execution_policy, "run forced_strict only if auto_strict is not 3/3");
  assert.equal(config.preflight.maximum_model_units, 6);
  assert.equal(config.model_specific_changes, false);
});


test("protocol fixture exposes only read and submit without arithmetic bait", () => {
  const projection = preflightProjectionV33();
  const prompt = buildPreflightPromptV33(projection);
  assert.deepEqual(config.preflight.tool_names, ["read_frozen_case", "submit_candidate_result"]);
  assert.equal(JSON.stringify(projection).includes("operation"), false);
  assert.doesNotMatch(prompt, /calculate|arithmetic|qwen|glm|deepseek/i);
  assert.match(prompt, /read_frozen_case/);
  assert.match(prompt, /submit_candidate_result/);
  assert.deepEqual(projection.protocol_submission.value, { protocol_ok: true });
});


test("forced variant selects read then submit while auto stays auto", () => {
  assert.equal(buildToolChoiceV33("auto_strict", false), "auto");
  assert.equal(buildToolChoiceV33("auto_strict", true), "auto");
  assert.equal(buildToolChoiceV33("forced_strict", false).function.name, "read_frozen_case");
  assert.equal(buildToolChoiceV33("forced_strict", true).function.name, "submit_candidate_result");
});


test("pre-validation attempts are visible but arguments and error text stay redacted", async () => {
  const recorder = createDiagnosticRecorderV33();
  await recorder.onEvent({
    type: "tool_execution_start",
    toolCallId: "call-1",
    toolName: "submit_candidate_result",
    args: { status: "wrong", unknown_sensitive_value: "must-not-persist" },
  });
  await recorder.onEvent({
    type: "tool_execution_end",
    toolCallId: "call-1",
    toolName: "submit_candidate_result",
    isError: true,
    result: {
      content: [{
        type: "text",
        text: "Validation failed for tool submit_candidate_result:\n  - status: must be equal to one of the allowed values\n\nReceived arguments:\n{unknown_sensitive_value: must-not-persist}",
      }],
      details: {},
    },
  });
  const serialized = JSON.stringify(recorder.events);
  assert.doesNotMatch(serialized, /must-not-persist|unknown_sensitive_value|Received arguments/);
  assert.match(serialized, /arguments_sha256/);
  assert.match(serialized, /enum_error/);
  assert.match(serialized, /\/status/);
  assert.equal(recorder.summary().observed_calls, 1);
  assert.equal(recorder.summary().validated_calls, 0);
  assert.equal(recorder.summary().pre_execution_rejections, 1);
});


test("validated call is counted separately from observed call", async () => {
  const recorder = createDiagnosticRecorderV33();
  await recorder.onEvent({ type: "tool_execution_start", toolCallId: "call-2", toolName: "read_frozen_case", args: { case_id: "PREFLIGHT-V3.3" } });
  await recorder.beforeToolCall({ toolCall: { id: "call-2", name: "read_frozen_case" }, args: { case_id: "PREFLIGHT-V3.3" } });
  await recorder.onEvent({ type: "tool_execution_end", toolCallId: "call-2", toolName: "read_frozen_case", isError: false, result: { content: [], details: {} } });
  assert.equal(recorder.summary().observed_calls, 1);
  assert.equal(recorder.summary().validated_calls, 1);
  assert.equal(recorder.summary().pre_execution_rejections, 0);
});


test("pinned runtime makes the bounded phase stop hook reachable", async () => {
  const faux = registerFauxProvider({ models: [{ id: "qwen3.8-max", name: "fixture" }] });
  try {
    faux.setResponses([
      fauxAssistantMessage(fauxToolCall("read_frozen_case", { case_id: "PREFLIGHT-V3.3" }), { stopReason: "toolUse" }),
      fauxAssistantMessage("must remain queued"),
    ]);
    const definitions = [
      { name: "read_frozen_case", parameters: { type: "object", required: ["case_id"], properties: { case_id: { type: "string" } } } },
      { name: "submit_candidate_result", parameters: { type: "object", properties: {} } },
    ];
    const tools = definitions.map((item) => ({
      ...item,
      label: item.name,
      description: item.name,
      executionMode: "sequential",
      execute: async () => ({ content: [{ type: "text", text: "ok" }], details: {} }),
    }));
    const agent = createPinnedAgentV33({
      model: faux.models[0],
      tools,
      shouldStopAfterTurn: async () => true,
    });
    await agent.prompt("fixture");
    assert.equal(faux.state.callCount, 1);
    assert.equal(faux.getPendingResponseCount(), 1);
  } finally {
    faux.unregister();
  }
});
