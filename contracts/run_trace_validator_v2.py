"""Validator for the versioned identity/tool-protocol correction."""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

from contracts.run_trace_validator import build_run_id, content_sha256, file_sha256


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v2.json"
MODEL_MANIFEST_PATH = ROOT / "contracts" / "model_manifest.frozen.v2.json"
ALLOWED_MODELS = {"qwen3.8-max", "glm-5.2", "deepseek-v4-pro"}


class HarnessContractV2Error(ValueError):
    pass


def _fail(errors: list[str]) -> None:
    if errors:
        raise HarnessContractV2Error("; ".join(errors))


def validate_model_manifest_v2(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("contract_type") != "model_manifest":
        errors.append("invalid model manifest contract_type")
    if manifest.get("contract_version") != "2.0.0":
        errors.append("unsupported model manifest version")
    models = manifest.get("models")
    if not isinstance(models, list):
        models = []
        errors.append("models must be a list")
    requested = [item.get("requested_model_id") for item in models if isinstance(item, dict)]
    if set(requested) != ALLOWED_MODELS or len(requested) != 3:
        errors.append("candidate model ids must be exact")
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("requested_model_id")
        if item.get("logical_label") != model_id or item.get("allowed_response_model_ids") != [model_id]:
            errors.append("logical/request/response model identities must match exactly")
    _fail(errors)
    return sorted(requested)


def validate_harness_config_v2(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config is None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if config.get("contract_version") != "2.0.0" or config.get("status") != "frozen":
        errors.append("active harness config must be frozen v2")
    if set(config.get("candidate_model_ids", [])) != ALLOWED_MODELS:
        errors.append("candidate model ids must be exact")
    provider = config.get("provider") or {}
    if provider.get("tool_schema_wire_format") != "openai_function":
        errors.append("Bailian tool schema must use OpenAI function wire format")
    if provider.get("tool_choice") != "auto":
        errors.append("Bailian-compatible tool_choice must be auto")
    tools = config.get("tools") or []
    if len(tools) != 4 or any(not isinstance(x.get("parameters"), dict) for x in tools if isinstance(x, dict)):
        errors.append("four JSON-schema tools are required")
    _fail(errors)
    return {
        "contract_version": "2.0.0",
        "candidate_models": 3,
        "tool_choice": provider["tool_choice"],
        "config_sha256": file_sha256(CONFIG_PATH),
    }


def verify_active_v2() -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_harness_config_v2(config)
    validate_model_manifest_v2(manifest)
    return {
        "config_sha256": file_sha256(CONFIG_PATH),
        "model_manifest_sha256": file_sha256(MODEL_MANIFEST_PATH),
    }


def validate_run_trace_v2(trace: Mapping[str, Any]) -> dict[str, Any]:
    validate_harness_config_v2()
    validate_model_manifest_v2(
        json.loads(MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
    )
    errors: list[str] = []
    identity = trace.get("run_identity") or {}
    provider = trace.get("provider") or {}
    requested = identity.get("requested_model_id")
    if trace.get("contract_type") != "run_trace" or trace.get("contract_version") != "2.0.0":
        errors.append("run trace must use contract v2")
    if requested not in ALLOWED_MODELS:
        errors.append("candidate model ids must be exact")
    if provider.get("requested_model_id") != requested:
        errors.append("provider/request identity mismatch")
    if provider.get("model_manifest_sha256") != file_sha256(MODEL_MANIFEST_PATH):
        errors.append("model manifest hash mismatch")
    if identity.get("harness_config_sha256") != file_sha256(CONFIG_PATH):
        errors.append("harness config hash mismatch")
    if trace.get("run_id") != build_run_id(identity):
        errors.append("run id mismatch")
    preflight = trace.get("preflight") or {}
    if trace.get("status") == "succeeded" and (
        provider.get("response_model_id") != requested
        or preflight.get("valid") is not True
        or preflight.get("identity_match") is not True
    ):
        errors.append("successful trace requires exact valid preflight identity")
    _fail(errors)
    attempts = trace.get("attempts") or []
    return {
        "status": trace.get("status"),
        "retries": max(0, len(attempts) - 1),
        "failure_type": (trace.get("failure") or {}).get("type"),
    }
