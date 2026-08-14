import { readFileSync } from "node:fs";

import {
  buildAnswerSchemaV35,
  buildNonAnswerSchemaV35,
  normalizePayloadV35,
} from "./live_acceptance_v3_5.mjs";


const CONFIG = JSON.parse(readFileSync(new URL("../../../contracts/run_trace_harness_config.v3.6.json", import.meta.url), "utf8"));


export function normalizePayloadV36(source, seed) {
  return normalizePayloadV35(source, seed);
}


export function buildAnswerSchemaV36(projection) {
  return buildAnswerSchemaV35(projection);
}


export function buildNonAnswerSchemaV36(projection) {
  return buildNonAnswerSchemaV35(projection);
}


export function buildRunPromptV36(projection) {
  const visible = {
    case_id: projection.case_id,
    task: projection.task,
    temporal: projection.temporal,
    financial_subject: projection.financial_subject,
    evidence_refs: projection.evidence_refs,
    evidence_contract: projection.evidence_contract,
    status_value_contract: projection.status_value_contract,
    answer_value_schema: projection.answer_value_schema,
    reason_code_vocabulary: projection.reason_code_vocabulary,
    reason_code_contract: projection.reason_code_contract,
    ...(projection.decimal_output_contract ? { decimal_output_contract: projection.decimal_output_contract } : {}),
  };
  return [
    `Execute frozen benchmark case ${projection.case_id}.`,
    projection.task.prompt,
    "Call read_frozen_case first. Read only records needed for material claims. Use calculate for arithmetic.",
    "Derive reason codes from candidate-visible facts and the reason_code_contract; do not infer hidden oracle values.",
    "For status answer call submit_candidate_answer exactly once. For any non-answer call submit_candidate_non_answer exactly once.",
    `Candidate-visible contract: ${JSON.stringify(visible)}`,
  ].join("\n");
}


export function classifyProviderAttemptV36(attempt) {
  if (attempt.no_response === true) return "provider_or_runtime_failure";
  if ([408, 429].includes(attempt.http_status) || (Number.isInteger(attempt.http_status) && attempt.http_status >= 500 && attempt.http_status <= 599)) return "provider_or_runtime_failure";
  if (attempt.provider_error_class != null && attempt.provider_error_class !== "none") return "provider_or_runtime_failure";
  if (attempt.stream_termination_reason === "empty_stream" && attempt.content_bytes === 0 && attempt.tool_call_bytes === 0 && attempt.valid_assistant_action === false) return "provider_or_runtime_failure";
  if (attempt.valid_submission === true) return "success";
  if (attempt.valid_assistant_action === true || (attempt.http_status >= 200 && attempt.http_status <= 299 && ((attempt.content_bytes || 0) > 0 || (attempt.tool_call_bytes || 0) > 0))) return "candidate_failure";
  return "indeterminate";
}


export function shouldRetryProviderAttemptV36(attempt, retriesUsed) {
  return classifyProviderAttemptV36(attempt) === "provider_or_runtime_failure"
    && retriesUsed < CONFIG.provider_retry_policy.maximum_provider_retries_per_failed_request;
}


export async function executeWithProviderRetryV36({ payload, send, sleep = async () => {}, retryAfterSeconds = null }) {
  const frozenPayload = JSON.stringify(payload);
  const attempts = [];
  for (let retryIndex = 0; retryIndex <= CONFIG.provider_retry_policy.maximum_provider_retries_per_failed_request; retryIndex += 1) {
    const replay = JSON.parse(frozenPayload);
    const attempt = await send(replay, retryIndex);
    attempts.push(attempt);
    const classification = classifyProviderAttemptV36(attempt);
    if (classification !== "provider_or_runtime_failure" || !shouldRetryProviderAttemptV36(attempt, retryIndex)) {
      return { classification, attempts, firstValidResponseAccepted: classification === "success" };
    }
    const waitSeconds = Number.isFinite(retryAfterSeconds)
      ? Math.min(Math.max(retryAfterSeconds, 0), CONFIG.provider_retry_policy.retry_after_cap_seconds)
      : CONFIG.provider_retry_policy.default_backoff_seconds;
    await sleep(waitSeconds * 1000);
  }
  throw new Error("unreachable provider retry state");
}
