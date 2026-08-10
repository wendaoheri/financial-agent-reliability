#!/usr/bin/env python3
"""Dependency-free validator for the frozen PER-25 harness and run_trace v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v1.json"
MODEL_MANIFEST_PATH = ROOT / "contracts" / "model_manifest.frozen.v1.json"
FREEZE_PATH = ROOT / "contracts" / "run_trace_contracts.frozen.v1.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "harness"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^run_[0-9a-f]{32}$")
ENDPOINT_ID_RE = re.compile(r"^bailian_[0-9a-f]{12}$")
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+/=-]{8,}|\bsk-[a-z0-9_-]{8,}|"
    r"BENCH_BAILIAN_API_KEY\s*[=:]\s*[^*\s][^\s]*)"
)
ALLOWED_MODELS = {"qwen-3.8-max", "glm-5.2", "deepseek-v4-pro"}
ALLOWED_STATUSES = {"succeeded", "failed", "invalidated"}
ALLOWED_FAILURES = {
    None,
    "timeout",
    "rate_limited",
    "provider_unavailable",
    "identity_mismatch",
    "fallback_detected",
    "parameters_ignored",
    "secret_leakage",
    "budget_exceeded",
    "unsafe_side_effect",
}


class HarnessContractError(ValueError):
    """Raised with every machine-detectable contract violation."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: str | pathlib.Path) -> Any:
    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: str | pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def build_run_id(run_identity: Mapping[str, Any]) -> str:
    return "run_" + content_sha256(run_identity)[:32]


def build_bundle_sha256(artifacts: Sequence[Mapping[str, Any]]) -> str:
    commitments = [f"{item['path']}\0{item['sha256']}\n" for item in artifacts]
    return hashlib.sha256("".join(sorted(commitments)).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _require_object(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return {}
    return value


def _require_list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return []
    return value


def _check_hash(value: Any, path: str, errors: list[str]) -> None:
    _require(isinstance(value, str) and bool(SHA256_RE.fullmatch(value)), f"{path}: invalid SHA-256", errors)


def _decimal(value: Any, path: str, errors: list[str]) -> Decimal | None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be a canonical non-negative decimal string")
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        errors.append(f"{path}: invalid decimal")
        return None
    if not parsed.is_finite() or parsed < 0 or str(parsed) != value:
        errors.append(f"{path}: must be a canonical non-negative decimal string")
        return None
    return parsed


def validate_harness_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config = load_json(CONFIG_PATH) if config is None else config
    errors: list[str] = []
    runtime = _require_object(config.get("runtime"), "runtime", errors)
    _require(config.get("contract_type") == "harness_config", "invalid harness contract_type", errors)
    _require(config.get("contract_version") == "1.0.0", "unsupported harness contract_version", errors)
    _require(config.get("status") == "frozen", "harness config must be frozen", errors)
    _require(runtime.get("package") == "@mariozechner/pi-agent-core", "wrong pi-agent-core package", errors)
    _require(runtime.get("version") == "0.73.1", "pi-agent-core version must be exactly 0.73.1", errors)
    _require(
        runtime.get("exact_dependency") == "@mariozechner/pi-agent-core@0.73.1",
        "pi-agent-core dependency must be exact and lock-compatible",
        errors,
    )
    _require(str(runtime.get("registry_integrity", "")).startswith("sha512-"), "registry integrity required", errors)
    _require(runtime.get("api") == "Agent", "Agent barrier API is required", errors)
    _require(runtime.get("tool_execution") == "sequential", "tools must execute sequentially", errors)

    provider = _require_object(config.get("provider"), "provider", errors)
    expected_env = {
        "BENCH_BAILIAN_API_KEY",
        "BENCH_BAILIAN_BASE_URL",
        "BENCH_BAILIAN_MODEL_IDS",
    }
    _require(provider.get("name") == "bailian", "only Bailian provider is allowed", errors)
    _require(set(provider.get("allowed_env", [])) == expected_env, "provider env allowlist changed", errors)
    _require(
        {provider.get("api_key_env"), provider.get("base_url_env"), provider.get("model_ids_env")} == expected_env,
        "provider must use only BENCH_BAILIAN_* variables",
        errors,
    )
    _require(set(config.get("candidate_model_ids", [])) == ALLOWED_MODELS, "candidate model ids must be exact", errors)
    _require(len(config.get("candidate_model_ids", [])) == 3, "exactly three candidate models required", errors)
    prompt = config.get("system_prompt")
    _require(isinstance(prompt, str) and len(prompt) > 200, "model-neutral system prompt is missing", errors)
    context = _require_object(config.get("context_contract"), "context_contract", errors)
    _require(context.get("provider_specific_prompt_addenda") is False, "provider-specific prompt addenda forbidden", errors)
    _require(context.get("memory_between_runs") is False, "cross-run memory forbidden", errors)

    tools = _require_list(config.get("tools"), "tools", errors)
    expected_tools = {"read_frozen_case", "read_frozen_evidence", "calculate", "simulated_ledger"}
    tool_names = {item.get("name") for item in tools if isinstance(item, dict)}
    _require(tool_names == expected_tools and len(tools) == 4, "frozen tool schemas changed", errors)
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        _require(tool.get("execution_mode") == "sequential", f"tools/{index}: sequential execution required", errors)
        _require(tool.get("side_effect") in {"none", "simulated_only"}, f"tools/{index}: unsafe side effect", errors)

    parameters = _require_object(config.get("request_parameters"), "request_parameters", errors)
    _require(
        parameters == {
            "temperature": "0.000000",
            "top_p": "1.000000",
            "max_tokens": 4096,
            "seed_required": True,
            "stream": True,
        },
        "frozen request parameters changed",
        errors,
    )
    budget = _require_object(config.get("resource_budget"), "resource_budget", errors)
    for field in ("max_turns", "max_model_requests", "max_tool_calls", "max_context_tokens", "max_output_tokens", "wall_clock_ms", "max_retries"):
        _require(isinstance(budget.get(field), int) and budget.get(field) > 0, f"resource_budget/{field}: positive integer required", errors)
    _decimal(budget.get("max_cost_usd"), "resource_budget/max_cost_usd", errors)
    security = _require_object(config.get("security"), "security", errors)
    _require(security.get("dataset_access") == "frozen_read_only", "frozen read-only data required", errors)
    _require(security.get("ledger_mode") == "simulated", "simulated ledger required", errors)
    _require(security.get("full_paid_matrix_runs_allowed") is False, "paid full-matrix runs must remain disabled", errors)
    _require(security.get("raw_provider_response_persistence") is False, "raw provider response persistence forbidden", errors)
    if errors:
        raise HarnessContractError(errors)
    return {
        "pi_agent_core": runtime["version"],
        "candidate_models": len(config["candidate_model_ids"]),
        "tool_execution": runtime["tool_execution"],
        "config_sha256": file_sha256(CONFIG_PATH),
    }


def validate_model_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(manifest.get("contract_type") == "model_manifest", "invalid model manifest contract_type", errors)
    _require(manifest.get("contract_version") == "1.0.0", "unsupported model manifest version", errors)
    _require(manifest.get("status") == "frozen_before_candidate_runs", "model manifest must be frozen before runs", errors)
    _require(manifest.get("provider") == "bailian", "only Bailian model manifests are allowed", errors)
    models = _require_list(manifest.get("models"), "models", errors)
    requested = [item.get("requested_model_id") for item in models if isinstance(item, dict)]
    _require(set(requested) == ALLOWED_MODELS and len(requested) == 3, "candidate model ids must be exact", errors)
    for index, item in enumerate(models):
        if not isinstance(item, dict):
            errors.append(f"models/{index}: must be an object")
            continue
        model_id = item.get("requested_model_id")
        _require(item.get("logical_label") == model_id, f"models/{index}: logical label must equal exact model id", errors)
        _require(item.get("allowed_response_model_ids") == [model_id], f"models/{index}: response id must match exactly", errors)
        _require(item.get("identity_rule") == "exact_response_match", f"models/{index}: exact identity rule required", errors)
        _require(item.get("live_preflight_required") is True, f"models/{index}: live preflight required", errors)
    if errors:
        raise HarnessContractError(errors)
    return sorted(requested)


def _scan_secrets(value: Any, path: str, errors: list[str]) -> None:
    sensitive_names = {"authorization", "api_key", "token", "cookie", "set-cookie", "x-api-key"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}/{key}"
            if key.lower() in sensitive_names and child not in (None, "[REDACTED]", "***"):
                errors.append(f"{child_path}: potential secret leakage in sensitive field")
            _scan_secrets(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_secrets(child, f"{path}/{index}", errors)
    elif isinstance(value, str) and SECRET_VALUE_RE.search(value):
        errors.append(f"{path}: potential secret leakage in value")


def validate_run_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    manifest = load_json(MODEL_MANIFEST_PATH)
    validate_harness_config(config)
    validate_model_manifest(manifest)
    errors: list[str] = []
    _scan_secrets(trace, "$", errors)
    _require(trace.get("contract_type") == "run_trace", "invalid run_trace contract_type", errors)
    _require(trace.get("contract_version") == "1.0.0", "unsupported run_trace version", errors)
    _require(trace.get("status") in ALLOWED_STATUSES, "invalid run status", errors)

    identity = _require_object(trace.get("run_identity"), "run_identity", errors)
    identity_fields = {
        "benchmark_id", "case_id", "variant_id", "requested_model_id", "repeat", "seed",
        "harness_config_sha256", "immutable_bundle_sha256",
    }
    _require(set(identity) == identity_fields, "run_identity fields changed", errors)
    _require(identity.get("requested_model_id") in ALLOWED_MODELS, "run_identity uses unregistered model", errors)
    _require(isinstance(identity.get("repeat"), int) and identity.get("repeat", 0) >= 1, "invalid repeat", errors)
    _require(isinstance(identity.get("seed"), int) and not isinstance(identity.get("seed"), bool), "invalid seed", errors)
    _require(identity.get("harness_config_sha256") == file_sha256(CONFIG_PATH), "harness config hash mismatch", errors)
    expected_run_id = build_run_id(identity)
    _require(trace.get("run_id") == expected_run_id and bool(RUN_ID_RE.fullmatch(str(trace.get("run_id", "")))), "idempotent run_id mismatch", errors)

    provider = _require_object(trace.get("provider"), "provider", errors)
    requested = provider.get("requested_model_id")
    response = provider.get("response_model_id")
    _require(provider.get("name") == "bailian", "trace provider must be Bailian", errors)
    _require(requested in ALLOWED_MODELS and requested == identity.get("requested_model_id"), "requested model id mismatch", errors)
    _require(ENDPOINT_ID_RE.fullmatch(str(provider.get("endpoint_id", ""))) is not None, "endpoint id must be a non-sensitive hash label", errors)
    _require("url" not in " ".join(provider).lower(), "provider URL must not be persisted", errors)
    _require(provider.get("model_manifest_sha256") == file_sha256(MODEL_MANIFEST_PATH), "model manifest hash mismatch", errors)

    request = _require_object(trace.get("request"), "request", errors)
    expected_parameters = dict(config["request_parameters"])
    expected_parameters.pop("seed_required")
    _require(request.get("parameters") == expected_parameters, "request parameters differ from frozen harness", errors)
    _require(request.get("seed") == identity.get("seed"), "request seed differs from run identity", errors)

    preflight = _require_object(trace.get("preflight"), "preflight", errors)
    _require(preflight.get("performed") is True, "live model preflight is required", errors)
    _require(preflight.get("fallback_attempted") is False, "model fallback is prohibited", errors)
    identity_match = response == requested and preflight.get("identity_match") is True
    fallback = preflight.get("fallback_detected") is True
    params_honored = preflight.get("parameters_honored") is True
    endpoint_verified = preflight.get("endpoint_verified") is True
    invalid_reasons: list[str] = []
    if not identity_match:
        invalid_reasons.append("identity_mismatch")
    if fallback:
        invalid_reasons.append("fallback_detected")
    if not params_honored:
        invalid_reasons.append("parameters_ignored")
    if not endpoint_verified:
        invalid_reasons.append("endpoint_unverified")
    if invalid_reasons:
        _require(trace.get("status") == "invalidated", "identity mismatch, fallback, or ignored parameters must invalidate the run", errors)
        expected_reason = invalid_reasons[0]
        _require(preflight.get("valid") is False, "invalid preflight cannot be marked valid", errors)
        _require(preflight.get("invalid_reason") == expected_reason, "preflight invalid_reason mismatch", errors)
    else:
        _require(preflight.get("valid") is True and preflight.get("invalid_reason") is None, "valid preflight flags inconsistent", errors)

    context = _require_object(trace.get("context"), "context", errors)
    expected_prompt_hash = content_sha256(config["system_prompt"])
    expected_tools_hash = content_sha256(config["tools"])
    _require(context.get("system_prompt_sha256") == expected_prompt_hash, "system prompt hash mismatch", errors)
    _require(context.get("tool_schema_sha256") == expected_tools_hash, "tool schema hash mismatch", errors)
    _check_hash(context.get("frozen_input_sha256"), "context/frozen_input_sha256", errors)
    _require(isinstance(context.get("messages_count"), int) and context.get("messages_count", -1) >= 1, "invalid messages_count", errors)

    tools = _require_list(trace.get("tool_calls"), "tool_calls", errors)
    allowed_tool_names = {tool["name"] for tool in config["tools"]}
    _require(len(tools) <= config["resource_budget"]["max_tool_calls"], "tool-call budget exceeded", errors)
    for index, tool in enumerate(tools):
        item = _require_object(tool, f"tool_calls/{index}", errors)
        _require(item.get("name") in allowed_tool_names, f"tool_calls/{index}: unregistered tool", errors)
        for field in ("arguments_sha256", "result_sha256"):
            _check_hash(item.get(field), f"tool_calls/{index}/{field}", errors)
        _require(item.get("status") in {"succeeded", "failed"}, f"tool_calls/{index}: invalid status", errors)
        _require(isinstance(item.get("duration_ms"), int) and item.get("duration_ms", -1) >= 0, f"tool_calls/{index}: invalid duration", errors)

    environment = _require_object(trace.get("environment"), "environment", errors)
    _require(environment.get("dataset_access") == "frozen_read_only", "formal runs must use frozen read-only data", errors)
    _require(environment.get("ledger_mode") == "simulated", "real trading is prohibited; simulated ledger required", errors)
    _require(environment.get("network_scope") == "bailian_inference_only", "network scope exceeds provider inference", errors)
    touched = _require_list(environment.get("touched_paths"), "environment/touched_paths", errors)
    forbidden = [fragment.lower().replace("\\", "/") for fragment in config["security"]["forbidden_path_fragments"]]
    for path in touched:
        normalized = str(path).lower().replace("\\", "/")
        if any(fragment in normalized for fragment in forbidden):
            errors.append(f"environment/touched_paths: forbidden config path {path}")

    timing = _require_object(trace.get("timing"), "timing", errors)
    duration = timing.get("duration_ms")
    _require(isinstance(timing.get("started_at"), str) and isinstance(timing.get("finished_at"), str), "timing timestamps required", errors)
    _require(isinstance(duration, int) and duration >= 0, "invalid total duration", errors)
    _require(isinstance(duration, int) and duration <= config["resource_budget"]["wall_clock_ms"], "wall-clock budget exceeded", errors)

    usage = _require_object(trace.get("usage"), "usage", errors)
    for field in ("input_tokens", "output_tokens", "total_tokens", "model_requests", "turns"):
        _require(isinstance(usage.get(field), int) and usage.get(field, -1) >= 0, f"usage/{field}: non-negative integer required", errors)
    _require(usage.get("total_tokens") == usage.get("input_tokens", 0) + usage.get("output_tokens", 0), "token totals do not reconcile", errors)
    _require(usage.get("output_tokens", 0) <= config["resource_budget"]["max_output_tokens"], "output token budget exceeded", errors)
    _require(usage.get("model_requests", 0) <= config["resource_budget"]["max_model_requests"], "model request budget exceeded", errors)
    _require(usage.get("turns", 0) <= config["resource_budget"]["max_turns"], "turn budget exceeded", errors)

    cost = _require_object(trace.get("cost"), "cost", errors)
    _require(cost.get("currency") == "USD", "cost currency must be USD", errors)
    cost_values = [_decimal(cost.get(field), f"cost/{field}", errors) for field in ("input_usd", "output_usd", "tool_usd", "total_usd")]
    if all(value is not None for value in cost_values):
        _require(sum(cost_values[:3], Decimal("0")) == cost_values[3], "cost totals do not reconcile", errors)
        _require(cost_values[3] <= Decimal(config["resource_budget"]["max_cost_usd"]), "cost budget exceeded", errors)

    attempts = _require_list(trace.get("attempts"), "attempts", errors)
    _require(bool(attempts), "at least one attempt required", errors)
    for index, attempt in enumerate(attempts):
        item = _require_object(attempt, f"attempts/{index}", errors)
        _require(item.get("attempt") == index + 1, f"attempts/{index}: sequence must start at one", errors)
        _require(item.get("outcome") in {"succeeded", "failed", "invalidated"}, f"attempts/{index}: invalid outcome", errors)
        _require(item.get("failure_type") in ALLOWED_FAILURES, f"attempts/{index}: unknown failure type", errors)
        _require(type(item.get("retryable")) is bool, f"attempts/{index}: retryable must be boolean", errors)
        _require(isinstance(item.get("duration_ms"), int) and item.get("duration_ms", -1) >= 0, f"attempts/{index}: invalid duration", errors)
    retry = _require_object(trace.get("retry"), "retry", errors)
    retries_used = retry.get("retries_used")
    _require(retry.get("max_retries") == config["resource_budget"]["max_retries"], "retry budget differs from harness", errors)
    _require(isinstance(retries_used, int) and retries_used == max(0, len(attempts) - 1), "retry count mismatch", errors)
    _require(isinstance(retries_used, int) and retries_used <= config["resource_budget"]["max_retries"], "retry budget exceeded", errors)

    resume = _require_object(trace.get("resume"), "resume", errors)
    checkpoint = _require_object(trace.get("checkpoint"), "checkpoint", errors)
    _require(type(resume.get("resumed")) is bool, "resume/resumed must be boolean", errors)
    _require(checkpoint.get("enabled") is True, "checkpointing must be enabled", errors)
    _check_hash(checkpoint.get("state_sha256"), "checkpoint/state_sha256", errors)
    _check_hash(checkpoint.get("prior_event_hash"), "checkpoint/prior_event_hash", errors)
    _require(isinstance(checkpoint.get("sequence"), int) and checkpoint.get("sequence", -1) >= 0, "checkpoint sequence invalid", errors)
    if resume.get("resumed") is True:
        _require(resume.get("source_run_id") == trace.get("run_id"), "resume must preserve the idempotent run_id", errors)
        _require(resume.get("checkpoint_id") == checkpoint.get("checkpoint_id"), "resume checkpoint id mismatch", errors)
        _require(resume.get("state_sha256") == checkpoint.get("state_sha256"), "resume state hash mismatch", errors)
        _require(resume.get("event_offset") == checkpoint.get("sequence"), "resume event offset mismatch", errors)
    else:
        _require(resume.get("source_run_id") is None and resume.get("checkpoint_id") is None, "non-resumed run must not claim a source", errors)

    failure = _require_object(trace.get("failure"), "failure", errors)
    failure_type = failure.get("type")
    _require(failure_type in ALLOWED_FAILURES, "unknown terminal failure type", errors)
    if trace.get("status") == "succeeded":
        _require(failure_type is None, "successful run cannot have terminal failure", errors)
    elif trace.get("status") == "failed":
        _require(failure_type in {"timeout", "rate_limited", "provider_unavailable", "budget_exceeded", "unsafe_side_effect"}, "failed run needs terminal operational failure", errors)
    elif trace.get("status") == "invalidated":
        _require(failure_type in {"identity_mismatch", "fallback_detected", "parameters_ignored", "secret_leakage"}, "invalidated run needs preflight or safety failure", errors)

    result = _require_object(trace.get("result"), "result", errors)
    _check_hash(result.get("response_sha256"), "result/response_sha256", errors)
    _require(result.get("raw_provider_response_stored") is False, "raw provider response must not be stored", errors)
    _require(result.get("output_stored") is False, "raw model output must not be stored in run_trace", errors)

    bundle = _require_object(trace.get("immutable_bundle"), "immutable_bundle", errors)
    artifacts = _require_list(bundle.get("artifacts"), "immutable_bundle/artifacts", errors)
    paths: list[str] = []
    for index, artifact in enumerate(artifacts):
        item = _require_object(artifact, f"immutable_bundle/artifacts/{index}", errors)
        _require(isinstance(item.get("path"), str) and not str(item.get("path")).startswith("/"), f"immutable_bundle/artifacts/{index}: relative path required", errors)
        _check_hash(item.get("sha256"), f"immutable_bundle/artifacts/{index}/sha256", errors)
        paths.append(str(item.get("path")))
    _require(paths == sorted(paths) and len(paths) == len(set(paths)) and bool(paths), "immutable bundle paths must be non-empty, unique, and sorted", errors)
    if artifacts and all(isinstance(item, dict) and isinstance(item.get("path"), str) and SHA256_RE.fullmatch(str(item.get("sha256", ""))) for item in artifacts):
        expected_bundle = build_bundle_sha256(artifacts)
        _require(bundle.get("bundle_sha256") == expected_bundle, "immutable bundle aggregate hash mismatch", errors)
        _require(identity.get("immutable_bundle_sha256") == expected_bundle, "run identity bundle hash mismatch", errors)

    redaction = _require_object(trace.get("redaction"), "redaction", errors)
    _require(redaction.get("applied") is True, "redaction must be applied", errors)
    _require(redaction.get("raw_sensitive_response_persisted") is False, "sensitive raw response persisted", errors)
    removed = set(redaction.get("secret_fields_removed", []))
    _require({"authorization", "api_key", "token", "cookie", "set-cookie"} <= removed, "redaction coverage incomplete", errors)

    if errors:
        raise HarnessContractError(errors)
    return {
        "run_id": trace["run_id"],
        "status": trace["status"],
        "failure_type": failure_type,
        "retries": retries_used,
    }


def verify_freeze() -> dict[str, Any]:
    manifest = load_json(FREEZE_PATH)
    errors: list[str] = []
    commitments: list[str] = []
    for item in manifest.get("files", []):
        relative = item.get("path")
        expected = item.get("sha256")
        path = ROOT / str(relative)
        if not path.is_file():
            errors.append(f"missing frozen file: {relative}")
            continue
        actual = file_sha256(path)
        if actual != expected:
            errors.append(f"frozen file hash mismatch: {relative} expected {expected} got {actual}")
        commitments.append(f"{relative}\0{expected}\n")
    aggregate = hashlib.sha256("".join(commitments).encode("utf-8")).hexdigest()
    if aggregate != manifest.get("contract_bundle_sha256"):
        errors.append("contract bundle commitment mismatch")
    if errors:
        raise HarnessContractError(errors)
    return {"files": len(commitments), "contract_bundle_sha256": aggregate}


def validate_fixtures() -> dict[str, Any]:
    accepted = 0
    rejected = 0
    for path in sorted(FIXTURE_PATH.glob("run_trace.*.json")):
        try:
            validate_run_trace(load_json(path))
        except HarnessContractError:
            if path.name != "run_trace.secret_leak.json":
                raise
            rejected += 1
        else:
            if path.name == "run_trace.secret_leak.json":
                raise HarnessContractError(["secret leak fixture was unexpectedly accepted"])
            accepted += 1
    return {"accepted": accepted, "expected_rejections": rejected}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify-freeze", "validate-fixtures", "validate-config"))
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-freeze":
            result = verify_freeze()
        elif args.command == "validate-fixtures":
            result = validate_fixtures()
        else:
            result = validate_harness_config()
    except (HarnessContractError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
