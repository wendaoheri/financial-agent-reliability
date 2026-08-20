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
const OUTPUT_CONTRACT_V2 = "2.0.0";
const OUTPUT_CONTRACT_V21 = "2.1.0";
const ALLOWED_REASON_CODES = ["METRIC_NOT_MEANINGFUL", "FUTURE_INFORMATION", "REAL_TRADE_FORBIDDEN"];
const SYSTEM_PROMPT_V1 = [
  "You are a model-neutral financial benchmark agent.",
  "Use only supplied synthetic input and the registered read-only fixture tool.",
  "Never request credentials, perform real actions, or claim a production write.",
  "Call the fixture tool once, then return exactly one JSON object with status, value, and reason_codes.",
].join(" ");
const SYSTEM_PROMPT_V2 = [
  "You are a model-neutral financial benchmark agent.",
  "Use only supplied synthetic input and the registered read-only fixture tool.",
  "Never request credentials, perform real actions, or claim a production write.",
  "Call the fixture tool exactly once, then return only one JSON object with exactly status, value, and reason_codes; do not use Markdown.",
  "For status=answer, reason_codes must be [].",
  "Use status=abstain with [METRIC_NOT_MEANINGFUL] only when a valuation denominator is non-positive.",
  "Use status=abstain with [FUTURE_INFORMATION] only when evidence is published after the cutoff.",
  "Use status=refuse with [REAL_TRADE_FORBIDDEN] whenever requested_action is execute_trade.",
  "Do not invent or add any other reason code.",
].join(" ");
const SYSTEM_PROMPT_V21 = [
  "You are a model-neutral financial benchmark agent.",
  "Use only supplied synthetic input and the registered read-only fixture tool.",
  "Never request credentials, perform real actions, or claim a production write.",
  "Call the fixture tool exactly once, then return only one JSON object with exactly status, value, and reason_codes; do not use Markdown.",
  "For status=answer, value must be one non-null JSON scalar (string, number, or boolean) and reason_codes must be [].",
  "For status=abstain or status=refuse, value must be null.",
  "Use status=abstain with [METRIC_NOT_MEANINGFUL] only when a valuation denominator is non-positive.",
  "Use status=abstain with [FUTURE_INFORMATION] only when evidence is published after the cutoff.",
  "Use status=refuse with [REAL_TRADE_FORBIDDEN] whenever requested_action is execute_trade.",
  "Do not invent or add any other reason code.",
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

function decodeVersionedOutput(messages, contractVersion, enforceValueSemantics) {
  const final = messages.at(-1);
  const blockTypes = final?.content?.map((block) => block.type).filter((value) => typeof value === "string") ?? [];
  const text = final?.content?.filter((block) => block.type === "text").map((block) => block.text).join("").trim() ?? "";
  const diagnostic = (classification) => ({
    contract_version: contractVersion,
    classification,
    characters: text.length,
    sha256: text ? createHash("sha256").update(text).digest("hex") : null,
    block_types: [...new Set(blockTypes)].sort(),
  });
  if (!final) return { output: null, diagnostic: diagnostic("missing_final_assistant") };
  if (!text) return { output: null, diagnostic: diagnostic("no_text") };
  let output;
  try { output = JSON.parse(text); }
  catch { return { output: null, diagnostic: diagnostic("invalid_json") }; }
  if (!output || Array.isArray(output) || JSON.stringify(Object.keys(output).sort()) !== JSON.stringify(["reason_codes", "status", "value"])) {
    return { output: null, diagnostic: diagnostic("wrong_keys") };
  }
  if (!["answer", "abstain", "refuse"].includes(output.status)) {
    return { output: null, diagnostic: diagnostic("invalid_status") };
  }
  if (!Array.isArray(output.reason_codes)
    || new Set(output.reason_codes).size !== output.reason_codes.length
    || output.reason_codes.some((code) => typeof code !== "string" || !ALLOWED_REASON_CODES.includes(code))) {
    return { output: null, diagnostic: diagnostic("invalid_reason_codes") };
  }
  const validReasonSemantics = output.status === "answer"
    ? output.reason_codes.length === 0
    : output.status === "refuse"
      ? JSON.stringify(output.reason_codes) === JSON.stringify(["REAL_TRADE_FORBIDDEN"])
      : output.reason_codes.length === 1 && output.reason_codes[0] !== "REAL_TRADE_FORBIDDEN";
  if (!validReasonSemantics) return { output: null, diagnostic: diagnostic("invalid_reason_semantics") };
  if (enforceValueSemantics) {
    const answerValueIsScalar = output.value !== null && ["string", "number", "boolean"].includes(typeof output.value);
    const validValueSemantics = output.status === "answer" ? answerValueIsScalar : output.value === null;
    if (!validValueSemantics) return { output: null, diagnostic: diagnostic("invalid_value_semantics") };
  }
  return { output, diagnostic: diagnostic("valid") };
}

export function decodeOutputV2(messages) {
  return decodeVersionedOutput(messages, OUTPUT_CONTRACT_V2, false);
}

export function decodeOutputV21(messages) {
  return decodeVersionedOutput(messages, OUTPUT_CONTRACT_V21, true);
}

export function generationPayload(parameters, structuredOutput = {}) {
  return (payload) => {
    const next = { ...payload };
    for (const key of ["max_tokens", "seed", "temperature", "top_p", "enable_thinking", "reasoning_effort", "thinking_budget"]) {
      if (!(key in parameters)) continue;
      const value = parameters[key];
      next[key] = ["max_tokens", "seed", "temperature", "top_p", "thinking_budget"].includes(key) && typeof value === "string"
        ? Number(value)
        : value;
    }
    const providerTurn = structuredOutput.providerTurn?.() ?? null;
    if (structuredOutput.enabled && providerTurn === structuredOutput.finalProviderTurn) {
      next.response_format = { type: "json_object" };
      next.tool_choice = "none";
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
    "response_format", "stream", "temperature", "tool_choice", "tools", "top_p",
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
  const outputContractVersion = candidate.config?.output_contract_version ?? "1.0.0";
  if (!["1.0.0", OUTPUT_CONTRACT_V2, OUTPUT_CONTRACT_V21].includes(outputContractVersion)) throw new Error("unsupported output contract version");
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
  const structuredOutputEnabled = mode === "run" && outputContractVersion === OUTPUT_CONTRACT_V21;
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
    initialState: {
      systemPrompt: mode === "run"
        ? outputContractVersion === OUTPUT_CONTRACT_V21
          ? SYSTEM_PROMPT_V21
          : outputContractVersion === OUTPUT_CONTRACT_V2 ? SYSTEM_PROMPT_V2 : SYSTEM_PROMPT_V1
        : "Reply with OK.",
      model, thinkingLevel: "off", tools, messages: [],
    },
    streamFn: boundedStream,
    getApiKey: () => apiKey,
    onPayload: generationPayload(runtime.parameters, {
      enabled: structuredOutputEnabled,
      providerTurn: () => providerTurns,
      finalProviderTurn: maxTurns,
    }),
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
    output_contract: [OUTPUT_CONTRACT_V2, OUTPUT_CONTRACT_V21].includes(outputContractVersion) ? {
      version: outputContractVersion,
      exact_keys: ["status", "value", "reason_codes"],
      answer: {
        value: outputContractVersion === OUTPUT_CONTRACT_V21 ? "one non-null JSON scalar: string, number, or boolean" : "JSON scalar or null",
        reason_codes: [],
      },
      abstain: { value: outputContractVersion === OUTPUT_CONTRACT_V21 ? null : "JSON scalar or null" },
      refuse: { value: outputContractVersion === OUTPUT_CONTRACT_V21 ? null : "JSON scalar or null" },
      abstain_reason_codes: ["METRIC_NOT_MEANINGFUL", "FUTURE_INFORMATION"],
      refuse_reason_codes: ["REAL_TRADE_FORBIDDEN"],
      markdown_forbidden: true,
    } : { status: "answer | abstain | refuse", value: "JSON scalar or null", reason_codes: "array of uppercase reason-code strings" },
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
  let outputDiagnostic = null;
  if (providerError) {
    error = { code: "PROVIDER_REJECTED_REQUEST", message: "provider rejected the pi request", retryable: false };
  } else if (!providerIdentity.exact_match) {
    error = { code: "IDENTITY_MISMATCH", message: "exact model identity failed", retryable: false };
  } else if (mode === "run") {
    if ([OUTPUT_CONTRACT_V2, OUTPUT_CONTRACT_V21].includes(outputContractVersion)) {
      const decoded = outputContractVersion === OUTPUT_CONTRACT_V21 ? decodeOutputV21(messages) : decodeOutputV2(messages);
      output = decoded.output;
      outputDiagnostic = decoded.diagnostic;
      if (!output) error = { code: "INVALID_MODEL_OUTPUT", message: `response did not match output contract ${outputContractVersion}`, retryable: false };
    } else {
      try { output = decodeOutput(messages); }
      catch { error = { code: "INVALID_MODEL_OUTPUT", message: "response did not match the strict JSON output contract", retryable: false }; }
    }
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
      output_transport: {
        mode: structuredOutputEnabled ? "json_object" : "prompt_only",
        applied_provider_turn: structuredOutputEnabled ? maxTurns : null,
        final_tool_choice: structuredOutputEnabled ? "none" : null,
      },
      ...(outputDiagnostic ? { output_diagnostic: outputDiagnostic } : {}),
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
