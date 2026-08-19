"""Additive capability-aware inference configuration v2.

The v1 loader is frozen by historical baselines.  This module provides the
new contract without changing those pinned bytes and dispatches legacy files
back to the v1 implementation.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from financial_agent_reliability.harness.secret_scan import (
    check_credential_env_name,
    scan_persisted_value_for_secrets,
)
from financial_agent_reliability.inference_config import (
    DEFAULT_PARAMETERS,
    DEFAULT_PREFLIGHT_INSTRUCTION,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOOL_CHOICE,
    InferenceConfigError,
    load_inference_config,
)


SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "contracts" / "inference.schema.v2.json"


@dataclass(frozen=True)
class ProviderConfigV2:
    name: str
    api: str
    base_url: str
    credential_env: str
    default_parameters: Mapping[str, Any]
    tool_choice: str
    timeout_seconds: float
    preflight_tool_instruction: str
    protocol: str
    adapter: str
    default_generation: Mapping[str, Any]


@dataclass(frozen=True)
class ModelConfigV2:
    model_id: str
    provider: str
    roles: tuple[str, ...]
    logical_label: str
    identity_rule: str
    allowed_response_model_ids: tuple[str, ...]
    live_preflight_required: bool
    parameter_overrides: Mapping[str, Any]
    capabilities: Mapping[str, Any]
    default_generation: Mapping[str, Any]


@dataclass(frozen=True)
class InferenceConfigV2:
    schema_version: str
    providers: tuple[ProviderConfigV2, ...]
    models: tuple[ModelConfigV2, ...]
    source_path: pathlib.Path
    source_sha256: str
    profiles: Mapping[str, Mapping[str, Any]]

    def provider(self, name: str) -> ProviderConfigV2:
        for provider in self.providers:
            if provider.name == name:
                return provider
        raise InferenceConfigError(f"unknown provider: {name}")

    def models_for_provider(self, name: str) -> tuple[ModelConfigV2, ...]:
        self.provider(name)
        return tuple(model for model in self.models if model.provider == name)

    def profile(self, name: str | None) -> Mapping[str, Any]:
        if name is None:
            return {}
        try:
            return dict(self.profiles[name])
        except KeyError as exc:
            raise InferenceConfigError(f"unknown generation profile: {name}") from exc


def _cross_field(raw: Mapping[str, Any]) -> None:
    providers = raw.get("providers") or []
    models = raw.get("models") or []
    provider_names = [provider.get("name") for provider in providers]
    if len(set(provider_names)) != len(provider_names):
        raise InferenceConfigError("providers[].name must be globally unique")
    model_ids = [model.get("model_id") for model in models]
    if len(set(model_ids)) != len(model_ids):
        raise InferenceConfigError("models[].model_id must be globally unique")
    credential_envs = [provider.get("credential_env") for provider in providers]
    if len(set(credential_envs)) != len(credential_envs):
        raise InferenceConfigError("providers[].credential_env must be pairwise distinct")
    profile_names = [profile.get("name") for profile in raw.get("profiles", [])]
    if len(set(profile_names)) != len(profile_names):
        raise InferenceConfigError("profiles[].name must be globally unique")
    known = set(provider_names)
    for model in models:
        if model.get("provider") not in known:
            raise InferenceConfigError(
                "models[].provider does not reference a declared provider: "
                f"{model.get('model_id')}"
            )
        allowed = model.get("allowed_response_model_ids")
        if allowed is not None and model.get("model_id") not in allowed:
            raise InferenceConfigError(
                "models[].allowed_response_model_ids must contain its own model_id: "
                f"{model.get('model_id')}"
            )


def load_inference_config_v2(path: str | pathlib.Path) -> InferenceConfigV2:
    config_path = pathlib.Path(path).resolve()
    try:
        config_bytes = config_path.read_bytes()
        raw = json.loads(config_bytes)
    except FileNotFoundError as exc:
        raise InferenceConfigError(f"inference config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise InferenceConfigError(f"inference config is not valid JSON: {config_path}") from exc
    findings = scan_persisted_value_for_secrets(raw)
    if findings:
        raise InferenceConfigError(
            f"inference config fails the secret scan gate at: {', '.join(findings)}"
        )
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(raw),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"$/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors[:8]
        )
        raise InferenceConfigError(f"schema validation failed: {detail}")
    _cross_field(raw)
    providers = tuple(
        ProviderConfigV2(
            name=item["name"],
            api=item["api"],
            base_url=item["base_url"],
            credential_env=item["credential_env"],
            default_parameters=dict(item.get("default_parameters") or DEFAULT_PARAMETERS),
            tool_choice=item.get("tool_choice", DEFAULT_TOOL_CHOICE),
            timeout_seconds=float(item.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            preflight_tool_instruction=item.get(
                "preflight_tool_instruction", DEFAULT_PREFLIGHT_INSTRUCTION
            ),
            protocol=item["protocol"],
            adapter=item["adapter"],
            default_generation=dict(item.get("default_generation") or {}),
        )
        for item in raw["providers"]
    )
    for provider in providers:
        if check_credential_env_name(
            provider.credential_env, f"providers[{provider.name}].credential_env"
        ):
            raise InferenceConfigError(
                f"credential_env name is secret-shaped (rule R2): {provider.credential_env}"
            )
    models = tuple(
        ModelConfigV2(
            model_id=item["model_id"],
            provider=item["provider"],
            roles=tuple(item["roles"]),
            logical_label=item.get("logical_label", item["model_id"]),
            identity_rule=item.get("identity_rule", "exact_response_match"),
            allowed_response_model_ids=tuple(
                item.get("allowed_response_model_ids", (item["model_id"],))
            ),
            live_preflight_required=bool(item.get("live_preflight_required", True)),
            parameter_overrides=dict(item.get("parameter_overrides") or {}),
            capabilities=dict(item["capabilities"]),
            default_generation=dict(item.get("default_generation") or {}),
        )
        for item in raw["models"]
    )
    return InferenceConfigV2(
        schema_version=str(raw["schema_version"]),
        providers=providers,
        models=models,
        source_path=config_path,
        source_sha256=hashlib.sha256(config_bytes).hexdigest(),
        profiles={
            profile["name"]: dict(profile["generation"])
            for profile in raw.get("profiles", [])
        },
    )


def load_inference_config_any(
    path: str | pathlib.Path, *, env: Mapping[str, str]
) -> Any:
    """Dispatch without changing the historically pinned v1 loader."""

    candidate = pathlib.Path(path)
    try:
        raw = json.loads(candidate.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise InferenceConfigError(f"cannot inspect inference config: {candidate}") from exc
    version = str(raw.get("schema_version", ""))
    if version.startswith("2."):
        return load_inference_config_v2(candidate)
    return load_inference_config(candidate, env=env)
