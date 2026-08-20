"""Minimal redaction-safe HTTP transport for Bailian's OpenAI-compatible API.

The transport deliberately returns a small normalized response. Provider bodies,
headers, credentials, and error text are never included in exceptions or traces.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from financial_agent_reliability.adapters.settings import BailianSettings


@dataclass(frozen=True)
class BailianHTTPError(RuntimeError):
    failure_type: str
    retryable: bool
    http_status: int | None = None
    provider_code: str | None = None
    request_id: str | None = None
    error_origin: str = "provider_payload"

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
    """Translate the provider-neutral request shape to Chat Completions."""

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


def _parse_sse_lines(
    lines: Any, *, started: float, clock: Any = time.perf_counter
) -> dict[str, Any]:
    model: str | None = None
    content: list[str] = []
    reasoning_digest = hashlib.sha256()
    reasoning_chars = 0
    tool_call_seen = False
    usage: dict[str, Any] = {}
    ttft_reasoning_ms: int | None = None
    ttft_content_ms: int | None = None
    for raw_line in lines:
        line = (
            raw_line.decode("utf-8", errors="replace")
            if isinstance(raw_line, bytes)
            else str(raw_line)
        ).strip()
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
                    value = delta["content"]
                    if value and ttft_content_ms is None:
                        ttft_content_ms = max(0, round((clock() - started) * 1000))
                    content.append(value)
                if isinstance(delta.get("reasoning_content"), str):
                    value = delta["reasoning_content"]
                    if value and ttft_reasoning_ms is None:
                        ttft_reasoning_ms = max(0, round((clock() - started) * 1000))
                    encoded = value.encode("utf-8")
                    reasoning_digest.update(encoded)
                    reasoning_chars += len(value)
                if delta.get("tool_calls"):
                    tool_call_seen = True
    return {
        "model": model,
        "output": "".join(content),
        "tool_call_supported": tool_call_seen,
        "usage": usage,
        "reasoning_summary": {
            "characters": reasoning_chars,
            "sha256": reasoning_digest.hexdigest() if reasoning_chars else None,
        },
        "stream_metrics": {
            "mode": "streaming",
            "ttft_reasoning_ms": ttft_reasoning_ms,
            "ttft_content_ms": ttft_content_ms,
            "e2e_ms": max(0, round((clock() - started) * 1000)),
        },
    }


def _parse_sse(raw: bytes) -> dict[str, Any]:
    started = time.perf_counter()
    return _parse_sse_lines(raw.splitlines(), started=started)


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
        "reasoning_summary": {"characters": 0, "sha256": None},
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


def _safe_request_id(headers: Any) -> str | None:
    if headers is None:
        return None
    for name in ("x-request-id", "request-id", "x-dashscope-request-id"):
        candidate = headers.get(name)
        if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", candidate):
            return candidate
    return None


class BailianHTTPTransport:
    def __init__(self, settings: BailianSettings, *, timeout_seconds: float = 120):
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def __call__(
        self, request: dict[str, Any], *, force_tool_call: bool = False
    ) -> Mapping[str, Any]:
        payload = build_chat_completions_payload(request, force_tool_call=force_tool_call)
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
            started = time.perf_counter()
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                headers = getattr(response, "headers", None)
                request_id = _safe_request_id(headers)
                getcode = getattr(response, "getcode", None)
                status = int(getcode() if callable(getcode) else response.status)
                if payload.get("stream") and hasattr(response, "__iter__"):
                    normalized = _parse_sse_lines(response, started=started)
                else:
                    raw = response.read()
                    normalized = (
                        _parse_json(raw) if raw.lstrip().startswith(b"{") else _parse_sse(raw)
                    )
                    elapsed = max(0, round((time.perf_counter() - started) * 1000))
                    normalized["stream_metrics"] = {
                        "mode": "non_streaming",
                        "ttft_reasoning_ms": None,
                        "ttft_content_ms": elapsed,
                        "e2e_ms": elapsed,
                    }
                normalized["http_observation"] = {
                    "status": status,
                    "provider_code": None,
                    "request_id": request_id,
                    "error_origin": None,
                }
        except HTTPError as exc:
            failure_type, retryable = _classify_http(exc.code)
            provider_code = _safe_provider_code(exc.read()) if exc.fp is not None else None
            raise BailianHTTPError(
                failure_type,
                retryable,
                exc.code,
                provider_code,
                _safe_request_id(exc.headers),
                "provider_http",
            ) from None
        except TimeoutError as exc:
            raise BailianHTTPError("timeout", True, error_origin="client_socket") from exc
        except URLError as exc:
            reason = exc.reason
            failure_type = (
                "timeout"
                if isinstance(reason, (TimeoutError, socket.timeout))
                else "provider_unavailable"
            )
            origin = "client_socket" if failure_type == "timeout" else "network"
            raise BailianHTTPError(failure_type, True, error_origin=origin) from None

        raw_usage = normalized.get("usage") or {}
        completion_details = raw_usage.get("completion_tokens_details") or {}
        normalized["usage"] = {
            "input_tokens": int(raw_usage.get("prompt_tokens", 0)),
            "output_tokens": int(raw_usage.get("completion_tokens", 0)),
        }
        if "reasoning_tokens" in completion_details:
            normalized["usage"]["reasoning_tokens"] = int(
                completion_details.get("reasoning_tokens", 0)
            )
        normalized["accepted_parameters"] = list(request["parameters"])
        normalized["fallback_detected"] = False
        return normalized
