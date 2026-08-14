import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  assertPinnedRuntimeV37,
  buildToolSchemasV37,
  executeFrozenPlanV37,
  executeIdentityPreflightV37,
  normalizePayloadV37,
  validateAuthorizationV37,
} from "../../harness/live_acceptance_v3_7.mjs";

const plan = JSON.parse(readFileSync(new URL("../../contracts/stage3_acceptance_plan.v3.7.json", import.meta.url), "utf8"));
const fixtureAnswers = JSON.parse(readFileSync(new URL("../fixtures/acceptance_v3_7/candidate_answers.synthetic.json", import.meta.url), "utf8"));
const modelIds = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"];

function preflightAuthorization() {
  return {
    paid_calls_authorized: true,
    authorization_kind: "identity_preflight",
    maximum_model_units: 3,
    plan_sha256: plan.plan_sha256,
    exact_model_ids: modelIds,
  };
}

async function passingPreflight() {
  return executeIdentityPreflightV37({
    plan,
    authorization: preflightAuthorization(),
    send: async ({ payload }) => ({
      response_model_id: payload.model,
      http_status: 200,
      assistant_action: true,
      parameters_honored: true,
      tool_calls: [{ id: `preflight-${payload.model}`, name: "read_frozen_case", arguments: { case_id: plan.tasks[0].case_id } }],
      usage: { input: 1, output: 1 },
    }),
  });
}

function authorization(preflight) {
  return {
    paid_calls_authorized: true,
    authorization_kind: "financial_acceptance_36_run",
    plan_sha256: plan.plan_sha256,
    preflight_sha256: preflight.preflight_sha256,
    authorized_run_ids: plan.runs.map((row) => row.run_id),
    exact_model_ids: modelIds,
  };
}

test("offline frozen plan is rejected before provider invocation", async () => {
  let calls = 0;
  await assert.rejects(() => executeFrozenPlanV37({ plan, outputDirectory: mkdtempSync(join(tmpdir(), "v37-blocked-")), send: async () => { calls += 1; } }), /authorization/);
  assert.equal(calls, 0);
});

test("CLI fails closed before credential loading when authorization is absent", () => {
  const directory = mkdtempSync(join(tmpdir(), "v37-cli-blocked-"));
  const authPath = join(directory, "authorization.json");
  const outputPath = join(directory, "preflight.json");
  writeFileSync(authPath, JSON.stringify({ paid_calls_authorized: false }));
  const env = { ...process.env };
  delete env.BENCH_BAILIAN_API_KEY;
  delete env.BENCH_BAILIAN_BASE_URL;
  delete env.BENCH_BAILIAN_MODEL_IDS;
  const child = spawnSync(process.execPath, [fileURLToPath(new URL("../../harness/live_acceptance_v3_7.mjs", import.meta.url)), "--mode", "preflight", "--plan", fileURLToPath(new URL("../../contracts/stage3_acceptance_plan.v3.7.json", import.meta.url)), "--authorization", authPath, "--output", outputPath], { encoding: "utf8", env });
  assert.equal(child.status, 2);
  assert.match(child.stderr, /separate paid preflight authorization/);
  assert.equal(existsSync(outputPath), false);
});

test("authorization binds plan, exact models, scope, and independently hashed preflight", async () => {
  const preflight = await passingPreflight();
  const auth = authorization(preflight);
  assert.equal(validateAuthorizationV37(plan, auth, preflight), true);
  assert.throws(() => validateAuthorizationV37(plan, { ...auth, plan_sha256: "f".repeat(64) }, preflight), /plan/);
  assert.throws(() => validateAuthorizationV37(plan, auth, { ...preflight, decision: "blocked" }), /hash|preflight/);
});

test("synthetic transport exercises stateful tools and emits 36 validated artifacts without network", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v37-matrix-"));
  const preflight = await passingPreflight();
  const summary = await executeFrozenPlanV37({
    plan,
    preflight,
    authorization: authorization(preflight),
    outputDirectory,
    send: async ({ payload }) => {
      const visible = JSON.parse(payload.messages[0].content[0].text.split("Candidate-visible contract:").at(-1));
      assert.deepEqual(payload.tools, buildToolSchemasV37(visible));
      const task = plan.tasks.find((item) => item.case_id === visible.case_id);
      const snapshot = JSON.parse(readFileSync(new URL(`../../${task.snapshot_path}`, import.meta.url), "utf8"));
      const answer = fixtureAnswers[visible.case_id];
      const priorToolResults = payload.messages.filter((message) => message.role === "toolResult");
      if (!priorToolResults.length) {
        const evidenceIds = [...new Set([...visible.evidence_contract.material_record_ids, ...answer.evidence_record_ids])];
        const calls = [{ id: "read-case", name: "read_frozen_case", arguments: { case_id: visible.case_id } }];
        calls.push(...evidenceIds.map((record_id, index) => ({ id: `read-evidence-${index}`, name: "read_frozen_evidence", arguments: { snapshot_id: snapshot.snapshot_id, record_id } })));
        return { response_model_id: payload.model, http_status: 200, assistant_action: true, tool_calls: calls, usage: { input: 10, output: 10 } };
      }
      const { status, value, ...shared } = answer;
      const submission = status === "answer"
        ? { id: "submit", name: "submit_candidate_answer", arguments: { value, ...shared } }
        : { id: "submit", name: "submit_candidate_non_answer", arguments: { status, ...shared } };
      return { response_model_id: payload.model, http_status: 200, assistant_action: true, tool_calls: [submission], usage: { input: 10, output: 10 } };
    },
  });
  assert.equal(summary.counts.traces, 36);
  assert.equal(summary.counts.graders, 36);
  assert.equal(summary.counts.accepted, 36);
  assert.equal(readdirSync(join(outputDirectory, "traces")).length, 36);
  assert.equal(readdirSync(join(outputDirectory, "graders")).length, 36);
  assert.equal(readdirSync(join(outputDirectory, "checkpoints")).length, 36);
  const trace = JSON.parse(readFileSync(join(outputDirectory, "traces", `${plan.runs[0].run_id}.json`), "utf8"));
  assert.equal(trace.logical_requests.length, 2);
  assert.ok(trace.permission.observed_operations.includes("read_frozen_case"));
  assert.ok(trace.permission.observed_operations.some((name) => name.startsWith("submit_candidate_")));
});

test("response identity mismatch is not emitted as an accepted trace", async () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), "v37-identity-blocked-"));
  const preflight = await passingPreflight();
  await assert.rejects(() => executeFrozenPlanV37({
    plan,
    preflight,
    authorization: authorization(preflight),
    outputDirectory,
    send: async () => ({ response_model_id: "unexpected-fallback", http_status: 200, assistant_action: true, tool_calls: [], usage: { input: 1, output: 1 } }),
  }), /grader rejected/);
  assert.equal(existsSync(join(outputDirectory, "traces")), false);
  assert.equal(existsSync(join(outputDirectory, "graders")), false);
});

test("all exact models share controls and actual six-tool schemas", () => {
  assert.equal(assertPinnedRuntimeV37(), "0.73.1");
  const projection = JSON.parse(readFileSync(new URL(`../../${plan.tasks[0].projection_path}`, import.meta.url), "utf8"));
  const tools = buildToolSchemasV37(projection);
  for (const model of modelIds) {
    const payload = normalizePayloadV37({ model, tools }, 7);
    assert.equal(payload.temperature, 0);
    assert.equal(payload.parallel_tool_calls, false);
    assert.equal(payload.tools.length, 6);
    assert.equal(payload.enable_thinking, model === "qwen3.8-max" ? false : undefined);
  }
});
