import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(dirname(dirname(HERE)));
const CONFIG = JSON.parse(
  readFileSync(join(ROOT, "contracts", "run_trace_harness_config.v2.json"), "utf8"),
);
const MODELS = new Set(CONFIG.candidate_model_ids);


export function assertPinnedRuntime() {
  const require = createRequire(import.meta.url);
  const entry = require.resolve("@mariozechner/pi-agent-core");
  const metadata = JSON.parse(readFileSync(join(dirname(dirname(entry)), "package.json"), "utf8"));
  if (metadata.version !== CONFIG.runtime.version || metadata.version !== "0.73.1") {
    throw new Error(`pi-agent-core identity mismatch: ${metadata.version}`);
  }
  return metadata.version;
}


export function createPinnedAgent({
  model,
  tools,
  streamFn,
  getApiKey,
  onPayload,
  onResponse,
  beforeToolCall,
  afterToolCall,
  maxRetryDelayMs,
  sessionId,
}) {
  assertPinnedRuntime();
  if (!model || !MODELS.has(model.id)) {
    throw new Error("model.id must be one exact frozen candidate ID");
  }
  const expectedNames = CONFIG.tools.map((tool) => tool.name);
  const actualNames = tools.map((tool) => tool.name);
  if (JSON.stringify(actualNames) !== JSON.stringify(expectedNames)) {
    throw new Error("tool order and names must match the frozen schema");
  }
  if (tools.some((tool) => tool.executionMode !== "sequential")) {
    throw new Error("every tool must execute sequentially");
  }
  return new Agent({
    initialState: {
      systemPrompt: CONFIG.system_prompt,
      model,
      thinkingLevel: "off",
      tools,
      messages: [],
    },
    toolExecution: "sequential",
    streamFn,
    getApiKey,
    onPayload,
    onResponse,
    beforeToolCall,
    afterToolCall,
    maxRetryDelayMs,
    sessionId,
  });
}
