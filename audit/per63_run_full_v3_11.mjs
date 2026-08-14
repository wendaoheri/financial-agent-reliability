// PER-63 run-to-completion launcher for the frozen v3.11 execution harness.
//
// Launcher only: all execution semantics live in the frozen harness
// `harness/live_acceptance_v3_11.mjs` (imported UNMODIFIED). A single call to
// executeFrozenPlanV311 with no deadline/limit processes the entire 550-unit
// continuation scope in one process, exactly as the v3.10 round processed its
// 270-unit first round. The frozen harness's native checkpoint/resume means a
// restart would skip already-finalized units byte-exact, so this process is
// safe to relaunch if it ever dies. Environment handling matches
// per63_run_chunks_v3_11.mjs. The API key is never printed.

import { existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { executeFrozenPlanV311, createPiTransportV311 } from "../harness/live_acceptance_v3_11.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const RUN_DIR = join(ROOT, "runs", "stage3", "acceptance-20260813-v3.11");
const EXPECTED_ENDPOINT_ID = "bailian_98bd231ca931"; // carry-over endpoint verified pre-execution

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const sha256 = (text) => createHash("sha256").update(text).digest("hex");
const sortValue = (value) => Array.isArray(value) ? value.map(sortValue) : (value && typeof value === "object") ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortValue(value[key])])) : value;
const canonical = (value) => JSON.stringify(sortValue(value));

function loadSettings() {
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

// Report-only invalidations for consumed-but-unfreezable units (frozen policy:
// never silently replaced; re-executing a started run_id is forbidden). Stored
// as an explicit, auditable input so any relaunch handles them idempotently.
function readPendingInvalidations() {
  const path = join(RUN_DIR, "pending-invalidations.json");
  if (!existsSync(path)) return [];
  return readJson(path).entries;
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
    deadlineMs: null,
    limit: null,
    progressPath: join(RUN_DIR, "driver-progress.jsonl"),
    invalidations: readPendingInvalidations(),
  });
  process.stdout.write(`${JSON.stringify({ done: true, summary: result })}\n`);
}

main().catch((error) => {
  process.stdout.write(`${JSON.stringify({ done: false, hard_stop: true, failure_type: String(error.message).split(":")[0], detail: String(error.message).slice(0, 400) })}\n`);
  process.exitCode = 2;
});
