// PER-63 chunk launcher for the frozen v3.11 execution harness.
//
// This is a launcher only: all execution semantics (authorization validation,
// checkpoint/resume, grading, invalidation policy, redaction) live in the
// frozen harness `harness/live_acceptance_v3_11.mjs`. One invocation executes
// one time-bounded chunk (deadline checked between units, never mid-unit) and
// exits; the frozen harness's native finalized-skip resume makes the next
// invocation continue exactly where this one stopped.
//
// Environment: BENCH_BAILIAN_API_KEY and BENCH_BAILIAN_BASE_URL pass through
// untouched. BENCH_BAILIAN_MODEL_IDS is rebuilt as a JSON array from the
// frozen config because the frozen harness JSON-parses it; the standing
// environment value is comma-separated. Model ids are public registrations,
// not secrets. The API key is never printed.

import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { executeFrozenPlanV311, createPiTransportV311 } from "../harness/live_acceptance_v3_11.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const RUN_DIR = join(ROOT, "runs", "stage3", "acceptance-20260813-v3.11");
const EXPECTED_ENDPOINT_ID = "bailian_98bd231ca931"; // carry-over endpoint verified pre-execution
const DEADLINE_MS = Number(process.env.PER63_CHUNK_DEADLINE_MS || "150000");

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const sha256 = (text) => createHash("sha256").update(text).digest("hex");
const sortValue = (value) => Array.isArray(value) ? value.map(sortValue) : (value && typeof value === "object") ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])])) : value;
const canonical = (value) => JSON.stringify(sortValue(value));

function loadSettings() {
  // Mirrors the frozen harness's loadSettings; BENCH_BAILIAN_MODEL_IDS is
  // rebuilt from the frozen config as a JSON array (the harness JSON-parses it).
  for (const name of ["BENCH_BAILIAN_API_KEY", "BENCH_BAILIAN_BASE_URL"]) {
    if (!process.env[name]) throw new Error(`missing required environment:${name}`);
  }
  const config = readJson(join(ROOT, "contracts", "run_trace_harness_config.v3.11.json"));
  const models = config.candidate_model_ids;
  process.env.BENCH_BAILIAN_MODEL_IDS = JSON.stringify(models);
  if (canonical(JSON.parse(process.env.BENCH_BAILIAN_MODEL_IDS)) !== canonical(models)) throw new Error("configured model IDs mismatch");
  const url = new URL(process.env.BENCH_BAILIAN_BASE_URL);
  const baseUrl = `${url.origin}${url.pathname.replace(/\/$/, "").replace(/\/chat\/completions$/, "")}`;
  const endpointId = `bailian_${sha256(url.origin.toLowerCase()).slice(0, 12)}`;
  if (endpointId !== EXPECTED_ENDPOINT_ID) throw new Error("endpoint drift versus carried-over preflight; hard stop");
  return { apiKey: process.env.BENCH_BAILIAN_API_KEY, baseUrl, endpointId };
}

async function main() {
  const plan = readJson(join(RUN_DIR, "stage3_acceptance_plan.v3.11.json"));
  const preflight = readJson(join(RUN_DIR, "preflight.json"));
  const authorization = readJson(join(RUN_DIR, "authorization.run.json"));
  const settings = loadSettings();
  const result = await executeFrozenPlanV311({
    plan,
    authorization,
    preflight,
    outputDirectory: RUN_DIR,
    send: createPiTransportV311(settings),
    endpointId: settings.endpointId,
    deadlineMs: DEADLINE_MS,
    progressPath: join(RUN_DIR, "driver-progress.jsonl"),
    invalidations: [],
  });
  const { resumed = null, executed = null, invalidated = null, remaining = null } = result || {};
  const done = result?.contract_type === "stage3_acceptance_runtime_summary";
  process.stdout.write(`${JSON.stringify({ done, counts: result?.counts ?? null, resumed, executed, invalidated, remaining })}\n`);
}

main().catch((error) => {
  process.stdout.write(`${JSON.stringify({ done: false, hard_stop: true, failure_type: String(error.message).split(":")[0] })}\n`);
  process.exitCode = 2;
});
