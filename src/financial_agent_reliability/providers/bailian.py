"""OpenAI-compatible Bailian adapter with exact model identity preflight."""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v2.json"
EXPECTED_MODELS = ("qwen3.8-max", "glm-5.2", "deepseek-v4-pro")


class BailianConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BailianSettings:
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model_ids: tuple[str, ...]
    endpoint_id: str
    origin_sha256: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "BailianSettings":
        required = (
            "BENCH_BAILIAN_API_KEY",
            "BENCH_BAILIAN_BASE_URL",
            "BENCH_BAILIAN_MODEL_IDS",
        )
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise BailianConfigError(f"missing required environment: {', '.join(missing)}")
        raw_models = env["BENCH_BAILIAN_MODEL_IDS"]
        try:
            decoded = json.loads(raw_models)
        except json.JSONDecodeError:
            decoded = [item.strip() for item in raw_models.split(",") if item.strip()]
        if not isinstance(decoded, list) or tuple(decoded) != EXPECTED_MODELS:
            raise BailianConfigError(
                "BENCH_BAILIAN_MODEL_IDS must contain exactly the three frozen model IDs"
            )
        parsed = urlsplit(env["BENCH_BAILIAN_BASE_URL"])
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise BailianConfigError("BENCH_BAILIAN_BASE_URL must be an absolute HTTP(S) URL")
        port = f":{parsed.port}" if parsed.port else ""
        origin = f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"
        origin_hash = hashlib.sha256(origin.encode("utf-8")).hexdigest()
        return cls(
            base_url=env["BENCH_BAILIAN_BASE_URL"],
            api_key=env["BENCH_BAILIAN_API_KEY"],
            model_ids=tuple(str(item) for item in decoded),
            endpoint_id=f"bailian_{origin_hash[:12]}",
            origin_sha256=origin_hash,
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


class BailianAdapter:
    """One model-neutral adapter instance bound to one exact candidate ID."""

    def __init__(self, settings: BailianSettings, model_id: str):
        if model_id not in EXPECTED_MODELS or model_id not in settings.model_ids:
            raise BailianConfigError("adapter model ID is not in the frozen exact identity set")
        self.settings = settings
        self.model_id = model_id
        self._config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def build_request(self, seed: int, user_content: str | None = None) -> dict[str, Any]:
        parameters = dict(self._config["request_parameters"])
        parameters.pop("seed_required")
        return {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self._config["system_prompt"]},
                {
                    "role": "user",
                    "content": user_content
                    or self._config["provider"]["preflight_tool_instruction"],
                },
            ],
            "tools": self._config["tools"],
            "parameters": dict(parameters, seed=seed),
        }

    def preflight(self, transport: Transport) -> PreflightResult:
        request = self.build_request(20260811)
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
        if response_model != self.model_id:
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


def build_all_adapters(settings: BailianSettings) -> tuple[BailianAdapter, ...]:
    return tuple(BailianAdapter(settings, model_id) for model_id in EXPECTED_MODELS)
