"""Environment-only credentials and endpoint settings for Bailian."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from financial_agent_reliability.config import RunConfig, endpoint_origin


class BailianConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BailianSettings:
    provider_name: str
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model_ids: tuple[str, ...]
    endpoint_id: str

    @classmethod
    def from_config(
        cls,
        config: RunConfig,
        env: Mapping[str, str],
        provider_name: str = "bailian",
    ) -> BailianSettings:
        provider = config.provider(provider_name)
        models = config.models_for_provider(provider_name)
        if not models:
            raise BailianConfigError(f"provider has no models: {provider_name}")
        base_url = env.get("BENCH_BAILIAN_BASE_URL", provider.base_url)
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise BailianConfigError("BENCH_BAILIAN_BASE_URL must be an absolute HTTP(S) URL")
        api_key = env.get(provider.credential_env)
        if not api_key:
            raise BailianConfigError(f"missing required environment: {provider.credential_env}")
        _origin, origin_hash = endpoint_origin(base_url)
        return cls(
            provider_name=provider_name,
            base_url=base_url,
            api_key=api_key,
            model_ids=tuple(model.model_id for model in models),
            endpoint_id=f"{provider_name}_{origin_hash[:12]}",
        )
