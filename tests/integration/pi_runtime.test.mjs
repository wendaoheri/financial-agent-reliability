import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { assertPinnedRuntime, createPinnedAgent } from "../../harness/pi_runtime.mjs";


const config = JSON.parse(
  readFileSync(new URL("../../contracts/run_trace_harness_config.v1.json", import.meta.url), "utf8"),
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
    id: "qwen-3.8-max",
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
    () => createPinnedAgent({ model: { id: "qwen3.8-max" }, tools: [] }),
    /exact frozen candidate ID/,
  );
});
