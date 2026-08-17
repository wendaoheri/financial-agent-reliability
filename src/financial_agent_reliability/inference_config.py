"""Provider/model-configurable inference layer (PER-323 Stage 2, contract §5.1).

Loads and validates ``configs/inference.json`` against
``configs/inference.schema.v1.json``. Secrets are never persisted: the
configuration stores only the NAME of the environment variable that carries
each provider credential; values are resolved into memory at runtime and are
excluded from ``repr``/``str`` everywhere downstream.

Resolution order (§2): explicit path > ``FARELI_INFERENCE_CONFIG`` >
default ``configs/inference.json`` (repository root).

The loader enforces, on top of the JSON Schema, the cross-field rules of §3.1
and the secret-scan-avoidance rules of §4.3 (R1 key names, R2 value shapes).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from financial_agent_reliability.harness.secret_scan import (
    check_credential_env_name,
    scan_persisted_value_for_secrets,
)


ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "configs" / "inference.json"
SCHEMA_PATH = ROOT / "configs" / "inference.schema.v1.json"
CONFIG_PATH_ENV = "FARELI_INFERENCE_CONFIG"
SUPPORTED_SCHEMA_MAJOR = 1
DEFAULT_PARAMETERS: Mapping[str, Any] = {
    "temperature": "0.000000",
    "top_p": "1.000000",
    "max_tokens": 4096,
    "stream": True,
}
DEFAULT_TOOL_CHOICE = "auto"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_PREFLIGHT_INSTRUCTION = "Call read_frozen_case with case_id PREFLIGHT."
PARAMETER_KEYS = frozenset({"temperature", "top_p", "max_tokens", "stream"})


class InferenceConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api: str
    base_url: str
    credential_env: str
    default_parameters: Mapping[str, Any]
    tool_choice: str
    timeout_seconds: float
    preflight_tool_instruction: str


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    provider: str
    roles: tuple[str, ...]
    logical_label: str
    identity_rule: str
    allowed_response_model_ids: tuple[str, ...]
    live_preflight_required: bool
    parameter_overrides: Mapping[str, Any]


@dataclass(frozen=True)
class InferenceConfig:
    schema_version: str
    providers: tuple[ProviderConfig, ...]
    models: tuple[ModelConfig, ...]

    def provider(self, name: str) -> ProviderConfig:
        for provider in self.providers:
            if provider.name == name:
                return provider
        raise InferenceConfigError(f"unknown provider: {name}")

    def models_for_provider(self, name: str) -> tuple[ModelConfig, ...]:
        self.provider(name)
        return tuple(model for model in self.models if model.provider == name)


@dataclass(frozen=True)
class ProviderRuntime:
    provider_name: str
    base_url: str
    credential: str = field(repr=False)
    endpoint_id: str = ""


def endpoint_origin(base_url: str) -> tuple[str, str]:
    """Return ``(origin, origin_sha256)`` for an absolute HTTP(S) base URL.

    Endpoint identity policy (F7): origin only — no path, query, or
    credentials; scheme and host lower-cased; explicit port preserved.
    """
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise InferenceConfigError(f"base_url must be an absolute HTTP(S) URL: {base_url}")
    port = f":{parsed.port}" if parsed.port else ""
    origin = f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"
    return origin, hashlib.sha256(origin.encode("utf-8")).hexdigest()


def _resolve_config_path(path: str | pathlib.Path | None, env: Mapping[str, str]) -> pathlib.Path:
    if path is not None:
        return pathlib.Path(path)
    environment_path = env.get(CONFIG_PATH_ENV)
    if environment_path:
        return pathlib.Path(environment_path)
    return DEFAULT_CONFIG_PATH


def _scan_raw_config(raw: Any) -> list[str]:
    """Rule R1 (secret-shaped key names) + rule R2 (secret-shaped values)."""
    return scan_persisted_value_for_secrets(raw)


def _validate_cross_field(raw: Mapping[str, Any]) -> None:
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
    known = set(provider_names)
    for model in models:
        if model.get("provider") not in known:
            raise InferenceConfigError(
                f"models[].provider does not reference a declared provider: {model.get('model_id')}"
            )
        allowed = model.get("allowed_response_model_ids")
        if allowed is not None and model.get("model_id") not in allowed:
            raise InferenceConfigError(
                "models[].allowed_response_model_ids must contain its own model_id: "
                f"{model.get('model_id')}"
            )


def _build_provider(raw: Mapping[str, Any]) -> ProviderConfig:
    defaults = dict(DEFAULT_PARAMETERS)
    defaults.update(raw.get("default_parameters") or {})
    return ProviderConfig(
        name=raw["name"],
        api=raw["api"],
        base_url=raw["base_url"],
        credential_env=raw["credential_env"],
        default_parameters=dict(defaults),
        tool_choice=raw.get("tool_choice", DEFAULT_TOOL_CHOICE),
        timeout_seconds=float(raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        preflight_tool_instruction=raw.get(
            "preflight_tool_instruction", DEFAULT_PREFLIGHT_INSTRUCTION
        ),
    )


def _build_model(raw: Mapping[str, Any]) -> ModelConfig:
    model_id = raw["model_id"]
    return ModelConfig(
        model_id=model_id,
        provider=raw["provider"],
        roles=tuple(raw["roles"]),
        logical_label=raw.get("logical_label", model_id),
        identity_rule=raw.get("identity_rule", "exact_response_match"),
        allowed_response_model_ids=tuple(
            raw.get("allowed_response_model_ids", (model_id,))
        ),
        live_preflight_required=bool(raw.get("live_preflight_required", True)),
        parameter_overrides=dict(raw.get("parameter_overrides") or {}),
    )


def load_inference_config(
    path: str | pathlib.Path | None = None,
    env: Mapping[str, str] = os.environ,
) -> InferenceConfig:
    """Load and validate the inference configuration (§2 resolution order).

    Raises :class:`InferenceConfigError` on any schema, cross-field, or
    secret-scan violation — before any network request can be constructed.
    """
    config_path = _resolve_config_path(path, env)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InferenceConfigError(f"inference config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise InferenceConfigError(f"inference config is not valid JSON: {config_path}") from exc

    findings = _scan_raw_config(raw)
    if findings:
        raise InferenceConfigError(
            f"inference config fails the secret scan gate at: {', '.join(findings)}"
        )
    if not isinstance(raw, Mapping) or raw.get("contract_type") != "inference_config":
        raise InferenceConfigError("contract_type must be 'inference_config'")

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(raw), key=lambda item: list(item.absolute_path))
    if errors:
        detail = "; ".join(
            f"$/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors[:8]
        )
        raise InferenceConfigError(f"schema validation failed: {detail}")

    version = str(raw["schema_version"])
    if not version.startswith(f"{SUPPORTED_SCHEMA_MAJOR}."):
        raise InferenceConfigError(
            f"schema_version major {version.split('.')[0]} does not match loader major "
            f"{SUPPORTED_SCHEMA_MAJOR}"
        )

    _validate_cross_field(raw)
    providers = tuple(_build_provider(provider) for provider in raw["providers"])
    models = tuple(_build_model(model) for model in raw["models"])
    for provider in providers:
        findings = check_credential_env_name(
            provider.credential_env, f"providers[{provider.name}].credential_env"
        )
        if findings:
            raise InferenceConfigError(
                f"credential_env name is secret-shaped (rule R2): {provider.credential_env}"
            )
    return InferenceConfig(schema_version=version, providers=providers, models=models)


def _base_url_override_env_names(provider_name: str) -> tuple[str, ...]:
    generic = f"FARELI_{provider_name.upper().replace('-', '_')}_BASE_URL"
    if provider_name == "bailian":
        return (generic, "BENCH_BAILIAN_BASE_URL")
    return (generic,)


def resolve_provider_runtime(
    config: InferenceConfig, provider_name: str, env: Mapping[str, str]
) -> ProviderRuntime:
    """Resolve base_url (env override wins, §3.5) and the in-memory credential.

    A missing credential environment variable raises before any network
    request can be constructed (fail-fast, design contract §3.5 rule 3).
    """
    provider = config.provider(provider_name)
    base_url = provider.base_url
    for name in _base_url_override_env_names(provider_name):
        override = env.get(name)
        if override:
            parsed = urlsplit(override)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                raise InferenceConfigError(f"{name} must be an absolute HTTP(S) URL")
            base_url = override
            break
    credential = env.get(provider.credential_env)
    if not credential:
        raise InferenceConfigError(
            f"missing required environment: {provider.credential_env} "
            f"(credential for provider '{provider_name}')"
        )
    _origin, origin_hash = endpoint_origin(base_url)
    return ProviderRuntime(
        provider_name=provider_name,
        base_url=base_url,
        credential=credential,
        endpoint_id=f"{provider_name}_{origin_hash[:12]}",
    )


def merged_parameters(config: InferenceConfig, model: ModelConfig) -> dict[str, Any]:
    """Effective request parameters: overrides > provider defaults (§3.5 rule 2)."""
    provider = config.provider(model.provider)
    parameters = dict(provider.default_parameters)
    for key, value in model.parameter_overrides.items():
        if key not in PARAMETER_KEYS:
            raise InferenceConfigError(f"parameter_overrides key outside whitelist: {key}")
        parameters[key] = value
    return parameters
