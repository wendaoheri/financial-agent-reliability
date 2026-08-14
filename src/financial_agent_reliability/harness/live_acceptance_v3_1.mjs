import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { streamSimple } from "@mariozechner/pi-ai";

import { createPinnedAgentV3 } from "./pi_runtime_v3.mjs";
import { buildRunPromptV3, calculateV3, createSubmissionCollector, normalizePayloadV3 } from "./live_acceptance_v3.mjs";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(dirname(dirname(HERE)));
const BASE_CONFIG = JSON.parse(readFileSync(join(ROOT, "contracts", "run_trace_harness_config.v3.json"), "utf8"));
const CORRECTION_PATH = join(ROOT, "contracts", "run_trace_harness_config.v3.1.json");
const CORRECTION = JSON.parse(readFileSync(CORRECTION_PATH, "utf8"));
const MODEL_MANIFEST = join(ROOT, "contracts", "model_manifest.frozen.v2.json");
const MODELS = CORRECTION.candidate_model_ids;


function sortValue(value) { if (Array.isArray(value)) return value.map(sortValue); if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])])); return value; }
function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.isBuffer(value) ? value : Buffer.from(String(value))).digest("hex"); }
function fileSha256(path) { return sha256(readFileSync(path)); }
function readJson(path) { return JSON.parse(readFileSync(path, "utf8")); }
function timestamp() { return new Date().toISOString(); }
function atomicJson(path, value) { mkdirSync(dirname(path), { recursive: true }); const temporary = `${path}.partial`; writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 }); renameSync(temporary, path); }


function loadSettings() {
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL", "BENCH_BAILIAN_MODEL_IDS"]) if (!process.env[name]) throw new Error(`missing ${name}`);
  let parsed; try { parsed = JSON.parse(process.env.BENCH_BAILIAN_MODEL_IDS); } catch { parsed = process.env.BENCH_BAILIAN_MODEL_IDS.split(",").map((item) => item.trim()); }
  if (canonical(parsed) !== canonical(MODELS)) throw new Error("exact model IDs required");
  const url = new URL(process.env.BENCH_BAILIAN_BASE_URL); let path = url.pathname.replace(/\/$/, ""); if (path.endsWith("/chat/completions")) path = path.slice(0, -"/chat/completions".length);
  return { apiKey: process.env.BENCH_BAILIAN_API_KEY, configuredBaseUrl: process.env.BENCH_BAILIAN_BASE_URL, baseUrl: `${url.origin}${path}`, endpointId: `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}` };
}


export function buildSubmitSchemaV31(projection) {
  const base = BASE_CONFIG.tools.find((item) => item.name === "submit_candidate_result").parameters;
  const schema = structuredClone(base);
  schema.properties.value = { anyOf: [structuredClone(projection.answer_value_schema), { type: "null" }] };
  schema.properties.evidence_record_ids.items = projection.evidence_contract.registered_record_ids.length
    ? { type: "string", enum: projection.evidence_contract.registered_record_ids }
    : { type: "string" };
  return schema;
}


function textResult(value, details = {}) { return { content: [{ type: "text", text: JSON.stringify(value) }], details }; }


function createToolsV31(projection, snapshot, collector, observations, ledger) {
  const definitions = Object.fromEntries(BASE_CONFIG.tools.map((item) => [item.name, item]));
  const allowed = new Set(projection.evidence_contract.registered_record_ids);
  const tool = (name, execute, parameters = definitions[name].parameters) => ({ name, label: name, description: definitions[name].description, parameters, executionMode: "sequential", execute });
  return [
    tool("read_frozen_case", async (_id, args) => { if (args.case_id !== projection.case_id) throw new Error("case identity mismatch"); return textResult(projection); }),
    tool("read_frozen_evidence", async (_id, args) => { if (!allowed.has(args.record_id) || args.snapshot_id !== snapshot.snapshot_id) throw new Error("unregistered evidence"); const record = snapshot.records.find((item) => item.record_id === args.record_id); if (!record) throw new Error("record unavailable"); observations[record.record_id] = { available_at: snapshot.temporal.available_at_cutoff || projection.temporal.available_at_cutoff }; return textResult({ snapshot_id: snapshot.snapshot_id, temporal: snapshot.temporal, record }); }),
    tool("calculate", async (_id, args) => textResult(calculateV3(args.operation, args.inputs))),
    tool("simulated_ledger", async (_id, args) => { if (!projection.task.permissions.includes("simulated_state_read")) throw new Error("ledger read not permitted"); if (["buy", "sell"].includes(args.operation) && !projection.task.permissions.includes("simulated_state_write")) throw new Error("ledger write not permitted"); if (args.operation !== "preview") ledger.set(args.instrument, args.quantity); return textResult({ ledger_mode: "simulated", operation: args.operation, real_execution: false }); }),
    tool("submit_candidate_result", collector.execute, buildSubmitSchemaV31(projection)),
  ];
}


function modelDefinition(id, baseUrl, maxTokens = 4096) {
  return { id, name: id, api: "openai-completions", provider: "bailian", baseUrl, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32768, maxTokens,
    compat: { supportsStore: false, supportsDeveloperRole: false, supportsReasoningEffort: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens", requiresToolResultName: false, requiresAssistantAfterToolResult: false, supportsStrictMode: false, sendSessionAffinityHeaders: false, supportsLongCacheRetention: false } };
}


function safeError(error) { const status = Number.isInteger(error?.status) ? error.status : null; let type = "provider_unavailable"; if (status === 401) type = "authentication_failed"; else if (status === 403) type = "permission_denied"; else if (status === 429) type = "rate_limited"; else if (status && status < 500) type = "provider_rejected_request"; return { type, http_status: status, provider_code: typeof error?.code === "string" && /^[\w.-]{1,64}$/.test(error.code) ? error.code : null }; }


function checkpoint(path, runId, state, type, payload) { const event = { run_id: runId, offset: state.offset, event_type: type, payload, previous_event_sha256: state.previous, state_sha256: sha256(canonical(payload)), created_at: timestamp() }; event.event_sha256 = sha256(canonical(event)); appendFileSync(path, `${canonical(event)}\n`, { mode: 0o600 }); state.offset += 1; state.previous = event.event_sha256; return event; }
function usage(messages) { const total = { input_tokens: 0, output_tokens: 0, total_tokens: 0 }; for (const message of messages) if (message.role === "assistant") { total.input_tokens += Number(message.usage?.input || 0); total.output_tokens += Number(message.usage?.output || 0); total.total_tokens += Number(message.usage?.totalTokens || 0); } return total; }


async function runAgent({ modelId, seed, projection, snapshot, settings, preflight = false }) {
  const collector = createSubmissionCollector(projection); const observations = {}; const ledger = new Map(); const toolEvents = []; const payloadHashes = []; const responseStatuses = [];
  let requests = 0; let toolCallCount = 0; let responseModelId = null; let failure = null;
  const tools = createToolsV31(projection, snapshot, collector, observations, ledger);
  const agent = createPinnedAgentV3({ model: modelDefinition(modelId, settings.baseUrl, preflight ? 512 : 4096), tools, getApiKey: () => settings.apiKey,
    streamFn: (active, context, options) => { requests += 1; if (requests > CORRECTION.resource_budget.max_model_requests) throw new Error("model request budget exceeded"); return streamSimple(active, context, { ...options, temperature: 0, maxTokens: preflight ? 512 : 4096, timeoutMs: 120000, maxRetries: 0, cacheRetention: "none" }); },
    onPayload: (payload) => { const normalized = normalizePayloadV3(payload, seed); payloadHashes.push(sha256(canonical(normalized))); return normalized; }, onResponse: (response) => responseStatuses.push(Number(response.status)),
    beforeToolCall: async ({ toolCall, args }) => { toolCallCount += 1; if (toolCallCount > CORRECTION.resource_budget.max_tool_calls) return { block: true, reason: "tool call budget exceeded" }; const safeArgs = toolCall.name === "submit_candidate_result" ? { submission_sha256: sha256(canonical(args)) } : args; toolEvents.push({ event: "start", tool_call_id: toolCall.id, tool_name: toolCall.name, arguments: safeArgs, started_at: timestamp() }); return undefined; },
  });
  agent.subscribe((event) => { if (event.type === "message_end" && event.message.role === "assistant" && event.message.responseModel) responseModelId = event.message.responseModel; if (event.type === "tool_execution_end") { const start = [...toolEvents].reverse().find((item) => item.event === "start" && item.tool_call_id === event.toolCallId); toolEvents.push({ event: "end", tool_call_id: event.toolCallId, tool_name: event.toolName, arguments: start?.arguments || {}, is_error: Boolean(event.isError), result_sha256: sha256(canonical(event.result)), finished_at: timestamp() }); } });
  const timer = setTimeout(() => agent.abort(), CORRECTION.resource_budget.wall_clock_ms);
  try { const suffix = preflight ? "\nFor this preflight submit status answer, value {\"protocol_ok\":true}, empty reason_codes/evidence_record_ids, low uncertainty, and true permission claim." : ""; await agent.prompt(`${buildRunPromptV3(projection)}${suffix}`); } catch (error) { failure = safeError(error); } finally { clearTimeout(timer); }
  const finalText = [...agent.state.messages].reverse().find((item) => item.role === "assistant")?.content?.filter((item) => item.type === "text").map((item) => item.text).join("") || "";
  return { collector, observations, ledger, toolEvents, payloadHashes, responseStatuses, requests, responseModelId: responseModelId || modelId, identityValid: (responseModelId || modelId) === modelId, failure, usage: usage(agent.state.messages), finalText };
}


async function preflightV31(settings, outputPath) {
  const projection = { case_id: "PREFLIGHT-V3.1", task: { prompt: "Validate the corrected structured submission schema.", inputs: { operation: "direct" }, permissions: ["synthetic_data_read"] }, temporal: { as_of: "2026-08-11T00:00:00Z" }, financial_subject: {}, evidence_refs: [], evidence_contract: { registered_record_ids: [], material_record_ids: [], minimum_material_evidence_count: 0 }, status_value_contract: { answer: "schema", "abstain|escalate|reject_action": "null" }, answer_value_schema: { type: "object", additionalProperties: false, required: ["protocol_ok"], properties: { protocol_ok: { type: "boolean" } } }, reason_code_vocabulary: readJson(join(ROOT, "contracts", "reason_codes.v3.json")).codes };
  const results = [];
  for (let index = 0; index < MODELS.length; index += 1) { const result = await runAgent({ modelId: MODELS[index], seed: 950000 + index, projection, snapshot: { snapshot_id: "none", records: [], temporal: {} }, settings, preflight: true }); results.push({ model_id: MODELS[index], response_model_id: result.responseModelId, identity_valid: result.identityValid, structured_submission_valid: result.collector.state.accepted, submit_attempts: result.collector.state.attempts, last_error: result.collector.state.lastError, tool_sequence: result.toolEvents.filter((item) => item.event === "start").map((item) => item.tool_name), model_requests: result.requests, status: !result.failure && result.identityValid && result.collector.state.accepted ? "passed" : "blocked", failure_type: result.failure?.type || null }); }
  const artifact = { contract_type: "stage3_acceptance_preflight", contract_version: "3.1.0", created_at: timestamp(), endpoint_id: settings.endpointId, harness_correction_sha256: fileSha256(CORRECTION_PATH), base_harness_sha256: fileSha256(join(ROOT, "contracts", "run_trace_harness_config.v3.json")), counts: { requested: 3, passed: results.filter((item) => item.status === "passed").length, blocked: results.filter((item) => item.status !== "passed").length }, results, raw_provider_responses_persisted: false, candidate_text_persisted: false, credentials_persisted: false };
  atomicJson(outputPath, artifact); return artifact;
}


async function executeOne(row, task, plan, settings, outputDirectory) {
  const tracePath = join(outputDirectory, "traces", `${row.run_id}.json`); if (existsSync(tracePath)) return readJson(tracePath);
  const projection = readJson(join(ROOT, task.projection_path)); const snapshot = readJson(join(ROOT, task.snapshot_path));
  if (fileSha256(join(ROOT, task.projection_path)) !== task.projection_sha256 || fileSha256(join(ROOT, task.snapshot_path)) !== task.snapshot_sha256) throw new Error("input hash drift");
  const cpPath = join(outputDirectory, "checkpoints", `${row.run_id}.jsonl`); mkdirSync(dirname(cpPath), { recursive: true }); if (existsSync(cpPath)) throw new Error("partial checkpoint requires diagnostic"); const cp = { offset: 0, previous: "0".repeat(64) }; checkpoint(cpPath, row.run_id, cp, "run_started", { plan_sha256: plan.plan_sha256, projection_sha256: task.projection_sha256, snapshot_sha256: task.snapshot_sha256 });
  const startedAt = timestamp(); const startedMs = Date.now(); const result = await runAgent({ modelId: row.model_id, seed: row.seed, projection, snapshot, settings });
  for (const event of result.toolEvents.filter((item) => item.event === "end")) checkpoint(cpPath, row.run_id, cp, "tool_completed", { tool_name: event.tool_name, is_error: event.is_error, result_sha256: event.result_sha256 });
  const candidate = result.collector.state.candidate; const leakage = [settings.apiKey, settings.configuredBaseUrl].some((value) => result.finalText.includes(value)); const parseError = candidate ? null : (result.collector.state.lastError || { category: result.finalText.trim() ? "invalid_json" : "empty_output", path: "/", response_sha256: sha256(result.finalText) }); const status = !result.identityValid ? "invalidated" : result.failure ? "failed" : "succeeded"; const completed = checkpoint(cpPath, row.run_id, cp, "run_completed", { status, structured_result_valid: Boolean(candidate), parse_error_category: parseError?.category || null });
  const finalLedger = Object.fromEntries(result.ledger.entries());
  const trace = { contract_type: "run_trace", contract_version: "3.1.0", run_id: row.run_id, run_identity: row.run_identity, status,
    provider: { name: "bailian", requested_model_id: row.model_id, response_model_id: result.responseModelId, endpoint_id: settings.endpointId, model_manifest_sha256: fileSha256(MODEL_MANIFEST) },
    request: { parameters: { temperature: 0, top_p: 1, max_tokens: 4096, seed: row.seed, stream: true }, tool_choice: "auto", payload_sha256s: result.payloadHashes, sdk_retries: 0 },
    preflight: { performed: true, identity_match: result.identityValid, fallback_detected: !result.identityValid, fallback_attempted: false, parameters_honored: !result.failure, valid: result.identityValid && !result.failure, authoritative_preflight_sha256: plan.authoritative_preflight.sha256 },
    context: { system_prompt_sha256: sha256(BASE_CONFIG.system_prompt), tool_schema_sha256: sha256(canonical(createToolsV31(projection, snapshot, createSubmissionCollector(projection), {}, new Map()).map((item) => ({ name: item.name, description: item.description, parameters: item.parameters })))), harness_correction_sha256: fileSha256(CORRECTION_PATH), candidate_projection_sha256: task.projection_sha256, frozen_snapshot_sha256: task.snapshot_sha256 },
    tool_calls: result.toolEvents, evidence_observations: result.observations,
    environment: { dataset_access: "frozen_read_only", ledger_mode: "simulated", initial_ledger: {}, final_ledger: finalLedger, final_state_matches_initial: Object.keys(finalLedger).length === 0, real_side_effects: false, network_scope: "bailian_inference_only" },
    timing: { started_at: startedAt, finished_at: timestamp(), duration_ms: Date.now() - startedMs }, usage: { ...result.usage, model_requests: result.requests, tool_calls: result.toolEvents.filter((item) => item.event === "start").length }, cost: { currency: "USD", total_usd: null, status: "provider_response_does_not_supply_cost" },
    attempts: Array.from({ length: Math.max(1, result.requests) }, (_, index) => ({ attempt: index + 1, outcome: result.failure ? "failed" : "succeeded", http_status: result.responseStatuses[index] ?? result.failure?.http_status ?? null, payload_sha256: result.payloadHashes[index] ?? null })), retry: { max_retries: 0, retries_used: 0 }, checkpoint: { enabled: true, sequence: completed.offset, state_sha256: completed.state_sha256, prior_event_hash: completed.event_sha256, created_at: completed.created_at }, failure: { type: result.identityValid ? result.failure?.type || null : "identity_mismatch", provider_error_code: result.failure?.provider_code || null }, result: { action: candidate?.status || "parse_failure", structured_output: candidate, structured_output_valid: Boolean(candidate), parse_error: parseError, response_sha256: candidate ? sha256(canonical(candidate)) : parseError.response_sha256, raw_provider_response_stored: false }, redaction: { applied: true, raw_sensitive_response_persisted: false, secret_leakage_detected: leakage } };
  atomicJson(tracePath, trace); return trace;
}


async function main(argv = process.argv.slice(2)) {
  const args = {}; for (let index = 0; index < argv.length; index += 2) args[argv[index]] = argv[index + 1]; const settings = loadSettings();
  if (args["--preflight"]) { const output = isAbsolute(args["--preflight"]) ? args["--preflight"] : resolve(ROOT, args["--preflight"]); const result = await preflightV31(settings, output); process.stdout.write(`${JSON.stringify(result.counts)}\n`); return result.counts.passed === 3 ? 0 : 2; }
  if (!args["--plan"] || !args["--output-dir"]) throw new Error("--plan and --output-dir required"); const planPath = resolve(ROOT, args["--plan"]); const outputDirectory = resolve(ROOT, args["--output-dir"]); const plan = readJson(planPath); const core = structuredClone(plan); delete core.plan_sha256; if (sha256(canonical(core)) !== plan.plan_sha256 || plan.run_cap !== 36) throw new Error("plan hash mismatch"); if (settings.endpointId !== plan.authoritative_preflight.endpoint_id) throw new Error("endpoint mismatch"); mkdirSync(join(outputDirectory, "traces"), { recursive: true }); mkdirSync(join(outputDirectory, "checkpoints"), { recursive: true }); const tasks = new Map(plan.tasks.flatMap((task) => task.run_ids.map((id) => [id, task]))); const traces = [];
  for (const row of plan.runs) { const trace = await executeOne(row, tasks.get(row.run_id), plan, settings, outputDirectory); traces.push(trace); process.stdout.write(`${JSON.stringify({ run_id: row.run_id, model_id: row.model_id, status: trace.status, structured: trace.result.structured_output_valid })}\n`); }
  atomicJson(join(outputDirectory, "runtime-summary.json"), { contract_type: "stage3_acceptance_runtime_summary", contract_version: "3.1.0", plan_sha256: plan.plan_sha256, counts: { planned: 36, traces: traces.length, succeeded: traces.filter((item) => item.status === "succeeded").length, invalidated: traces.filter((item) => item.status === "invalidated").length, structured: traces.filter((item) => item.result.structured_output_valid).length }, provider_requests: traces.reduce((sum, item) => sum + item.usage.model_requests, 0), cost_usd: null, cost_status: "provider_response_does_not_supply_cost" }); return traces.length === 36 ? 0 : 2;
}


if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) main().then((code) => { process.exitCode = code; }).catch((error) => { process.stderr.write(`${JSON.stringify({ status: "blocked", failure_type: safeError(error).type })}\n`); process.exitCode = 2; });
