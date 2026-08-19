"""Provider-neutral generation policy resolution and provider adaptation.

The public configuration expresses intent.  This module resolves that intent
against a model capability contract before emitting any provider parameters.
Unsupported combinations fail before a network request can be constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class GenerationConfigError(ValueError):
    """Raised when requested generation behavior cannot be represented safely."""


_TRI_STATE = frozenset({"auto", "on", "off"})
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})


@dataclass(frozen=True)
class ResolvedGeneration:
    requested: Mapping[str, Any]
    resolved: Mapping[str, Any]
    effective_parameters: Mapping[str, Any]
    sources: Mapping[str, str]
    provider_adapter: str
    protocol: str
    capabilities: Mapping[str, Any]

    def trace_record(self) -> dict[str, Any]:
        return {
            "requested": dict(self.requested),
            "resolved": dict(self.resolved),
            "effective_parameters": dict(self.effective_parameters),
            "sources": dict(self.sources),
            "provider_adapter": self.provider_adapter,
            "protocol": self.protocol,
            "capabilities": dict(self.capabilities),
        }


def _merge(
    target: dict[str, Any],
    incoming: Mapping[str, Any] | None,
    source: str,
    sources: dict[str, str],
) -> None:
    if not incoming:
        return
    for key, value in incoming.items():
        if key == "reasoning":
            if not isinstance(value, Mapping):
                raise GenerationConfigError("generation.reasoning must be an object")
            reasoning = target.setdefault("reasoning", {})
            for nested_key, nested_value in value.items():
                reasoning[nested_key] = nested_value
                sources[f"reasoning.{nested_key}"] = source
        else:
            target[key] = value
            sources[key] = source


def _tri_state(value: Any, label: str) -> str:
    if value not in _TRI_STATE:
        raise GenerationConfigError(f"{label} must be auto, on, or off")
    return str(value)


def _concrete_mode(requested: str, capability: str, label: str) -> str:
    if capability not in {"required", "supported", "optional", "unsupported"}:
        raise GenerationConfigError(f"invalid {label} capability: {capability}")
    normalized = "supported" if capability == "optional" else capability
    if requested == "on" and normalized == "unsupported":
        raise GenerationConfigError(f"{label}=on is unsupported by this model")
    if requested == "off" and normalized == "required":
        raise GenerationConfigError(f"{label}=off is invalid because this model requires it")
    if requested != "auto":
        return requested
    if normalized == "required":
        return "on"
    if normalized == "unsupported":
        return "off"
    # Optional capabilities default off unless a provider/model/profile chose
    # an explicit value.  This keeps ``auto`` deterministic and auditable.
    return "off"


def _provider_parameters(
    *, adapter: str, protocol: str, resolved: Mapping[str, Any], capabilities: Mapping[str, Any]
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "stream": resolved["stream"] == "on",
        "max_tokens": int(resolved["max_output_tokens"]),
    }
    for key in ("temperature", "top_p", "seed"):
        value = resolved.get(key)
        if value is not None:
            parameters[key] = value

    reasoning = resolved["reasoning"]
    mode = reasoning["mode"]
    effort = reasoning.get("effort")
    budget = reasoning.get("budget_tokens")
    controls = set(capabilities.get("reasoning_controls", ()))
    if effort is not None and "effort" not in controls:
        raise GenerationConfigError("reasoning.effort is unsupported by this model")
    if budget is not None and "budget_tokens" not in controls:
        raise GenerationConfigError("reasoning.budget_tokens is unsupported by this model")
    if effort is not None and budget is not None:
        raise GenerationConfigError(
            "reasoning.effort and reasoning.budget_tokens are mutually exclusive"
        )
    if mode == "off" and (effort is not None or budget is not None):
        raise GenerationConfigError("reasoning controls require reasoning.mode=on")

    if adapter in {"bailian", "dashscope"}:
        if capabilities.get("reasoning") != "required":
            parameters["enable_thinking"] = mode == "on"
        if effort is not None:
            parameters["reasoning_effort"] = effort
        if budget is not None:
            parameters["thinking_budget"] = int(budget)
    elif adapter == "openai":
        if effort is not None:
            parameters["reasoning_effort"] = effort
        elif mode == "on" and "effort" not in controls:
            raise GenerationConfigError("OpenAI reasoning requires a supported effort control")
    elif adapter == "anthropic":
        if mode == "on":
            if budget is None:
                raise GenerationConfigError("Anthropic thinking requires budget_tokens")
            parameters["thinking"] = {"type": "enabled", "budget_tokens": int(budget)}
            parameters["max_tokens"] += int(budget)
        else:
            parameters["thinking"] = {"type": "disabled"}
    elif adapter == "gemini":
        parameters["thinking_config"] = {
            "thinking_budget": int(budget) if mode == "on" and budget is not None else 0
        }
    elif adapter in {"bigmodel", "glm"}:
        parameters["thinking"] = {"type": "enabled" if mode == "on" else "disabled"}
    else:
        raise GenerationConfigError(f"unsupported provider adapter: {adapter}")

    if protocol not in {
        "openai_chat_completions",
        "openai_responses",
        "anthropic_messages",
        "gemini_generate_content",
    }:
        raise GenerationConfigError(f"unsupported inference protocol: {protocol}")
    return parameters


def resolve_generation(
    provider: Any,
    model: Any,
    *,
    profile: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
) -> ResolvedGeneration:
    """Resolve provider -> model -> profile -> candidate generation policy."""

    requested: dict[str, Any] = {
        "stream": "auto",
        "reasoning": {"mode": "auto", "effort": None, "budget_tokens": None},
        "max_output_tokens": 4096,
        "temperature": None,
        "top_p": None,
        "seed": None,
    }
    sources: dict[str, str] = {
        "stream": "built_in",
        "reasoning.mode": "built_in",
        "reasoning.effort": "built_in",
        "reasoning.budget_tokens": "built_in",
        "max_output_tokens": "built_in",
        "temperature": "built_in",
        "top_p": "built_in",
        "seed": "built_in",
    }
    _merge(requested, provider.default_generation, "provider", sources)
    _merge(requested, model.default_generation, "model", sources)
    _merge(requested, profile, "profile", sources)
    _merge(requested, candidate, "candidate", sources)

    stream_requested = _tri_state(requested["stream"], "stream")
    reasoning_requested = _tri_state(requested["reasoning"]["mode"], "reasoning.mode")
    capabilities = dict(model.capabilities)
    resolved = {
        **requested,
        "stream": _concrete_mode(
            stream_requested, str(capabilities.get("stream", "supported")), "stream"
        ),
        "reasoning": {
            **requested["reasoning"],
            "mode": _concrete_mode(
                reasoning_requested,
                str(capabilities.get("reasoning", "unsupported")),
                "reasoning",
            ),
        },
    }
    effort = resolved["reasoning"].get("effort")
    if effort is not None and effort not in _REASONING_EFFORTS:
        raise GenerationConfigError("reasoning.effort must be low, medium, high, or xhigh")
    budget = resolved["reasoning"].get("budget_tokens")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget < 1):
        raise GenerationConfigError("reasoning.budget_tokens must be a positive integer")
    maximum = resolved.get("max_output_tokens")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise GenerationConfigError("max_output_tokens must be a positive integer")

    parameters = _provider_parameters(
        adapter=provider.adapter,
        protocol=provider.protocol,
        resolved=resolved,
        capabilities=capabilities,
    )
    return ResolvedGeneration(
        requested=requested,
        resolved=resolved,
        effective_parameters=parameters,
        sources=sources,
        provider_adapter=provider.adapter,
        protocol=provider.protocol,
        capabilities=capabilities,
    )
