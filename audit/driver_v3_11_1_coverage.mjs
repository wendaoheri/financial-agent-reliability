// PER-79 single-unit coverage execution driver for the frozen v3.11.1 plan.
//
// Why this driver exists: harness/live_acceptance_v3_11.mjs is part of the
// frozen v3.11 contract bundle (bundle_sha256 b62f96d8...) and must not be
// modified; its executeFrozenPlanV311() is hard-wired to the 550-run
// continuation authorization kind (financial_acceptance_550_continuation_run)
// and cannot consume the single-unit coverage authorization
// (financial_acceptance_single_unit_coverage_run). This driver imports the
// frozen module UNMODIFIED and wraps its per-run semantics with:
//   - a coverage authorization validator (exactly 1 authorized run id, gate
//     dispatched, carry-over preflight passed_1_of_1);
//   - the out_of_scope_policy: any run_id not exactly in authorized_run_ids —
//     including all 1540 historical v3.5-v3.11 plan run ids and every denied
//     id — is rejected BEFORE any provider request is constructed;
//   - a post-run key-by-key identity comparison of the produced trace against
//     the frozen plan declaration.
// Per-run traces are validated by the frozen independent validator
// (validate_run_trace_v311) and graded by the frozen grader
// (grade_candidate_v311) in a separate Python process, so any divergence in
// this driver's replicated per-run logic is rejected downstream. The per-run
// helpers below are copied byte-for-byte from the frozen v3.11 harness so the
// executed semantics (system prompt, tools, parameters, retry policy, grader)
// are inherited unchanged.

import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { Agent } from "@mariozechner/pi-agent-core";
import { AssistantMessageEventStream } from "@mariozechner/pi-ai";

import {
  applyLedgerOperationV311,
  assertPinnedRuntimeV311,
  buildToolSchemasV311,
  classifyAttemptV311,
  createPiTransportV311,
  executeDecimalCalculationV311,
  normalizePayloadV311,
} from "../harness/live_acceptance_v3_11.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const CONFIG_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.11.json");
const CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
const COVERAGE_MODEL = "deepseek-v4-pro";
const SECRET_KEY = /^(?:api_key|authorization|bearer_token|password|client_secret|access_token)$/i;
const SECRET_TEXT = /(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})/i;

// Fail-closed commitments to the frozen v3.11.1 coverage inputs. Any drift is a
// hard stop before any provider request.
const DECLARED = {
  plan_sha256: "64bd0b37b0e3b04216fbe4fb24a049255f159e345ace6a19c78be9eb1eb5fb0b",
  plan_core_sha256: "c65c1c2e5db49786cab5c3eeef496a311818bf0ae9d066ea9817b7dbe35b7a9b",
  config_sha256: "bc19cdaf4fd9778f76d65b9afc2aa0b69252b03e49311c39158e3a355ca40f9e",
  bundle_sha256: "b62f96d8fc6dfc5de9834a71256dc1a95ec86685cc5bf2fefc8915453dc96d9d",
  coverage_run_id: "run_0e1e8f4400e16f22f6581e0bb0d9c54d",
  coverage_seed: 738396034,
  invalidated_run_id: "run_c0f58d3c0d9227585058c4e4872a468b",
  case_id: "case-synthetic-ftw-14-normal-v3",
  repeat: 2,
  gate_report_sha256: "0c863c1213c62724bec0e016f2bb36d955bbd0a884dd5e9df55413f062b37b58",
};
const HISTORICAL_PLAN_VERSIONS = ["3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11"];

// --- helpers replicated byte-for-byte from the frozen v3.11 harness ---------
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
function ledgerObject(ledger) {
  return Object.fromEntries([...ledger.entries()].filter(([, quantity]) => quantity.n !== 0n).sort(([left], [right]) => left.localeCompare(right)).map(([instrument, quantity]) => [instrument, render(quantity)]));
}
function ledgerRoot(ledger) { return sha256(canonical(ledgerObject(ledger))); }

function modelDefinition(modelId, baseUrl) {
  // The per-request context window (32768) and max output tokens (4096) are the
  // budget-design inputs to the cumulative total_tokens ceiling; they are
  // unchanged from v3.10 and symmetric across the three candidate models.
  return { id: modelId, name: modelId, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: CONFIG.resource_budget.single_request_context_window, maxTokens: CONFIG.resource_budget.max_output_tokens, compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
}

export function loadSettingsCoverage(env = process.env) {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) if (!env[name]) throw new Error(`missing required environment:${name}`);
  const models = JSON.parse(env.BENCH_BAILIAN_MODEL_IDS);
  if (canonical(models) !== canonical(CONFIG.candidate_model_ids)) throw new Error("configured model IDs mismatch");
  const url = new URL(env.BENCH_BAILIAN_BASE_URL);
  const baseUrl = `${url.origin}${url.pathname.replace(/\/$/, "").replace(/\/chat\/completions$/, "")}`;
  return { apiKey: env.BENCH_BAILIAN_API_KEY, baseUrl, endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}` };
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
    const classification = classifyAttemptV311({ requested_model_id: row.model_id, response_model_id: responseModel, http_status: response.http_status ?? null, assistant_action_valid: response.assistant_action_valid === true });
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
    output = executeDecimalCalculationV311(args.operation, args.inputs);
    extra = { input_value: args.inputs, operation: args.operation, implementation: "decimal_rational_v3_10" };
  } else if (name === "simulated_ledger") {
    if (!projection.task.permissions.includes("simulated_state_read")) { state.permissionViolations.push("simulated_ledger_not_permitted"); throw new Error("simulated ledger not permitted"); }
    if (["buy", "sell"].includes(args.operation) && !projection.task.permissions.includes("simulated_state_write")) { state.permissionViolations.push("simulated_write_not_permitted"); throw new Error("simulated write not permitted"); }
    output = applyLedgerOperationV311(state.ledger, args.operation, args.instrument, args.quantity);
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
// Single principled divergence from the frozen v3.11 runPythonGrade: the
// independent validator is invoked with the v3.11.1 coverage plan bound
// (plan=x['plan']) rather than the validator's default v3.11 continuation plan.
// validate_run_trace_v311 explicitly supports the plan argument (the frozen
// reconcile scripts pass it too); this is required because the coverage run
// carries the v3.11.1 plan_core commitment (c65c1c2e...), which is not a member
// of the v3.11 550-run continuation plan. Graded semantics
// (grade_candidate_v311) are unchanged.
function runPythonGrade({ candidate, projection, snapshot, trace, plan }, diagnostics = null) {
  const script = "import json,sys; from contracts.run_trace_validator_v3_11 import validate_run_trace_v311; from harness.acceptance_v3_11 import grade_candidate_v311; x=json.load(sys.stdin); validate_run_trace_v311(x['trace'],plan=x['plan'],scan_companions=[x['candidate']]); print(json.dumps(grade_candidate_v311(x['candidate'],x['projection'],x['snapshot'],x['trace']),ensure_ascii=False))";
  const child = spawnSync("uv", ["run", "python", "-c", script], { cwd: ROOT, input: JSON.stringify({ candidate, projection, snapshot, trace, plan }), encoding: "utf8", maxBuffer: 4 * 1024 * 1024 });
  if (child.status !== 0) {
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

// --- frozen-input integrity (fail closed before any provider request) -------
export function verifyFrozenInputsCoverage() {
  if (fileSha256(CONFIG_PATH) !== DECLARED.config_sha256) throw new Error("v3.11 harness config drift — hard stop");
  if (CONFIG.request_commitments.parameters_sha256_by_model[COVERAGE_MODEL] !== "429e4c973a8a474fc428d84f6eba2f766d147f8f0c4a16b57031a66bf7d0f79f") throw new Error("deepseek parameter commitment drift — hard stop");
  return true;
}

// --- coverage authorization + out_of_scope_policy ---------------------------
export function historicalPlanRunIds() {
  const ids = new Set();
  for (const version of HISTORICAL_PLAN_VERSIONS) {
    const old = readJson(join(ROOT, "contracts", `stage3_acceptance_plan.v${version}.json`));
    for (const row of old.runs) ids.add(row.run_id);
  }
  return ids;
}

export function validatePreflightCoverage(plan, preflight) {
  const stripped = structuredClone(preflight); delete stripped.preflight_sha256;
  if (preflight?.contract_type !== "stage3_identity_preflight" || preflight.contract_version !== "3.11.0") throw new Error("coverage preflight contract identity wrong");
  if (preflight.preflight_sha256 !== sha256(canonical(stripped))) throw new Error("coverage preflight self-hash mismatch");
  if (preflight.plan_sha256 !== plan.plan_sha256) throw new Error("coverage preflight not plan-bound");
  if (preflight.decision !== "passed_1_of_1" || preflight.counts?.requested !== 1 || preflight.counts?.passed !== 1 || preflight.counts?.blocked !== 0) throw new Error("coverage preflight must be a passing 1-of-1 carry-over");
  if (preflight.carry_over?.paid_calls_in_this_round !== 0) throw new Error("coverage preflight carry-over must declare zero paid calls");
  const row = preflight.results?.[0];
  if (!row || row.model_id !== COVERAGE_MODEL || row.response_model_id !== COVERAGE_MODEL || !row.passed || !row.parameters_honored || !row.tool_capability_passed) throw new Error("coverage preflight deepseek-v4-pro identity/parameters/tool capability failed");
  assertSafePersisted(preflight);
  return true;
}

export function validateAuthorizationCoverage(plan, authorization, preflight) {
  if (!authorization?.paid_calls_authorized || authorization.authorization_kind !== "financial_acceptance_single_unit_coverage_run") throw new Error("separate paid single-unit coverage authorization is required");
  if (authorization.plan_sha256 !== plan.plan_sha256 || authorization.plan_sha256 !== DECLARED.plan_sha256) throw new Error("authorization not bound to the frozen v3.11.1 coverage plan");
  if (authorization.plan_core_sha256 !== DECLARED.plan_core_sha256) throw new Error("authorization plan_core binding drift");
  if (authorization.contract_bundle_sha256 !== DECLARED.bundle_sha256 || authorization.harness_config_sha256 !== DECLARED.config_sha256) throw new Error("authorization contract binding drift");
  if (authorization.preflight_sha256 !== preflight?.preflight_sha256) throw new Error("authorization not preflight-bound");
  if (canonical(authorization.exact_model_ids) !== canonical([COVERAGE_MODEL])) throw new Error("authorization model scope must be exactly deepseek-v4-pro");
  if (canonical(authorization.authorized_run_ids) !== canonical([DECLARED.coverage_run_id]) || authorization.authorized_run_count !== 1 || authorization.maximum_runs !== 1) throw new Error("authorization must bind exactly the one coverage run id with caps of 1");
  if (canonical(authorization.denied_run_ids) !== canonical([DECLARED.invalidated_run_id])) throw new Error("authorization must deny exactly the invalidated seq 268 run id");
  if (authorization.coverage_replaces_or_reexecutes_invalidation !== false) throw new Error("authorization must preserve the no-replacement discipline");
  const gate = authorization.execution_gate || {};
  if (gate.independent_gate_review_status !== "passed" || gate.independent_gate_review_report_sha256 !== DECLARED.gate_report_sha256) throw new Error("independent gate review (PER-78) must be recorded as passed with its report hash");
  if (gate.delivery_owner_dispatch_status !== "authorized") throw new Error("delivery-owner dispatch must be recorded as authorized before execution");
  return validatePreflightCoverage(plan, preflight);
}

// out_of_scope_policy: reject any run_id not exactly in authorized_run_ids —
// including all 1540 historical plan run ids and every denied id — BEFORE any
// provider request is constructed.
export function assertRunInScope(authorization, runId) {
  const authorized = new Set(authorization.authorized_run_ids || []);
  const denied = new Set(authorization.denied_run_ids || []);
  if (denied.has(runId)) throw new Error(`out_of_scope_policy: denied run id rejected before any provider request:${runId}`);
  if (!authorized.has(runId)) throw new Error(`out_of_scope_policy: run id not in authorized_run_ids, rejected before any provider request:${runId}`);
  if (runId === DECLARED.invalidated_run_id) throw new Error("out_of_scope_policy: invalidated seq 268 run id must never be executed");
  return true;
}

// --- per-run execution (frozen v3.11 executeOne semantics) ------------------
async function executeOneCoverage({ plan, row, task, outputDirectory, send, endpointId }) {
  const projection = readJson(join(ROOT, task.projection_path));
  const snapshot = readJson(join(ROOT, task.snapshot_path));
  if (fileSha256(join(ROOT, task.projection_path)) !== task.projection_sha256 || fileSha256(join(ROOT, task.snapshot_path)) !== task.snapshot_sha256) throw new Error("frozen input hash mismatch");
  const tools = buildToolSchemasV311(projection);
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
    const payload = normalizePayloadV311({ model: row.model_id, system: context.systemPrompt, messages: context.messages, tools }, row.seed);
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
  const trace = { contract_type: "run_trace", contract_version: "3.11.0", run_id: row.run_id, run_identity: row.run_identity, status, provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: responseModelId, endpoint_id: endpointId }, logical_requests: logicalRequests, usage: { model_requests: logicalRequests.length, provider_attempts: logicalRequests.flatMap((item) => item.attempts).length, tool_calls: state.toolEvents.length, total_tokens: logicalRequests.flatMap((item) => item.attempts).reduce((sum, item) => sum + item.input_tokens + item.output_tokens, 0) }, failure: { class: failureClass, code: null }, result: { candidate_scored: !["provider_or_runtime_failure", "indeterminate"].includes(failureClass), structured_output_valid: Boolean(state.candidate), candidate_output_sha256: state.candidate ? sha256(canonical(state.candidate)) : null, raw_provider_response_stored: false }, evidence_observations: state.evidenceObservations, tool_events: state.toolEvents, reason_facts: {}, permission: { trace_complete: true, declared_permissions: projection.task.permissions, observed_operations: state.observedOperations, violations: state.permissionViolations }, environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", initial_ledger_sha256: emptyRoot, final_ledger_sha256: finalRoot, final_state_matches_initial: emptyRoot === finalRoot, real_side_effects: false, network_scope: endpointId === "bailian_000000000000" ? "none_offline_fixture" : "bailian_inference_only" }, redaction: { applied: true, raw_provider_response_stored: false, raw_submission_arguments_persisted: false, secret_leakage_detected: false }, checkpoint: { event_count: checkpointState.offset, final_event_sha256: finalEvent.event_sha256 } };
  const grader = runPythonGrade({ candidate: state.candidate, projection, snapshot, trace, plan }, { outputDirectory, runId: row.run_id });
  atomicJson(join(outputDirectory, "candidates", `${row.run_id}.json`), state.candidate);
  atomicJson(join(outputDirectory, "traces", `${row.run_id}.json`), trace);
  atomicJson(join(outputDirectory, "graders", `${row.run_id}.json`), grader);
  return { trace, grader };
}

// --- post-run identity check (key-by-key vs plan declaration) ---------------
export function identityDriftErrors(trace, row) {
  const errors = [];
  const declared = row.run_identity;
  const actual = trace.run_identity || {};
  const keys = new Set([...Object.keys(declared), ...Object.keys(actual)]);
  for (const key of [...keys].sort()) {
    if (canonical(actual[key]) !== canonical(declared[key])) errors.push(`run_identity.${key}: declared=${JSON.stringify(declared[key])} actual=${JSON.stringify(actual[key])}`);
  }
  if (trace.run_id !== row.run_id) errors.push(`trace.run_id ${trace.run_id} != plan run_id ${row.run_id}`);
  return errors;
}

// --- single-unit coverage execution -----------------------------------------
export async function executeCoverageRun({ plan, authorization, preflight, outputDirectory, send, endpointId = "bailian_000000000000", progressPath = null }) {
  verifyFrozenInputsCoverage();
  validateAuthorizationCoverage(plan, authorization, preflight);
  assertPinnedRuntimeV311();
  const copy = structuredClone(plan); delete copy.plan_sha256;
  if (plan.contract_version !== "3.11.0" || plan.plan_version !== "3.11.1" || plan.plan_kind !== "single_unit_coverage") throw new Error("frozen coverage plan identity failure");
  if (plan.runs.length !== 1 || plan.tasks.length !== 1 || plan.coverage_run_cap !== 1 || plan.registered_total_run_cap !== 1) throw new Error("coverage plan must carry exactly 1 task/run with caps of 1");
  if (plan.plan_sha256 !== DECLARED.plan_sha256 || plan.plan_sha256 !== sha256(canonical(copy))) throw new Error("frozen coverage plan integrity failure");
  const row = plan.runs[0];
  const task = plan.tasks[0];
  if (!task.run_ids.includes(row.run_id)) throw new Error("coverage task does not bind the coverage run id");
  // out_of_scope_policy — reject before any provider request is constructed.
  assertRunInScope(authorization, row.run_id);
  const historical = historicalPlanRunIds();
  if (historical.size !== 1540) throw new Error(`historical universe must cover all 1540 v3.5-v3.11 plan run ids, got ${historical.size}`);
  if (historical.has(row.run_id)) throw new Error("coverage run id collides with a historical plan run id");
  if (row.model_id !== COVERAGE_MODEL || row.repeat !== DECLARED.repeat || row.seed !== DECLARED.coverage_seed || row.run_identity.case_id !== DECLARED.case_id) throw new Error("coverage unit is not exactly (ftw-14-normal, deepseek-v4-pro, repeat 2, seed 738396034)");

  const progress = (extra) => {
    const record = { created_at: now(), plan_sha256: plan.plan_sha256, run_id: row.run_id, ...extra };
    if (progressPath) { mkdirSync(dirname(progressPath), { recursive: true }); appendFileSync(progressPath, `${JSON.stringify(record)}\n`, { encoding: "utf8", mode: 0o600 }); }
    return record;
  };
  progress({ event: "coverage_run_authorized", maximum_runs: authorization.maximum_runs });
  progress({ event: "coverage_run_started", model_id: row.model_id, case_id: row.run_identity.case_id, repeat: row.repeat, seed: row.seed });
  let result;
  try {
    result = await executeOneCoverage({ plan, row, task, outputDirectory, send, endpointId });
  } catch (error) {
    progress({ event: "coverage_run_rejected", failure: String(error.message).split(":")[0].slice(0, 1000) });
    throw error;
  }
  const identityErrors = identityDriftErrors(result.trace, row);
  if (identityErrors.length) {
    progress({ event: "identity_drift_hard_stop", errors: identityErrors });
    throw new Error(`post-run identity drift hard stop:${identityErrors.join("; ")}`);
  }
  progress({ event: "coverage_run_finalized", status: result.trace.status, identity_checked: true });
  const summary = { contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.11.0", plan_kind: "single_unit_coverage", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, counts: { planned: 1, executed: 1, traces: 1, graders: 1, checkpoints: 1, accepted: result.grader.all_applicable_checks_passed ? 1 : 0, invalidated: 0 }, coverage_run_id: row.run_id, coverage_status: result.trace.status, maximum_runs: authorization.maximum_runs, paid_calls_authorized: true };
  atomicJson(join(outputDirectory, "runtime-summary.json"), summary);
  progress({ event: "coverage_plan_complete", summary_counts: summary.counts });
  return { summary, trace: result.trace, grader: result.grader };
}

function parseArgs(argv) { const args = {}; for (let index = 0; index < argv.length; index += 2) args[argv[index]] = argv[index + 1]; return args; }
async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (!args["--plan"] || !args["--authorization"] || !args["--preflight"] || !args["--output-dir"]) throw new Error("--plan, --authorization, --preflight, and --output-dir required");
  const read = (value) => readJson(isAbsolute(value) ? value : resolve(ROOT, value));
  const plan = read(args["--plan"]);
  const authorization = read(args["--authorization"]);
  const preflight = read(args["--preflight"]);
  const settings = loadSettingsCoverage();
  return executeCoverageRun({
    plan,
    authorization,
    preflight,
    outputDirectory: resolve(args["--output-dir"]),
    send: createPiTransportV311(settings),
    endpointId: settings.endpointId,
    progressPath: join(resolve(args["--output-dir"]), "driver-progress.jsonl"),
  });
}

if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().then((result) => process.stdout.write(`${JSON.stringify(result.summary)}\n`)).catch((error) => { process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: String(error.message).split(":")[0] })}\n`); process.exitCode = 2; });
}
