import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { genericRepairPromptV32 } from "../../harness/live_acceptance_v3_2.mjs";


const correction = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.2.json", import.meta.url), "utf8"));


test("v3.2 freezes one model-neutral repair round", () => {
  assert.equal(correction.contract_version, "3.2.0");
  assert.equal(correction.repair_policy.maximum_repair_rounds, 1);
  assert.equal(correction.repair_policy.model_specific_repairs, false);
  assert.match(genericRepairPromptV32(), /No valid structured submission was recorded/);
  assert.doesNotMatch(genericRepairPromptV32(), /qwen|glm|deepseek/i);
});
