"""Pure protocol codecs used by provider adapters and offline golden tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ProtocolCodecError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedEvent:
    kind: str
    text: str | None = None
    usage: Mapping[str, Any] | None = None


def build_protocol_payload(
    protocol: str,
    *,
    model: str,
    messages: list[Mapping[str, Any]],
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    """Translate normalized effective parameters into one provider wire shape."""

    values = dict(parameters)
    if protocol == "openai_chat_completions":
        return {"model": model, "messages": messages, **values}
    if protocol == "openai_responses":
        payload: dict[str, Any] = {
            "model": model,
            "input": messages,
            "stream": bool(values.pop("stream", False)),
            "max_output_tokens": values.pop("max_tokens"),
        }
        effort = values.pop("reasoning_effort", None)
        if effort is not None:
            payload["reasoning"] = {"effort": effort}
        payload.update(values)
        return payload
    if protocol == "anthropic_messages":
        system = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        )
        payload = {
            "model": model,
            "messages": [dict(message) for message in messages if message.get("role") != "system"],
            "max_tokens": values.pop("max_tokens"),
            "stream": bool(values.pop("stream", False)),
        }
        if system:
            payload["system"] = system
        payload.update(values)
        return payload
    if protocol == "gemini_generate_content":
        system_parts = [
            {"text": str(message.get("content", ""))}
            for message in messages
            if message.get("role") == "system"
        ]
        contents = [
            {
                "role": "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": str(message.get("content", ""))}],
            }
            for message in messages
            if message.get("role") != "system"
        ]
        generation = {
            "maxOutputTokens": values.pop("max_tokens"),
            "temperature": values.pop("temperature", None),
            "topP": values.pop("top_p", None),
        }
        thinking = values.pop("thinking_config", None)
        if thinking is not None:
            generation["thinkingConfig"] = {
                "thinkingBudget": thinking["thinking_budget"]
            }
        generation = {key: value for key, value in generation.items() if value is not None}
        payload = {"model": model, "contents": contents, "generationConfig": generation}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        # Gemini selects streaming through the RPC method, not a JSON field.
        payload["stream"] = bool(values.pop("stream", False))
        if values:
            raise ProtocolCodecError(
                "unsupported Gemini effective parameters: " + ", ".join(sorted(values))
            )
        return payload
    raise ProtocolCodecError(f"unsupported inference protocol: {protocol}")


def normalize_stream_event(protocol: str, event: Mapping[str, Any]) -> list[NormalizedEvent]:
    """Normalize one decoded provider event without retaining hidden reasoning."""

    normalized: list[NormalizedEvent] = []
    if protocol in {"openai_chat_completions", "openai_responses"}:
        if protocol == "openai_responses":
            event_type = event.get("type")
            delta = event.get("delta")
            if event_type in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"} and isinstance(delta, str):
                normalized.append(NormalizedEvent("reasoning_delta", text=delta))
            elif event_type == "response.output_text.delta" and isinstance(delta, str):
                normalized.append(NormalizedEvent("content_delta", text=delta))
            if isinstance(event.get("usage"), Mapping):
                normalized.append(NormalizedEvent("usage", usage=dict(event["usage"])))
            return normalized
        if isinstance(event.get("usage"), Mapping):
            normalized.append(NormalizedEvent("usage", usage=dict(event["usage"])))
        choices = event.get("choices") or []
        if choices and isinstance(choices[0], Mapping):
            delta = choices[0].get("delta") or {}
            reasoning = delta.get("reasoning_content") if isinstance(delta, Mapping) else None
            content = delta.get("content") if isinstance(delta, Mapping) else None
            if isinstance(reasoning, str) and reasoning:
                normalized.append(NormalizedEvent("reasoning_delta", text=reasoning))
            if isinstance(content, str) and content:
                normalized.append(NormalizedEvent("content_delta", text=content))
        return normalized
    if protocol == "anthropic_messages":
        delta = event.get("delta") or {}
        if event.get("type") == "content_block_delta" and isinstance(delta, Mapping):
            if delta.get("type") == "thinking_delta" and isinstance(delta.get("thinking"), str):
                normalized.append(NormalizedEvent("reasoning_delta", text=delta["thinking"]))
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                normalized.append(NormalizedEvent("content_delta", text=delta["text"]))
        usage = event.get("usage") or delta.get("usage") if isinstance(delta, Mapping) else None
        if isinstance(usage, Mapping):
            normalized.append(NormalizedEvent("usage", usage=dict(usage)))
        return normalized
    if protocol == "gemini_generate_content":
        for candidate in event.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                text = part.get("text")
                if isinstance(text, str) and text:
                    normalized.append(
                        NormalizedEvent(
                            "reasoning_delta" if part.get("thought") is True else "content_delta",
                            text=text,
                        )
                    )
        if isinstance(event.get("usageMetadata"), Mapping):
            normalized.append(NormalizedEvent("usage", usage=dict(event["usageMetadata"])))
        return normalized
    raise ProtocolCodecError(f"unsupported inference protocol: {protocol}")
