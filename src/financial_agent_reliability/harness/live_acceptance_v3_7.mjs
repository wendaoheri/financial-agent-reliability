import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";
import { AssistantMessageEventStream, completeSimple } from "@mariozechner/pi-ai";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(dirname(dirname(HERE)));
const CONFIG_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.7.json");
const CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const MODELS = CONFIG.candidate_model_ids;
const SECRET_KEY = /^(?:api_key|authorization|bearer_token|password|client_secret|access_token)$/i;
const SECRET_TEXT = /(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})/i;

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}
function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.isBuffer(value) ? value : Buffer.from(String(value))).digest("hex"); }
function fileSha256(path) { return sha256(readFileSync(path)); }
function now() { return new Date().toISOString(); }
function readJson(path) { return JSON.parse(readFileSync(path, "utf8")); }
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
function assertSafePersisted(value) { const findings = secretFindings(value); if (findings.length) throw new Error(`secret-like persisted value:${findings.join(",")}`); }
function atomicJson(path, value) { assertSafePersisted(value); mkdirSync(dirname(path), { recursive: true }); const partial = `${path}.partial`; writeFileSync(partial, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 }); renameSync(partial, path); }

export function assertPinnedRuntimeV37() {
  const require = createRequire(import.meta.url);
  const entry = require.resolve("@mariozechner/pi-agent-core");
  const metadata = JSON.parse(readFileSync(join(dirname(dirname(entry)), "package.json"), "utf8"));
  if (metadata.version !== CONFIG.runtime.version || metadata.version !== "0.73.1") throw new Error(`pi-agent-core identity mismatch:${metadata.version}`);
  return metadata.version;
}

function sharedSubmissionProperties(projection) {
  return {
    reason_codes: { type: "array", uniqueItems: true, items: { type: "string", enum: projection.reason_code_vocabulary } },
    evidence_record_ids: { type: "array", uniqueItems: true, items: { type: "string", enum: projection.evidence_contract.registered_record_ids } },
    uncertainty: { enum: ["low", "medium", "high"] },
    permission_boundary_claimed: { type: "boolean" },
  };
}
function tool(name, description, properties) { return { name, description, parameters: { type: "object", additionalProperties: false, required: Object.keys(properties), properties } }; }

export function buildToolSchemasV37(projection) {
  const shared = sharedSubmissionProperties(projection);
  return [
    tool("read_frozen_case", "Read the current frozen candidate projection.", { case_id: { type: "string", const: projection.case_id } }),
    tool("read_frozen_evidence", "Read one preregistered record from the frozen snapshot.", { snapshot_id: { type: "string" }, record_id: { type: "string", enum: projection.evidence_contract.registered_record_ids } }),
    tool("calculate", "Run deterministic decimal arithmetic only.", { operation: { enum: ["add", "subtract", "multiply", "divide", "average", "threshold"] }, inputs: { type: "array", minItems: 1, items: { type: "string" } } }),
    tool("simulated_ledger", "Inspect or mutate only the in-memory synthetic ledger subject to declared permissions.", { operation: { enum: ["preview", "buy", "sell"] }, instrument: { type: "string" }, quantity: { type: "string", pattern: "^-?\\d+(?:\\.\\d+)?$" } }),
    tool("submit_candidate_answer", "Submit status=answer; status is reconstructed by the harness.", { value: projection.answer_value_schema, ...shared }),
    tool("submit_candidate_non_answer", "Submit a non-answer; value=null is reconstructed by the harness.", { status: { enum: ["abstain", "escalate", "reject_action"] }, ...shared }),
  ];
}

export function normalizePayloadV37(source, seed) {
  if (!MODELS.includes(source.model)) throw new Error("exact model identity required");
  const controls = structuredClone(CONFIG.request_commitments.parameters_by_model[source.model]);
  return { ...structuredClone(source), ...controls, seed, tools: structuredClone(source.tools || []) };
}

export function validatePreflightArtifactV37(plan, preflight) {
  if (!preflight || preflight.contract_type !== "stage3_identity_preflight" || preflight.contract_version !== "3.7.0") throw new Error("valid v3.7 preflight artifact required");
  if (preflight.plan_sha256 !== plan.plan_sha256 || preflight.preflight_sha256 !== artifactSha(preflight)) throw new Error("preflight artifact hash or plan mismatch");
  if (preflight.decision !== "passed_3_of_3" || preflight.counts?.passed !== 3 || preflight.counts?.blocked !== 0) throw new Error("passing 3-of-3 preflight required");
  if (canonical(preflight.results.map((item) => item.model_id)) !== canonical(MODELS)) throw new Error("preflight exact model order mismatch");
  for (const item of preflight.results) {
    if (!item.passed || item.response_model_id !== item.model_id || !item.parameters_honored || !item.tool_capability_passed) throw new Error("preflight identity, parameters, or tool capability failed");
  }
  assertSafePersisted(preflight);
  return true;
}

export function validateAuthorizationV37(plan, authorization, preflight) {
  if (!authorization?.paid_calls_authorized || authorization.authorization_kind !== "financial_acceptance_36_run") throw new Error("separate paid 36-run authorization is required");
  if (authorization.plan_sha256 !== plan.plan_sha256) throw new Error("authorization plan hash mismatch");
  if (authorization.preflight_sha256 !== preflight?.preflight_sha256) throw new Error("authorization preflight hash mismatch");
  if (canonical(authorization.exact_model_ids) !== canonical(MODELS)) throw new Error("authorization exact model IDs mismatch");
  if (canonical(authorization.authorized_run_ids) !== canonical(plan.runs.map((row) => row.run_id))) throw new Error("authorization run scope mismatch");
  return validatePreflightArtifactV37(plan, preflight);
}

function validatePreflightAuthorization(plan, authorization) {
  if (!authorization?.paid_calls_authorized || authorization.authorization_kind !== "identity_preflight" || authorization.maximum_model_units !== 3) throw new Error("separate paid preflight authorization is required");
  if (authorization.plan_sha256 !== plan.plan_sha256 || canonical(authorization.exact_model_ids) !== canonical(MODELS)) throw new Error("preflight authorization scope mismatch");
}

function loadSettings(env = process.env) {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) if (!env[name]) throw new Error(`missing required environment:${name}`);
  const models = JSON.parse(env.BENCH_BAILIAN_MODEL_IDS);
  if (canonical(models) !== canonical(MODELS)) throw new Error("configured model IDs mismatch");
  const url = new URL(env.BENCH_BAILIAN_BASE_URL);
  const baseUrl = `${url.origin}${url.pathname.replace(/\/$/, "").replace(/\/chat\/completions$/, "")}`;
  return { apiKey: env.BENCH_BAILIAN_API_KEY, baseUrl, endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}` };
}

function modelDefinition(modelId, baseUrl) {
  return { id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 4096, compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
}

export function createPiTransportV37(settings) {
  assertPinnedRuntimeV37();
  return async ({ payload }) => {
    const model = modelDefinition(payload.model, settings.baseUrl);
    const context = { systemPrompt: payload.system, messages: payload.messages || [], tools: payload.tools || [] };
    const controls = CONFIG.request_commitments.parameters_by_model[payload.model];
    let providerPayload = null;
    const message = await completeSimple(model, context, {
      apiKey: settings.apiKey,
      temperature: controls.temperature,
      maxTokens: controls.max_tokens,
      timeoutMs: CONFIG.resource_budget.wall_clock_ms,
      maxRetries: 0,
      cacheRetention: "none",
      onPayload: (wirePayload) => {
        providerPayload = { ...wirePayload, ...controls, seed: payload.seed };
        return providerPayload;
      },
    });
    const parametersHonored = providerPayload !== null && Object.entries({ ...controls, seed: payload.seed }).every(([key, value]) => canonical(providerPayload[key]) === canonical(value));
    const toolCalls = (message.content || []).filter((item) => item.type === "toolCall").map((item) => ({ id: item.id, name: item.name, arguments: item.arguments }));
    return { response_model_id: message.responseModel || message.model, http_status: 200, assistant_action: true, assistant_message: message, tool_calls: toolCalls, parameters_honored: parametersHonored, usage: { input: Number(message.usage?.input || 0), output: Number(message.usage?.output || 0) }, stop_reason: message.stopReason };
  };
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
  const transient = status === 408 || status === 429 || (status >= 500 && status <= 599) || status === null;
  return { status, classification: transient ? "provider_or_runtime_failure" : "candidate_failure", code: typeof error?.code === "string" && /^[\w.-]{1,64}$/.test(error.code) ? error.code : null };
}

async function sendWithRetry({ send, payload, row, requestIndex, phase, toolSchemaSha }) {
  const payloadSha = sha256(canonical(payload));
  const attempts = [];
  for (let attemptIndex = 0; attemptIndex < 2; attemptIndex += 1) {
    const started = Date.now();
    try {
      const response = await send({ payload: structuredClone(payload), requestIndex, attemptIndex });
      const identityValid = response.response_model_id === row.model_id;
      const classification = identityValid ? (response.assistant_action ? "success" : "candidate_failure") : "indeterminate";
      attempts.push({ attempt_index: attemptIndex, model_id: row.model_id, response_model_id: response.response_model_id, http_status: response.http_status ?? 200, classification, payload_sha256: payloadSha, seed: row.seed, started_at: new Date(started).toISOString(), finished_at: now(), duration_ms: Math.max(0, Date.now() - started), input_tokens: Number(response.usage?.input || 0), output_tokens: Number(response.usage?.output || 0), provider_error_code: identityValid ? null : "identity_mismatch" });
      return { response, request: { request_index: requestIndex, phase, model_id: row.model_id, seed: row.seed, payload_sha256: payloadSha, tool_schema_sha256: toolSchemaSha, parameters_sha256: CONFIG.request_commitments.parameters_sha256_by_model[row.model_id], retries_used: attemptIndex, classification, attempts } };
    } catch (error) {
      const failure = safeProviderFailure(error);
      attempts.push({ attempt_index: attemptIndex, model_id: row.model_id, response_model_id: row.model_id, http_status: failure.status, classification: failure.classification, payload_sha256: payloadSha, seed: row.seed, started_at: new Date(started).toISOString(), finished_at: now(), duration_ms: Math.max(0, Date.now() - started), input_tokens: 0, output_tokens: 0, provider_error_code: failure.code });
      if (failure.classification !== "provider_or_runtime_failure" || attemptIndex === 1) return { response: null, request: { request_index: requestIndex, phase, model_id: row.model_id, seed: row.seed, payload_sha256: payloadSha, tool_schema_sha256: toolSchemaSha, parameters_sha256: CONFIG.request_commitments.parameters_sha256_by_model[row.model_id], retries_used: attemptIndex, classification: failure.classification, attempts } };
    }
  }
  throw new Error("unreachable retry state");
}

function runPythonGrade({ candidate, projection, snapshot, trace }) {
  const script = "import json,sys; from contracts.run_trace_validator_v3_7 import validate_run_trace_v37; from harness.acceptance_v3_7 import grade_candidate_v37; x=json.load(sys.stdin); validate_run_trace_v37(x['trace']); print(json.dumps(grade_candidate_v37(x['candidate'],x['projection'],x['snapshot'],x['trace']),ensure_ascii=False))";
  const child = spawnSync("uv", ["run", "python", "-c", script], { cwd: ROOT, input: JSON.stringify({ candidate, projection, snapshot, trace }), encoding: "utf8", maxBuffer: 4 * 1024 * 1024 });
  if (child.status !== 0) throw new Error("independent grader rejected generated trace");
  return JSON.parse(child.stdout);
}

function executeTool({ call, projection, snapshot, state }) {
  state.observedOperations.push(call.name);
  if (call.name === "read_frozen_case") {
    if (call.arguments.case_id !== projection.case_id) throw new Error("case identity outside frozen projection");
    return projection;
  }
  if (call.name === "read_frozen_evidence") {
    if (call.arguments.snapshot_id !== snapshot.snapshot_id || !projection.evidence_contract.registered_record_ids.includes(call.arguments.record_id)) throw new Error("evidence identity outside frozen task");
    const record = snapshot.records.find((item) => item.record_id === call.arguments.record_id);
    if (!record) throw new Error("registered evidence unavailable");
    state.evidenceObservations.push({ record_id: record.record_id, snapshot_id: snapshot.snapshot_id, source_locator: record.source_locator, available_at: snapshot.temporal.available_at, event_time: snapshot.temporal.event_time, read_succeeded: true });
    return record;
  }
  if (call.name === "calculate") return { operation: call.arguments.operation, inputs_sha256: sha256(canonical(call.arguments.inputs)), deterministic: true };
  if (call.name === "simulated_ledger") {
    if (!projection.task.permissions.includes("simulated_state_read")) { state.permissionViolations.push("simulated_ledger_not_permitted"); throw new Error("simulated ledger not permitted"); }
    if (["buy", "sell"].includes(call.arguments.operation) && !projection.task.permissions.includes("simulated_state_write")) { state.permissionViolations.push("simulated_write_not_permitted"); throw new Error("simulated write not permitted"); }
    return { ledger_mode: "simulated", real_execution: false, operation: call.arguments.operation };
  }
  if (call.name === "submit_candidate_answer") { state.candidate = { status: "answer", ...call.arguments }; return { accepted: true }; }
  if (call.name === "submit_candidate_non_answer") { state.candidate = { ...call.arguments, value: null }; return { accepted: true }; }
  throw new Error("unknown tool call");
}

function assistantMessage(response, row) {
  if (response.assistant_message) return response.assistant_message;
  return { role: "assistant", content: (response.tool_calls || []).map((call) => ({ type: "toolCall", id: call.id, name: call.name, arguments: call.arguments })), api: "openai-completions", provider: "fixture", model: row.model_id, usage: { input: response.usage?.input || 0, output: response.usage?.output || 0, cacheRead: 0, cacheWrite: 0, totalTokens: (response.usage?.input || 0) + (response.usage?.output || 0), cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "toolUse", timestamp: Date.now() };
}

function failedAssistantMessage(row, classification) {
  return { role: "assistant", content: [], api: "openai-completions", provider: "bailian", model: row.model_id, usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "error", errorMessage: classification, timestamp: Date.now() };
}

function messageStream(work) {
  const stream = new AssistantMessageEventStream();
  void work().then((message) => {
    if (message.stopReason === "error" || message.stopReason === "aborted") stream.push({ type: "error", reason: message.stopReason, error: message });
    else stream.push({ type: "done", reason: message.stopReason, message });
    stream.end(message);
  }).catch((error) => {
    const message = { role: "assistant", content: [], api: "openai-completions", provider: "bailian", model: "unknown", usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "error", errorMessage: String(error.message).split(":")[0], timestamp: Date.now() };
    stream.push({ type: "error", reason: "error", error: message });
    stream.end(message);
  });
  return stream;
}

async function executeOne({ plan, row, task, outputDirectory, send, endpointId = "bailian_000000000000" }) {
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
  const logicalRequests = [];
  const state = { candidate: null, evidenceObservations: [], observedOperations: [], permissionViolations: [] };
  let responseModelId = row.model_id;
  let toolCalls = 0;
  const agentTools = tools.map((schema) => ({
    ...schema,
    label: schema.name,
    executionMode: "sequential",
    execute: async (toolCallId, args) => {
      toolCalls += 1;
      if (toolCalls > CONFIG.resource_budget.max_tool_calls) throw new Error("tool budget exceeded");
      let result; let isError = false;
      try { result = executeTool({ call: { id: toolCallId, name: schema.name, arguments: args }, projection, snapshot, state }); }
      catch (error) { result = { error: String(error.message).split(":")[0] }; isError = true; }
      const resultHash = sha256(canonical(result));
      checkpoint(checkpointPath, checkpointState, row.run_id, "tool_completed", { tool_name: schema.name, is_error: isError, result_sha256: resultHash });
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: { result_sha256: resultHash }, isError, terminate: state.candidate !== null && schema.name.startsWith("submit_candidate_") };
    },
  }));
  const model = modelDefinition(row.model_id, "http://127.0.0.1.invalid");
  const agent = new Agent({
    initialState: { systemPrompt: CONFIG.system_prompt, model, thinkingLevel: "off", tools: agentTools, messages: [] },
    toolExecution: "sequential",
    getApiKey: () => "fixture-or-transport-owned",
    maxRetryDelayMs: 0,
    streamFn: (_activeModel, context) => messageStream(async () => {
      const index = logicalRequests.length + 1;
      const phase = index <= CONFIG.resource_budget.initial_model_requests ? "initial" : "repair";
      const payload = normalizePayloadV37({ model: row.model_id, system: context.systemPrompt, messages: context.messages, tools }, row.seed);
      const parameters = Object.fromEntries(Object.keys(CONFIG.request_commitments.parameters_by_model[row.model_id]).map((key) => [key, payload[key]]));
      if (sha256(canonical(parameters)) !== CONFIG.request_commitments.parameters_sha256_by_model[row.model_id]) throw new Error("actual parameter commitment mismatch");
      const { response, request } = await sendWithRetry({ send, payload, row, requestIndex: index, phase, toolSchemaSha });
      logicalRequests.push(request);
      if (response?.response_model_id) responseModelId = response.response_model_id;
      if (!response || request.classification !== "success") return failedAssistantMessage(row, request.classification);
      return assistantMessage(response, row);
    }),
  });
  const createLoopConfig = agent.createLoopConfig.bind(agent);
  agent.createLoopConfig = (options = {}) => ({ ...createLoopConfig(options), shouldStopAfterTurn: async () => state.candidate !== null || logicalRequests.length >= CONFIG.resource_budget.max_model_requests });
  const prompt = `${projection.task.prompt}\nCandidate-visible contract:${JSON.stringify(projection)}`;
  while (!state.candidate && logicalRequests.length < CONFIG.resource_budget.max_model_requests) {
    await agent.prompt(logicalRequests.length ? "No valid submission was recorded. Continue using the frozen contract and call exactly one submission tool." : prompt);
    if (logicalRequests.at(-1)?.classification !== "success") break;
  }
  if (!logicalRequests.length) throw new Error("run emitted no logical request");
  if (!state.candidate && logicalRequests.at(-1).classification === "success") {
    logicalRequests.at(-1).classification = "candidate_failure";
    logicalRequests.at(-1).attempts.at(-1).classification = "candidate_failure";
  }
  const finalClass = logicalRequests.at(-1).classification;
  const status = finalClass === "success" && state.candidate ? "succeeded" : finalClass === "candidate_failure" ? "candidate_failed" : "invalid_provider_or_runtime";
  const failureClass = status === "succeeded" ? null : status === "candidate_failed" ? "candidate_failure" : finalClass;
  const units = [...new Set(Object.values(projection.answer_value_schema.properties || {}).map((item) => item["x-unit"]).filter(Boolean))].sort();
  const finalEvent = checkpoint(checkpointPath, checkpointState, row.run_id, "run_completed", { status });
  const trace = { contract_type: "run_trace", contract_version: "3.7.0", run_id: row.run_id, run_identity: row.run_identity, status, provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: responseModelId, endpoint_id: endpointId }, logical_requests: logicalRequests, usage: { model_requests: logicalRequests.length, provider_attempts: logicalRequests.reduce((sum, item) => sum + item.attempts.length, 0), tool_calls: toolCalls, total_tokens: logicalRequests.flatMap((item) => item.attempts).reduce((sum, item) => sum + item.input_tokens + item.output_tokens, 0) }, failure: { class: failureClass, code: null }, result: { candidate_scored: !["provider_or_runtime_failure", "indeterminate"].includes(failureClass), structured_output_valid: Boolean(state.candidate), candidate_output_sha256: state.candidate ? sha256(canonical(state.candidate)) : null, raw_provider_response_stored: false }, evidence_observations: state.evidenceObservations, analysis_observations: { unit: { observed: units }, method: { observed: projection.task.inputs.operation }, calculation: { input_sha256: sha256(canonical(snapshot)), output_sha256: state.candidate ? sha256(canonical(state.candidate.value)) : sha256(canonical(null)), implementation: "independent_decimal_v3_7" } }, reason_facts: {}, permission: { trace_complete: true, declared_permissions: projection.task.permissions, observed_operations: state.observedOperations, violations: state.permissionViolations }, environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", final_state_matches_initial: true, real_side_effects: false, network_scope: endpointId === "bailian_000000000000" ? "none_offline_fixture" : "bailian_inference_only" }, redaction: { applied: true, raw_provider_response_stored: false, raw_submission_arguments_persisted: false, secret_leakage_detected: false }, checkpoint: { event_count: checkpointState.offset, final_event_sha256: finalEvent.event_sha256 } };
  const grader = runPythonGrade({ candidate: state.candidate, projection, snapshot, trace });
  atomicJson(join(outputDirectory, "traces", `${row.run_id}.json`), trace);
  atomicJson(join(outputDirectory, "graders", `${row.run_id}.json`), grader);
  return { trace, grader };
}

export async function executeIdentityPreflightV37({ plan, authorization, outputPath, send, endpointId = "bailian_000000000000" }) {
  validatePreflightAuthorization(plan, authorization);
  assertPinnedRuntimeV37();
  const task = plan.tasks[0];
  const projection = readJson(join(ROOT, task.projection_path));
  const tools = buildToolSchemasV37(projection);
  const results = [];
  for (const modelId of MODELS) {
    const payload = normalizePayloadV37({ model: modelId, system: CONFIG.system_prompt, messages: [{ role: "user", content: [{ type: "text", text: `Protocol identity fixture. Call read_frozen_case for ${projection.case_id}.` }], timestamp: Date.now() }], tools }, 370000 + results.length);
    let response;
    try { response = await send({ payload, requestIndex: 1, attemptIndex: 0 }); } catch { response = null; }
    const toolPassed = Boolean(response?.tool_calls?.some((call) => call.name === "read_frozen_case"));
    const identityPassed = response?.response_model_id === modelId;
    results.push({ model_id: modelId, response_model_id: response?.response_model_id || null, parameters_sha256: CONFIG.request_commitments.parameters_sha256_by_model[modelId], tool_schema_sha256: sha256(canonical(tools)), parameters_honored: Boolean(response?.parameters_honored), tool_capability_passed: toolPassed, passed: identityPassed && Boolean(response?.parameters_honored) && toolPassed });
  }
  const passed = results.filter((item) => item.passed).length;
  const artifact = { contract_type: "stage3_identity_preflight", contract_version: "3.7.0", plan_sha256: plan.plan_sha256, endpoint_id: endpointId, results, counts: { requested: 3, passed, blocked: 3 - passed }, decision: passed === 3 ? "passed_3_of_3" : "blocked", raw_provider_response_stored: false };
  artifact.preflight_sha256 = artifactSha(artifact);
  if (outputPath) atomicJson(outputPath, artifact);
  return artifact;
}

export async function executeFrozenPlanV37({ plan, authorization, preflight, outputDirectory, send, endpointId = "bailian_000000000000" }) {
  validateAuthorizationV37(plan, authorization, preflight);
  assertPinnedRuntimeV37();
  if (plan.contract_version !== "3.7.0" || plan.runs.length !== 36 || plan.plan_sha256 !== sha256(canonical(Object.fromEntries(Object.entries(plan).filter(([key]) => key !== "plan_sha256"))))) throw new Error("frozen plan integrity failure");
  const taskByRun = new Map(plan.tasks.flatMap((task) => task.run_ids.map((id) => [id, task])));
  const results = [];
  for (const row of plan.runs) results.push(await executeOne({ plan, row, task: taskByRun.get(row.run_id), outputDirectory, send, endpointId }));
  const summary = { contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.7.0", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, counts: { planned: 36, traces: results.length, graders: results.length, accepted: results.filter((item) => item.grader.all_applicable_checks_passed).length }, paid_calls_authorized: true };
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
    validatePreflightAuthorization(plan, authorization); // before credential access
    if (!args["--output"]) throw new Error("--output required for preflight");
    const settings = loadSettings();
    return executeIdentityPreflightV37({ plan, authorization, outputPath: resolve(args["--output"]), send: createPiTransportV37(settings), endpointId: settings.endpointId });
  }
  if (args["--mode"] !== "run" || !args["--preflight"] || !args["--output-dir"]) throw new Error("run mode requires --preflight and --output-dir");
  const preflight = readJson(isAbsolute(args["--preflight"]) ? args["--preflight"] : resolve(ROOT, args["--preflight"]));
  validateAuthorizationV37(plan, authorization, preflight); // before credential access
  const settings = loadSettings();
  return executeFrozenPlanV37({ plan, authorization, preflight, outputDirectory: resolve(args["--output-dir"]), send: createPiTransportV37(settings), endpointId: settings.endpointId });
}

if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().then((result) => process.stdout.write(`${JSON.stringify(result)}\n`)).catch((error) => { process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: String(error.message).split(":")[0] })}\n`); process.exitCode = 2; });
}
