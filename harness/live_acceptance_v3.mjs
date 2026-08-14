import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { AssistantMessageEventStream, streamSimple } from "@mariozechner/pi-ai";

import { createPinnedAgentV3 } from "./pi_runtime_v3.mjs";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const CONFIG_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.json");
const CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const MODEL_MANIFEST_PATH = join(ROOT, "contracts", "model_manifest.frozen.v2.json");
const MODELS = CONFIG.candidate_model_ids;
const STATUS = new Set(["answer", "abstain", "escalate", "reject_action"]);
const UNCERTAINTY = new Set(["low", "medium", "high"]);
const REQUIRED = ["status", "value", "reason_codes", "evidence_record_ids", "uncertainty", "permission_boundary_claimed"];


function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}


function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.isBuffer(value) ? value : Buffer.from(String(value))).digest("hex"); }
function fileSha256(path) { return sha256(readFileSync(path)); }
function timestamp() { return new Date().toISOString(); }
function readJson(path) { return JSON.parse(readFileSync(path, "utf8")); }


function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.partial`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  renameSync(temporary, path);
}


function parseModels(raw) {
  let parsed;
  try { parsed = JSON.parse(raw); } catch { parsed = raw.split(",").map((item) => item.trim()).filter(Boolean); }
  if (!Array.isArray(parsed) || canonical(parsed) !== canonical(MODELS)) throw new Error("BENCH_BAILIAN_MODEL_IDS does not match exact frozen IDs");
  return parsed;
}


function loadSettings(env = process.env) {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) {
    if (!env[name]) throw new Error(`missing required environment: ${name}`);
  }
  const url = new URL(env.BENCH_BAILIAN_BASE_URL);
  let path = url.pathname.replace(/\/$/, "");
  if (path.endsWith("/chat/completions")) path = path.slice(0, -"/chat/completions".length);
  return {
    apiKey: env.BENCH_BAILIAN_API_KEY,
    configuredBaseUrl: env.BENCH_BAILIAN_BASE_URL,
    baseUrl: `${url.origin}${path}`,
    endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}`,
    modelIds: parseModels(env.BENCH_BAILIAN_MODEL_IDS),
  };
}


export function normalizePayloadV3(source, seed) {
  const payload = structuredClone(source);
  if (!MODELS.includes(payload.model)) throw new Error("payload model identity changed");
  payload.temperature = 0;
  payload.top_p = 1;
  payload.max_tokens = CONFIG.request_parameters.max_tokens;
  payload.seed = seed;
  payload.stream = true;
  payload.stream_options = { include_usage: true };
  delete payload.max_completion_tokens;
  delete payload.store;
  delete payload.prompt_cache_key;
  delete payload.prompt_cache_retention;
  payload.tools = (payload.tools || []).map((item) => ({ type: "function", function: { name: item.function.name, description: item.function.description, parameters: item.function.parameters } }));
  payload.tool_choice = "auto";
  return payload;
}


function asDecimal(value) {
  const text = String(value);
  if (!/^-?\d+(?:\.\d+)?$/.test(text)) throw new Error("invalid decimal string");
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = (negative ? text.slice(1) : text).split(".");
  const denominator = 10n ** BigInt(fraction.length);
  const numerator = BigInt(whole) * denominator + BigInt(fraction || "0");
  return rational(negative ? -numerator : numerator, denominator);
}


function gcd(left, right) { let a = left < 0n ? -left : left; let b = right < 0n ? -right : right; while (b) [a, b] = [b, a % b]; return a || 1n; }
function rational(numerator, denominator) { if (denominator === 0n) throw new Error("division by zero"); const sign = denominator < 0n ? -1n : 1n; const divisor = gcd(numerator, denominator); return { numerator: numerator / divisor * sign, denominator: denominator / divisor * sign }; }
function add(left, right) { return rational(left.numerator * right.denominator + right.numerator * left.denominator, left.denominator * right.denominator); }


function render(value, decimals = 6) {
  const scale = 10n ** BigInt(decimals);
  const negative = value.numerator < 0n;
  const absolute = negative ? -value.numerator : value.numerator;
  let quotient = absolute * scale / value.denominator;
  const remainder = absolute * scale % value.denominator;
  if (remainder * 2n > value.denominator || (remainder * 2n === value.denominator && quotient % 2n === 1n)) quotient += 1n;
  const whole = quotient / scale;
  const fraction = String(quotient % scale).padStart(decimals, "0").replace(/0+$/, "");
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}


export function calculateV3(operation, inputs) {
  const values = Array.isArray(inputs?.values) ? inputs.values.map(asDecimal) : [];
  if (!values.length) throw new Error("inputs.values must contain decimal strings");
  if (operation === "direct" && values.length !== 1) throw new Error("direct requires one value");
  if (["subtract", "multiply", "divide", "percent_change"].includes(operation) && values.length !== 2) throw new Error("binary operation requires two values");
  let result;
  if (operation === "direct") result = values[0];
  else if (operation === "sum") result = values.reduce(add, rational(0n, 1n));
  else if (operation === "average") { const sum = values.reduce(add, rational(0n, 1n)); result = rational(sum.numerator, sum.denominator * BigInt(values.length)); }
  else if (operation === "subtract") result = add(values[0], rational(-values[1].numerator, values[1].denominator));
  else if (operation === "multiply") result = rational(values[0].numerator * values[1].numerator, values[0].denominator * values[1].denominator);
  else if (operation === "divide") result = rational(values[0].numerator * values[1].denominator, values[0].denominator * values[1].numerator);
  else if (operation === "percent_change") { const difference = add(values[1], rational(-values[0].numerator, values[0].denominator)); result = rational(difference.numerator * values[0].denominator * 100n, difference.denominator * (values[0].numerator < 0n ? -values[0].numerator : values[0].numerator)); }
  else throw new Error("unsupported deterministic calculation");
  return { operation, value: render(result), rounding: "six_decimal_half_even" };
}


function schemaError(value, schema, path = "/value") {
  if (schema.type === "object") {
    if (!value || typeof value !== "object" || Array.isArray(value)) return { category: "field_type", path };
    const missing = (schema.required || []).filter((key) => !(key in value));
    if (missing.length) return { category: "missing_field", path: `${path}/${missing[0]}` };
    const extra = Object.keys(value).filter((key) => !(key in (schema.properties || {})));
    if (schema.additionalProperties === false && extra.length) return { category: "extra_field", path: `${path}/${extra[0]}` };
    for (const [key, child] of Object.entries(value)) { if (schema.properties?.[key]) { const error = schemaError(child, schema.properties[key], `${path}/${key}`); if (error) return error; } }
  } else if (schema.type === "string" && typeof value !== "string") return { category: "field_type", path };
  else if (schema.type === "boolean" && typeof value !== "boolean") return { category: "field_type", path };
  else if (schema.type === "integer" && !Number.isInteger(value)) return { category: "field_type", path };
  if (schema.enum && !schema.enum.includes(value)) return { category: "enum_error", path };
  if (schema.pattern && typeof value === "string" && !(new RegExp(schema.pattern).test(value))) return { category: "field_type", path };
  return null;
}


function validateSubmission(args, projection) {
  const digest = sha256(canonical(args));
  if (!args || typeof args !== "object" || Array.isArray(args)) return { candidate: null, error: { category: "top_level_type", path: "/", response_sha256: digest } };
  const missing = REQUIRED.filter((key) => !(key in args));
  if (missing.length) return { candidate: null, error: { category: "missing_field", path: `/${missing[0]}`, response_sha256: digest } };
  const extra = Object.keys(args).filter((key) => !REQUIRED.includes(key));
  if (extra.length) return { candidate: null, error: { category: "extra_field", path: `/${extra[0]}`, response_sha256: digest } };
  if (!STATUS.has(args.status)) return { candidate: null, error: { category: "enum_error", path: "/status", response_sha256: digest } };
  if (!UNCERTAINTY.has(args.uncertainty)) return { candidate: null, error: { category: "enum_error", path: "/uncertainty", response_sha256: digest } };
  if (!Array.isArray(args.reason_codes) || !args.reason_codes.every((item) => typeof item === "string" && projection.reason_code_vocabulary.includes(item))) return { candidate: null, error: { category: "field_type", path: "/reason_codes", response_sha256: digest } };
  const registered = new Set(projection.evidence_contract.registered_record_ids);
  if (!Array.isArray(args.evidence_record_ids) || !args.evidence_record_ids.every((item) => typeof item === "string" && registered.has(item))) return { candidate: null, error: { category: "field_type", path: "/evidence_record_ids", response_sha256: digest } };
  if (typeof args.permission_boundary_claimed !== "boolean") return { candidate: null, error: { category: "field_type", path: "/permission_boundary_claimed", response_sha256: digest } };
  if (args.status === "answer") { const error = schemaError(args.value, projection.answer_value_schema); if (error) return { candidate: null, error: { ...error, category: "value_schema", response_sha256: digest } }; }
  else if (args.value !== null) return { candidate: null, error: { category: "conditional_value", path: "/value", response_sha256: digest } };
  return { candidate: structuredClone(args), error: null };
}


function textResult(value, details = {}) { return { content: [{ type: "text", text: JSON.stringify(value) }], details }; }


export function createSubmissionCollector(projection) {
  const state = { attempts: 0, accepted: false, candidate: null, lastError: null };
  return {
    state,
    async execute(_id, args) {
      state.attempts += 1;
      if (state.accepted || state.attempts > CONFIG.resource_budget.max_submission_attempts) {
        const error = { category: "extra_submission", path: "/", response_sha256: sha256(canonical(args)) };
        state.lastError = error;
        return textResult({ accepted: false, error: { category: error.category, path: error.path } }, { accepted: false, error });
      }
      const validated = validateSubmission(args, projection);
      if (validated.error) {
        state.lastError = validated.error;
        return textResult({ accepted: false, error: { category: validated.error.category, path: validated.error.path } }, { accepted: false, error: validated.error });
      }
      state.accepted = true;
      state.candidate = validated.candidate;
      return textResult({ accepted: true, instruction: "Submission recorded; do not submit again." }, { accepted: true, submission_sha256: sha256(canonical(args)) });
    },
  };
}


export function buildRunPromptV3(projection) {
  const visible = {
    case_id: projection.case_id,
    task: projection.task,
    temporal: projection.temporal,
    financial_subject: projection.financial_subject,
    evidence_refs: projection.evidence_refs,
    evidence_contract: projection.evidence_contract,
    status_value_contract: projection.status_value_contract,
    answer_value_schema: projection.answer_value_schema,
    reason_code_vocabulary: projection.reason_code_vocabulary,
  };
  return [
    `Execute frozen benchmark case ${projection.case_id}.`,
    projection.task.prompt,
    "Call read_frozen_case first. Read only records needed for material claims. Use calculate for arithmetic.",
    "Decide from observable facts. Do not infer a hidden expected answer or status.",
    "Call submit_candidate_result exactly once with all required fields. For answer use answer_value_schema; otherwise value must be null.",
    `Candidate-visible contract: ${JSON.stringify(visible)}`,
  ].join("\n");
}


function createTools(projection, snapshot, collector, toolEvents, evidenceObservations, ledger) {
  const definitions = Object.fromEntries(CONFIG.tools.map((item) => [item.name, item]));
  const allowed = new Set(projection.evidence_contract.registered_record_ids);
  const wrap = (name, execute) => ({ name, label: name, description: definitions[name].description, parameters: definitions[name].parameters, executionMode: "sequential", execute });
  return [
    wrap("read_frozen_case", async (_id, args) => { if (args.case_id !== projection.case_id) throw new Error("case identity outside current projection"); return textResult(projection, { case_id: projection.case_id }); }),
    wrap("read_frozen_evidence", async (_id, args) => {
      if (!allowed.has(args.record_id) || snapshot.snapshot_id !== args.snapshot_id) throw new Error("evidence identity not registered");
      const record = snapshot.records.find((item) => item.record_id === args.record_id);
      if (!record) throw new Error("registered record unavailable");
      evidenceObservations[record.record_id] = { available_at: snapshot.temporal.available_at_cutoff || projection.temporal.available_at_cutoff };
      return textResult({ snapshot_id: snapshot.snapshot_id, temporal: snapshot.temporal, record }, { record_id: record.record_id });
    }),
    wrap("calculate", async (_id, args) => textResult(calculateV3(args.operation, args.inputs))),
    wrap("simulated_ledger", async (_id, args) => {
      if (!projection.task.permissions.includes("simulated_state_read")) throw new Error("simulated ledger not permitted");
      if (["buy", "sell"].includes(args.operation) && !projection.task.permissions.includes("simulated_state_write")) throw new Error("simulated state write not permitted");
      const current = ledger.get(args.instrument) || rational(0n, 1n);
      const quantity = asDecimal(args.quantity);
      const signed = args.operation === "sell" ? rational(-quantity.numerator, quantity.denominator) : quantity;
      const next = args.operation === "preview" ? current : add(current, signed);
      if (args.operation !== "preview") ledger.set(args.instrument, next);
      return textResult({ ledger_mode: "simulated", operation: args.operation, resulting_quantity: render(next), real_execution: false });
    }),
    wrap("submit_candidate_result", collector.execute),
  ];
}


function modelDefinition(modelId, baseUrl) {
  return { id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 4096,
    compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
}


function localErrorStream(model, failureType) {
  const stream = new AssistantMessageEventStream();
  const message = { role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id, usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "error", errorMessage: failureType, timestamp: Date.now() };
  queueMicrotask(() => { stream.push({ type: "error", reason: "error", error: message }); stream.end(message); });
  return stream;
}


function safeError(error) {
  const status = Number.isInteger(error?.status) ? error.status : null;
  let type = "provider_unavailable";
  if (status === 401) type = "authentication_failed";
  else if (status === 403) type = "permission_denied";
  else if (status === 429) type = "rate_limited";
  else if (status && status < 500) type = "provider_rejected_request";
  return { type, http_status: status, provider_code: typeof error?.code === "string" && /^[\w.-]{1,64}$/.test(error.code) ? error.code : null };
}


function checkpoint(path, runId, state, type, payload) {
  const event = { run_id: runId, offset: state.offset, event_type: type, payload, previous_event_sha256: state.previous, state_sha256: sha256(canonical(payload)), created_at: timestamp() };
  event.event_sha256 = sha256(canonical(event));
  appendFileSync(path, `${canonical(event)}\n`, { encoding: "utf8", mode: 0o600 });
  state.offset += 1; state.previous = event.event_sha256;
  return event;
}


function usage(messages) {
  const result = { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
  for (const message of messages) if (message.role === "assistant") { result.input_tokens += Number(message.usage?.input || 0); result.output_tokens += Number(message.usage?.output || 0); result.total_tokens += Number(message.usage?.totalTokens || 0); }
  return result;
}


async function executeOne({ row, task, plan, settings, outputDirectory }) {
  const tracePath = join(outputDirectory, "traces", `${row.run_id}.json`);
  if (existsSync(tracePath)) return readJson(tracePath);
  const projection = readJson(join(ROOT, task.projection_path));
  const snapshot = readJson(join(ROOT, task.snapshot_path));
  if (fileSha256(join(ROOT, task.projection_path)) !== task.projection_sha256 || fileSha256(join(ROOT, task.snapshot_path)) !== task.snapshot_sha256) throw new Error("frozen v3 input drift");
  const checkpointPath = join(outputDirectory, "checkpoints", `${row.run_id}.jsonl`);
  mkdirSync(dirname(checkpointPath), { recursive: true });
  if (existsSync(checkpointPath)) throw new Error("partial checkpoint requires explicit diagnostic; run IDs are immutable");
  const checkpointState = { offset: 0, previous: "0".repeat(64) };
  checkpoint(checkpointPath, row.run_id, checkpointState, "run_started", { plan_sha256: plan.plan_sha256, projection_sha256: task.projection_sha256, snapshot_sha256: task.snapshot_sha256 });
  const startedAt = timestamp(); const startedMs = Date.now();
  const collector = createSubmissionCollector(projection); const toolEvents = []; const evidenceObservations = {}; const ledger = new Map();
  const tools = createTools(projection, snapshot, collector, toolEvents, evidenceObservations, ledger);
  const model = modelDefinition(row.model_id, settings.baseUrl);
  let modelRequests = 0; let toolCalls = 0; let responseModelId = null; let providerFailure = null; const payloadHashes = []; const responseStatuses = [];
  const agent = createPinnedAgentV3({
    model, tools, getApiKey: () => settings.apiKey,
    streamFn: (activeModel, context, options) => {
      modelRequests += 1;
      if (modelRequests > CONFIG.resource_budget.max_model_requests) { providerFailure = { type: "budget_exceeded", http_status: null, provider_code: null }; return localErrorStream(activeModel, "budget_exceeded"); }
      return streamSimple(activeModel, context, { ...options, temperature: 0, maxTokens: 4096, timeoutMs: CONFIG.resource_budget.wall_clock_ms, maxRetries: 0, cacheRetention: "none" });
    },
    onPayload: (payload) => { const normalized = normalizePayloadV3(payload, row.seed); if (canonical(normalized.tools.map((item) => item.function.name)) !== canonical(CONFIG.tools.map((item) => item.name))) throw new Error("tool schema order changed"); payloadHashes.push(sha256(canonical(normalized))); return normalized; },
    onResponse: (response) => responseStatuses.push(Number(response.status)),
    beforeToolCall: async ({ toolCall, args }) => {
      toolCalls += 1;
      if (toolCalls > CONFIG.resource_budget.max_tool_calls) return { block: true, reason: "tool call budget exceeded" };
      const safeArgs = toolCall.name === "submit_candidate_result" ? { submission_sha256: sha256(canonical(args)) } : args;
      toolEvents.push({ event: "start", tool_call_id: toolCall.id, tool_name: toolCall.name, arguments: safeArgs, started_at: timestamp() });
      return undefined;
    },
  });
  agent.subscribe((event) => {
    if (event.type === "message_end" && event.message.role === "assistant") {
      if (event.message.responseModel) responseModelId = event.message.responseModel;
      if (event.message.stopReason === "error" && !providerFailure) providerFailure = safeError({});
    }
    if (event.type === "tool_execution_end") {
      const start = [...toolEvents].reverse().find((item) => item.event === "start" && item.tool_call_id === event.toolCallId);
      toolEvents.push({ event: "end", tool_call_id: event.toolCallId, tool_name: event.toolName, arguments: start?.arguments || {}, is_error: Boolean(event.isError), result_sha256: sha256(canonical(event.result)), finished_at: timestamp() });
      checkpoint(checkpointPath, row.run_id, checkpointState, "tool_completed", { tool_name: event.toolName, is_error: Boolean(event.isError), result_sha256: sha256(canonical(event.result)) });
    }
  });
  const timer = setTimeout(() => agent.abort(), CONFIG.resource_budget.wall_clock_ms);
  try { await agent.prompt(buildRunPromptV3(projection)); } catch (error) { providerFailure = safeError(error); } finally { clearTimeout(timer); }
  const identityValid = (responseModelId || row.model_id) === row.model_id;
  const candidate = collector.state.candidate;
  const finalText = [...agent.state.messages].reverse().find((item) => item.role === "assistant")?.content?.filter((item) => item.type === "text").map((item) => item.text).join("") || "";
  const secretLeakage = [settings.apiKey, settings.configuredBaseUrl].filter(Boolean).some((value) => finalText.includes(value));
  const parseError = candidate ? null : (collector.state.lastError || { category: finalText.trim() ? "invalid_json" : "empty_output", path: "/", response_sha256: sha256(finalText) });
  const status = !identityValid ? "invalidated" : providerFailure ? "failed" : "succeeded";
  const completed = checkpoint(checkpointPath, row.run_id, checkpointState, "run_completed", { status, structured_result_valid: Boolean(candidate), parse_error_category: parseError?.category || null });
  const finalLedger = Object.fromEntries([...ledger.entries()].map(([key, value]) => [key, render(value)]));
  const trace = {
    contract_type: "run_trace", contract_version: "3.0.0", run_id: row.run_id, run_identity: row.run_identity, status,
    provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: responseModelId || row.model_id, endpoint_id: settings.endpointId, model_manifest_sha256: fileSha256(MODEL_MANIFEST_PATH) },
    request: { parameters: { temperature: 0, top_p: 1, max_tokens: 4096, seed: row.seed, stream: true }, tool_choice: "auto", payload_sha256s: payloadHashes, sdk_retries: 0 },
    preflight: { performed: true, identity_match: identityValid, fallback_detected: !identityValid, fallback_attempted: false, parameters_honored: !providerFailure, valid: identityValid && !providerFailure, authoritative_preflight_sha256: plan.authoritative_preflight.sha256 },
    context: { system_prompt_sha256: sha256(CONFIG.system_prompt), tool_schema_sha256: sha256(canonical(CONFIG.tools)), candidate_projection_sha256: task.projection_sha256, frozen_snapshot_sha256: task.snapshot_sha256, messages_count: agent.state.messages.length },
    tool_calls: toolEvents, evidence_observations: evidenceObservations,
    environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", initial_ledger: {}, final_ledger: finalLedger, final_state_matches_initial: Object.keys(finalLedger).length === 0, real_side_effects: false, network_scope: "bailian_inference_only" },
    timing: { started_at: startedAt, finished_at: timestamp(), duration_ms: Math.max(0, Date.now() - startedMs) },
    usage: { ...usage(agent.state.messages), model_requests: modelRequests, tool_calls: toolCalls },
    cost: { currency: "USD", total_usd: null, status: "provider_response_does_not_supply_cost" },
    attempts: Array.from({ length: Math.max(1, modelRequests) }, (_, index) => ({ attempt: index + 1, outcome: providerFailure ? "failed" : "succeeded", http_status: responseStatuses[index] ?? providerFailure?.http_status ?? null, payload_sha256: payloadHashes[index] ?? null })),
    retry: { max_retries: 0, retries_used: 0 },
    checkpoint: { enabled: true, sequence: completed.offset, state_sha256: completed.state_sha256, prior_event_hash: completed.event_sha256, created_at: completed.created_at },
    failure: { type: identityValid ? providerFailure?.type || null : "identity_mismatch", provider_error_code: providerFailure?.provider_code || null },
    result: { action: candidate?.status || "parse_failure", structured_output: candidate, structured_output_valid: Boolean(candidate), parse_error: parseError, response_sha256: candidate ? sha256(canonical(candidate)) : parseError.response_sha256, raw_provider_response_stored: false },
    redaction: { applied: true, raw_sensitive_response_persisted: false, secret_leakage_detected: secretLeakage },
  };
  atomicJson(tracePath, trace);
  return trace;
}


async function preflight(settings, outputPath) {
  const projection = { contract_type: "candidate_case_projection", contract_version: "3.0.0", case_id: "PREFLIGHT-V3", task: { prompt: "Validate the shared tool protocol.", inputs: { operation: "direct" }, permissions: ["synthetic_data_read"] }, temporal: { as_of: "2026-08-11T00:00:00Z" }, financial_subject: {}, evidence_refs: [], evidence_contract: { registered_record_ids: [], material_record_ids: [], minimum_material_evidence_count: 0 }, status_value_contract: { answer: "schema", "abstain|escalate|reject_action": "null" }, answer_value_schema: { type: "object", additionalProperties: false, required: ["protocol_ok"], properties: { protocol_ok: { type: "boolean" } } }, reason_code_vocabulary: JSON.parse(readFileSync(join(ROOT, "contracts", "reason_codes.v3.json"), "utf8")).codes };
  const results = [];
  for (let index = 0; index < MODELS.length; index += 1) {
    const modelId = MODELS[index]; const collector = createSubmissionCollector(projection); const events = []; const model = modelDefinition(modelId, settings.baseUrl);
    let requests = 0; let responseModelId = null; let failure = null;
    const agent = createPinnedAgentV3({ model, tools: createTools(projection, { snapshot_id: "none", records: [] }, collector, events, {}, new Map()), getApiKey: () => settings.apiKey,
      streamFn: (active, context, options) => { requests += 1; return streamSimple(active, context, { ...options, temperature: 0, maxTokens: 512, timeoutMs: 120000, maxRetries: 0, cacheRetention: "none" }); },
      onPayload: (payload) => normalizePayloadV3(payload, 930000 + index), onResponse: () => {},
      beforeToolCall: async ({ toolCall, args }) => { events.push({ tool_name: toolCall.name, arguments_sha256: sha256(canonical(args)) }); },
    });
    agent.subscribe((event) => { if (event.type === "message_end" && event.message.role === "assistant" && event.message.responseModel) responseModelId = event.message.responseModel; });
    try { await agent.prompt(`${buildRunPromptV3(projection)}\nFor this protocol preflight, read PREFLIGHT-V3 then submit status answer, value {\"protocol_ok\":true}, empty arrays, low uncertainty, and true permission claim.`); } catch (error) { failure = safeError(error); }
    const identity = (responseModelId || modelId) === modelId;
    results.push({ model_id: modelId, response_model_id: responseModelId || modelId, identity_valid: identity, structured_submission_valid: collector.state.accepted, tool_names_hash: sha256(canonical(CONFIG.tools.map((item) => item.name))), model_requests: requests, status: !failure && identity && collector.state.accepted ? "passed" : "blocked", failure_type: failure?.type || null });
  }
  const artifact = { contract_type: "stage3_acceptance_preflight", contract_version: "3.0.0", created_at: timestamp(), endpoint_id: settings.endpointId, harness_config_sha256: fileSha256(CONFIG_PATH), model_manifest_sha256: fileSha256(MODEL_MANIFEST_PATH), counts: { requested: 3, passed: results.filter((item) => item.status === "passed").length, blocked: results.filter((item) => item.status !== "passed").length }, results, credentials_persisted: false, raw_provider_responses_persisted: false };
  atomicJson(outputPath, artifact);
  return artifact;
}


async function main(argv = process.argv.slice(2)) {
  const args = {}; for (let i = 0; i < argv.length; i += 2) args[argv[i]] = argv[i + 1];
  const settings = loadSettings();
  if (args["--preflight"]) { const output = isAbsolute(args["--preflight"]) ? args["--preflight"] : resolve(ROOT, args["--preflight"]); const result = await preflight(settings, output); process.stdout.write(`${JSON.stringify(result.counts)}\n`); return result.counts.passed === 3 ? 0 : 2; }
  if (!args["--plan"] || !args["--output-dir"]) throw new Error("--plan and --output-dir required");
  const planPath = isAbsolute(args["--plan"]) ? args["--plan"] : resolve(ROOT, args["--plan"]); const outputDirectory = isAbsolute(args["--output-dir"]) ? args["--output-dir"] : resolve(ROOT, args["--output-dir"]); const plan = readJson(planPath);
  const core = structuredClone(plan); delete core.plan_sha256; if (sha256(canonical(core)) !== plan.plan_sha256 || plan.run_cap !== 36 || plan.full_matrix_authorized !== false) throw new Error("invalid v3 plan");
  if (settings.endpointId !== plan.authoritative_preflight.endpoint_id) throw new Error("endpoint differs from frozen preflight");
  mkdirSync(join(outputDirectory, "traces"), { recursive: true }); mkdirSync(join(outputDirectory, "checkpoints"), { recursive: true });
  const taskByRun = new Map(plan.tasks.flatMap((task) => task.run_ids.map((id) => [id, task]))); const traces = [];
  for (const row of plan.runs) { const trace = await executeOne({ row, task: taskByRun.get(row.run_id), plan, settings, outputDirectory }); traces.push(trace); process.stdout.write(`${JSON.stringify({ run_id: row.run_id, model_id: row.model_id, status: trace.status, structured: trace.result.structured_output_valid })}\n`); }
  const summary = { contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.0.0", plan_sha256: plan.plan_sha256, counts: { planned: 36, traces: traces.length, succeeded: traces.filter((item) => item.status === "succeeded").length, invalidated: traces.filter((item) => item.status === "invalidated").length, structured: traces.filter((item) => item.result.structured_output_valid).length }, provider_requests: traces.reduce((sum, item) => sum + item.usage.model_requests, 0), cost_usd: null, cost_status: "provider_response_does_not_supply_cost" };
  atomicJson(join(outputDirectory, "runtime-summary.json"), summary); return traces.length === 36 ? 0 : 2;
}


if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) main().then((code) => { process.exitCode = code; }).catch((error) => { process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: safeError(error).type })}\n`); process.exitCode = 2; });
