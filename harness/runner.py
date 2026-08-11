"""Offline-capable runner that emits the frozen run_trace v1 shape."""

from __future__ import annotations

import hashlib
import json
import pathlib
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from contracts.run_trace_validator import (
    build_run_id,
    content_sha256,
    file_sha256,
)
from harness.bundle import ImmutableBundle
from harness.checkpoint import CheckpointStore
from harness.redaction import redact
from providers.bailian import BailianAdapter, Transport


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v2.json"
MODEL_MANIFEST_PATH = ROOT / "contracts" / "model_manifest.frozen.v2.json"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_decimal(value: str | Decimal) -> str:
    parsed = Decimal(value)
    return f"{parsed:.6f}"


class OfflineHarness:
    """Execute an injected transport; this class itself performs no network I/O."""

    def __init__(
        self,
        adapter: BailianAdapter,
        bundle: ImmutableBundle,
        checkpoint_directory: pathlib.Path,
        *,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.adapter = adapter
        self.bundle = bundle
        self.checkpoint_directory = pathlib.Path(checkpoint_directory)
        self.sleeper = sleeper or (lambda _seconds: None)
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def run(
        self,
        *,
        case_id: str,
        variant_id: str,
        repeat: int,
        seed: int,
        frozen_input_path: str,
        preflight_transport: Transport,
        inference_transport: Transport,
    ) -> dict[str, Any]:
        self.bundle.verify()
        relative_artifacts = [
            {"path": path, "sha256": sha256} for path, sha256 in self.bundle.artifacts
        ]
        frozen_path = self.bundle.root / frozen_input_path
        if frozen_input_path not in {item["path"] for item in relative_artifacts}:
            raise ValueError("frozen input is not committed in the immutable bundle")
        identity = {
            "benchmark_id": "financial-agent-reliability-v1",
            "case_id": case_id,
            "variant_id": variant_id,
            "requested_model_id": self.adapter.model_id,
            "repeat": repeat,
            "seed": seed,
            "harness_config_sha256": file_sha256(CONFIG_PATH),
            "immutable_bundle_sha256": self.bundle.bundle_sha256,
        }
        run_id = build_run_id(identity)
        checkpoint_path = self.checkpoint_directory / f"{run_id}.jsonl"
        resumed = checkpoint_path.is_file()
        store = (
            CheckpointStore.resume(self.checkpoint_directory, run_id)
            if resumed
            else CheckpointStore(self.checkpoint_directory, run_id)
        )
        started_at = _timestamp()
        started_ns = time.monotonic_ns()
        preflight = self.adapter.preflight(preflight_transport)
        attempts: list[dict[str, Any]] = []
        response: Mapping[str, Any] = {}
        terminal_failure: str | None = preflight.failure_type
        status = "invalidated" if not preflight.valid and not preflight.retryable else "failed"
        if preflight.valid:
            request = self.adapter.build_request(
                seed,
                frozen_path.read_text(encoding="utf-8"),
            )
            max_retries = int(self.config["resource_budget"]["max_retries"])
            backoffs = list(self.config["resource_budget"]["retry_backoff_ms"])
            for attempt_number in range(1, max_retries + 2):
                attempt_started = _timestamp()
                attempt_ns = time.monotonic_ns()
                failure_type: str | None = None
                retryable = False
                http_status: int | None = 200
                try:
                    candidate = inference_transport(request)
                    response_model = candidate.get("model")
                    if response_model != self.adapter.model_id:
                        failure_type = "identity_mismatch"
                        status = "invalidated"
                        terminal_failure = failure_type
                    elif candidate.get("fallback_detected") is True:
                        failure_type = "fallback_detected"
                        status = "invalidated"
                        terminal_failure = failure_type
                    else:
                        response = candidate
                        status = "succeeded"
                        terminal_failure = None
                except TimeoutError:
                    failure_type = "timeout"
                    retryable = True
                    http_status = None
                    status = "failed"
                    terminal_failure = failure_type
                except ConnectionError:
                    failure_type = "provider_unavailable"
                    retryable = True
                    http_status = 503
                    status = "failed"
                    terminal_failure = failure_type
                duration_ms = max(0, (time.monotonic_ns() - attempt_ns) // 1_000_000)
                should_retry = retryable and attempt_number <= max_retries
                backoff_ms = backoffs[attempt_number - 1] if should_retry else 0
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "started_at": attempt_started,
                        "finished_at": _timestamp(),
                        "duration_ms": duration_ms,
                        "outcome": status if status != "succeeded" else "succeeded",
                        "failure_type": failure_type,
                        "retryable": retryable,
                        "http_status": http_status,
                        "backoff_ms": backoff_ms,
                    }
                )
                if not should_retry:
                    break
                self.sleeper(backoff_ms / 1000)
        else:
            attempts.append(
                {
                    "attempt": 1,
                    "started_at": started_at,
                    "finished_at": _timestamp(),
                    "duration_ms": 0,
                    "outcome": status,
                    "failure_type": terminal_failure,
                    "retryable": preflight.retryable,
                    "http_status": None,
                    "backoff_ms": 0,
                }
            )

        persisted_state = {
            "status": status,
            "failure_type": terminal_failure,
            "response_sha256": hashlib.sha256(
                str(response.get("output", "")).encode("utf-8")
            ).hexdigest(),
        }
        checkpoint = store.append("run_completed", persisted_state)
        duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        raw_usage = response.get("usage", {}) if isinstance(response, Mapping) else {}
        input_tokens = int(raw_usage.get("input_tokens", 0))
        output_tokens = int(raw_usage.get("output_tokens", 0))
        raw_cost = response.get("cost", {}) if isinstance(response, Mapping) else {}
        input_cost = Decimal(str(raw_cost.get("input_usd", "0")))
        output_cost = Decimal(str(raw_cost.get("output_usd", "0")))
        checkpoint_id = f"cp_{checkpoint.offset:04d}"
        response_model = (
            str(response.get("model"))
            if response.get("model") is not None
            else (preflight.response_model_id or "unverified")
        )
        trace = {
            "contract_type": "run_trace",
            "contract_version": "2.0.0",
            "run_id": run_id,
            "run_identity": identity,
            "status": status,
            "provider": {
                "name": "bailian",
                "requested_model_id": self.adapter.model_id,
                "response_model_id": response_model,
                "endpoint_id": self.adapter.settings.endpoint_id,
                "model_manifest_sha256": file_sha256(MODEL_MANIFEST_PATH),
            },
            "request": {
                "parameters": {
                    key: value
                    for key, value in self.config["request_parameters"].items()
                    if key != "seed_required"
                },
                "seed": seed,
            },
            "preflight": {
                "performed": True,
                "identity_match": preflight.response_model_id == self.adapter.model_id,
                "fallback_detected": preflight.failure_type == "fallback_detected",
                "fallback_attempted": False,
                "parameters_honored": preflight.failure_type != "parameters_ignored",
                "endpoint_verified": True,
                "valid": preflight.valid,
                "invalid_reason": preflight.failure_type if not preflight.valid else None,
            },
            "context": {
                "system_prompt_sha256": content_sha256(self.config["system_prompt"]),
                "tool_schema_sha256": content_sha256(self.config["tools"]),
                "frozen_input_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                "messages_count": 2,
            },
            "tool_calls": [],
            "environment": {
                "dataset_access": "frozen_read_only",
                "ledger_mode": "simulated",
                "network_scope": "bailian_inference_only",
                "touched_paths": [],
            },
            "timing": {
                "started_at": started_at,
                "finished_at": _timestamp(),
                "duration_ms": duration_ms,
            },
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "model_requests": len(attempts),
                "turns": 1,
            },
            "cost": {
                "currency": "USD",
                "input_usd": _canonical_decimal(input_cost),
                "output_usd": _canonical_decimal(output_cost),
                "tool_usd": "0.000000",
                "total_usd": _canonical_decimal(input_cost + output_cost),
            },
            "attempts": attempts,
            "retry": {
                "max_retries": self.config["resource_budget"]["max_retries"],
                "retries_used": max(0, len(attempts) - 1),
            },
            "resume": {
                "resumed": resumed,
                "source_run_id": run_id if resumed else None,
                "checkpoint_id": checkpoint_id if resumed else None,
                "state_sha256": checkpoint.state_sha256 if resumed else None,
                "event_offset": checkpoint.offset if resumed else None,
            },
            "checkpoint": {
                "enabled": True,
                "checkpoint_id": checkpoint_id,
                "sequence": checkpoint.offset,
                "state_sha256": checkpoint.state_sha256,
                "prior_event_hash": checkpoint.event_sha256,
                "created_at": _timestamp(),
            },
            "failure": {
                "type": terminal_failure,
                "stage": "preflight" if not preflight.valid else ("provider_request" if terminal_failure else None),
                "retryable": bool(attempts[-1]["retryable"]),
                "message_redacted": None,
            },
            "result": {
                "response_sha256": persisted_state["response_sha256"],
                "action": response.get("action", "abstain"),
                "output_stored": False,
                "raw_provider_response_stored": False,
            },
            "immutable_bundle": {
                "bundle_sha256": self.bundle.bundle_sha256,
                "artifacts": relative_artifacts,
            },
            "redaction": {
                "applied": True,
                "secret_fields_removed": [
                    "authorization", "api_key", "token", "cookie", "set-cookie"
                ],
                "raw_sensitive_response_persisted": False,
            },
        }
        return redact(trace)
