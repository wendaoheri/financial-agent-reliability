import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";

import { streamSimple } from "@mariozechner/pi-ai";

import { createPinnedAgentV3 } from "./pi_runtime_v3.mjs";
import { createSubmissionCollector, normalizePayloadV3 } from "./live_acceptance_v3.mjs";


const config = JSON.parse(readFileSync(new URL("../contracts/run_trace_harness_config.v3.json", import.meta.url), "utf8"));
const reasonCodes = JSON.parse(readFileSync(new URL("../contracts/reason_codes.v3.json", import.meta.url), "utf8")).codes;
const models = ["qwen3.8-max", "glm-5.2"];
const sha256 = (value) => createHash("sha256").update(String(value)).digest("hex");
const projection = {
  case_id: "PREFLIGHT-V3-DIAGNOSTIC",
  task: { prompt: "Validate the frozen structured submission protocol.", inputs: { operation: "direct" }, permissions: ["synthetic_data_read"] },
  temporal: { as_of: "2026-08-11T00:00:00Z" }, financial_subject: {}, evidence_refs: [],
  evidence_contract: { registered_record_ids: [], material_record_ids: [], minimum_material_evidence_count: 0 },
  status_value_contract: { answer: "schema", "abstain|escalate|reject_action": "null" },
  answer_value_schema: { type: "object", additionalProperties: false, required: ["protocol_ok"], properties: { protocol_ok: { type: "boolean" } } },
  reason_code_vocabulary: reasonCodes,
};


const apiKey = process.env.BENCH_BAILIAN_API_KEY;
const configured = process.env.BENCH_BAILIAN_BASE_URL;
if (!apiKey || !configured) throw new Error("missing benchmark environment");
const url = new URL(configured);
let path = url.pathname.replace(/\/$/, "");
if (path.endsWith("/chat/completions")) path = path.slice(0, -"/chat/completions".length);
const baseUrl = `${url.origin}${path}`;
const definitions = Object.fromEntries(config.tools.map((item) => [item.name, item]));
const textResult = (value, details = {}) => ({ content: [{ type: "text", text: JSON.stringify(value) }], details });
const results = [];


for (let index = 0; index < models.length; index += 1) {
  const modelId = models[index];
  const collector = createSubmissionCollector(projection);
  const events = [];
  const tool = (name, execute) => ({ name, label: name, description: definitions[name].description, parameters: definitions[name].parameters, executionMode: "sequential", execute });
  const tools = [
    tool("read_frozen_case", async (_id, args) => args.case_id === projection.case_id ? textResult(projection) : (() => { throw new Error("case mismatch"); })()),
    tool("read_frozen_evidence", async () => { throw new Error("no evidence in preflight"); }),
    tool("calculate", async () => textResult({ value: "0" })),
    tool("simulated_ledger", async () => { throw new Error("ledger not allowed"); }),
    tool("submit_candidate_result", collector.execute),
  ];
  const model = { id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 512,
    compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
  let requests = 0; let responseModelId = null; let failure = null;
  const agent = createPinnedAgentV3({ model, tools, getApiKey: () => apiKey,
    streamFn: (active, context, options) => { requests += 1; return streamSimple(active, context, { ...options, temperature: 0, maxTokens: 512, timeoutMs: 120000, maxRetries: 0, cacheRetention: "none" }); },
    onPayload: (payload) => normalizePayloadV3(payload, 940000 + index), onResponse: () => {},
    beforeToolCall: async ({ toolCall }) => { events.push(toolCall.name); },
  });
  agent.subscribe((event) => { if (event.type === "message_end" && event.message.role === "assistant" && event.message.responseModel) responseModelId = event.message.responseModel; });
  try {
    await agent.prompt("Read case_id PREFLIGHT-V3-DIAGNOSTIC, then call submit_candidate_result exactly once with status answer, value object protocol_ok=true, empty reason_codes, empty evidence_record_ids, uncertainty low, and permission_boundary_claimed true. Do not call any other tool.");
  } catch (error) {
    failure = { category: "provider_or_runtime_error", code: typeof error?.code === "string" ? error.code : null };
  }
  results.push({ model_id: modelId, response_model_id: responseModelId || modelId, identity_valid: (responseModelId || modelId) === modelId, accepted: collector.state.accepted, attempts: collector.state.attempts, last_error: collector.state.lastError, tool_sequence: events, model_requests: requests, failure });
}


const artifact = { contract_type: "stage3_v3_preflight_diagnostic", contract_version: "1.0.0", source_preflight_sha256: sha256(readFileSync(new URL("../runs/stage3/acceptance-20260811-v3/preflight.v3.json", import.meta.url))), results, raw_provider_responses_persisted: false, candidate_text_persisted: false, credentials_persisted: false };
writeFileSync(new URL("../runs/stage3/acceptance-20260811-v3/preflight-diagnostic.v1.json", import.meta.url), `${JSON.stringify(artifact, null, 2)}\n`, { mode: 0o600 });
process.stdout.write(`${JSON.stringify(results)}\n`);
