"""Deterministic validation for the v3.5 financial acceptance harness."""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from contracts.run_trace_validator import build_run_id, file_sha256


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v3.5.json"
MODELS = {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"}


class HarnessContractV35Error(ValueError):
    pass


def validate_harness_config_v35(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config = config or json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if config.get("contract_version") != "3.5.0" or config.get("status") != "frozen":
        errors.append("v3.5 config must be frozen")
    if config.get("candidate_model_ids") != ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]:
        errors.append("exact model order required")
    expected_tools = ["read_frozen_case", "read_frozen_evidence", "calculate", "simulated_ledger", "submit_candidate_answer", "submit_candidate_non_answer"]
    if config.get("tool_names") != expected_tools:
        errors.append("exact shared tool order required")
    controls = (config.get("provider") or {}).get("common_request_controls") or {}
    if controls.get("tool_choice") != "auto" or controls.get("tool_stream") is not False or controls.get("parallel_tool_calls") is not False:
        errors.append("Bailian common controls invalid")
    if ((config.get("provider") or {}).get("qwen3.8-max") or {}).get("enable_thinking") is not False:
        errors.append("Qwen thinking must be explicitly disabled")
    budget = config.get("resource_budget") or {}
    if budget.get("max_retries") != 0 or budget.get("initial_model_requests", 0) + budget.get("repair_model_requests", 0) != budget.get("max_model_requests"):
        errors.append("bounded request and retry policy invalid")
    execution = config.get("execution") or {}
    if execution.get("authorized_run_cap") != 36 or execution.get("full_810_matrix_authorized") is not False:
        errors.append("authorized run scope invalid")
    if errors:
        raise HarnessContractV35Error("; ".join(errors))
    return {"config_sha256": file_sha256(CONFIG_PATH), "models": 3, "tools": 6}


def validate_run_trace_v35(trace: Mapping[str, Any]) -> None:
    validate_harness_config_v35()
    errors: list[str] = []
    identity = trace.get("run_identity") or {}
    provider = trace.get("provider") or {}
    requested = identity.get("requested_model_id")
    if trace.get("contract_type") != "run_trace" or trace.get("contract_version") != "3.5.0":
        errors.append("trace must be v3.5")
    if requested not in MODELS or provider.get("requested_model_id") != requested:
        errors.append("requested identity invalid")
    if trace.get("run_id") != build_run_id(identity):
        errors.append("run id mismatch")
    if identity.get("harness_config_sha256") != file_sha256(CONFIG_PATH):
        errors.append("config hash mismatch")
    if trace.get("status") == "succeeded" and (provider.get("response_model_id") != requested or not (trace.get("preflight") or {}).get("identity_match")):
        errors.append("successful trace identity mismatch")
    request = trace.get("request") or {}
    parameters = request.get("parameters") or {}
    if request.get("tool_choice") != "auto" or parameters.get("tool_stream") is not False or parameters.get("parallel_tool_calls") is not False:
        errors.append("request controls changed")
    if requested == "qwen3.8-max" and parameters.get("enable_thinking") is not False:
        errors.append("Qwen thinking control missing")
    if requested != "qwen3.8-max" and parameters.get("enable_thinking") is not None:
        errors.append("Qwen-only parameter leaked to another model")
    if (trace.get("result") or {}).get("raw_provider_response_stored") is not False:
        errors.append("raw response persistence forbidden")
    redaction = trace.get("redaction") or {}
    if redaction.get("raw_submission_arguments_persisted") is not False:
        errors.append("raw submission persistence forbidden")
    if (trace.get("environment") or {}).get("real_side_effects") is not False:
        errors.append("real side effect forbidden")
    if errors:
        raise HarnessContractV35Error("; ".join(errors))
