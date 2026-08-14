import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(dirname(dirname(HERE)));
const CONFIG = JSON.parse(readFileSync(join(ROOT, "contracts", "run_trace_harness_config.v3.5.json"), "utf8"));
const MODELS = new Set(CONFIG.candidate_model_ids);


export function assertPinnedRuntimeV35() {
  const require = createRequire(import.meta.url);
  const entry = require.resolve("@mariozechner/pi-agent-core");
  const metadata = JSON.parse(readFileSync(join(dirname(dirname(entry)), "package.json"), "utf8"));
  if (metadata.version !== CONFIG.runtime.version || metadata.version !== "0.73.1") {
    throw new Error(`pi-agent-core identity mismatch: ${metadata.version}`);
  }
  return metadata.version;
}


export function createPinnedAgentV35(options) {
  assertPinnedRuntimeV35();
  if (!options.model || !MODELS.has(options.model.id)) throw new Error("model.id must be one exact frozen candidate ID");
  const actual = options.tools.map((item) => item.name);
  if (JSON.stringify(CONFIG.tool_names) !== JSON.stringify(actual)) throw new Error("v3.5 tool order changed");
  if (options.tools.some((item) => item.executionMode !== "sequential")) throw new Error("all tools must be sequential");
  const agent = new Agent({
    initialState: {
      systemPrompt: CONFIG.system_prompt,
      model: options.model,
      thinkingLevel: "off",
      tools: options.tools,
      messages: [],
    },
    toolExecution: "sequential",
    streamFn: options.streamFn,
    getApiKey: options.getApiKey,
    onPayload: options.onPayload,
    onResponse: options.onResponse,
    beforeToolCall: options.beforeToolCall,
    afterToolCall: options.afterToolCall,
    maxRetryDelayMs: 0,
  });
  const createLoopConfig = agent.createLoopConfig.bind(agent);
  agent.createLoopConfig = (loopOptions = {}) => ({
    ...createLoopConfig(loopOptions),
    shouldStopAfterTurn: options.shouldStopAfterTurn,
  });
  return agent;
}
