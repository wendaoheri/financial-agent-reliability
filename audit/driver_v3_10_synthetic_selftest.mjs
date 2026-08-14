// Synthetic self-test for the PER-59 resumable driver. No paid calls: uses the
// same fixture-answer synthetic transport as the frozen integration test.
// Verifies: (1) chunked execution + resume skips finalized runs untouched,
// (2) all 270 synthetic units pass the frozen validator + grader end-to-end,
// (3) checkpoint hash chains verify, (4) a tampered/partial checkpoint causes a
// hard stop instead of silent replacement.

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";

import {
  buildToolSchemasV310,
  executeIdentityPreflightV310,
  firstRoundRunsV310,
} from "../harness/live_acceptance_v3_10.mjs";
import { executeResumable, finalizedState, verifyCheckpointChain } from "./driver_v3_10_live_resume.mjs";

const ROOT = new URL("..", import.meta.url).pathname;
const config = JSON.parse(readFileSync(new URL("../contracts/run_trace_harness_config.v3.10.json", import.meta.url), "utf8"));
const plan = JSON.parse(readFileSync(new URL("../contracts/stage3_acceptance_plan.v3.10.json", import.meta.url), "utf8"));
const fixtureAnswers = JSON.parse(readFileSync(new URL("../tests/fixtures/acceptance_v3_10/candidate_answers.synthetic.json", import.meta.url), "utf8"));
const modelIds = [...config.candidate_model_ids];

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])]));
  return value;
}
function canonical(value) { return JSON.stringify(sortValue(value)); }
function sha256(value) { return createHash("sha256").update(Buffer.from(String(value))).digest("hex"); }

async function syntheticPreflight() {
  return executeIdentityPreflightV310({
    plan,
    authorization: { paid_calls_authorized: true, authorization_kind: "identity_preflight", maximum_model_units: 3, plan_sha256: plan.plan_sha256, exact_model_ids: modelIds },
    send: async ({ payload }) => ({ response_model_id: payload.model, http_status: 200, assistant_action_valid: true, parameters_honored: true, tool_calls: [{ id: `preflight-${payload.model}`, name: "read_frozen_case", arguments: { case_id: plan.tasks[0].case_id } }], usage: { input: 1, output: 1 } }),
  });
}
function runAuthorization(preflight) {
  return { paid_calls_authorized: true, authorization_kind: "financial_acceptance_270_run", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, authorized_run_ids: firstRoundRunsV310(plan).map((row) => row.run_id), exact_model_ids: modelIds };
}
function calculationCall(visible, snapshot) {
  const inputs = visible.task.inputs;
  const recordForYear = (year) => snapshot.records.find((item) => String(item.payload.year) === String(year));
  if (inputs.operation === "scale") {
    const record = recordForYear(inputs.target_year);
    return { id: "calculate", name: "calculate", arguments: { operation: "divide", inputs: [String(record.payload.value), String(inputs.divisor)] } };
  }
  if (inputs.operation === "method" && inputs.method === "three_year_average") return { id: "calculate", name: "calculate", arguments: { operation: "average", inputs: snapshot.records.map((item) => String(item.payload.value)) } };
  if (inputs.operation === "threshold") {
    const record = recordForYear(inputs.target_year);
    return { id: "calculate", name: "calculate", arguments: { operation: "threshold", inputs: [String(record.payload.value), String(inputs.threshold)] } };
  }
  if (inputs.operation === "average") {
    return { id: "calculate", name: "calculate", arguments: { operation: "average", inputs: inputs.years.map((year) => String(recordForYear(year).payload.value)) } };
  }
  return null;
}
function syntheticSend() {
  return async ({ payload }) => {
    const visible = JSON.parse(payload.messages[0].content[0].text.split("Candidate-visible contract:").at(-1));
    const task = plan.tasks.find((item) => item.case_id === visible.case_id);
    const snapshot = JSON.parse(readFileSync(new URL(`../${task.snapshot_path}`, import.meta.url), "utf8"));
    const answer = fixtureAnswers[visible.case_id];
    const priorToolResults = payload.messages.filter((message) => message.role === "toolResult");
    if (!priorToolResults.length) {
      const evidenceIds = [...new Set([...visible.evidence_contract.material_record_ids, ...answer.evidence_record_ids])];
      const calls = [{ id: "read-case", name: "read_frozen_case", arguments: { case_id: visible.case_id } }];
      calls.push(...evidenceIds.map((record_id, index) => ({ id: `read-evidence-${index}`, name: "read_frozen_evidence", arguments: { snapshot_id: snapshot.snapshot_id, record_id } })));
      const calculation = calculationCall(visible, snapshot);
      if (calculation) calls.push(calculation);
      return { response_model_id: payload.model, http_status: 200, assistant_action_valid: true, tool_calls: calls, usage: { input: 10, output: 10 } };
    }
    const { status, value, ...shared } = answer;
    const submission = status === "answer" ? { id: "submit", name: "submit_candidate_answer", arguments: { value, ...shared } } : { id: "submit", name: "submit_candidate_non_answer", arguments: { status, ...shared } };
    return { response_model_id: payload.model, http_status: 200, assistant_action_valid: true, tool_calls: [submission], usage: { input: 10, output: 10 } };
  };
}

async function main() {
  const preflight = await syntheticPreflight();
  const authorization = runAuthorization(preflight);
  const outputDirectory = mkdtempSync(join(tmpdir(), "v310-driver-selftest-"));

  // chunk 1: execute only the first 100 runs
  const chunk1 = await executeResumable({ plan, authorization, preflight, outputDirectory, send: syntheticSend(), limit: 100 });
  assert.equal(chunk1.status, "chunk_complete");
  assert.equal(chunk1.executed, 100);
  assert.equal(chunk1.resumed, 0);
  assert.equal(chunk1.remaining, 170);
  const traceSnapshot = readFileSync(join(outputDirectory, "traces", `${firstRoundRunsV310(plan)[0].run_id}.json`), "utf8");

  // chunk 2: resume to completion; finalized artifacts must stay byte-exact
  const summary = await executeResumable({ plan, authorization, preflight, outputDirectory, send: syntheticSend() });
  assert.deepEqual(summary.counts, { planned: 270, candidates: 270, traces: 270, graders: 270, accepted: 270, invalidated: 0 });
  assert.equal(readFileSync(join(outputDirectory, "traces", `${firstRoundRunsV310(plan)[0].run_id}.json`), "utf8"), traceSnapshot, "resumed run artifacts must be untouched");

  // all 270 checkpoint chains verify with terminal run_completed
  for (const row of firstRoundRunsV310(plan)) {
    const chain = verifyCheckpointChain(join(outputDirectory, "checkpoints", `${row.run_id}.jsonl`), row.run_id);
    assert.ok(chain.valid, `${row.run_id}: ${chain.reason}`);
    assert.equal(chain.events.at(-1).event_type, "run_completed");
    assert.equal(finalizedState(outputDirectory, row.run_id), "finalized");
  }

  // a partially written checkpoint (simulated interruption) must hard stop
  const partialDir = mkdtempSync(join(tmpdir(), "v310-driver-partial-"));
  const firstRow = firstRoundRunsV310(plan)[0];
  mkdirSync(join(partialDir, "checkpoints"), { recursive: true });
  writeFileSync(join(partialDir, "checkpoints", `${firstRow.run_id}.jsonl`), "");
  assert.equal(finalizedState(partialDir, firstRow.run_id), "partial");
  await assert.rejects(
    () => executeResumable({ plan, authorization, preflight, outputDirectory: partialDir, send: syntheticSend() }),
    /resume hard stop/,
  );

  // a tampered finalized checkpoint must also hard stop (never silently rerun)
  const target = firstRow.run_id;
  const path = join(outputDirectory, "checkpoints", `${target}.jsonl`);
  const lines = readFileSync(path, "utf8").trim().split("\n");
  const event = JSON.parse(lines[1]);
  event.payload = { ...event.payload, tampered: true };
  lines[1] = canonical(event);
  writeFileSync(path, `${lines.join("\n")}\n`);
  assert.equal(finalizedState(outputDirectory, target), "partial");
  await assert.rejects(
    () => executeResumable({ plan, authorization, preflight, outputDirectory, send: syntheticSend() }),
    /resume hard stop/,
  );

  // explicit invalidation (report-only, never replace) unblocks the scope and
  // freezes a forensic report; the remaining finalized units stay untouched.
  // Remove the target's never-frozen artifacts first to mirror the real
  // failure mode (validator rejected the trace before persistence).
  for (const sub of ["traces", "graders", "candidates"]) unlinkSync(join(outputDirectory, sub, `${target}.json`));
  const invalidationReason = "self-test: independent validator rejected generated artifacts (synthetic)";
  const finalSummary = await executeResumable({ plan, authorization, preflight, outputDirectory, send: syntheticSend(), invalidations: [{ run_id: target, reason: invalidationReason }] });
  assert.deepEqual(finalSummary.counts, { planned: 270, candidates: 269, traces: 269, graders: 269, accepted: 269, invalidated: 1 });
  assert.deepEqual(finalSummary.invalidated_run_ids, [target]);
  const report = JSON.parse(readFileSync(join(outputDirectory, "invalidated-runs.json"), "utf8"));
  assert.equal(report.entries.length, 1);
  assert.equal(report.entries[0].run_id, target);
  assert.equal(report.entries[0].replaced_or_reexecuted, false);
  assert.equal(report.entries[0].reason, invalidationReason);

  // a later invocation WITHOUT explicit invalidations auto-loads the persisted
  // invalidation report and still completes the scope
  const autoResumed = await executeResumable({ plan, authorization, preflight, outputDirectory, send: syntheticSend() });
  assert.deepEqual(autoResumed.counts, { planned: 270, candidates: 269, traces: 269, graders: 269, accepted: 269, invalidated: 1 });
  assert.equal(JSON.parse(readFileSync(join(outputDirectory, "invalidated-runs.json"), "utf8")).entries.length, 1, "auto-loaded invalidation must not duplicate the report entry");

  // invalidating a finalized run is refused (carry the real invalidation so the
  // loop can pass the already-invalidated sequence-1 unit first)
  const finalizedTarget = firstRoundRunsV310(plan)[1].run_id;
  await assert.rejects(
    () => executeResumable({ plan, authorization, preflight, outputDirectory, send: syntheticSend(), invalidations: [{ run_id: target, reason: invalidationReason }, { run_id: finalizedTarget, reason: "must be refused" }] }),
    /refusing invalidation/,
  );

  console.log(JSON.stringify({ status: "pass", checks: ["chunk+resume", "270/270 accepted", "chains verified", "partial hard stop", "tamper hard stop", "invalidation report-only path", "invalidation guard rails"], outputDirectory }));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
