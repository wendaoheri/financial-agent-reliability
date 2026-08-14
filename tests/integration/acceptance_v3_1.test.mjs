import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { buildSubmitSchemaV31 } from "../../harness/live_acceptance_v3_1.mjs";


const projection = JSON.parse(readFileSync(new URL("../../cases/candidate_v3/case-public-fkw-01-normal-v3.json", import.meta.url), "utf8"));
const correction = JSON.parse(readFileSync(new URL("../../contracts/run_trace_harness_config.v3.1.json", import.meta.url), "utf8"));


test("v3.1 preserves v3 and records the failed preflight rationale", () => {
  assert.equal(correction.contract_version, "3.1.0");
  assert.equal(correction.supersedes.version, "3.0.0");
  assert.match(correction.supersedes.rationale, /value schema/i);
});


test("dynamic submit schema publishes the case answer shape and null branch", () => {
  const schema = buildSubmitSchemaV31(projection);
  assert.equal(schema.properties.value.anyOf[0].properties.year.type, "string");
  assert.deepEqual(schema.properties.value.anyOf[1], { type: "null" });
  assert.equal(JSON.stringify(schema).includes("expected_value"), false);
  assert.equal(JSON.stringify(schema).includes("27811517000000"), false);
});
