"""Minimal redaction-safe HTTP transport for Bailian's OpenAI-compatible API.

The transport deliberately returns a small normalized response. Provider bodies,
headers, credentials, and error text are never included in exceptions or traces.
"""

from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from providers.bailian import BailianSettings


@dataclass(frozen=True)
class BailianHTTPError(RuntimeError):
    failure_type: str
    retryable: bool
    http_status: int | None = None
    provider_code: str | None = None

    def __str__(self) -> str:
        status = f" http_status={self.http_status}" if self.http_status is not None else ""
        return f"Bailian request failed: {self.failure_type}{status}"


def _number(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def build_chat_completions_payload(
    request: Mapping[str, Any], *, force_tool_call: bool = False
) -> dict[str, Any]:
    """Translate the frozen provider-neutral shape to Chat Completions."""

    parameters = dict(request["parameters"])
    payload: dict[str, Any] = {
        "model": request["model"],
        "messages": request["messages"],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in request["tools"]
        ],
    }
    payload.update({key: _number(value) for key, value in parameters.items()})
    if force_tool_call:
        # Bailian's three configured model endpoints accept the standard
        # OpenAI function schema with automatic selection. The OpenAI string
        # value "required" is rejected by qwen/deepseek here and is ignored by
        # glm, while "auto" is accepted and emits the instructed tool call.
        payload["tool_choice"] = "auto"
    return payload


def _join_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")).rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return normalized + "/chat/completions"


def _parse_sse(raw: bytes) -> dict[str, Any]:
    model: str | None = None
    content: list[str] = []
    tool_call_seen = False
    usage: dict[str, Any] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise BailianHTTPError("invalid_provider_response", False) from exc
        if chunk.get("model") is not None:
            model = str(chunk["model"])
        if isinstance(chunk.get("usage"), Mapping):
            usage = dict(chunk["usage"])
        choices = chunk.get("choices") or []
        if choices and isinstance(choices[0], Mapping):
            delta = choices[0].get("delta") or {}
            if isinstance(delta, Mapping):
                if isinstance(delta.get("content"), str):
                    content.append(delta["content"])
                if delta.get("tool_calls"):
                    tool_call_seen = True
    return {
        "model": model,
        "output": "".join(content),
        "tool_call_supported": tool_call_seen,
        "usage": usage,
    }


def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BailianHTTPError("invalid_provider_response", False) from exc
    if not isinstance(body, Mapping):
        raise BailianHTTPError("invalid_provider_response", False)
    choices = body.get("choices") or []
    message: Mapping[str, Any] = {}
    if choices and isinstance(choices[0], Mapping):
        candidate = choices[0].get("message") or {}
        if isinstance(candidate, Mapping):
            message = candidate
    return {
        "model": str(body["model"]) if body.get("model") is not None else None,
        "output": message.get("content") or "",
        "tool_call_supported": bool(message.get("tool_calls")),
        "usage": dict(body.get("usage") or {}),
    }


def _classify_http(status: int) -> tuple[str, bool]:
    if status == 429:
        return "rate_limited", True
    if status in {408, 504}:
        return "timeout", True
    if status >= 500:
        return "provider_unavailable", True
    if status == 401:
        return "authentication_failed", False
    if status == 403:
        return "permission_denied", False
    return "provider_rejected_request", False


def _safe_provider_code(raw: bytes) -> str | None:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(body, Mapping):
        return None
    error = body.get("error")
    if not isinstance(error, Mapping):
        return None
    candidate = error.get("code") or error.get("type")
    if not isinstance(candidate, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", candidate):
        return None
    return candidate


class BailianHTTPTransport:
    def __init__(self, settings: BailianSettings, *, timeout_seconds: float = 120):
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def __call__(
        self, request: dict[str, Any], *, force_tool_call: bool = False
    ) -> Mapping[str, Any]:
        payload = build_chat_completions_payload(
            request, force_tool_call=force_tool_call
        )
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = Request(
            _join_url(self.settings.base_url),
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if payload.get("stream") else "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            failure_type, retryable = _classify_http(exc.code)
            provider_code = _safe_provider_code(exc.read()) if exc.fp is not None else None
            raise BailianHTTPError(failure_type, retryable, exc.code, provider_code) from None
        except (TimeoutError, socket.timeout) as exc:
            raise BailianHTTPError("timeout", True) from exc
        except URLError as exc:
            reason = exc.reason
            failure_type = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "provider_unavailable"
            raise BailianHTTPError(failure_type, True) from None

        stripped = raw.lstrip()
        normalized = _parse_json(raw) if stripped.startswith(b"{") else _parse_sse(raw)
        raw_usage = normalized.get("usage") or {}
        normalized["usage"] = {
            "input_tokens": int(raw_usage.get("prompt_tokens", 0)),
            "output_tokens": int(raw_usage.get("completion_tokens", 0)),
        }
        normalized["accepted_parameters"] = list(request["parameters"])
        normalized["fallback_detected"] = False
        return normalized
