import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const projectRequire = createRequire(join(process.cwd(), "package.json"));
const coreEntry = projectRequire.resolve("@mariozechner/pi-agent-core");
const aiEntry = join(dirname(dirname(dirname(coreEntry))), "pi-ai", "dist", "index.js");
const { Agent } = await import(pathToFileURL(coreEntry).href);
const { streamSimple } = await import(pathToFileURL(aiEntry).href);

const PINNED_VERSION = "0.73.1";
const SYSTEM_PROMPT = [
  "You are a model-neutral financial benchmark agent.",
  "Use only supplied synthetic input and the registered read-only fixture tool.",
  "Never request credentials, perform real actions, or claim a production write.",
  "Call the fixture tool once, then return exactly one JSON object with status, value, and reason_codes.",
].join(" ");

export function assertPinnedLiveRuntime() {
  const packagePath = join(dirname(dirname(coreEntry)), "package.json");
  const metadata = JSON.parse(readFileSync(packagePath, "utf8"));
  if (metadata.version !== PINNED_VERSION) throw new Error("pi-agent-core identity mismatch");
  return metadata.version;
}

export function makeLiveModel(runtime, candidate) {
  return {
    id: candidate.model,
    name: `${candidate.model} Bailian exact-identity pilot`,
    api: "openai-completions",
    provider: "bailian",
    baseUrl: runtime.base_url,
    reasoning: Boolean(runtime.reasoning),
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 32768,
    maxTokens: Number(runtime.parameters.max_tokens),
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsStore: false,
      supportsStrictMode: false,
      supportsUsageInStreaming: false,
      maxTokensField: "max_tokens",
    },
  };
}

function compactEvent(event) {
  const compact = { type: event.type };
  if ("toolName" in event) compact.tool = event.toolName;
  if ("isError" in event) compact.is_error = Boolean(event.isError);
  if (event.type === "message_end" && event.message?.role === "assistant") {
    compact.stop_reason = event.message.stopReason;
  }
  return compact;
}

function assistants(agent) {
  return agent.state.messages.filter((message) => message.role === "assistant");
}

function identity(messages, candidate, runtime) {
  // pi-ai preserves an explicit responseModel only when it differs from the
  // requested model. Exact responses retain message.model.
  const responseModels = messages.map((message) => message.responseModel ?? message.model ?? null);
  return {
    requested_model: candidate.model,
    response_model: responseModels.at(-1) ?? null,
    exact_match: responseModels.length > 0 && responseModels.every((value) => value === candidate.model),
    endpoint_id: runtime.endpoint_id,
  };
}

function usage(messages) {
  return messages.reduce((total, message) => ({
    input_tokens: total.input_tokens + Number(message.usage?.input ?? 0),
    output_tokens: total.output_tokens + Number(message.usage?.output ?? 0),
  }), { input_tokens: 0, output_tokens: 0 });
}

function decodeOutput(messages) {
  const final = messages.at(-1);
  if (!final) throw new Error("pi agent produced no assistant message");
  const text = final.content.filter((block) => block.type === "text").map((block) => block.text).join("").trim();
  const normalized = text.startsWith("```json") && text.endsWith("```")
    ? text.slice(7, -3).trim()
    : text.startsWith("```") && text.endsWith("```") ? text.slice(3, -3).trim() : text;
  const output = JSON.parse(normalized);
  if (!output || Array.isArray(output) || JSON.stringify(Object.keys(output).sort()) !== JSON.stringify(["reason_codes", "status", "value"])) {
    throw new Error("pi agent final output violates the strict JSON contract");
  }
  if (!["answer", "abstain", "refuse"].includes(output.status) || !Array.isArray(output.reason_codes)) {
    throw new Error("pi agent final output contains invalid fields");
  }
  return output;
}

export function generationPayload(parameters) {
  return (payload) => {
    const next = { ...payload };
    for (const key of ["max_tokens", "seed", "temperature", "top_p", "enable_thinking", "reasoning_effort", "thinking_budget"]) {
      if (!(key in parameters)) continue;
      const value = parameters[key];
      next[key] = ["max_tokens", "seed", "temperature", "top_p", "thinking_budget"].includes(key) && typeof value === "string"
        ? Number(value)
        : value;
    }
    return next;
  };
}

export function safeProviderFailure(errorMessage) {
  if (typeof errorMessage !== "string") return { status: null, provider_code: null, parameter: null };
  const statusMatch = errorMessage.match(/(?:^|\b)([45]\d{2})(?:\b|$)/);
  const codeMatch = errorMessage.match(/["']?code["']?\s*[:=]\s*["']([A-Za-z0-9_.-]{1,64})["']/i);
  const knownParameters = [
    "enable_thinking", "max_tokens", "messages", "reasoning_effort", "seed",
    "stream", "temperature", "tool_choice", "tools", "top_p",
  ];
  const parameter = knownParameters.find((name) => new RegExp(`\\b${name}\\b`, "i").test(errorMessage)) ?? null;
  return {
    status: statusMatch ? Number(statusMatch[1]) : null,
    provider_code: codeMatch?.[1] ?? null,
    parameter,
  };
}

export async function runLivePiAgent(payload, dependencies = {}) {
  const runtimeVersion = assertPinnedLiveRuntime();
  const { mode, request, candidate, runtime } = payload;
  if (!candidate || !runtime || candidate.agent !== `pi-agent-${PINNED_VERSION}`) throw new Error("invalid live pi request");
  if (!["preflight", "run"].includes(mode)) throw new Error("invalid live pi mode");
  const apiKey = dependencies.apiKey ?? process.env.BENCH_BAILIAN_API_KEY;
  if (!apiKey) throw new Error("missing BENCH_BAILIAN_API_KEY");
  const maxTurns = Number(runtime.max_provider_turns);
  if (!Number.isInteger(maxTurns) || maxTurns < 1 || maxTurns > 2) throw new Error("invalid provider-turn cap");
  const model = dependencies.model ?? makeLiveModel(runtime, candidate);
  let providerTurns = 0;
  const baseStream = dependencies.streamFn ?? streamSimple;
  const boundedStream = (streamModel, context, options) => {
    providerTurns += 1;
    if (providerTurns > maxTurns) throw new Error("provider-turn cap exceeded before request");
    return baseStream(streamModel, context, {
      ...options,
      apiKey,
      maxRetries: 0,
      timeoutMs: Number(runtime.timeout_ms),
    });
  };
  const events = [];
  const toolCalls = [];
  const http = { status: null, provider_code: null, request_id: null, error_origin: null };
  const tools = [];
  if (mode === "run") {
    if (!request || request.tools?.length !== 1 || request.resources?.length !== 1) throw new Error("live pi pilot requires one read-only fixture tool");
    const resource = request.resources[0];
    const toolName = request.tools[0];
    tools.push({
      name: toolName,
      label: toolName,
      description: "Read the one registered synthetic benchmark fixture.",
      parameters: {
        type: "object", additionalProperties: false, required: ["fixture_id"],
        properties: { fixture_id: { type: "string" } },
      },
      executionMode: "sequential",
      execute: async (_callId, args) => {
        if (args.fixture_id !== resource.fixture_id) throw new Error("fixture id is outside the registered resource boundary");
        const call = { tool: toolName, action: "read", status: "ok", simulated: true, request: { fixture_id: resource.fixture_id }, response: { ...resource } };
        toolCalls.push(call);
        return { content: [{ type: "text", text: JSON.stringify(call.response) }], details: call.response };
      },
    });
  }
  const agent = new Agent({
    initialState: { systemPrompt: mode === "run" ? SYSTEM_PROMPT : "Reply with OK.", model, thinkingLevel: "off", tools, messages: [] },
    streamFn: boundedStream,
    getApiKey: () => apiKey,
    onPayload: generationPayload(runtime.parameters),
    onResponse: (response) => {
      http.status = Number(response.status);
      http.request_id = response.headers?.["x-request-id"] ?? response.headers?.["x-dashscope-request-id"] ?? null;
    },
    toolExecution: "sequential",
    sessionId: `${mode}:${candidate.id}:${request?.task_id ?? "identity"}`,
  });
  agent.subscribe((event) => { if (event.type !== "message_update") events.push(compactEvent(event)); });
  const started = performance.now();
  await agent.prompt(mode === "run" ? JSON.stringify({
    task_id: request.task_id,
    instruction: request.input.prompt,
    input: request.input.variant,
    resources: request.resources,
    output_contract: { status: "answer | abstain | refuse", value: "JSON scalar or null", reason_codes: "array of uppercase reason-code strings" },
  }) : "Return OK for exact model identity preflight.");
  const messages = assistants(agent);
  const providerIdentity = identity(messages, candidate, runtime);
  const providerError = messages.find((message) => message.stopReason === "error");
  if (providerError) {
    const failure = safeProviderFailure(providerError.errorMessage);
    http.status = failure.status;
    http.provider_code = failure.provider_code;
    http.error_origin = failure.parameter ? `provider_payload:${failure.parameter}` : "provider_payload";
  }
  const thinking = messages.flatMap((message) => message.content.filter((block) => block.type === "thinking").map((block) => block.thinking)).join("");
  let output = null;
  let error = null;
  if (providerError) {
    error = { code: "PROVIDER_REJECTED_REQUEST", message: "provider rejected the pi request", retryable: false };
  } else if (!providerIdentity.exact_match) {
    error = { code: "IDENTITY_MISMATCH", message: "exact model identity failed", retryable: false };
  } else if (mode === "run") {
    try { output = decodeOutput(messages); }
    catch { error = { code: "INVALID_MODEL_OUTPUT", message: "response did not match the strict JSON output contract", retryable: false }; }
  }
  return {
    runtime: { package: "@mariozechner/pi-agent-core", version: runtimeVersion },
    output, error,
    latency_ms: Math.max(0, Math.round(performance.now() - started)),
    usage: usage(messages),
    provider_identity: providerIdentity,
    provider_observability: {
      generation_profile: runtime.generation_profile,
      stream_metrics: { mode: "streaming", ttft_reasoning_ms: null, ttft_content_ms: null, e2e_ms: Math.max(0, Math.round(performance.now() - started)) },
      reasoning_summary: { characters: thinking.length, sha256: thinking ? createHash("sha256").update(thinking).digest("hex") : null },
      http,
    },
    provider_turns: providerTurns,
    tool_calls: toolCalls,
    agent_events: events,
  };
}

async function main() {
  try {
    const payload = JSON.parse(readFileSync(0, "utf8"));
    process.stdout.write(`${JSON.stringify(await runLivePiAgent(payload))}\n`);
  } catch {
    process.stdout.write(`${JSON.stringify({ output: null, error: { code: "PI_AGENT_ERROR", message: "pi live runtime failed", retryable: false }, latency_ms: 0, usage: { input_tokens: 0, output_tokens: 0 }, provider_identity: null, provider_observability: null, tool_calls: [], agent_events: [] })}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
