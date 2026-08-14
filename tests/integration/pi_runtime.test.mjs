import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { assertPinnedRuntime, createPinnedAgent } from "../../src/financial_agent_reliability/harness/pi_runtime.mjs";
import {
  buildRunPrompt,
  gradeStructuredCandidate,
  normalizePayload,
  resolveResponseModelIdentity,
} from "../../src/financial_agent_reliability/harness/live_smoke.mjs";


const config = JSON.parse(
  readFileSync(new URL("../../contracts/run_trace_harness_config.v2.json", import.meta.url), "utf8"),
);


test("constructs the real pinned Agent with frozen prompt and sequential tools", () => {
  assert.equal(assertPinnedRuntime(), "0.73.1");
  const tools = config.tools.map((definition) => ({
    name: definition.name,
    label: definition.name,
    description: definition.description,
    parameters: definition.parameters,
    executionMode: "sequential",
    execute: async () => ({ content: [{ type: "text", text: "fixture" }], details: {} }),
  }));
  const model = {
    id: "qwen3.8-max",
    name: "offline fixture identity",
    api: "openai-completions",
    provider: "bailian",
    baseUrl: "https://example.invalid/v1",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 32768,
    maxTokens: 4096,
  };
  const agent = createPinnedAgent({
    model,
    tools,
    streamFn: () => {
      throw new Error("offline constructor test must not call a provider");
    },
    getApiKey: async () => {
      throw new Error("offline constructor test must not read a secret");
    },
  });
  assert.equal(agent.toolExecution, "sequential");
  assert.equal(agent.state.systemPrompt, config.system_prompt);
  assert.deepEqual(agent.state.tools.map((tool) => tool.name), config.tools.map((tool) => tool.name));
});


test("rejects aliases before Agent construction", () => {
  assert.throws(
    () => createPinnedAgent({ model: { id: "qwen-3.8-max" }, tools: [] }),
    /exact frozen candidate ID/,
  );
});


test("normalizes Bailian payload with every frozen parameter", () => {
  const payload = normalizePayload(
    {
      model: "qwen3.8-max",
      tools: [{
        type: "function",
        function: {
          name: "read_frozen_case",
          description: "Read one frozen case.",
          parameters: { type: "object", properties: {} },
        },
      }],
    },
    12345,
  );
  assert.equal(payload.seed, 12345);
  assert.equal(payload.temperature, 0);
  assert.equal(payload.top_p, 1);
  assert.equal(payload.max_tokens, 4096);
  assert.equal(payload.stream, true);
  assert.equal(payload.tool_choice, "auto");
  assert.equal(payload.stream_options.include_usage, true);
});


test("structured smoke grader is deterministic and strict", () => {
  const caseCard = {
    case_id: "case-fixture",
    oracle: {
      expected_status: "answer",
      expected_value: { value: "12.50" },
      reason_codes: [],
    },
    evidence_refs: [{ record_ids: ["record-1"] }],
    quality: { tier: "Gold" },
    risk: { level: "high", loss_class: "financial" },
    task: { permissions: ["synthetic_data_read"] },
  };
  const accepted = gradeStructuredCandidate({
    caseCard,
    candidateText: JSON.stringify({
      status: "answer",
      value: { value: "12.50" },
      reason_codes: [],
      evidence_record_ids: ["record-1"],
      permission_boundary_preserved: true,
      uncertainty: "low",
    }),
    runId: "run_00000000000000000000000000000000",
    modelId: "qwen3.8-max",
    familyId: "FKW-01",
    variantId: "baseline",
    repeat: 1,
    durationMs: 10,
    usage: { input_tokens: 2, output_tokens: 1, total_tokens: 3 },
    toolEvents: [],
    providerIdentityValid: true,
  });
  assert.equal(accepted.end_to_end_complete, true);
  assert.equal(accepted.critical_invariants.calculation_reproducible_and_units_correct, true);
  assert.equal(accepted.max_loss_level, "L0");

  const rejected = gradeStructuredCandidate({
    caseCard,
    candidateText: '{"status":"answer","value":{"value":12.5}}',
    runId: "run_00000000000000000000000000000000",
    modelId: "qwen3.8-max",
    familyId: "FKW-01",
    variantId: "baseline",
    repeat: 1,
    durationMs: 10,
    usage: { input_tokens: 2, output_tokens: 1, total_tokens: 3 },
    toolEvents: [],
    providerIdentityValid: true,
  });
  assert.equal(rejected.oracle_match, false);
  assert.equal(rejected.max_loss_level, "L3");
});


test("run prompt contains no oracle answer", () => {
  const prompt = buildRunPrompt({
    case_id: "case-fixture",
    task: { prompt: "Use evidence.", inputs: { operation: "direct" } },
    temporal: { as_of: "2026-01-01T00:00:00Z" },
    evidence_refs: [{ snapshot_id: "snapshot-1", record_ids: ["record-1"] }],
    oracle: { expected_value: "must-not-leak" },
  });
  assert.match(prompt, /case-fixture/);
  assert.doesNotMatch(prompt, /must-not-leak/);
});


test("pi responseModel absence means the requested identity was unchanged", () => {
  assert.deepEqual(resolveResponseModelIdentity("qwen3.8-max", null), {
    effectiveModelId: "qwen3.8-max",
    valid: true,
  });
  assert.deepEqual(resolveResponseModelIdentity("qwen3.8-max", "other-model"), {
    effectiveModelId: "other-model",
    valid: false,
  });
});
