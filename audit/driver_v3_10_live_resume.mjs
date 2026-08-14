// PER-59 resumable execution driver for the frozen v3.10 first-round 270 runs.
//
// Why this driver exists: harness/live_acceptance_v3_10.mjs is part of the
// frozen v3.10 contract bundle (SHA-256 b49e8ea8...) and must not be modified.
// Its executeFrozenPlanV310() executes all 270 first-round units in one
// process and refuses to touch a run_id whose checkpoint already exists, so a
// 270-unit (~2h) batch could never survive an interruption. This driver
// imports the frozen module UNMODIFIED and wraps its per-run semantics with
// checkpoint/resume orchestration:
//   - a run whose trace/grader/candidate/checkpoint artifacts are all present
//     and whose checkpoint hash chain verifies to a run_completed terminal
//     event is counted as finalized and skipped (artifacts untouched);
//   - a run with any partial/inconsistent artifact state is a HARD STOP
//     (invalidation is reported, never silently replaced: no_post_hoc_selection);
//   - pending runs execute with the exact frozen per-run logic.
// Per-run traces are still validated by the frozen independent validator and
// graded by the frozen grader in a separate Python process, so any divergence
// in this driver's replication is rejected downstream.

import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";
import { AssistantMessageEventStream } from "@mariozechner/pi-ai";

import {
  applyLedgerOperationV310,
  assertPinnedRuntimeV310,
  buildToolSchemasV310,
  classifyAttemptV310,
  createPiTransportV310,
  executeDecimalCalculationV310,
  firstRoundRunsV310,
  normalizePayloadV310,
  validateAuthorizationV310,
} from "../harness/live_acceptance_v3_10.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const CONFIG = JSON.parse(readFileSync(join(ROOT, "contracts", "run_trace_harness_config.v3.10.json"), "utf8"));
const MODELS = CONFIG.candidate_model_ids;
const SECRET_KEY = /^(?:api_key|authorization|bearer_token|password|client_secret|access_token)$/i;
const SECRET_TEXT = /(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})/i;

// --- helpers replicated byte-for-byte from the frozen harness ---------------
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

function checkpoint(path, state, runId, eventType, payload) {
  const event = { run_id: runId, offset: state.offset, event_type: eventType, payload, previous_event_sha256: state.previous, created_at: now() };
  event.event_sha256 = sha256(canonical(event));
  assertSafePersisted(event);
  appendFileSync(path, `${canonical(event)}\n`, { encoding: "utf8", mode: 0o600 });
  state.offset += 1; state.previous = event.event_sha256;
  return event;
}

function modelDefinition(modelId, baseUrl) {
  return { id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens: 4096, compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
}

export function loadSettingsDriver(env = process.env) {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) if (!env[name]) throw new Error(`missing required environment:${name}`);
  const models = JSON.parse(env.BENCH_BAILIAN_MODEL_IDS);
  if (canonical(models) !== canonical(MODELS)) throw new Error("configured model IDs mismatch");
  const url = new URL(env.BENCH_BAILIAN_BASE_URL);
  const baseUrl = `${url.origin}${url.pathname.replace(/\/$/, "").replace(/\/chat\/completions$/, "")}`;
  return { apiKey: env.BENCH_BAILIAN_API_KEY, baseUrl, endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}` };
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
    const classification = classifyAttemptV310({ requested_model_id: row.model_id, response_model_id: responseModel, http_status: response.http_status ?? null, assistant_action_valid: response.assistant_action_valid === true });
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
    output = executeDecimalCalculationV310(args.operation, args.inputs);
    extra = { input_value: args.inputs, operation: args.operation, implementation: "decimal_rational_v3_10" };
  } else if (name === "simulated_ledger") {
    if (!projection.task.permissions.includes("simulated_state_read")) { state.permissionViolations.push("simulated_ledger_not_permitted"); throw new Error("simulated ledger not permitted"); }
    if (["buy", "sell"].includes(args.operation) && !projection.task.permissions.includes("simulated_state_write")) { state.permissionViolations.push("simulated_write_not_permitted"); throw new Error("simulated write not permitted"); }
    output = applyLedgerOperationV310(state.ledger, args.operation, args.instrument, args.quantity);
    extra = { operation: args.operation, implementation: "stateful_ledger_v3_10", state_before_sha256: output.state_before_sha256, state_after_sha256: output.state_after_sha256, ledger_transition: { instrument: args.instrument, quantity: args.quantity, resulting_quantity: output.resulting_quantity } };
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
function runPythonGrade({ candidate, projection, snapshot, trace }, diagnostics = null) {
  const script = "import json,sys; from contracts.run_trace_validator_v3_10 import validate_run_trace_v310; from harness.acceptance_v3_10 import grade_candidate_v310; x=json.load(sys.stdin); validate_run_trace_v310(x['trace'],scan_companions=[x['candidate']]); print(json.dumps(grade_candidate_v310(x['candidate'],x['projection'],x['snapshot'],x['trace']),ensure_ascii=False))";
  const child = spawnSync("uv", ["run", "python", "-c", script], { cwd: ROOT, input: JSON.stringify({ candidate, projection, snapshot, trace }), encoding: "utf8", maxBuffer: 4 * 1024 * 1024 });
  if (child.status !== 0) {
    // persist the full subprocess transcript so the failure is diagnosable
    // without re-executing the (already consumed) run identity
    if (diagnostics) {
      try {
        const redact = (text) => String(text).replace(new RegExp(SECRET_TEXT.source, "gi"), "[REDACTED]");
        atomicJson(join(diagnostics.outputDirectory, "grading-failures", `${diagnostics.runId}.json`), {
          run_id: diagnostics.runId, exit_status: child.status, signal: child.signal ?? null,
          stderr: redact(child.stderr || "").slice(-65536), stdout_tail: redact(child.stdout || "").slice(-4096), created_at: now(),
        });
      } catch { /* diagnostic persistence must never mask the hard stop */ }
    }
    throw new Error(`independent validator/grader rejected generated artifacts:${(child.stderr || "").trim().split("\n").slice(-3).join(" | ")}`);
  }
  return JSON.parse(child.stdout);
}

// --- resume verification -----------------------------------------------------
export function verifyCheckpointChain(checkpointPath, expectedRunId) {
  const lines = readFileSync(checkpointPath, "utf8").split("\n").filter((line) => line.length > 0);
  if (!lines.length) return { valid: false, reason: "empty checkpoint", events: [] };
  let previous = "0".repeat(64);
  const events = [];
  for (const [index, line] of lines.entries()) {
    let event;
    try { event = JSON.parse(line); } catch { return { valid: false, reason: `unparseable event at offset ${index}`, events }; }
    const recorded = event.event_sha256;
    const recomputed = sha256(canonical({ ...event, event_sha256: undefined }));
    // canonical() drops undefined-valued keys via JSON.stringify, matching the
    // frozen hashing order (hash computed before the field was attached).
    if (recomputed !== recorded) return { valid: false, reason: `hash mismatch at offset ${index}`, events };
    if (event.offset !== index) return { valid: false, reason: `offset gap at offset ${index}`, events };
    if (event.previous_event_sha256 !== previous) return { valid: false, reason: `chain break at offset ${index}`, events };
    if (event.run_id !== expectedRunId) return { valid: false, reason: `run id mismatch at offset ${index}`, events };
    previous = recorded;
    events.push(event);
  }
  return { valid: true, events };
}

export function finalizedState(outputDirectory, runId) {
  const paths = {
    trace: join(outputDirectory, "traces", `${runId}.json`),
    grader: join(outputDirectory, "graders", `${runId}.json`),
    candidate: join(outputDirectory, "candidates", `${runId}.json`),
    checkpoint: join(outputDirectory, "checkpoints", `${runId}.jsonl`),
  };
  const any = Object.values(paths).some((path) => existsSync(path));
  if (!any) return "pending";
  // the checkpoint ledger is the authority on whether the run started; a
  // started-but-uncompleted chain is a partial (interrupted) unit and must
  // hard stop rather than be silently re-executed.
  let chain;
  if (existsSync(paths.checkpoint)) {
    chain = verifyCheckpointChain(paths.checkpoint, runId);
    if (!chain.valid || chain.events.at(-1).event_type !== "run_completed") return "partial";
  } else return "inconsistent";
  const present = Object.values(paths).every((path) => existsSync(path));
  if (!present) return "inconsistent";
  let trace;
  try { trace = readJson(paths.trace); } catch { return "inconsistent"; }
  try { readJson(paths.grader); } catch { return "inconsistent"; }
  const terminal = chain.events.at(-1);
  if (trace.run_id !== runId) return "inconsistent";
  if (trace.checkpoint?.event_count !== chain.events.length) return "inconsistent";
  if (trace.checkpoint?.final_event_sha256 !== terminal.event_sha256) return "inconsistent";
  return "finalized";
}

// --- per-run execution (frozen executeOne semantics) --------------------------
async function executeOne({ plan, row, task, outputDirectory, send, endpointId }) {
  const projection = readJson(join(ROOT, task.projection_path));
  const snapshot = readJson(join(ROOT, task.snapshot_path));
  if (fileSha256(join(ROOT, task.projection_path)) !== task.projection_sha256 || fileSha256(join(ROOT, task.snapshot_path)) !== task.snapshot_sha256) throw new Error("frozen input hash mismatch");
  const tools = buildToolSchemasV310(projection);
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
    const payload = normalizePayloadV310({ model: row.model_id, system: context.systemPrompt, messages: context.messages, tools }, row.seed);
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
  const finalRoot = state.ledger.size ? sha256(canonical(Object.fromEntries([...state.ledger.entries()].filter(([, quantity]) => quantity.n !== 0n).sort(([left], [right]) => left.localeCompare(right)).map(([instrument, quantity]) => [instrument, renderRational(quantity)])))) : sha256(canonical({}));
  const finalEvent = checkpoint(checkpointPath, checkpointState, row.run_id, "run_completed", { status, final_ledger_sha256: finalRoot });
  const trace = { contract_type: "run_trace", contract_version: "3.10.0", run_id: row.run_id, run_identity: row.run_identity, status, provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: responseModelId, endpoint_id: endpointId }, logical_requests: logicalRequests, usage: { model_requests: logicalRequests.length, provider_attempts: logicalRequests.flatMap((item) => item.attempts).length, tool_calls: state.toolEvents.length, total_tokens: logicalRequests.flatMap((item) => item.attempts).reduce((sum, item) => sum + item.input_tokens + item.output_tokens, 0) }, failure: { class: failureClass, code: null }, result: { candidate_scored: !["provider_or_runtime_failure", "indeterminate"].includes(failureClass), structured_output_valid: Boolean(state.candidate), candidate_output_sha256: state.candidate ? sha256(canonical(state.candidate)) : null, raw_provider_response_stored: false }, evidence_observations: state.evidenceObservations, tool_events: state.toolEvents, reason_facts: {}, permission: { trace_complete: true, declared_permissions: projection.task.permissions, observed_operations: state.observedOperations, violations: state.permissionViolations }, environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", initial_ledger_sha256: emptyRoot, final_ledger_sha256: finalRoot, final_state_matches_initial: emptyRoot === finalRoot, real_side_effects: false, network_scope: endpointId === "bailian_000000000000" ? "none_offline_fixture" : "bailian_inference_only" }, redaction: { applied: true, raw_provider_response_stored: false, raw_submission_arguments_persisted: false, secret_leakage_detected: false }, checkpoint: { event_count: checkpointState.offset, final_event_sha256: finalEvent.event_sha256 } };
  const grader = runPythonGrade({ candidate: state.candidate, projection, snapshot, trace }, { outputDirectory, runId: row.run_id });
  atomicJson(join(outputDirectory, "candidates", `${row.run_id}.json`), state.candidate);
  atomicJson(join(outputDirectory, "traces", `${row.run_id}.json`), trace);
  atomicJson(join(outputDirectory, "graders", `${row.run_id}.json`), grader);
  return { trace, grader };
}

// rational rendering helper identical in output to the frozen ledgerRoot path
function gcd(a, b) { let left = a < 0n ? -a : a; let right = b < 0n ? -b : b; while (right) [left, right] = [right, left % right]; return left || 1n; }
function renderRational(value, digits = 18) {
  const scale = 10n ** BigInt(digits);
  const negative = value.n < 0n;
  const absolute = negative ? -value.n : value.n;
  let quotient = absolute * scale / value.d;
  const remainder = absolute * scale % value.d;
  const twice = remainder * 2n;
  if (twice > value.d || (twice === value.d && quotient % 2n === 1n)) quotient += 1n;
  const scaled = negative ? -quotient : quotient;
  const neg = scaled < 0n;
  const abs = neg ? -scaled : scaled;
  const whole = abs / scale;
  let fraction = String(abs % scale).padStart(digits, "0").replace(/0+$/, "");
  const sign = neg && (whole !== 0n || fraction) ? "-" : "";
  return fraction ? `${sign}${whole}.${fraction}` : `${sign}${whole}`;
}

// --- invalidation (report-only, never replace; no_post_hoc_selection) --------
// A run whose execution consumed its frozen identity but whose artifacts cannot
// be frozen (e.g. the independent validator/grader rejected the generated
// trace) is invalidated: its checkpoint forensic record is persisted and the
// remaining scope continues. The guard rails below make this strictly narrower
// than the hard stop it replaces — it only applies to explicitly named run ids
// whose on-disk state is already non-finalizable (never pending or finalized),
// and it never re-executes anything.
function recordInvalidation(outputDirectory, row, state, reason) {
  const checkpointPath = join(outputDirectory, "checkpoints", `${row.run_id}.jsonl`);
  const chain = existsSync(checkpointPath) ? verifyCheckpointChain(checkpointPath, row.run_id) : { valid: false, reason: "no checkpoint", events: [] };
  const entry = {
    run_id: row.run_id, sequence: row.sequence, model_id: row.model_id, case_id: row.run_identity.case_id,
    repeat: row.repeat, seed: row.seed, run_identity: row.run_identity,
    disk_state_at_invalidation: state, reason, invalidated_at: now(),
    replaced_or_reexecuted: false,
    checkpoint_forensics: {
      present: existsSync(checkpointPath), chain_valid: chain.valid, chain_problem: chain.reason ?? null,
      event_count: chain.events.length,
      terminal_event: chain.events.length ? chain.events.at(-1) : null,
      events: chain.events,
    },
  };
  const reportPath = join(outputDirectory, "invalidated-runs.json");
  const existing = existsSync(reportPath) ? readJson(reportPath) : { contract_type: "stage3_run_invalidation_report", contract_version: "3.10.0", policy: "invalidated units are reported against their frozen identities; replacements require a new plan version and are never silently reselected (plan.replication_design.invalidation_policy)", entries: [] };
  if (!existing.entries.some((item) => item.run_id === row.run_id)) {
    existing.entries.push(entry);
    existing.entry_count = existing.entries.length;
    existing.report_sha256 = null;
    existing.report_sha256 = sha256(canonical({ ...existing, report_sha256: undefined }));
    atomicJson(reportPath, existing);
  }
  return entry;
}

// --- resumable plan execution -------------------------------------------------
export async function executeResumable({ plan, authorization, preflight, outputDirectory, send, endpointId = "bailian_000000000000", limit = null, deadlineMs = null, progressPath = null, invalidations = [] }) {
  validateAuthorizationV310(plan, authorization, preflight);
  assertPinnedRuntimeV310();
  const copy = structuredClone(plan); delete copy.plan_sha256;
  if (plan.contract_version !== "3.10.0" || plan.runs.length !== plan.registered_total_run_cap || plan.runs.length !== 810 || plan.plan_sha256 !== sha256(canonical(copy))) throw new Error("frozen plan integrity failure");
  const scope = firstRoundRunsV310(plan);
  const taskByRun = new Map(plan.tasks.flatMap((task) => task.run_ids.map((runId) => [runId, task])));
  // previously recorded invalidations are authoritative across resumes: the
  // loop re-scans the whole scope on every invocation, so a unit invalidated
  // in an earlier invocation must stay invalidated without re-passing it.
  const invalidationByRun = new Map(invalidations.map((item) => [item.run_id, item.reason]));
  const reportPath = join(outputDirectory, "invalidated-runs.json");
  if (existsSync(reportPath)) {
    for (const entry of readJson(reportPath).entries || []) {
      if (!invalidationByRun.has(entry.run_id)) invalidationByRun.set(entry.run_id, entry.reason);
    }
  }
  const startedAt = Date.now();
  let resumed = 0; let executed = 0; let invalidated = 0;
  const progress = (extra) => {
    const record = { created_at: now(), resumed, executed, invalidated, remaining: scope.length - resumed - executed - invalidated, ...extra };
    if (progressPath) { mkdirSync(dirname(progressPath), { recursive: true }); appendFileSync(progressPath, `${JSON.stringify(record)}\n`, { encoding: "utf8", mode: 0o600 }); }
    return record;
  };
  for (const row of scope) {
    const state = finalizedState(outputDirectory, row.run_id);
    if (invalidationByRun.has(row.run_id)) {
      if (state === "pending" || state === "finalized") throw new Error(`refusing invalidation of ${row.run_id}: on-disk state is ${state}; invalidation only applies to consumed-but-unfreezable units`);
      recordInvalidation(outputDirectory, row, state, invalidationByRun.get(row.run_id));
      invalidated += 1;
      progress({ event: "run_invalidated", run_id: row.run_id, sequence: row.sequence, reason: invalidationByRun.get(row.run_id) });
      continue;
    }
    if (state === "finalized") { resumed += 1; continue; }
    if (state !== "pending") {
      progress({ event: "hard_stop", run_id: row.run_id, sequence: row.sequence, state });
      throw new Error(`resume hard stop: run ${row.run_id} (sequence ${row.sequence}) is ${state}; invalidation must be reported, never silently replaced`);
    }
    if (executed >= (limit ?? Infinity)) break;
    if (deadlineMs && Date.now() - startedAt > deadlineMs) break;
    progress({ event: "run_started", run_id: row.run_id, sequence: row.sequence, model_id: row.model_id, case_id: row.run_identity.case_id });
    try {
      await executeOne({ plan, row, task: taskByRun.get(row.run_id), outputDirectory, send, endpointId });
    } catch (error) {
      progress({ event: "run_rejected", run_id: row.run_id, sequence: row.sequence, model_id: row.model_id, case_id: row.run_identity.case_id, failure: String(error.message).slice(0, 1000) });
      throw error;
    }
    executed += 1;
    progress({ event: "run_finalized", run_id: row.run_id, sequence: row.sequence });
  }
  const allDone = resumed + executed + invalidated === scope.length;
  if (allDone) {
    const graderFiles = readdirSync(join(outputDirectory, "graders"));
    const graders = graderFiles.map((name) => readJson(join(outputDirectory, "graders", name)));
    const summary = { contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.10.0", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, counts: { planned: scope.length, candidates: graderFiles.length, traces: readdirSync(join(outputDirectory, "traces")).length, graders: graders.length, accepted: graders.filter((item) => item.all_applicable_checks_passed).length, invalidated }, invalidated_run_ids: [...invalidationByRun.keys()], paid_calls_authorized: true };
    atomicJson(join(outputDirectory, "runtime-summary.json"), summary);
    progress({ event: "plan_complete", summary_counts: summary.counts });
    return summary;
  }
  progress({ event: "chunk_complete" });
  return { status: "chunk_complete", resumed, executed, invalidated, remaining: scope.length - resumed - executed - invalidated };
}

function parseArgs(argv) { const args = {}; for (let index = 0; index < argv.length; index += 2) args[argv[index]] = argv[index + 1]; return args; }
async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (!args["--plan"] || !args["--authorization"] || !args["--preflight"] || !args["--output-dir"]) throw new Error("--plan, --authorization, --preflight, and --output-dir required");
  const read = (value) => readJson(isAbsolute(value) ? value : resolve(ROOT, value));
  const plan = read(args["--plan"]);
  const authorization = read(args["--authorization"]);
  const preflight = read(args["--preflight"]);
  const settings = loadSettingsDriver();
  const invalidations = [];
  if (args["--invalidate"]) {
    if (!args["--invalidate-reason"]) throw new Error("--invalidate requires --invalidate-reason");
    invalidations.push({ run_id: args["--invalidate"], reason: args["--invalidate-reason"] });
  }
  return executeResumable({
    plan,
    authorization,
    preflight,
    outputDirectory: resolve(args["--output-dir"]),
    send: createPiTransportV310(settings),
    endpointId: settings.endpointId,
    limit: args["--limit"] ? Number(args["--limit"]) : null,
    deadlineMs: args["--deadline-ms"] ? Number(args["--deadline-ms"]) : null,
    progressPath: join(resolve(args["--output-dir"]), "driver-progress.jsonl"),
    invalidations,
  });
}

if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().then((result) => process.stdout.write(`${JSON.stringify(result)}\n`)).catch((error) => { process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: String(error.message).split(":")[0] })}\n`); process.exitCode = 2; });
}
