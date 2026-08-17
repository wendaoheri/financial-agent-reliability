"""OpenAI-compatible Bailian adapter with exact model identity preflight.

PER-323 Stage 2 (§5.2): bailian is now one configurable provider among the
inference configuration (``configs/inference.json``). Public module paths and
symbol names are preserved (``BailianSettings``, ``BailianAdapter``,
``BailianConfigError``, ``PreflightResult``, ``build_all_adapters``); the
module-level ``CONFIG_PATH`` pin to the removed frozen directory is gone —
request templates come from ``configs/harness_contract.v1.json`` and the
provider/model blocks from the inference configuration. Secrets still come
only from environment variables.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from financial_agent_reliability.inference_config import (
    InferenceConfig,
    InferenceConfigError,
    ProviderConfig,
    endpoint_origin,
    load_inference_config,
    merged_parameters,
)


ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_HARNESS_CONTRACT_PATH = ROOT / "configs" / "harness_contract.v1.json"
PROVIDER_NAME = "bailian"
#: Transitional compatibility variable (design contract §4.1): if still set,
#: its parsed value must match the configured bailian model set item by item.
LEGACY_MODEL_IDS_ENV = "BENCH_BAILIAN_MODEL_IDS"


class BailianConfigError(ValueError):
    pass


def expected_models(config: InferenceConfig | None = None) -> tuple[str, ...]:
    """Configured bailian candidate model IDs (replaces the hard-coded tuple)."""
    config = config or load_inference_config()
    return tuple(model.model_id for model in config.models_for_provider(PROVIDER_NAME))


def __getattr__(name: str) -> Any:
    """PEP 562: keep ``EXPECTED_MODELS`` importable during the transition."""
    if name == "EXPECTED_MODELS":
        return expected_models()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass(frozen=True)
class BailianSettings:
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model_ids: tuple[str, ...]
    endpoint_id: str
    origin_sha256: str

    @classmethod
    def from_config(
        cls,
        config: InferenceConfig,
        env: Mapping[str, str],
        provider_name: str = PROVIDER_NAME,
    ) -> "BailianSettings":
        provider = config.provider(provider_name)
        models = config.models_for_provider(provider_name)
        if not models:
            raise BailianConfigError(
                f"provider '{provider_name}' has no models in the inference config"
            )
        model_ids = tuple(model.model_id for model in models)
        if provider_name == PROVIDER_NAME:
            _check_legacy_model_ids_env(env, model_ids)
        base_url = _resolve_base_url(provider, env)
        credential_env = provider.credential_env
        api_key = env.get(credential_env)
        if not api_key:
            raise BailianConfigError(f"missing required environment: {credential_env}")
        _origin, origin_hash = endpoint_origin(base_url)
        return cls(
            base_url=base_url,
            api_key=api_key,
            model_ids=model_ids,
            endpoint_id=f"{provider_name}_{origin_hash[:12]}",
            origin_sha256=origin_hash,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "BailianSettings":
        """Compatibility entry: semantics equal to ``from_config(load_inference_config(), env)``."""
        return cls.from_config(load_inference_config(env=env), env)


def _resolve_base_url(provider: ProviderConfig, env: Mapping[str, str]) -> str:
    """Env override wins over the config file (design contract §3.5 rule 1)."""
    candidates = [f"FARELI_{provider.name.upper().replace('-', '_')}_BASE_URL"]
    if provider.name == PROVIDER_NAME:
        candidates.append("BENCH_BAILIAN_BASE_URL")
    for name in candidates:
        override = env.get(name)
        if override:
            parsed = urlsplit(override)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                raise BailianConfigError(f"{name} must be an absolute HTTP(S) URL")
            return override
    return provider.base_url


def _check_legacy_model_ids_env(env: Mapping[str, str], model_ids: tuple[str, ...]) -> None:
    raw_models = env.get(LEGACY_MODEL_IDS_ENV)
    if not raw_models:
        return
    try:
        decoded = json.loads(raw_models)
    except json.JSONDecodeError:
        decoded = [item.strip() for item in raw_models.split(",") if item.strip()]
    if not isinstance(decoded, list) or tuple(str(item) for item in decoded) != model_ids:
        raise BailianConfigError(
            "BENCH_BAILIAN_MODEL_IDS must contain exactly the configured model IDs "
            f"({', '.join(model_ids)}) — transitional strict-consistency rule, design "
            "contract §4.1/Q3"
        )


@dataclass(frozen=True)
class PreflightResult:
    model_id: str
    response_model_id: str | None
    valid: bool
    failure_type: str | None
    retryable: bool
    fallback_attempted: bool
    endpoint_id: str
    provider_error_code: str | None = None
    http_status: int | None = None


Transport = Callable[[dict[str, Any]], Mapping[str, Any]]


def _load_harness_contract(harness_contract: str | pathlib.Path | Mapping[str, Any] | None) -> Mapping[str, Any]:
    if isinstance(harness_contract, Mapping):
        return harness_contract
    path = pathlib.Path(harness_contract) if harness_contract else DEFAULT_HARNESS_CONTRACT_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BailianConfigError(f"harness contract not found: {path}") from exc


class BailianAdapter:
    """One model-neutral adapter instance bound to one exact candidate ID."""

    def __init__(
        self,
        settings: BailianSettings,
        model_id: str,
        harness_contract: str | pathlib.Path | Mapping[str, Any] | None = None,
        *,
        config: InferenceConfig | None = None,
        parameters: Mapping[str, Any] | None = None,
        preflight_tool_instruction: str | None = None,
    ):
        if model_id not in settings.model_ids:
            raise BailianConfigError("adapter model ID is not in the configured exact identity set")
        self.settings = settings
        self.model_id = model_id
        self._harness = _load_harness_contract(harness_contract)
        if parameters is None or preflight_tool_instruction is None:
            config = config or load_inference_config()
            provider = config.provider(PROVIDER_NAME)
            if preflight_tool_instruction is None:
                preflight_tool_instruction = provider.preflight_tool_instruction
            if parameters is None:
                model = next(
                    item for item in config.models if item.model_id == model_id
                )
                parameters = merged_parameters(config, model)
        self._parameters: Mapping[str, Any] = dict(parameters)
        self._preflight_instruction = preflight_tool_instruction

    @property
    def parameters(self) -> Mapping[str, Any]:
        return dict(self._parameters)

    def build_request(self, seed: int, user_content: str | None = None) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self._harness["system_prompt"]},
                {
                    "role": "user",
                    "content": user_content or self._preflight_instruction,
                },
            ],
            "tools": self._harness["tools"],
            "parameters": dict(self._parameters, seed=seed),
        }

    def preflight(self, transport: Transport) -> PreflightResult:
        preflight_seed = int(self._harness.get("seed_policy", {}).get("preflight_seed", 20260811))
        request = self.build_request(preflight_seed)
        try:
            response = transport(request)
        except TimeoutError:
            return PreflightResult(
                self.model_id, None, False, "timeout", True, False, self.settings.endpoint_id
            )
        except Exception as exc:
            failure_type = getattr(exc, "failure_type", None)
            retryable = getattr(exc, "retryable", None)
            if isinstance(failure_type, str) and isinstance(retryable, bool):
                return PreflightResult(
                    self.model_id,
                    None,
                    False,
                    failure_type,
                    retryable,
                    False,
                    self.settings.endpoint_id,
                    getattr(exc, "provider_code", None),
                    getattr(exc, "http_status", None),
                )
            raise
        response_model = response.get("model")
        fallback = bool(response.get("fallback_detected", False))
        allowed = self._allowed_response_model_ids()
        if response_model not in allowed:
            return PreflightResult(
                self.model_id,
                str(response_model) if response_model is not None else None,
                False,
                "identity_mismatch",
                False,
                False,
                self.settings.endpoint_id,
            )
        if fallback:
            return PreflightResult(
                self.model_id, str(response_model), False, "fallback_detected", False, False,
                self.settings.endpoint_id,
            )
        required_parameters = set(request["parameters"])
        accepted = set(response.get("accepted_parameters", ()))
        if accepted != required_parameters:
            return PreflightResult(
                self.model_id, str(response_model), False, "parameters_ignored", False, False,
                self.settings.endpoint_id,
            )
        if response.get("tool_call_supported") is not True:
            return PreflightResult(
                self.model_id, str(response_model), False, "tool_capability_unverified", False, False,
                self.settings.endpoint_id,
            )
        return PreflightResult(
            self.model_id, str(response_model), True, None, False, False,
            self.settings.endpoint_id,
        )

    def _allowed_response_model_ids(self) -> frozenset[str]:
        try:
            config = load_inference_config()
            model = next(
                (item for item in config.models if item.model_id == self.model_id), None
            )
            if model is not None:
                return frozenset(model.allowed_response_model_ids)
        except InferenceConfigError:
            pass
        return frozenset({self.model_id})


def build_all_adapters(
    settings: BailianSettings,
    *,
    config: InferenceConfig | None = None,
    harness_contract: str | pathlib.Path | Mapping[str, Any] | None = None,
) -> tuple[BailianAdapter, ...]:
    config = config or load_inference_config()
    provider = config.provider(PROVIDER_NAME)
    adapters: list[BailianAdapter] = []
    for model in config.models_for_provider(PROVIDER_NAME):
        adapters.append(
            BailianAdapter(
                settings,
                model.model_id,
                harness_contract,
                config=config,
                parameters=merged_parameters(config, model),
                preflight_tool_instruction=provider.preflight_tool_instruction,
            )
        )
    return tuple(adapters)
