import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";
import { AssistantMessageEventStream, completeSimple } from "@mariozechner/pi-ai";

import { buildToolSchemasV37 } from "./live_acceptance_v3_7.mjs";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const CONFIG_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.9.json");
const CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const MODELS = CONFIG.candidate_model_ids;
const SECRET_KEY = /^(?:api_key|authorization|bearer_token|password|client_secret|access_token)$/i;
const SECRET_TEXT = /(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})/i;

export const buildToolSchemasV39 = buildToolSchemasV37;

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}
function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.isBuffer(value) ? value : Buffer.from(String(value))).digest("hex"); }
function fileSha256(path) { return sha256(readFileSync(path)); }
function readJson(path) { return JSON.parse(readFileSync(path, "utf8")); }
function now() { return new Date().toISOString(); }
function artifactSha(value) { const copy = structuredClone(value); delete copy.preflight_sha256; return sha256(canonical(copy)); }

function secretFindings(value, path = "$") {
  const findings = [];
  if (Array.isArray(value)) value.forEach((item, index) => findings.push(...secretFindings(item, `${path}[${index}]`)));
  else if (value && typeof value === "object") for (const [key, child] of Object.entries(value)) {
    const next = `${path}.${key}`;
    if (SECRET_KEY.test(key)) findings.push(next);
    findings.push(...secretFindings(child, next));
  } else if (typeof value === "string" && SECRET_TEXT.test(value)) findings.push(path);
  return findings;
}
function assertSafePersisted(value) {
  const findings = secretFindings(value);
  if (findings.length) throw new Error(`secret-like persisted value:${findings.join(",")}`);
}
function atomicJson(path, value) {
  assertSafePersisted(value);
  mkdirSync(dirname(path), { recursive: true });
  const partial = `${path}.partial`;
  writeFileSync(partial, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  renameSync(partial, path);
}

function gcd(a, b) {
  let left = a < 0n ? -a : a;
  let right = b < 0n ? -b : b;
  while (right) [left, right] = [right, left % right];
  return left || 1n;
}
function rational(numerator, denominator = 1n) {
  if (denominator === 0n) throw new Error("division by zero");
  const sign = denominator < 0n ? -1n : 1n;
  const divisor = gcd(numerator, denominator);
  return { n: sign * numerator / divisor, d: sign * denominator / divisor };
}
function parseDecimal(value) {
  const match = String(value).match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error("invalid decimal input");
  const fraction = match[3] || "";
  const numerator = BigInt(`${match[1]}${match[2]}${fraction}`);
  return rational(numerator, 10n ** BigInt(fraction.length));
}
function add(left, right) { return rational(left.n * right.d + right.n * left.d, left.d * right.d); }
function subtract(left, right) { return rational(left.n * right.d - right.n * left.d, left.d * right.d); }
function multiply(left, right) { return rational(left.n * right.n, left.d * right.d); }
function divide(left, right) { return rational(left.n * right.d, left.d * right.n); }
function roundedScaled(value, digits) {
  const scale = 10n ** BigInt(digits);
  const negative = value.n < 0n;
  const absolute = negative ? -value.n : value.n;
  let quotient = absolute * scale / value.d;
  const remainder = absolute * scale % value.d;
  const twice = remainder * 2n;
  if (twice > value.d || (twice === value.d && quotient % 2n === 1n)) quotient += 1n;
  return negative ? -quotient : quotient;
}
function render(value, digits = 18, fixed = false) {
  const scaled = roundedScaled(value, digits);
  const negative = scaled < 0n;
  const absolute = negative ? -scaled : scaled;
  const scale = 10n ** BigInt(digits);
  const whole = absolute / scale;
  let fraction = String(absolute % scale).padStart(digits, "0");
  if (!fixed) fraction = fraction.replace(/0+$/, "");
  const sign = negative && (whole !== 0n || fraction) ? "-" : "";
  return fraction ? `${sign}${whole}.${fraction}` : `${sign}${whole}`;
}

export function executeDecimalCalculationV39(operation, inputs) {
  if (!Array.isArray(inputs) || inputs.length === 0) throw new Error("calculate inputs required");
  const values = inputs.map(parseDecimal);
  let value;
  if (operation === "add") value = values.reduce(add);
  else if (operation === "subtract") value = values.slice(1).reduce(subtract, values[0]);
  else if (operation === "multiply") value = values.reduce(multiply);
  else if (operation === "divide") value = values.slice(1).reduce(divide, values[0]);
  else if (operation === "average") value = divide(values.reduce(add), rational(BigInt(values.length)));
  else if (operation === "threshold") {
    if (values.length !== 2) throw new Error("threshold requires value and threshold");
    const meets = values[0].n * values[1].d >= values[1].n * values[0].d;
    return { operation, value: render(values[0], 6, true), threshold: String(inputs[1]), meets_threshold: meets };
  } else throw new Error("unsupported calculation operation");
  return { operation, value: operation === "average" ? render(value, 6, true) : render(value) };
}

function ledgerObject(ledger) {
  return Object.fromEntries([...ledger.entries()].filter(([, quantity]) => quantity.n !== 0n).sort(([left], [right]) => left.localeCompare(right)).map(([instrument, quantity]) => [instrument, render(quantity)]));
}
function ledgerRoot(ledger) { return sha256(canonical(ledgerObject(ledger))); }

export function applyLedgerOperationV39(ledger, operation, instrument, quantity) {
  if (!(ledger instanceof Map)) throw new Error("ledger must be a Map");
  const before = ledgerRoot(ledger);
  const current = ledger.get(instrument) || rational(0n);
  const delta = parseDecimal(quantity);
  let next = current;
  if (operation === "buy") next = add(current, delta);
  else if (operation === "sell") next = subtract(current, delta);
  else if (operation !== "preview") throw new Error("unsupported ledger operation");
  if (operation !== "preview") {
    if (next.n === 0n) ledger.delete(instrument);
    else ledger.set(instrument, next);
  }
  return { ledger_mode: "simulated", real_execution: false, operation, instrument, resulting_quantity: render(next), state_before_sha256: before, state_after_sha256: ledgerRoot(ledger) };
}

export function classifyAttemptV39({ requested_model_id, response_model_id, http_status, assistant_action_valid }) {
  if (!Number.isInteger(http_status) || http_status === 408 || http_status === 429 || http_status < 200 || http_status > 299) return "provider_or_runtime_failure";
  if (response_model_id !== requested_model_id) return "indeterminate";
  return assistant_action_valid === true ? "success" : assistant_action_valid === false ? "candidate_failure" : "indeterminate";
}

export function normalizePayloadV39(source, seed) {
  if (!MODELS.includes(source.model)) throw new Error("exact model identity required");
  return { ...structuredClone(source), ...structuredClone(CONFIG.request_commitments.parameters_by_model[source.model]), seed, tools: structuredClone(source.tools || []) };
}

export function assertPinnedRuntimeV39() {
  const require = createRequire(import.meta.url);
  const entry = require.resolve("@mariozechner/pi-agent-core");
  const metadata = JSON.parse(readFileSync(join(dirname(dirname(entry)), "package.json"), "utf8"));
  if (metadata.version !== CONFIG.runtime.version || metadata.version !== "0.73.1") throw new Error(`pi-agent-core identity mismatch:${metadata.version}`);
  return metadata.version;
}

function modelDefinition(modelId, baseUrl) {
  return { id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 4096, compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
}

function loadSettings(env = process.env) {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) if (!env[name]) throw new Error(`missing required environment:${name}`);
  const models = JSON.parse(env.BENCH_BAILIAN_MODEL_IDS);
  if (canonical(models) !== canonical(MODELS)) throw new Error("configured model IDs mismatch");
  const url = new URL(env.BENCH_BAILIAN_BASE_URL);
  const baseUrl = `${url.origin}${url.pathname.replace(/\/$/, "").replace(/\/chat\/completions$/, "")}`;
  return { apiKey: env.BENCH_BAILIAN_API_KEY, baseUrl, endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}` };
}

export function createPiTransportV39(settings) {
  assertPinnedRuntimeV39();
  return async ({ payload }) => {
    const model = modelDefinition(payload.model, settings.baseUrl);
    let providerPayload = null;
    const controls = CONFIG.request_commitments.parameters_by_model[payload.model];
    const message = await completeSimple(model, { systemPrompt: payload.system, messages: payload.messages || [], tools: payload.tools || [] }, {
      apiKey: settings.apiKey, temperature: controls.temperature, maxTokens: controls.max_tokens,
      timeoutMs: CONFIG.resource_budget.wall_clock_ms, maxRetries: 0, cacheRetention: "none",
      onPayload: (wirePayload) => { providerPayload = { ...wirePayload, ...controls, seed: payload.seed }; return providerPayload; },
    });
    const toolCalls = (message.content || []).filter((item) => item.type === "toolCall").map((item) => ({ id: item.id, name: item.name, arguments: item.arguments }));
    return { response_model_id: message.responseModel || message.model, http_status: 200, assistant_action_valid: Array.isArray(message.content), assistant_message: message, tool_calls: toolCalls, parameters_honored: providerPayload !== null && Object.entries({ ...controls, seed: payload.seed }).every(([key, value]) => canonical(providerPayload[key]) === canonical(value)), usage: { input: Number(message.usage?.input || 0), output: Number(message.usage?.output || 0) } };
  };
}

function validatePreflightAuthorization(plan, authorization) {
  if (!authorization?.paid_calls_authorized || authorization.authorization_kind !== "identity_preflight" || authorization.maximum_model_units !== 3) throw new Error("separate paid preflight authorization is required");
  if (authorization.plan_sha256 !== plan.plan_sha256 || canonical(authorization.exact_model_ids) !== canonical(MODELS)) throw new Error("preflight authorization scope mismatch");
}
export function validatePreflightArtifactV39(plan, preflight) {
  if (preflight?.contract_version !== "3.9.0" || preflight.contract_type !== "stage3_identity_preflight" || preflight.preflight_sha256 !== artifactSha(preflight) || preflight.plan_sha256 !== plan.plan_sha256) throw new Error("valid plan-bound v3.9 preflight required");
  if (preflight.decision !== "passed_3_of_3" || preflight.counts?.passed !== 3 || preflight.counts?.blocked !== 0) throw new Error("passing 3-of-3 preflight required");
  if (canonical(preflight.results.map((item) => item.model_id)) !== canonical(MODELS) || preflight.results.some((item) => !item.passed || item.response_model_id !== item.model_id || !item.parameters_honored || !item.tool_capability_passed)) throw new Error("preflight identity, parameters, or tool capability failed");
  assertSafePersisted(preflight);
  return true;
}
export function validateAuthorizationV39(plan, authorization, preflight) {
  if (!authorization?.paid_calls_authorized || authorization.authorization_kind !== "financial_acceptance_36_run") throw new Error("separate paid 36-run authorization is required");
  if (authorization.plan_sha256 !== plan.plan_sha256 || authorization.preflight_sha256 !== preflight?.preflight_sha256) throw new Error("authorization hash mismatch");
  if (canonical(authorization.exact_model_ids) !== canonical(MODELS) || canonical(authorization.authorized_run_ids) !== canonical(plan.runs.map((item) => item.run_id))) throw new Error("authorization scope mismatch");
  return validatePreflightArtifactV39(plan, preflight);
}

function checkpoint(path, state, runId, eventType, payload) {
  const event = { run_id: runId, offset: state.offset, event_type: eventType, payload, previous_event_sha256: state.previous, created_at: now() };
  event.event_sha256 = sha256(canonical(event));
  assertSafePersisted(event);
  appendFileSync(path, `${canonical(event)}\n`, { encoding: "utf8", mode: 0o600 });
  state.offset += 1; state.previous = event.event_sha256;
  return event;
}

function safeProviderFailure(error) {
  const status = Number.isInteger(error?.status) ? error.status : null;
  return { response_model_id: null, http_status: status, assistant_action_valid: false, provider_error_code: typeof error?.code === "string" && /^[\w.-]{1,64}$/.test(error.code) ? error.code : null };
}
async function sendWithRetry({ send, payload, row, requestIndex, phase, toolSchemaSha }) {
  const payloadSha = sha256(canonical(payload));
  const attempts = [];
  let response = null;
  for (let attemptIndex = 0; attemptIndex < 2; attemptIndex += 1) {
    const started = Date.now();
    try { response = await send({ payload: structuredClone(payload), requestIndex, attemptIndex }); }
    catch (error) { response = safeProviderFailure(error); }
    const responseModel = response.response_model_id ?? null;
    const classification = classifyAttemptV39({ requested_model_id: row.model_id, response_model_id: responseModel, http_status: response.http_status ?? null, assistant_action_valid: response.assistant_action_valid === true });
    attempts.push({ attempt_index: attemptIndex, model_id: row.model_id, response_model_id: responseModel, http_status: response.http_status ?? null, assistant_action_valid: response.assistant_action_valid === true, classification, payload_sha256: payloadSha, seed: row.seed, started_at: new Date(started).toISOString(), finished_at: now(), duration_ms: Math.max(0, Date.now() - started), input_tokens: Number(response.usage?.input || 0), output_tokens: Number(response.usage?.output || 0), provider_error_code: response.provider_error_code || (classification === "indeterminate" ? "identity_mismatch" : null) });
    if (classification !== "provider_or_runtime_failure" || attemptIndex === 1) break;
  }
  const classification = attempts.at(-1).classification;
  return { response: classification === "success" ? response : null, request: { request_index: requestIndex, phase, model_id: row.model_id, seed: row.seed, payload_sha256: payloadSha, tool_schema_sha256: toolSchemaSha, parameters_sha256: CONFIG.request_commitments.parameters_sha256_by_model[row.model_id], retries_used: attempts.length - 1, classification, attempts } };
}

function unitBasisSha(projection, record) {
  return sha256(canonical({ answer_schema: projection.answer_value_schema, record_id: record.record_id, source_unit: String(record.payload?.unit ?? "not_applicable") }));
}
function makeToolEvent(sequence, name, args, output, extra = {}) {
  return { sequence, tool_name: name, success: !output.error, input_sha256: sha256(canonical(extra.input_value ?? args)), output_sha256: sha256(canonical(output)), unit_basis_sha256: extra.unit_basis_sha256 ?? null, operation: extra.operation ?? null, record_id: extra.record_id ?? null, implementation: extra.implementation ?? null, state_before_sha256: extra.state_before_sha256 ?? null, state_after_sha256: extra.state_after_sha256 ?? null, ledger_transition: extra.ledger_transition ?? null };
}
function executeTool({ name, args, projection, snapshot, state }) {
  state.observedOperations.push(name);
  let output; let extra = {};
  if (name === "read_frozen_case") {
    if (args.case_id !== projection.case_id) throw new Error("case identity outside frozen projection");
    output = projection;
  } else if (name === "read_frozen_evidence") {
    if (args.snapshot_id !== snapshot.snapshot_id || !projection.evidence_contract.registered_record_ids.includes(args.record_id)) throw new Error("evidence identity outside frozen task");
    output = snapshot.records.find((item) => item.record_id === args.record_id);
    if (!output) throw new Error("registered evidence unavailable");
    state.evidenceObservations.push({ record_id: output.record_id, snapshot_id: snapshot.snapshot_id, source_locator: output.source_locator, available_at: snapshot.temporal.available_at, event_time: snapshot.temporal.event_time, read_succeeded: true });
    extra = { unit_basis_sha256: unitBasisSha(projection, output), operation: "read", record_id: output.record_id };
  } else if (name === "calculate") {
    output = executeDecimalCalculationV39(args.operation, args.inputs);
    extra = { input_value: args.inputs, operation: args.operation, implementation: "decimal_rational_v3_9" };
  } else if (name === "simulated_ledger") {
    if (!projection.task.permissions.includes("simulated_state_read")) { state.permissionViolations.push("simulated_ledger_not_permitted"); throw new Error("simulated ledger not permitted"); }
    if (["buy", "sell"].includes(args.operation) && !projection.task.permissions.includes("simulated_state_write")) { state.permissionViolations.push("simulated_write_not_permitted"); throw new Error("simulated write not permitted"); }
    output = applyLedgerOperationV39(state.ledger, args.operation, args.instrument, args.quantity);
    extra = { operation: args.operation, implementation: "stateful_ledger_v3_9", state_before_sha256: output.state_before_sha256, state_after_sha256: output.state_after_sha256, ledger_transition: { instrument: args.instrument, quantity: args.quantity, resulting_quantity: output.resulting_quantity } };
  } else if (name === "submit_candidate_answer") {
    state.candidate = { status: "answer", ...args }; output = { accepted: true };
  } else if (name === "submit_candidate_non_answer") {
    state.candidate = { ...args, value: null }; output = { accepted: true };
  } else throw new Error("unknown tool call");
  state.toolEvents.push(makeToolEvent(state.toolEvents.length + 1, name, args, output, extra));
  return output;
}

function assistantMessage(response, row) {
  if (response.assistant_message) return response.assistant_message;
  return { role: "assistant", content: (response.tool_calls || []).map((call) => ({ type: "toolCall", id: call.id, name: call.name, arguments: call.arguments })), api: "openai-completions", provider: "fixture", model: row.model_id, usage: { input: response.usage?.input || 0, output: response.usage?.output || 0, cacheRead: 0, cacheWrite: 0, totalTokens: (response.usage?.input || 0) + (response.usage?.output || 0), cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "toolUse", timestamp: Date.now() };
}
function failedAssistantMessage(row, classification) { return { role: "assistant", content: [], api: "openai-completions", provider: "bailian", model: row.model_id, usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "error", errorMessage: classification, timestamp: Date.now() }; }
function messageStream(work) {
  const stream = new AssistantMessageEventStream();
  void work().then((message) => { if (message.stopReason === "error") stream.push({ type: "error", reason: "error", error: message }); else stream.push({ type: "done", reason: message.stopReason, message }); stream.end(message); }).catch((error) => { const message = failedAssistantMessage({ model_id: "unknown" }, String(error.message).split(":")[0]); stream.push({ type: "error", reason: "error", error: message }); stream.end(message); });
  return stream;
}
function runPythonGrade({ candidate, projection, snapshot, trace }) {
  const script = "import json,sys; from contracts.run_trace_validator_v3_9 import validate_run_trace_v39; from harness.acceptance_v3_9 import grade_candidate_v39; x=json.load(sys.stdin); validate_run_trace_v39(x['trace'],scan_companions=[x['candidate']]); print(json.dumps(grade_candidate_v39(x['candidate'],x['projection'],x['snapshot'],x['trace']),ensure_ascii=False))";
  const child = spawnSync("uv", ["run", "python", "-c", script], { cwd: ROOT, input: JSON.stringify({ candidate, projection, snapshot, trace }), encoding: "utf8", maxBuffer: 4 * 1024 * 1024 });
  if (child.status !== 0) throw new Error("independent validator/grader rejected generated artifacts");
  return JSON.parse(child.stdout);
}

async function executeOne({ plan, row, task, outputDirectory, send, endpointId }) {
  const projection = readJson(join(ROOT, task.projection_path));
  const snapshot = readJson(join(ROOT, task.snapshot_path));
  if (fileSha256(join(ROOT, task.projection_path)) !== task.projection_sha256 || fileSha256(join(ROOT, task.snapshot_path)) !== task.snapshot_sha256) throw new Error("frozen input hash mismatch");
  const tools = buildToolSchemasV37(projection);
  const toolSchemaSha = sha256(canonical(tools));
  if (toolSchemaSha !== task.tool_schema_sha256) throw new Error("actual tool schema commitment mismatch");
  const checkpointPath = join(outputDirectory, "checkpoints", `${row.run_id}.jsonl`);
  if (existsSync(checkpointPath)) throw new Error("immutable run already has checkpoint");
  mkdirSync(dirname(checkpointPath), { recursive: true });
  const checkpointState = { offset: 0, previous: "0".repeat(64) };
  checkpoint(checkpointPath, checkpointState, row.run_id, "run_started", { plan_sha256: plan.plan_sha256, tool_schema_sha256: toolSchemaSha });
  const emptyRoot = sha256(canonical({}));
  const state = { candidate: null, evidenceObservations: [], observedOperations: [], permissionViolations: [], ledger: new Map(), toolEvents: [] };
  const logicalRequests = [];
  let responseModelId = row.model_id;
  const agentTools = tools.map((schema) => ({ ...schema, label: schema.name, executionMode: "sequential", execute: async (_id, args) => {
    if (state.toolEvents.length >= CONFIG.resource_budget.max_tool_calls) throw new Error("tool budget exceeded");
    let result; let isError = false;
    try { result = executeTool({ name: schema.name, args, projection, snapshot, state }); }
    catch (error) { result = { error: String(error.message).split(":")[0] }; isError = true; state.toolEvents.push(makeToolEvent(state.toolEvents.length + 1, schema.name, args, result)); }
    checkpoint(checkpointPath, checkpointState, row.run_id, "tool_completed", { tool_name: schema.name, is_error: isError, input_sha256: sha256(canonical(args)), result_sha256: sha256(canonical(result)) });
    return { content: [{ type: "text", text: JSON.stringify(result) }], details: { result_sha256: sha256(canonical(result)) }, isError, terminate: Boolean(state.candidate) && schema.name.startsWith("submit_candidate_") };
  } }));
  const agent = new Agent({ initialState: { systemPrompt: CONFIG.system_prompt, model: modelDefinition(row.model_id, "http://127.0.0.1.invalid"), thinkingLevel: "off", tools: agentTools, messages: [] }, toolExecution: "sequential", getApiKey: () => "transport-owned", maxRetryDelayMs: 0, streamFn: (_model, context) => messageStream(async () => {
    const requestIndex = logicalRequests.length + 1;
    const phase = requestIndex <= CONFIG.resource_budget.initial_model_requests ? "initial" : "repair";
    const payload = normalizePayloadV39({ model: row.model_id, system: context.systemPrompt, messages: context.messages, tools }, row.seed);
    const parameterValues = Object.fromEntries(Object.keys(CONFIG.request_commitments.parameters_by_model[row.model_id]).map((key) => [key, payload[key]]));
    if (sha256(canonical(parameterValues)) !== CONFIG.request_commitments.parameters_sha256_by_model[row.model_id]) throw new Error("actual parameter commitment mismatch");
    const outcome = await sendWithRetry({ send, payload, row, requestIndex, phase, toolSchemaSha });
    logicalRequests.push(outcome.request);
    if (outcome.response?.response_model_id) responseModelId = outcome.response.response_model_id;
    return outcome.response ? assistantMessage(outcome.response, row) : failedAssistantMessage(row, outcome.request.classification);
  }) });
  const createLoopConfig = agent.createLoopConfig.bind(agent);
  agent.createLoopConfig = (options = {}) => ({ ...createLoopConfig(options), shouldStopAfterTurn: async () => Boolean(state.candidate) || logicalRequests.length >= CONFIG.resource_budget.max_model_requests });
  const prompt = `${projection.task.prompt}\nCandidate-visible contract:${JSON.stringify(projection)}`;
  while (!state.candidate && logicalRequests.length < CONFIG.resource_budget.max_model_requests) {
    await agent.prompt(logicalRequests.length ? "No valid submission was recorded. Continue with the frozen inputs and submit exactly once." : prompt);
    if (logicalRequests.at(-1)?.classification !== "success") break;
  }
  if (!logicalRequests.length) throw new Error("run emitted no logical request");
  if (!state.candidate && logicalRequests.at(-1).classification === "success") {
    logicalRequests.at(-1).classification = "candidate_failure";
    logicalRequests.at(-1).attempts.at(-1).classification = "candidate_failure";
    logicalRequests.at(-1).attempts.at(-1).assistant_action_valid = false;
  }
  const finalClass = logicalRequests.at(-1).classification;
  const status = finalClass === "success" && state.candidate ? "succeeded" : finalClass === "candidate_failure" ? "candidate_failed" : "invalid_provider_or_runtime";
  const failureClass = status === "succeeded" ? null : status === "candidate_failed" ? "candidate_failure" : finalClass;
  const finalRoot = ledgerRoot(state.ledger);
  const finalEvent = checkpoint(checkpointPath, checkpointState, row.run_id, "run_completed", { status, final_ledger_sha256: finalRoot });
  const trace = { contract_type: "run_trace", contract_version: "3.9.0", run_id: row.run_id, run_identity: row.run_identity, status, provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: responseModelId, endpoint_id: endpointId }, logical_requests: logicalRequests, usage: { model_requests: logicalRequests.length, provider_attempts: logicalRequests.flatMap((item) => item.attempts).length, tool_calls: state.toolEvents.length, total_tokens: logicalRequests.flatMap((item) => item.attempts).reduce((sum, item) => sum + item.input_tokens + item.output_tokens, 0) }, failure: { class: failureClass, code: null }, result: { candidate_scored: !["provider_or_runtime_failure", "indeterminate"].includes(failureClass), structured_output_valid: Boolean(state.candidate), candidate_output_sha256: state.candidate ? sha256(canonical(state.candidate)) : null, raw_provider_response_stored: false }, evidence_observations: state.evidenceObservations, tool_events: state.toolEvents, reason_facts: {}, permission: { trace_complete: true, declared_permissions: projection.task.permissions, observed_operations: state.observedOperations, violations: state.permissionViolations }, environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", initial_ledger_sha256: emptyRoot, final_ledger_sha256: finalRoot, final_state_matches_initial: emptyRoot === finalRoot, real_side_effects: false, network_scope: endpointId === "bailian_000000000000" ? "none_offline_fixture" : "bailian_inference_only" }, redaction: { applied: true, raw_provider_response_stored: false, raw_submission_arguments_persisted: false, secret_leakage_detected: false }, checkpoint: { event_count: checkpointState.offset, final_event_sha256: finalEvent.event_sha256 } };
  const grader = runPythonGrade({ candidate: state.candidate, projection, snapshot, trace });
  atomicJson(join(outputDirectory, "candidates", `${row.run_id}.json`), state.candidate);
  atomicJson(join(outputDirectory, "traces", `${row.run_id}.json`), trace);
  atomicJson(join(outputDirectory, "graders", `${row.run_id}.json`), grader);
  return { trace, grader };
}

export async function executeIdentityPreflightV39({ plan, authorization, outputPath, send, endpointId = "bailian_000000000000" }) {
  validatePreflightAuthorization(plan, authorization);
  assertPinnedRuntimeV39();
  const task = plan.tasks[0];
  const projection = readJson(join(ROOT, task.projection_path));
  const tools = buildToolSchemasV37(projection);
  const results = [];
  for (const modelId of MODELS) {
    const payload = normalizePayloadV39({ model: modelId, system: CONFIG.system_prompt, messages: [{ role: "user", content: [{ type: "text", text: `Protocol identity fixture. Call read_frozen_case for ${projection.case_id}.` }], timestamp: Date.now() }], tools }, 380000 + results.length);
    let response; try { response = await send({ payload, requestIndex: 1, attemptIndex: 0 }); } catch { response = null; }
    const passed = response?.response_model_id === modelId && response?.parameters_honored === true && response?.tool_calls?.some((call) => call.name === "read_frozen_case");
    results.push({ model_id: modelId, response_model_id: response?.response_model_id || null, parameters_sha256: CONFIG.request_commitments.parameters_sha256_by_model[modelId], tool_schema_sha256: sha256(canonical(tools)), parameters_honored: Boolean(response?.parameters_honored), tool_capability_passed: Boolean(response?.tool_calls?.some((call) => call.name === "read_frozen_case")), passed: Boolean(passed) });
  }
  const count = results.filter((item) => item.passed).length;
  const artifact = { contract_type: "stage3_identity_preflight", contract_version: "3.9.0", plan_sha256: plan.plan_sha256, endpoint_id: endpointId, results, counts: { requested: 3, passed: count, blocked: 3 - count }, decision: count === 3 ? "passed_3_of_3" : "blocked", raw_provider_response_stored: false };
  artifact.preflight_sha256 = artifactSha(artifact);
  if (outputPath) atomicJson(outputPath, artifact);
  return artifact;
}

export async function executeFrozenPlanV39({ plan, authorization, preflight, outputDirectory, send, endpointId = "bailian_000000000000" }) {
  validateAuthorizationV39(plan, authorization, preflight);
  assertPinnedRuntimeV39();
  const copy = structuredClone(plan); delete copy.plan_sha256;
  if (plan.contract_version !== "3.9.0" || plan.runs.length !== 36 || plan.plan_sha256 !== sha256(canonical(copy))) throw new Error("frozen plan integrity failure");
  const taskByRun = new Map(plan.tasks.flatMap((task) => task.run_ids.map((runId) => [runId, task])));
  const results = [];
  for (const row of plan.runs) results.push(await executeOne({ plan, row, task: taskByRun.get(row.run_id), outputDirectory, send, endpointId }));
  const summary = { contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.9.0", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, counts: { planned: 36, candidates: results.length, traces: results.length, graders: results.length, accepted: results.filter((item) => item.grader.all_applicable_checks_passed).length }, paid_calls_authorized: true };
  atomicJson(join(outputDirectory, "runtime-summary.json"), summary);
  return summary;
}

function parseArgs(argv) { const args = {}; for (let index = 0; index < argv.length; index += 2) args[argv[index]] = argv[index + 1]; return args; }
async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (!args["--mode"] || !args["--plan"] || !args["--authorization"]) throw new Error("--mode, --plan, and --authorization required");
  const plan = readJson(isAbsolute(args["--plan"]) ? args["--plan"] : resolve(ROOT, args["--plan"]));
  const authorization = readJson(isAbsolute(args["--authorization"]) ? args["--authorization"] : resolve(ROOT, args["--authorization"]));
  if (args["--mode"] === "preflight") {
    validatePreflightAuthorization(plan, authorization);
    if (!args["--output"]) throw new Error("--output required for preflight");
    const settings = loadSettings();
    return executeIdentityPreflightV39({ plan, authorization, outputPath: resolve(args["--output"]), send: createPiTransportV39(settings), endpointId: settings.endpointId });
  }
  if (args["--mode"] !== "run" || !args["--preflight"] || !args["--output-dir"]) throw new Error("run mode requires --preflight and --output-dir");
  const preflight = readJson(isAbsolute(args["--preflight"]) ? args["--preflight"] : resolve(ROOT, args["--preflight"]));
  validateAuthorizationV39(plan, authorization, preflight);
  const settings = loadSettings();
  return executeFrozenPlanV39({ plan, authorization, preflight, outputDirectory: resolve(args["--output-dir"]), send: createPiTransportV39(settings), endpointId: settings.endpointId });
}

if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().then((result) => process.stdout.write(`${JSON.stringify(result)}\n`)).catch((error) => { process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: String(error.message).split(":")[0] })}\n`); process.exitCode = 2; });
}
