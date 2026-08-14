import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { AssistantMessageEventStream, streamSimple } from "@mariozechner/pi-ai";

import { calculateV3, createSubmissionCollector } from "./live_acceptance_v3.mjs";
import { createPinnedAgentV35 } from "./pi_runtime_v3_5.mjs";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(dirname(dirname(HERE)));
const CONFIG_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.5.json");
const CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const BASE_CONFIG = JSON.parse(readFileSync(join(ROOT, "contracts", "run_trace_harness_config.v3.json"), "utf8"));
const WIRE = JSON.parse(readFileSync(join(ROOT, "contracts", "candidate_submission_wire_contract.v3.4.json"), "utf8"));
const MODEL_MANIFEST_PATH = join(ROOT, "contracts", "model_manifest.frozen.v2.json");
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
function readJson(path) { return JSON.parse(readFileSync(path, "utf8")); }


function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.partial`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  renameSync(temporary, path);
}


function loadSettings(env = process.env) {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) {
    if (!env[name]) throw new Error(`missing required environment: ${name}`);
  }
  let models;
  try { models = JSON.parse(env.BENCH_BAILIAN_MODEL_IDS); }
  catch { models = env.BENCH_BAILIAN_MODEL_IDS.split(",").map((item) => item.trim()).filter(Boolean); }
  if (!Array.isArray(models) || canonical(models) !== canonical(MODELS)) throw new Error("BENCH_BAILIAN_MODEL_IDS does not match exact frozen IDs");
  const url = new URL(env.BENCH_BAILIAN_BASE_URL);
  let path = url.pathname.replace(/\/$/, "");
  if (path.endsWith("/chat/completions")) path = path.slice(0, -"/chat/completions".length);
  return {
    apiKey: env.BENCH_BAILIAN_API_KEY,
    configuredBaseUrl: env.BENCH_BAILIAN_BASE_URL,
    baseUrl: `${url.origin}${path}`,
    endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}`,
  };
}


export function normalizePayloadV35(source, seed) {
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


function descriptionSchema(source, description) {
  const schema = structuredClone(source);
  schema.description = description;
  if (schema.type === "object") {
    for (const [name, child] of Object.entries(schema.properties || {})) {
      if (!child.description) child.description = `Required case-visible answer field: ${name}.`;
    }
  }
  return schema;
}


function sharedSubmissionProperties(projection) {
  return {
    reason_codes: {
      type: "array",
      description: "Zero or more codes selected only from the candidate-visible global reason-code vocabulary.",
      items: { type: "string", enum: projection.reason_code_vocabulary },
    },
    evidence_record_ids: {
      type: "array",
      description: "Candidate-visible evidence record IDs actually read and materially supporting the result.",
      items: projection.evidence_contract.registered_record_ids.length
        ? { type: "string", enum: projection.evidence_contract.registered_record_ids }
        : { type: "string" },
    },
    uncertainty: {
      type: "string",
      description: "Calibrated uncertainty of the submitted result.",
      enum: ["low", "medium", "high"],
    },
    permission_boundary_claimed: {
      type: "boolean",
      description: "Diagnostic self-report only; actual permission grading uses the tool trace and environment state.",
    },
  };
}


export function buildAnswerSchemaV35(projection) {
  return {
    type: "object",
    additionalProperties: false,
    required: ["value", "reason_codes", "evidence_record_ids", "uncertainty", "permission_boundary_claimed"],
    properties: {
      value: descriptionSchema(projection.answer_value_schema, "Final answer value; it must match the case-visible answer_value_schema exactly, including units represented by its fields."),
      ...sharedSubmissionProperties(projection),
    },
  };
}


export function buildNonAnswerSchemaV35(projection) {
  return {
    type: "object",
    additionalProperties: false,
    required: ["status", "reason_codes", "evidence_record_ids", "uncertainty", "permission_boundary_claimed"],
    properties: {
      status: {
        type: "string",
        description: "Non-answer action selected from abstain, escalate, or reject_action.",
        enum: ["abstain", "escalate", "reject_action"],
      },
      ...sharedSubmissionProperties(projection),
    },
  };
}


export function buildRunPromptV35(projection) {
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
    "For status answer, call submit_candidate_answer exactly once with value matching answer_value_schema.",
    "For abstain, escalate, or reject_action, call submit_candidate_non_answer exactly once; that tool has no value field and the harness records value=null.",
    `Candidate-visible contract: ${JSON.stringify(visible)}`,
  ].join("\n");
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
function render(value, decimals = 6) { const scale = 10n ** BigInt(decimals); const negative = value.numerator < 0n; const absolute = negative ? -value.numerator : value.numerator; let quotient = absolute * scale / value.denominator; const remainder = absolute * scale % value.denominator; if (remainder * 2n > value.denominator || (remainder * 2n === value.denominator && quotient % 2n === 1n)) quotient += 1n; const whole = quotient / scale; const fraction = String(quotient % scale).padStart(decimals, "0").replace(/0+$/, ""); return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`; }
function textResult(value, details = {}) { return { content: [{ type: "text", text: JSON.stringify(value) }], details }; }


function createTools(projection, snapshot, collector, evidenceObservations, ledger) {
  const definitions = Object.fromEntries(BASE_CONFIG.tools.map((item) => [item.name, item]));
  const allowed = new Set(projection.evidence_contract.registered_record_ids);
  const wrap = (name, description, parameters, execute) => ({ name, label: name, description, parameters, executionMode: "sequential", execute });
  return [
    wrap("read_frozen_case", definitions.read_frozen_case.description, definitions.read_frozen_case.parameters, async (_id, args) => {
      if (args.case_id !== projection.case_id) throw new Error("case identity outside current projection");
      return textResult(projection, { case_id_sha256: sha256(args.case_id) });
    }),
    wrap("read_frozen_evidence", definitions.read_frozen_evidence.description, definitions.read_frozen_evidence.parameters, async (_id, args) => {
      if (!allowed.has(args.record_id) || snapshot.snapshot_id !== args.snapshot_id) throw new Error("evidence identity not registered");
      const record = snapshot.records.find((item) => item.record_id === args.record_id);
      if (!record) throw new Error("registered record unavailable");
      evidenceObservations[record.record_id] = { available_at: snapshot.temporal.available_at_cutoff || projection.temporal.available_at_cutoff };
      return textResult({ snapshot_id: snapshot.snapshot_id, temporal: snapshot.temporal, record }, { record_id_sha256: sha256(record.record_id) });
    }),
    wrap("calculate", definitions.calculate.description, definitions.calculate.parameters, async (_id, args) => textResult(calculateV3(args.operation, args.inputs))),
    wrap("simulated_ledger", definitions.simulated_ledger.description, definitions.simulated_ledger.parameters, async (_id, args) => {
      if (!projection.task.permissions.includes("simulated_state_read")) throw new Error("simulated ledger not permitted");
      if (["buy", "sell"].includes(args.operation) && !projection.task.permissions.includes("simulated_state_write")) throw new Error("simulated state write not permitted");
      const current = ledger.get(args.instrument) || rational(0n, 1n);
      const quantity = asDecimal(args.quantity);
      const signed = args.operation === "sell" ? rational(-quantity.numerator, quantity.denominator) : quantity;
      const next = args.operation === "preview" ? current : add(current, signed);
      if (args.operation !== "preview") ledger.set(args.instrument, next);
      return textResult({ ledger_mode: "simulated", operation: args.operation, resulting_quantity: render(next), real_execution: false });
    }),
    wrap(WIRE.tools.answer.name, WIRE.tools.answer.description, buildAnswerSchemaV35(projection), async (id, args) => collector.execute(id, { status: "answer", ...args })),
    wrap(WIRE.tools.non_answer.name, WIRE.tools.non_answer.description, buildNonAnswerSchemaV35(projection), async (id, args) => collector.execute(id, { ...args, value: null })),
  ];
}


function modelDefinition(modelId, baseUrl) {
  return {
    id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: CONFIG.resource_budget.max_output_tokens,
    compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false },
  };
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
  if (/budget/i.test(String(error?.message || ""))) type = "budget_exceeded";
  else if (status === 401) type = "authentication_failed";
  else if (status === 403) type = "permission_denied";
  else if (status === 429) type = "rate_limited";
  else if (status && status < 500) type = "provider_rejected_request";
  return { type, http_status: status, provider_code: typeof error?.code === "string" && /^[\w.-]{1,64}$/.test(error.code) ? error.code : null };
}


function checkpoint(path, runId, state, type, payload) {
  const event = { run_id: runId, offset: state.offset, event_type: type, payload, previous_event_sha256: state.previous, state_sha256: sha256(canonical(payload)), created_at: timestamp() };
  event.event_sha256 = sha256(canonical(event));
  appendFileSync(path, `${canonical(event)}\n`, { encoding: "utf8", mode: 0o600 });
  state.offset += 1;
  state.previous = event.event_sha256;
  return event;
}


function usage(messages) {
  const result = { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
  for (const message of messages) if (message.role === "assistant") {
    result.input_tokens += Number(message.usage?.input || 0);
    result.output_tokens += Number(message.usage?.output || 0);
    result.total_tokens += Number(message.usage?.totalTokens || 0);
  }
  return result;
}


function redactedArguments(toolName, args) {
  if ([WIRE.tools.answer.name, WIRE.tools.non_answer.name].includes(toolName)) return { submission_sha256: sha256(canonical(args)) };
  if (toolName === "read_frozen_case") return { case_id_sha256: sha256(String(args.case_id)) };
  if (toolName === "read_frozen_evidence") return { snapshot_id_sha256: sha256(String(args.snapshot_id)), record_id_sha256: sha256(String(args.record_id)) };
  if (toolName === "simulated_ledger") return { operation: args.operation, instrument_sha256: sha256(String(args.instrument)), quantity_sha256: sha256(String(args.quantity)) };
  return structuredClone(args);
}


async function executeOne({ row, task, plan, settings, outputDirectory }) {
  const tracePath = join(outputDirectory, "traces", `${row.run_id}.json`);
  if (existsSync(tracePath)) return readJson(tracePath);
  const projection = readJson(join(ROOT, task.projection_path));
  const snapshot = readJson(join(ROOT, task.snapshot_path));
  if (fileSha256(join(ROOT, task.projection_path)) !== task.projection_sha256 || fileSha256(join(ROOT, task.snapshot_path)) !== task.snapshot_sha256) throw new Error("frozen v3.5 input drift");
  const checkpointPath = join(outputDirectory, "checkpoints", `${row.run_id}.jsonl`);
  mkdirSync(dirname(checkpointPath), { recursive: true });
  if (existsSync(checkpointPath)) throw new Error("partial checkpoint requires explicit diagnostic; run IDs are immutable");
  const checkpointState = { offset: 0, previous: "0".repeat(64) };
  checkpoint(checkpointPath, row.run_id, checkpointState, "run_started", { plan_sha256: plan.plan_sha256, projection_sha256: task.projection_sha256, snapshot_sha256: task.snapshot_sha256 });
  const startedAt = timestamp();
  const startedMs = Date.now();
  const collector = createSubmissionCollector(projection);
  const toolEvents = [];
  const evidenceObservations = {};
  const ledger = new Map();
  const tools = createTools(projection, snapshot, collector, evidenceObservations, ledger);
  const model = modelDefinition(row.model_id, settings.baseUrl);
  let modelRequests = 0;
  let phaseRequests = 0;
  let phase = "initial";
  let phaseLimit = CONFIG.resource_budget.initial_model_requests;
  let repairRounds = 0;
  let validatedToolCalls = 0;
  let responseModelId = null;
  let providerFailure = null;
  const payloadHashes = [];
  const responseStatuses = [];
  const agent = createPinnedAgentV35({
    model,
    tools,
    getApiKey: () => settings.apiKey,
    streamFn: (activeModel, context, options) => {
      modelRequests += 1;
      phaseRequests += 1;
      if (modelRequests > CONFIG.resource_budget.max_model_requests) {
        providerFailure = { type: "budget_exceeded", http_status: null, provider_code: null };
        return localErrorStream(activeModel, "budget_exceeded");
      }
      return streamSimple(activeModel, context, { ...options, temperature: 0, maxTokens: CONFIG.resource_budget.max_output_tokens, timeoutMs: CONFIG.resource_budget.wall_clock_ms, maxRetries: 0, cacheRetention: "none" });
    },
    onPayload: (payload) => {
      const normalized = normalizePayloadV35(payload, row.seed);
      if (canonical(normalized.tools.map((item) => item.function.name)) !== canonical(CONFIG.tool_names)) throw new Error("tool schema order changed");
      payloadHashes.push(sha256(canonical(normalized)));
      return normalized;
    },
    onResponse: (response) => responseStatuses.push(Number(response.status)),
    beforeToolCall: async ({ toolCall, args }) => {
      validatedToolCalls += 1;
      if (validatedToolCalls > CONFIG.resource_budget.max_tool_calls) return { block: true, reason: "tool call budget exceeded" };
      toolEvents.push({ event: "start", tool_call_id: toolCall.id, tool_name: toolCall.name, arguments: redactedArguments(toolCall.name, args), started_at: timestamp() });
      return undefined;
    },
    shouldStopAfterTurn: async () => collector.state.accepted || phaseRequests >= phaseLimit,
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
  try {
    await agent.prompt(buildRunPromptV35(projection));
    if (!collector.state.accepted && !providerFailure) {
      repairRounds = 1;
      phase = "repair";
      phaseRequests = 0;
      phaseLimit = CONFIG.resource_budget.repair_model_requests;
      await agent.prompt("No valid final submission has been recorded. Use the same candidate-visible contract: call submit_candidate_answer for answer, or submit_candidate_non_answer for abstain, escalate, or reject_action. Do not infer hidden expected values.");
    }
  } catch (error) {
    providerFailure = safeError(error);
  } finally {
    clearTimeout(timer);
  }
  const identityValid = (responseModelId || row.model_id) === row.model_id;
  const candidate = collector.state.candidate;
  const finalText = [...agent.state.messages].reverse().find((item) => item.role === "assistant")?.content?.filter((item) => item.type === "text").map((item) => item.text).join("") || "";
  const secretLeakage = [settings.apiKey, settings.configuredBaseUrl].filter(Boolean).some((value) => finalText.includes(value));
  const parseError = candidate ? null : (collector.state.lastError || { category: finalText.trim() ? "invalid_json" : "empty_output", path: "/", response_sha256: sha256(finalText) });
  const status = !identityValid ? "invalidated" : providerFailure ? "failed" : "succeeded";
  const completed = checkpoint(checkpointPath, row.run_id, checkpointState, "run_completed", { status, structured_result_valid: Boolean(candidate), parse_error_category: parseError?.category || null });
  const finalLedger = Object.fromEntries([...ledger.entries()].map(([key, value]) => [key, render(value)]));
  const trace = {
    contract_type: "run_trace", contract_version: "3.5.0", run_id: row.run_id, run_identity: row.run_identity, status,
    provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: responseModelId || row.model_id, endpoint_id: settings.endpointId, model_manifest_sha256: fileSha256(MODEL_MANIFEST_PATH) },
    request: { parameters: { temperature: 0, top_p: 1, max_tokens: CONFIG.resource_budget.max_output_tokens, seed: row.seed, stream: true, tool_stream: false, parallel_tool_calls: false, enable_thinking: row.model_id === "qwen3.8-max" ? false : null }, tool_choice: "auto", payload_sha256s: payloadHashes, sdk_retries: 0 },
    preflight: { performed: true, identity_match: identityValid, fallback_detected: !identityValid, fallback_attempted: false, parameters_honored: !providerFailure, valid: identityValid && !providerFailure, authoritative_preflight_sha256: plan.authoritative_preflight.sha256 },
    context: { system_prompt_sha256: sha256(CONFIG.system_prompt), tool_schema_sha256: sha256(canonical(tools.map((item) => ({ name: item.name, description: item.description, parameters: item.parameters })))), candidate_projection_sha256: task.projection_sha256, frozen_snapshot_sha256: task.snapshot_sha256, messages_count: agent.state.messages.length },
    tool_calls: toolEvents, evidence_observations: evidenceObservations,
    environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", initial_ledger: {}, final_ledger: finalLedger, final_state_matches_initial: Object.keys(finalLedger).length === 0, real_side_effects: false, network_scope: "bailian_inference_only" },
    timing: { started_at: startedAt, finished_at: timestamp(), duration_ms: Math.max(0, Date.now() - startedMs) },
    usage: { ...usage(agent.state.messages), model_requests: modelRequests, tool_calls: validatedToolCalls },
    cost: { currency: "USD", total_usd: null, status: "provider_response_does_not_supply_cost" },
    attempts: Array.from({ length: Math.max(1, modelRequests) }, (_, index) => ({ attempt: index + 1, outcome: providerFailure ? "failed" : "succeeded", http_status: responseStatuses[index] ?? providerFailure?.http_status ?? null, payload_sha256: payloadHashes[index] ?? null })),
    retry: { max_retries: 0, retries_used: 0, repair_rounds_used: repairRounds, initial_requests: phase === "initial" ? phaseRequests : modelRequests - phaseRequests, repair_requests: phase === "repair" ? phaseRequests : 0 },
    checkpoint: { enabled: true, sequence: completed.offset, state_sha256: completed.state_sha256, prior_event_hash: completed.event_sha256, created_at: completed.created_at },
    failure: { type: identityValid ? providerFailure?.type || null : "identity_mismatch", provider_error_code: providerFailure?.provider_code || null },
    result: { action: candidate?.status || "parse_failure", structured_output: candidate, structured_output_valid: Boolean(candidate), parse_error: parseError, response_sha256: candidate ? sha256(canonical(candidate)) : parseError.response_sha256, raw_provider_response_stored: false },
    redaction: { applied: true, raw_sensitive_response_persisted: false, raw_submission_arguments_persisted: false, secret_leakage_detected: secretLeakage },
  };
  atomicJson(tracePath, trace);
  return trace;
}


async function main(argv = process.argv.slice(2)) {
  const args = {};
  for (let index = 0; index < argv.length; index += 2) args[argv[index]] = argv[index + 1];
  const settings = loadSettings();
  if (!args["--plan"] || !args["--output-dir"]) throw new Error("--plan and --output-dir required");
  const planPath = isAbsolute(args["--plan"]) ? args["--plan"] : resolve(ROOT, args["--plan"]);
  const outputDirectory = isAbsolute(args["--output-dir"]) ? args["--output-dir"] : resolve(ROOT, args["--output-dir"]);
  const plan = readJson(planPath);
  const core = structuredClone(plan);
  delete core.plan_sha256;
  if (sha256(canonical(core)) !== plan.plan_sha256 || plan.run_cap !== 36 || plan.full_matrix_authorized !== false || plan.contract_version !== "3.5.0") throw new Error("invalid v3.5 plan");
  if (settings.endpointId !== plan.authoritative_preflight.endpoint_id) throw new Error("endpoint differs from frozen preflight");
  mkdirSync(join(outputDirectory, "traces"), { recursive: true });
  mkdirSync(join(outputDirectory, "checkpoints"), { recursive: true });
  const taskByRun = new Map(plan.tasks.flatMap((task) => task.run_ids.map((id) => [id, task])));
  const traces = [];
  for (const row of plan.runs) {
    const trace = await executeOne({ row, task: taskByRun.get(row.run_id), plan, settings, outputDirectory });
    traces.push(trace);
    process.stdout.write(`${JSON.stringify({ run_id: row.run_id, model_id: row.model_id, status: trace.status, structured: trace.result.structured_output_valid })}\n`);
  }
  const summary = {
    contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.5.0", plan_sha256: plan.plan_sha256,
    counts: { planned: 36, traces: traces.length, succeeded: traces.filter((item) => item.status === "succeeded").length, failed: traces.filter((item) => item.status === "failed").length, invalidated: traces.filter((item) => item.status === "invalidated").length, structured: traces.filter((item) => item.result.structured_output_valid).length },
    provider_requests: traces.reduce((sum, item) => sum + item.usage.model_requests, 0), cost_usd: null, cost_status: "provider_response_does_not_supply_cost",
  };
  atomicJson(join(outputDirectory, "runtime-summary.json"), summary);
  return traces.length === 36 ? 0 : 2;
}


if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().then((code) => { process.exitCode = code; }).catch((error) => {
    process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: safeError(error).type })}\n`);
    process.exitCode = 2;
  });
}
