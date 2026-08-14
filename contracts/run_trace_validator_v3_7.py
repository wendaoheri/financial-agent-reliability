"""Strict, plan-bound validation for superseding Stage-3 traces (v3.7)."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v3.7.json"
PLAN_PATH = ROOT / "contracts" / "stage3_acceptance_plan.v3.7.json"
SCHEMA_PATH = ROOT / "contracts" / "run_trace.schema.v3.7.json"
MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SECRET_TEXT = re.compile(r"(?:Bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,}|AKID[A-Za-z0-9_-]{8,})", re.I)
SECRET_KEYS = {"api_key", "authorization", "bearer_token", "password", "client_secret", "access_token"}


class HarnessContractV37Error(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_run_id(identity: Mapping[str, Any]) -> str:
    return f"run_{content_sha256(identity)[:32]}"


def scan_persisted_value_for_secrets(value: Any, path: str = "$") -> list[str]:
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


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(errors: list[str]) -> None:
    if errors:
        raise HarnessContractV37Error("; ".join(errors))


def validate_run_trace_v37(
    trace: Mapping[str, Any],
    *,
    plan: Mapping[str, Any] | None = None,
    scan_companions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate schema, frozen identity, every logical request, and hard safety gates."""
    errors: list[str] = []
    secret_findings = scan_persisted_value_for_secrets(trace)
    for index, companion in enumerate(scan_companions or []):
        secret_findings.extend(f"companion[{index}]{item[1:]}" for item in scan_persisted_value_for_secrets(companion))
    if secret_findings:
        errors.append(f"secret-like persisted value: {sorted(secret_findings)}")
        _fail(errors)

    # Emit stable contract-domain failures before generic schema diagnostics.
    identity_preview = trace.get("run_identity") or {}
    requested_preview = identity_preview.get("requested_model_id")
    provider_preview = trace.get("provider") or {}
    if provider_preview.get("response_model_id") != requested_preview:
        errors.append("response model fallback or mismatch")
    for request_index, request in enumerate(trace.get("logical_requests") or [], 1):
        for attempt in request.get("attempts") or []:
            if attempt.get("model_id") != requested_preview:
                errors.append(f"request {request_index} attempt model mismatch")
    _fail(errors)

    schema = _load(SCHEMA_PATH)
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(trace), key=lambda item: list(item.path))
    if schema_errors:
        errors.extend(f"schema:{'/'.join(map(str, item.path)) or '$'}:{item.message}" for item in schema_errors)
        _fail(errors)

    config = _load(CONFIG_PATH)
    plan = dict(plan or _load(PLAN_PATH))
    identity = trace["run_identity"]
    if trace["run_id"] != build_run_id(identity):
        errors.append("run id does not bind run identity")
    row = next((item for item in plan["runs"] if item["run_id"] == trace["run_id"]), None)
    if row is None or row.get("run_identity") != identity:
        errors.append("run identity is not an exact frozen plan membership")
    if identity["requested_model_id"] not in MODELS:
        errors.append("requested model is not an exact candidate ID")
    if identity["harness_config_sha256"] != file_sha256(CONFIG_PATH):
        errors.append("harness config hash mismatch")
    if identity["plan_core_sha256"] != plan["plan_core_sha256"]:
        errors.append("plan core hash mismatch")
    task = next((item for item in plan["tasks"] if trace["run_id"] in item["run_ids"]), None)
    if task is None or task.get("case_id") != identity["case_id"]:
        errors.append("run is not bound to one frozen task")

    requested = identity["requested_model_id"]
    if trace["provider"]["requested_model_id"] != requested:
        errors.append("provider requested model mismatch")
    if trace["provider"]["response_model_id"] != requested:
        errors.append("response model fallback or mismatch")

    logical_requests = trace["logical_requests"]
    max_requests = config["resource_budget"]["max_model_requests"]
    if len(logical_requests) > max_requests:
        errors.append("logical request budget exceeded")
    provider_attempts = 0
    for request_index, request in enumerate(logical_requests, 1):
        if request["request_index"] != request_index:
            errors.append(f"logical request {request_index} index mismatch")
        if request["model_id"] != requested:
            errors.append(f"logical request {request_index} model mismatch")
        if request["seed"] != identity["seed"]:
            errors.append(f"logical request {request_index} seed mismatch")
        if task is None or request["tool_schema_sha256"] != task.get("tool_schema_sha256"):
            errors.append(f"logical request {request_index} tool schema hash mismatch")
        if request["parameters_sha256"] != config["request_commitments"]["parameters_sha256_by_model"][requested]:
            errors.append(f"logical request {request_index} parameters hash mismatch")
        attempts = request["attempts"]
        provider_attempts += len(attempts)
        for attempt_index, attempt in enumerate(attempts):
            if attempt["attempt_index"] != attempt_index:
                errors.append(f"request {request_index} provider attempt index mismatch")
            if attempt["model_id"] != requested:
                errors.append(f"request {request_index} attempt model mismatch")
            if attempt["payload_sha256"] != request["payload_sha256"]:
                errors.append(f"request {request_index} provider retry must be identical replay")
            if attempt["seed"] != request["seed"]:
                errors.append(f"request {request_index} provider retry seed mismatch")
        if len(attempts) == 2 and attempts[0]["classification"] != "provider_or_runtime_failure":
            errors.append(f"request {request_index} semantic retry forbidden")
        if request["retries_used"] != len(attempts) - 1:
            errors.append(f"request {request_index} retry accounting mismatch")
        if request["classification"] != attempts[-1]["classification"]:
            errors.append(f"request {request_index} final classification mismatch")

    usage = trace["usage"]
    if usage["model_requests"] != len(logical_requests):
        errors.append("model request accounting mismatch")
    if usage["provider_attempts"] != provider_attempts:
        errors.append("provider attempt accounting mismatch")
    if usage["tool_calls"] > config["resource_budget"]["max_tool_calls"]:
        errors.append("tool call budget exceeded")
    if usage["total_tokens"] > config["resource_budget"]["max_total_tokens"]:
        errors.append("token budget exceeded")

    final_class = logical_requests[-1]["classification"]
    expected = {
        "success": ("succeeded", None, True),
        "candidate_failure": ("candidate_failed", "candidate_failure", True),
        "provider_or_runtime_failure": ("invalid_provider_or_runtime", "provider_or_runtime_failure", False),
        "indeterminate": ("invalid_provider_or_runtime", "indeterminate", False),
    }[final_class]
    actual = (trace["status"], trace["failure"]["class"], trace["result"]["candidate_scored"])
    if actual != expected:
        errors.append("status, failure class, and candidate scoring disagree")
    if trace["permission"]["violations"] or not trace["permission"]["trace_complete"]:
        errors.append("permission boundary violation")
    if trace["environment"]["real_side_effects"] or not trace["environment"]["final_state_matches_initial"]:
        errors.append("unsafe environment terminal state")
    if not trace["redaction"]["applied"] or trace["redaction"]["raw_provider_response_stored"] or trace["redaction"]["raw_submission_arguments_persisted"]:
        errors.append("redaction hard gate failed")
    _fail(errors)
    return {"status": trace["status"], "candidate_scored": expected[2], "logical_requests": len(logical_requests), "provider_attempts": provider_attempts}
