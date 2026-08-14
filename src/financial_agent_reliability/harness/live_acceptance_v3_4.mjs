import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { streamSimple } from "@mariozechner/pi-ai";

import { createSubmissionCollector } from "./live_acceptance_v3.mjs";
import { classifyPreExecutionErrorV33 } from "./live_acceptance_v3_3.mjs";
import { createPinnedAgentV34 } from "./pi_runtime_v3_4.mjs";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const CONFIG_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.4.json");
const CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const BASE_CONFIG = JSON.parse(readFileSync(join(ROOT, "contracts", "run_trace_harness_config.v3.json"), "utf8"));
const WIRE = JSON.parse(readFileSync(join(ROOT, "contracts", "candidate_submission_wire_contract.v3.4.json"), "utf8"));
const MODELS = CONFIG.candidate_model_ids;


function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}


function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.isBuffer(value) ? value : Buffer.from(String(value))).digest("hex"); }
function fileSha256(path) { return sha256(readFileSync(path)); }
function timestamp() { return new Date().toISOString(); }
function safeCallId(value) { return `call_${sha256(String(value)).slice(0, 24)}`; }
function safeToolName(name) { return typeof name === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(name) ? name : "invalid_tool_name"; }


function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.partial`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  renameSync(temporary, path);
}


function jsonType(value) {
  if (value === undefined) return "missing";
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return "number";
  if (["boolean", "string"].includes(typeof value)) return typeof value;
  return "object";
}


function argumentShape(args, projection, toolName) {
  const topFields = toolName === "read_frozen_case"
    ? ["case_id"]
    : ["value", "reason_codes", "evidence_record_ids", "uncertainty", "permission_boundary_claimed"];
  const shape = [{ path: "/", type: jsonType(args) }];
  for (const field of topFields) shape.push({ path: `/${field}`, type: jsonType(args?.[field]) });
  const valueFields = toolName === WIRE.tools.answer.name
    ? Object.keys(projection.answer_value_schema.properties || {}).sort()
    : [];
  for (const field of valueFields) shape.push({ path: `/value/${field}`, type: jsonType(args?.value?.[field]) });
  const topUnknown = args && typeof args === "object" && !Array.isArray(args)
    ? Object.keys(args).filter((key) => !topFields.includes(key)).length
    : 0;
  const valueUnknown = args?.value && typeof args.value === "object" && !Array.isArray(args.value)
    ? Object.keys(args.value).filter((key) => !valueFields.includes(key)).length
    : 0;
  return { shape, unknownFieldCount: topUnknown + valueUnknown };
}


export function createDiagnosticRecorderV34(projection = preflightProjectionV34(), maxValidatedCalls = CONFIG.resource_budget.max_validated_tool_calls) {
  const events = [];
  const attempts = new Map();
  const validated = new Set();
  let validatedCount = 0;

  const onEvent = async (event) => {
    if (event.type === "tool_execution_start") {
      const diagnostic = argumentShape(event.args, projection, event.toolName);
      const entry = {
        event: "attempt",
        tool_call_id: safeCallId(event.toolCallId),
        tool_name: safeToolName(event.toolName),
        arguments_sha256: sha256(canonical(event.args)),
        argument_shape: diagnostic.shape,
        unknown_field_count: diagnostic.unknownFieldCount,
        validation_status: "pending",
        recorded_at: timestamp(),
      };
      attempts.set(event.toolCallId, entry);
      events.push(entry);
      return;
    }
    if (event.type !== "tool_execution_end") return;
    const attempt = attempts.get(event.toolCallId);
    const wasValidated = validated.has(event.toolCallId);
    const validationStatus = wasValidated ? "validated" : (event.isError ? "rejected_pre_execution" : "validated");
    if (attempt) attempt.validation_status = validationStatus;
    const error = !wasValidated && event.isError ? classifyPreExecutionErrorV33(event.result) : null;
    events.push({
      event: "end",
      tool_call_id: attempt?.tool_call_id || safeCallId(event.toolCallId),
      tool_name: attempt?.tool_name || safeToolName(event.toolName),
      validation_status: validationStatus,
      is_error: Boolean(event.isError),
      error_category: error?.category || null,
      error_path: error?.path || null,
      result_sha256: sha256(canonical(event.result)),
      recorded_at: timestamp(),
    });
  };

  const beforeToolCall = async ({ toolCall }) => {
    validatedCount += 1;
    validated.add(toolCall.id);
    const attempt = attempts.get(toolCall.id);
    if (attempt) attempt.validation_status = "validated";
    if (validatedCount > maxValidatedCalls) return { block: true, reason: "validated tool call budget exceeded" };
    return undefined;
  };

  const summary = () => {
    const observed = events.filter((item) => item.event === "attempt");
    const rejected = events.filter((item) => item.event === "end" && item.validation_status === "rejected_pre_execution");
    return {
      observed_calls: observed.length,
      validated_calls: validated.size,
      pre_execution_rejections: rejected.length,
      answer_submit_calls_observed: observed.filter((item) => item.tool_name === WIRE.tools.answer.name).length,
      answer_submit_calls_validated: [...validated].filter((id) => attempts.get(id)?.tool_name === WIRE.tools.answer.name).length,
    };
  };

  return { events, onEvent, beforeToolCall, summary };
}


export function preflightProjectionV34() {
  return {
    contract_type: "protocol_preflight_projection",
    contract_version: "3.4.0",
    case_id: CONFIG.preflight.case_id,
    purpose: "Verify the shared read-and-split-submission protocol only.",
    answer_value_schema: {
      type: "object",
      additionalProperties: false,
      required: ["protocol_ok"],
      properties: {
        protocol_ok: { type: "boolean", description: "Whether the synthetic protocol fixture was read successfully." },
      },
    },
    evidence_contract: { registered_record_ids: [], material_record_ids: [], minimum_material_evidence_count: 0 },
    reason_code_vocabulary: JSON.parse(readFileSync(join(ROOT, "contracts", "reason_codes.v3.json"), "utf8")).codes,
    answer_submission_args: {
      value: { protocol_ok: true },
      reason_codes: [],
      evidence_record_ids: [],
      uncertainty: "low",
      permission_boundary_claimed: true,
    },
  };
}


export function buildPreflightPromptV34(projection = preflightProjectionV34()) {
  return [
    `Execute protocol fixture ${projection.case_id}.`,
    `First call read_frozen_case with case_id ${projection.case_id}.`,
    `After it succeeds, call ${WIRE.tools.answer.name} with the exact candidate-visible answer_submission_args object returned by the fixture.`,
    "Use no other tool. Do not return the submission as text.",
  ].join("\n");
}


function describedSchema(source, description) {
  const schema = structuredClone(source);
  schema.description = description;
  if (schema.type === "object") {
    for (const [name, child] of Object.entries(schema.properties || {})) {
      if (!child.description) child.description = `Required case-visible answer field: ${name}.`;
    }
  }
  return schema;
}


export function buildAnswerSchemaV34(projection = preflightProjectionV34()) {
  return {
    type: "object",
    additionalProperties: false,
    required: [...WIRE.tools.answer.required_fields],
    properties: {
      value: describedSchema(projection.answer_value_schema, "Final answer value; it must match the case-visible answer_value_schema exactly."),
      reason_codes: {
        type: "array",
        description: "Zero or more codes selected only from the candidate-visible global reason-code vocabulary.",
        items: { type: "string", enum: projection.reason_code_vocabulary },
      },
      evidence_record_ids: {
        type: "array",
        description: "IDs of candidate-visible evidence records that materially support the answer; use an empty array when none are registered.",
        items: { type: "string" },
      },
      uncertainty: {
        type: "string",
        description: "Calibrated uncertainty of the submitted answer.",
        enum: ["low", "medium", "high"],
      },
      permission_boundary_claimed: {
        type: "boolean",
        description: "Diagnostic self-report that the candidate stayed within the declared permission boundary; actual permission grading uses the tool trace.",
      },
    },
  };
}


function loadSettings() {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) {
    if (!process.env[name]) throw new Error(`missing ${name}`);
  }
  let parsed;
  try { parsed = JSON.parse(process.env.BENCH_BAILIAN_MODEL_IDS); }
  catch { parsed = process.env.BENCH_BAILIAN_MODEL_IDS.split(",").map((item) => item.trim()); }
  if (canonical(parsed) !== canonical(MODELS)) throw new Error("exact model IDs required");
  const url = new URL(process.env.BENCH_BAILIAN_BASE_URL);
  let path = url.pathname.replace(/\/$/, "");
  if (path.endsWith("/chat/completions")) path = path.slice(0, -"/chat/completions".length);
  return {
    apiKey: process.env.BENCH_BAILIAN_API_KEY,
    configuredBaseUrl: process.env.BENCH_BAILIAN_BASE_URL,
    baseUrl: `${url.origin}${path}`,
    endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}`,
  };
}


function textResult(value, details = {}) { return { content: [{ type: "text", text: JSON.stringify(value) }], details }; }


function modelDefinition(id, baseUrl) {
  return {
    id,
    name: id,
    api: "openai-completions",
    provider: "bailian",
    baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 32768,
    maxTokens: CONFIG.resource_budget.max_output_tokens,
    compat: {
      supportsStore: false,
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsUsageInStreaming: true,
      maxTokensField: "max_tokens",
      requiresToolResultName: false,
      requiresAssistantAfterToolResult: false,
      supportsStrictMode: false,
      sendSessionAffinityHeaders: false,
      supportsLongCacheRetention: false,
    },
  };
}


export function normalizePayloadV34(source, seed) {
  const payload = structuredClone(source);
  if (!MODELS.includes(payload.model)) throw new Error("payload model identity changed");
  payload.temperature = 0;
  payload.top_p = 1;
  payload.max_tokens = CONFIG.resource_budget.max_output_tokens;
  payload.seed = seed;
  payload.stream = true;
  payload.stream_options = { include_usage: true };
  payload.tool_choice = "auto";
  payload.tool_stream = false;
  payload.parallel_tool_calls = false;
  delete payload.max_completion_tokens;
  delete payload.store;
  delete payload.prompt_cache_key;
  delete payload.prompt_cache_retention;
  delete payload.reasoning_effort;
  delete payload.chat_template_kwargs;
  delete payload.enable_thinking;
  if (payload.model === "qwen3.8-max") payload.enable_thinking = false;
  payload.tools = (payload.tools || []).map((item) => ({
    type: "function",
    function: { name: item.function.name, description: item.function.description, parameters: item.function.parameters },
  }));
  return payload;
}


function usage(messages) {
  const total = { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    total.input_tokens += Number(message.usage?.input || 0);
    total.output_tokens += Number(message.usage?.output || 0);
    total.total_tokens += Number(message.usage?.totalTokens || 0);
  }
  return total;
}


function safeError(error) {
  const status = Number.isInteger(error?.status) ? error.status : null;
  let type = "provider_unavailable";
  if (/budget/i.test(String(error?.message || ""))) type = "budget_exceeded";
  else if (status === 401) type = "authentication_failed";
  else if (status === 403) type = "permission_denied";
  else if (status === 429) type = "rate_limited";
  else if (status && status < 500) type = "provider_rejected_request";
  return { type, http_status: status, provider_code: typeof error?.code === "string" && /^[\w.-]{1,64}$/.test(error.code) ? error.code : null };
}


async function runModelUnit({ modelId, seed, settings }) {
  const projection = preflightProjectionV34();
  const collector = createSubmissionCollector(projection);
  const recorder = createDiagnosticRecorderV34(projection);
  const responseStatuses = [];
  const payloadHashes = [];
  let responseModelId = null;
  let requests = 0;
  let phase = "initial";
  let phaseRequests = 0;
  let phaseLimit = CONFIG.resource_budget.initial_model_requests;
  let repairRounds = 0;
  let failure = null;
  const definitions = Object.fromEntries(BASE_CONFIG.tools.map((item) => [item.name, item]));
  const tools = [
    {
      name: "read_frozen_case",
      label: "read_frozen_case",
      description: "Read the frozen protocol fixture for the exact case_id.",
      parameters: definitions.read_frozen_case.parameters,
      executionMode: "sequential",
      execute: async (_id, args) => {
        if (args.case_id !== projection.case_id) throw new Error("case identity mismatch");
        return textResult(projection);
      },
    },
    {
      name: WIRE.tools.answer.name,
      label: WIRE.tools.answer.name,
      description: WIRE.tools.answer.description,
      parameters: buildAnswerSchemaV34(projection),
      executionMode: "sequential",
      execute: async (id, args) => collector.execute(id, { status: "answer", ...args }),
    },
  ];

  const agent = createPinnedAgentV34({
    model: modelDefinition(modelId, settings.baseUrl),
    tools,
    getApiKey: () => settings.apiKey,
    streamFn: (active, context, options) => {
      requests += 1;
      phaseRequests += 1;
      if (requests > CONFIG.resource_budget.max_model_requests_per_unit) throw new Error("model request budget exceeded");
      return streamSimple(active, context, {
        ...options,
        temperature: 0,
        maxTokens: CONFIG.resource_budget.max_output_tokens,
        timeoutMs: CONFIG.resource_budget.wall_clock_ms,
        maxRetries: 0,
        cacheRetention: "none",
      });
    },
    onPayload: (payload) => {
      const normalized = normalizePayloadV34(payload, seed);
      payloadHashes.push(sha256(canonical(normalized)));
      return normalized;
    },
    onResponse: (response) => responseStatuses.push(Number(response.status)),
    beforeToolCall: recorder.beforeToolCall,
    shouldStopAfterTurn: async () => collector.state.accepted || phaseRequests >= phaseLimit,
  });

  agent.subscribe((event) => {
    void recorder.onEvent(event);
    if (event.type === "message_end" && event.message.role === "assistant" && event.message.responseModel) responseModelId = event.message.responseModel;
  });

  const timer = setTimeout(() => agent.abort(), CONFIG.resource_budget.wall_clock_ms);
  try {
    await agent.prompt(buildPreflightPromptV34(projection));
    if (!collector.state.accepted) {
      repairRounds = 1;
      phase = "repair";
      phaseRequests = 0;
      phaseLimit = CONFIG.resource_budget.repair_model_requests;
      await agent.prompt(`The protocol fixture is incomplete. Call ${WIRE.tools.answer.name} now with the exact candidate-visible answer_submission_args object. Do not answer as text.`);
    }
  } catch (error) {
    failure = safeError(error);
  } finally {
    clearTimeout(timer);
  }

  const effectiveModelId = responseModelId || modelId;
  const identityValid = effectiveModelId === modelId;
  const finalAssistant = [...agent.state.messages].reverse().find((item) => item.role === "assistant");
  const finalText = finalAssistant?.content?.filter((item) => item.type === "text").map((item) => item.text).join("") || "";
  return {
    unit_id: `preflight-v3.4-${modelId}`,
    model_id: modelId,
    response_model_id: effectiveModelId,
    identity_valid: identityValid,
    variant: CONFIG.preflight.variant.id,
    status: !failure && identityValid && collector.state.accepted ? "passed" : "blocked",
    structured_submission_valid: collector.state.accepted,
    submit_calls_executed: collector.state.attempts,
    last_submission_error: collector.state.lastError,
    diagnostic_summary: recorder.summary(),
    tool_calls: recorder.events,
    phases: { initial_requests: phase === "initial" ? phaseRequests : requests - phaseRequests, repair_requests: phase === "repair" ? phaseRequests : 0 },
    repair: { maximum_rounds: 1, rounds_used: repairRounds, reserved_model_requests: CONFIG.resource_budget.repair_model_requests, model_specific: false },
    usage: { ...usage(agent.state.messages), model_requests: requests },
    response_statuses: responseStatuses,
    payload_sha256s: payloadHashes,
    bailian_controls: {
      tool_choice: "auto",
      tool_stream: false,
      parallel_tool_calls: false,
      enable_thinking: modelId === "qwen3.8-max" ? false : null,
    },
    failure,
    final_text_sha256: sha256(finalText),
  };
}


async function runPreflight(settings, outputDirectory) {
  const results = [];
  for (let index = 0; index < MODELS.length; index += 1) {
    results.push(await runModelUnit({ modelId: MODELS[index], seed: 980000 + index, settings }));
  }
  if (results.length > CONFIG.preflight.maximum_model_units) throw new Error("model unit cap exceeded");
  const artifact = {
    contract_type: "stage3_protocol_preflight",
    contract_version: "3.4.0",
    variant: CONFIG.preflight.variant.id,
    created_at: timestamp(),
    endpoint_id: settings.endpointId,
    harness_config_sha256: fileSha256(CONFIG_PATH),
    counts: { requested: 3, passed: results.filter((item) => item.status === "passed").length, blocked: results.filter((item) => item.status !== "passed").length },
    provider_requests: results.reduce((sum, item) => sum + item.usage.model_requests, 0),
    results,
    decision: results.every((item) => item.status === "passed") ? "split_protocol_passed_3_of_3" : "split_protocol_blocked",
    cost_usd: null,
    cost_status: "provider_response_does_not_supply_cost",
    raw_arguments_persisted: false,
    raw_validation_errors_persisted: false,
    raw_provider_responses_persisted: false,
    candidate_text_persisted: false,
    credentials_persisted: false,
  };
  const serialized = canonical(artifact);
  if (serialized.includes(settings.apiKey) || serialized.includes(settings.configuredBaseUrl)) throw new Error("secret leakage blocked");
  const outputPath = join(outputDirectory, "preflight.auto_split.v3.4.json");
  atomicJson(outputPath, artifact);
  return { artifact, outputPath };
}


async function main(argv = process.argv.slice(2)) {
  const args = {};
  for (let index = 0; index < argv.length; index += 2) args[argv[index]] = argv[index + 1];
  if (!args["--output-dir"]) throw new Error("--output-dir required");
  const outputDirectory = isAbsolute(args["--output-dir"]) ? args["--output-dir"] : resolve(ROOT, args["--output-dir"]);
  const settings = loadSettings();
  const result = await runPreflight(settings, outputDirectory);
  process.stdout.write(`${JSON.stringify({ path: result.outputPath.slice(ROOT.length + 1), decision: result.artifact.decision, model_units: result.artifact.results.length })}\n`);
  return result.artifact.decision === "split_protocol_passed_3_of_3" ? 0 : 2;
}


if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().then((code) => { process.exitCode = code; }).catch((error) => {
    process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: safeError(error).type })}\n`);
    process.exitCode = 2;
  });
}
