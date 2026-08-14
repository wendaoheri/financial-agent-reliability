import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { executeFrozenPlanV38, executeIdentityPreflightV38, buildToolSchemasV38 } from "../harness/live_acceptance_v3_8.mjs";

const ROOT = new URL("../", import.meta.url);
const plan = JSON.parse(readFileSync(new URL("../contracts/stage3_acceptance_plan.v3.8.json", import.meta.url), "utf8"));
const fixtureAnswers = JSON.parse(readFileSync(new URL("../tests/fixtures/acceptance_v3_7/candidate_answers.synthetic.json", import.meta.url), "utf8"));
const modelIds = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"];

function calculationCall(visible, snapshot) {
  const inputs = visible.task.inputs;
  if (inputs.operation === "scale") {
    const record = snapshot.records.find((item) => String(item.payload.year) === String(inputs.target_year));
    return { id: "calculate", name: "calculate", arguments: { operation: "divide", inputs: [String(record.payload.value), String(inputs.divisor)] } };
  }
  if (inputs.operation === "method" && inputs.method === "three_year_average") return { id: "calculate", name: "calculate", arguments: { operation: "average", inputs: snapshot.records.map((item) => String(item.payload.value)) } };
  if (inputs.operation === "threshold") {
    const record = snapshot.records.find((item) => String(item.payload.year) === String(inputs.target_year));
    return { id: "calculate", name: "calculate", arguments: { operation: "threshold", inputs: [String(record.payload.value), String(inputs.threshold)] } };
  }
  return null;
}

const preflight = await executeIdentityPreflightV38({
  plan,
  authorization: { paid_calls_authorized: true, authorization_kind: "identity_preflight", maximum_model_units: 3, plan_sha256: plan.plan_sha256, exact_model_ids: modelIds },
  send: async ({ payload }) => ({ response_model_id: payload.model, http_status: 200, assistant_action_valid: true, parameters_honored: true, tool_calls: [{ id: `preflight-${payload.model}`, name: "read_frozen_case", arguments: { case_id: plan.tasks[0].case_id } }], usage: { input: 1, output: 1 } }),
});
const outputDirectory = mkdtempSync(join(tmpdir(), "v38-audit-chain-"));
const summary = await executeFrozenPlanV38({
  plan,
  preflight,
  authorization: { paid_calls_authorized: true, authorization_kind: "financial_acceptance_36_run", plan_sha256: plan.plan_sha256, preflight_sha256: preflight.preflight_sha256, authorized_run_ids: plan.runs.map((row) => row.run_id), exact_model_ids: modelIds },
  outputDirectory,
  send: async ({ payload }) => {
    const visible = JSON.parse(payload.messages[0].content[0].text.split("Candidate-visible contract:").at(-1));
    const task = plan.tasks.find((item) => item.case_id === visible.case_id);
    const snapshot = JSON.parse(readFileSync(new URL(task.snapshot_path, ROOT), "utf8"));
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
  },
});
console.log(JSON.stringify({ outputDirectory, preflight_decision: preflight.decision, counts: summary.counts }));
