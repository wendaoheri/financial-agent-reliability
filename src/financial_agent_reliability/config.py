"""Load the single run configuration used by the benchmark MVP."""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from financial_agent_reliability.security import scan_persisted_value_for_secrets


class ConfigError(ValueError):
    """Raised before execution when a run configuration is invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api: str
    protocol: str
    adapter: str
    base_url: str
    credential_env: str
    default_generation: Mapping[str, Any]
    timeout_seconds: float


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    provider: str
    allowed_response_model_ids: tuple[str, ...]
    capabilities: Mapping[str, Any]
    default_generation: Mapping[str, Any]


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    providers: tuple[ProviderConfig, ...]
    models: tuple[ModelConfig, ...]
    profiles: Mapping[str, Mapping[str, Any]]
    source_path: pathlib.Path
    source_sha256: str

    def provider(self, name: str) -> ProviderConfig:
        try:
            return next(item for item in self.providers if item.name == name)
        except StopIteration as exc:
            raise ConfigError(f"unknown provider: {name}") from exc

    def models_for_provider(self, name: str) -> tuple[ModelConfig, ...]:
        self.provider(name)
        return tuple(item for item in self.models if item.provider == name)

    def profile(self, name: str | None) -> Mapping[str, Any]:
        if name is None:
            return {}
        try:
            return dict(self.profiles[name])
        except KeyError as exc:
            raise ConfigError(f"unknown generation profile: {name}") from exc


def _schema() -> Mapping[str, Any]:
    path = resources.files("financial_agent_reliability.schemas").joinpath("config.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _format_error(error: Any) -> str:
    location = "/".join(str(part) for part in error.absolute_path) or "$"
    return f"{location}: {error.message}"


def _cross_validate(raw: Mapping[str, Any]) -> None:
    providers = raw.get("providers", [])
    models = raw.get("models", [])
    provider_names = [str(item["name"]) for item in providers]
    model_ids = [str(item["model_id"]) for item in models]
    candidate_ids = [str(item["id"]) for item in raw["candidates"]]
    for label, values in (
        ("provider name", provider_names),
        ("model id", model_ids),
        ("candidate id", candidate_ids),
    ):
        if len(values) != len(set(values)):
            raise ConfigError(f"duplicate {label}")
    known_providers = set(provider_names)
    known_models = set(model_ids)
    for model in models:
        if model["provider"] not in known_providers:
            raise ConfigError(f"unknown provider for model: {model['model_id']}")
    for candidate in raw["candidates"]:
        if candidate["adapter"] == "bailian-live" and candidate["model"] not in known_models:
            raise ConfigError(f"unknown live candidate model: {candidate['model']}")


def load_run_config(path: str | pathlib.Path) -> RunConfig:
    """Load a run config; credentials remain environment names, never values."""

    source = pathlib.Path(path).resolve()
    try:
        payload = source.read_bytes()
        raw = json.loads(payload)
    except FileNotFoundError as exc:
        raise ConfigError(f"run config not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"run config is invalid JSON: {source}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("run config must be a JSON object")
    findings = scan_persisted_value_for_secrets(raw)
    if findings:
        raise ConfigError("run config fails secret scan at: " + ", ".join(findings))
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(raw),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise ConfigError("run config schema failed: " + _format_error(errors[0]))
    _cross_validate(raw)
    providers = tuple(
        ProviderConfig(
            name=item["name"],
            api=item["api"],
            protocol=item["protocol"],
            adapter=item["adapter"],
            base_url=item["base_url"],
            credential_env=item["credential_env"],
            default_generation=dict(item.get("default_generation") or {}),
            timeout_seconds=float(item.get("timeout_seconds", 120)),
        )
        for item in raw.get("providers", [])
    )
    models = tuple(
        ModelConfig(
            model_id=item["model_id"],
            provider=item["provider"],
            allowed_response_model_ids=tuple(
                item.get("allowed_response_model_ids", [item["model_id"]])
            ),
            capabilities=dict(item.get("capabilities") or {}),
            default_generation=dict(item.get("default_generation") or {}),
        )
        for item in raw.get("models", [])
    )
    return RunConfig(
        schema_version=str(raw["schema_version"]),
        providers=providers,
        models=models,
        profiles={item["name"]: dict(item["generation"]) for item in raw.get("profiles", [])},
        source_path=source,
        source_sha256=hashlib.sha256(payload).hexdigest(),
    )


def endpoint_origin(base_url: str) -> tuple[str, str]:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ConfigError("base_url must be an absolute HTTP(S) URL")
    port = f":{parsed.port}" if parsed.port else ""
    origin = f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"
    return origin, hashlib.sha256(origin.encode()).hexdigest()
