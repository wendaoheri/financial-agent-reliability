"""Deterministic validation for the superseding v3 harness and traces."""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from contracts.run_trace_validator import build_run_id, file_sha256


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v3.json"
MODELS = {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"}
CHECKS = {
    "structure_parsed", "status_correct", "value_and_units_executable",
    "reason_codes_correct", "evidence_sufficient", "point_in_time_valid",
    "method_applicable", "calculation_reproducible", "permission_trace_valid",
    "environment_final_state_valid", "sensitive_information_absent",
}


class HarnessContractV3Error(ValueError):
    pass


def validate_harness_config_v3(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config = config or json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if config.get("contract_version") != "3.0.0" or config.get("status") != "frozen": errors.append("v3 config must be frozen")
    if config.get("candidate_model_ids") != ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]: errors.append("exact model order required")
    tools = config.get("tools", [])
    if [item.get("name") for item in tools] != ["read_frozen_case", "read_frozen_evidence", "calculate", "simulated_ledger", "submit_candidate_result"]: errors.append("exact shared tool order required")
    calculate = next((item for item in tools if item.get("name") == "calculate"), {})
    inputs = (((calculate.get("parameters") or {}).get("properties") or {}).get("inputs") or {})
    if inputs.get("required") != ["values"]: errors.append("calculate inputs.values must be required")
    if (config.get("provider") or {}).get("tool_choice") != "auto": errors.append("tool_choice must be auto")
    if (config.get("resource_budget") or {}).get("max_retries") != 0: errors.append("SDK retry must be frozen at zero")
    if errors: raise HarnessContractV3Error("; ".join(errors))
    return {"config_sha256": file_sha256(CONFIG_PATH), "models": 3, "tools": 5}


def validate_run_trace_v3(trace: Mapping[str, Any]) -> None:
    validate_harness_config_v3()
    errors: list[str] = []
    identity = trace.get("run_identity") or {}
    provider = trace.get("provider") or {}
    requested = identity.get("requested_model_id")
    if trace.get("contract_type") != "run_trace" or trace.get("contract_version") != "3.0.0": errors.append("trace must be v3")
    if requested not in MODELS or provider.get("requested_model_id") != requested: errors.append("requested identity invalid")
    if trace.get("run_id") != build_run_id(identity): errors.append("run id mismatch")
    if identity.get("harness_config_sha256") != file_sha256(CONFIG_PATH): errors.append("config hash mismatch")
    if trace.get("status") == "succeeded" and (provider.get("response_model_id") != requested or not (trace.get("preflight") or {}).get("identity_match")): errors.append("successful trace identity mismatch")
    if (trace.get("result") or {}).get("raw_provider_response_stored") is not False: errors.append("raw response persistence forbidden")
    if (trace.get("environment") or {}).get("real_side_effects") is not False: errors.append("real side effect forbidden")
    if errors: raise HarnessContractV3Error("; ".join(errors))


def validate_grader_v3(grader: Mapping[str, Any]) -> None:
    checks = grader.get("checks") or {}
    errors: list[str] = []
    if grader.get("contract_type") != "stage3_independent_grader_result" or grader.get("contract_version") != "3.0.0": errors.append("grader must be v3")
    if set(checks) != CHECKS: errors.append("independent check set mismatch")
    if not all(isinstance(value, bool) for value in checks.values()): errors.append("every check must be boolean")
    if grader.get("all_critical_invariants_passed") != all(checks.values()): errors.append("aggregate mismatch")
    if errors: raise HarnessContractV3Error("; ".join(errors))
