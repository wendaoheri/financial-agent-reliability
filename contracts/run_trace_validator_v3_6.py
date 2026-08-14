"""Deterministic v3.6 run-trace and provider-failure validation.

This module is deliberately provider-response-text blind.  It accepts only the
redacted fields frozen in the v3.6 trace contract and never reads credentials.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v3.6.json"
MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
TOOLS = [
    "read_frozen_case",
    "read_frozen_evidence",
    "calculate",
    "simulated_ledger",
    "submit_candidate_answer",
    "submit_candidate_non_answer",
]
HEX64 = set("0123456789abcdef")
SECRET_TEXT = re.compile(r"(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,})", re.IGNORECASE)
SECRET_KEYS = {"api_key", "authorization", "bearer_token", "password", "client_secret"}


class HarnessContractV36Error(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_run_id(identity: Mapping[str, Any]) -> str:
    return f"run_{content_sha256(identity)[:32]}"


def scan_persisted_value_for_secrets(value: Any, path: str = "$") -> list[str]:
    """Scan synthetic/persisted values without reading environment credentials."""
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in SECRET_KEYS:
                findings.append(child_path)
            findings.extend(scan_persisted_value_for_secrets(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_persisted_value_for_secrets(child, f"{path}[{index}]"))
    elif isinstance(value, str) and SECRET_TEXT.search(value):
        findings.append(path)
    return findings


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def validate_harness_config_v36(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config is None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if config.get("contract_version") != "3.6.0" or config.get("status") != "frozen_offline_validated":
        errors.append("v3.6 config must be frozen_offline_validated")
    if config.get("candidate_model_ids") != MODELS:
        errors.append("exact model IDs and order required")
    if config.get("tool_names") != TOOLS:
        errors.append("exact shared tool order required")
    provider = config.get("provider") or {}
    controls = provider.get("common_request_controls") or {}
    if controls.get("tool_choice") != "auto" or controls.get("tool_stream") is not False or controls.get("parallel_tool_calls") is not False:
        errors.append("Bailian common request controls invalid")
    if (provider.get("qwen3.8-max") or {}).get("enable_thinking") is not False:
        errors.append("Qwen thinking must be explicitly disabled")
    retry = config.get("provider_retry_policy") or {}
    if retry.get("maximum_provider_retries_per_failed_request") != 1 or retry.get("maximum_attempts_per_request") != 2:
        errors.append("symmetric retry cap invalid")
    if retry.get("semantic_failure_retries") != 0 or retry.get("same_payload_seed_tools_parameters") is not True:
        errors.append("semantic retry or replay identity policy invalid")
    context = config.get("context_contract") or {}
    if context.get("same_prompt_tools_budget_retry_grader_for_all_models") is not True:
        errors.append("candidate context is not symmetric")
    execution = config.get("execution") or {}
    if execution.get("paid_calls_authorized") is not False or execution.get("offline_validation_only") is not True:
        errors.append("v3.6 implementation issue must remain offline only")
    if errors:
        raise HarnessContractV36Error("; ".join(errors))
    return {"config_sha256": file_sha256(CONFIG_PATH), "models": 3, "tools": 6}


def classify_attempt(attempt: Mapping[str, Any]) -> str:
    """Classify one redacted attempt without consulting candidate semantics."""
    if attempt.get("no_response") is True:
        return "provider_or_runtime_failure"
    status = attempt.get("http_status")
    if status in {408, 429} or isinstance(status, int) and 500 <= status <= 599:
        return "provider_or_runtime_failure"
    if attempt.get("provider_error_class") not in {None, "none"}:
        return "provider_or_runtime_failure"
    if (
        attempt.get("stream_termination_reason") == "empty_stream"
        and attempt.get("content_bytes") == 0
        and attempt.get("tool_call_bytes") == 0
        and attempt.get("valid_assistant_action") is False
    ):
        return "provider_or_runtime_failure"
    if attempt.get("valid_submission") is True:
        return "success"
    if attempt.get("valid_assistant_action") is True or (
        isinstance(status, int)
        and 200 <= status <= 299
        and (attempt.get("content_bytes", 0) > 0 or attempt.get("tool_call_bytes", 0) > 0)
    ):
        return "candidate_failure"
    return "indeterminate"


def validate_run_trace_v36(trace: Mapping[str, Any]) -> dict[str, Any]:
    validate_harness_config_v36()
    errors: list[str] = []
    if trace.get("contract_type") != "run_trace" or trace.get("contract_version") != "3.6.0":
        errors.append("trace must be v3.6")
    identity = trace.get("run_identity") or {}
    requested = identity.get("requested_model_id")
    if requested not in MODELS:
        errors.append("requested model identity invalid")
    if trace.get("run_id") != build_run_id(identity):
        errors.append("run id mismatch")
    if identity.get("harness_config_sha256") != file_sha256(CONFIG_PATH):
        errors.append("config hash mismatch")
    provider = trace.get("provider") or {}
    if provider.get("requested_model_id") != requested:
        errors.append("provider requested model mismatch")
    attempts = trace.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        errors.append("attempt count must be one or two")
        attempts = []
    classifications: list[str] = []
    forbidden = {"error_message", "raw_response", "response_body", "api_key"}
    for index, attempt in enumerate(attempts):
        missing = {
            "attempt", "retry_index", "http_status", "no_response", "provider_error_class",
            "provider_error_code", "stream_termination_reason", "content_bytes", "tool_call_bytes",
            "payload_sha256", "seed", "started_at", "finished_at", "duration_ms", "token_usage",
            "last_valid_tool_turn", "valid_assistant_action", "valid_submission",
        } - set(attempt)
        if missing:
            errors.append(f"attempt {index + 1} missing required fields: {sorted(missing)}")
            continue
        if forbidden & set(attempt):
            errors.append("raw or sensitive provider fields forbidden")
        if attempt.get("attempt") != index + 1 or attempt.get("retry_index") != index:
            errors.append("attempt and retry indexes invalid")
        if not _sha(attempt.get("payload_sha256")):
            errors.append("payload hash invalid")
        classifications.append(classify_attempt(attempt))
    if len(attempts) == 2:
        if classifications and classifications[0] != "provider_or_runtime_failure":
            errors.append("semantic failure must not be retried")
        first, second = attempts
        replay_fields = ["payload_sha256", "seed", "model_id", "tool_schema_sha256", "parameters_sha256"]
        if any(first.get(field) != second.get(field) for field in replay_fields):
            errors.append("provider retry must replay identical payload, seed, model, tools, and parameters")
    retry = trace.get("retry") or {}
    if retry.get("maximum_retries") != 1 or retry.get("retries_used") != max(0, len(attempts) - 1):
        errors.append("retry accounting invalid")
    if len(attempts) == 2:
        retry_after = retry.get("retry_after_seconds")
        expected_backoff = min(retry_after, 30) if isinstance(retry_after, (int, float)) and retry_after >= 0 else 2
        expected_source = "retry_after" if isinstance(retry_after, (int, float)) and retry_after >= 0 else "default"
        if retry.get("backoff_seconds_applied") != expected_backoff or retry.get("backoff_source") != expected_source:
            errors.append("retry backoff does not honor capped Retry-After or the frozen default")
    elif retry.get("backoff_seconds_applied") != 0 or retry.get("backoff_source") != "not_applicable":
        errors.append("non-retried request must not record backoff")
    final_class = classifications[-1] if classifications else "indeterminate"
    persisted = (trace.get("failure") or {}).get("class")
    candidate_scored = (trace.get("result") or {}).get("candidate_scored")
    status = trace.get("status")
    if final_class == "success":
        expected_class, expected_status, expected_scored = None, "succeeded", True
    elif final_class == "candidate_failure":
        expected_class, expected_status, expected_scored = "candidate_failure", "candidate_failed", True
    elif final_class == "provider_or_runtime_failure":
        expected_class, expected_status, expected_scored = "provider_or_runtime_failure", "invalid_provider_or_runtime", False
    else:
        expected_class, expected_status, expected_scored = "indeterminate", "invalid_provider_or_runtime", False
    if persisted != expected_class or status != expected_status or candidate_scored is not expected_scored:
        errors.append("failure class, status, and candidate scoring policy disagree")
    result = trace.get("result") or {}
    if result.get("raw_provider_response_stored") is not False:
        errors.append("raw provider response persistence forbidden")
    redaction = trace.get("redaction") or {}
    if redaction.get("raw_submission_arguments_persisted") is not False:
        errors.append("raw submission arguments persistence forbidden")
    environment = trace.get("environment") or {}
    if environment.get("real_side_effects") is not False:
        errors.append("real side effects forbidden")
    if errors:
        raise HarnessContractV36Error("; ".join(errors))
    return {
        "status": status,
        "failure_class": expected_class,
        "candidate_scored": expected_scored,
        "retry": {"retries_used": len(attempts) - 1, "attempts": len(attempts)},
    }
