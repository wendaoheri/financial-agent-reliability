"""Live Stage 3 preflight orchestration with bounded retries and safe evidence."""

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable

from contracts.run_trace_validator import file_sha256
from harness.bundle import ImmutableBundle
from providers.bailian import BailianSettings, build_all_adapters
from providers.bailian_http import BailianHTTPTransport


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v2.json"
MODEL_MANIFEST_PATH = ROOT / "contracts" / "model_manifest.frozen.v2.json"
INVALIDATING_FAILURES = {
    "identity_mismatch",
    "fallback_detected",
    "parameters_ignored",
    "tool_capability_unverified",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_live_preflights(
    settings: BailianSettings,
    *,
    transport_factory: Callable[..., Any] = BailianHTTPTransport,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    budget = config["resource_budget"]
    max_retries = int(budget["max_retries"])
    backoffs = list(budget["retry_backoff_ms"])
    models: list[dict[str, Any]] = []
    started_at = _timestamp()

    for adapter in build_all_adapters(settings):
        transport = transport_factory(
            settings, timeout_seconds=float(budget["wall_clock_ms"]) / 1000
        )
        attempts: list[dict[str, Any]] = []
        last_usage = {"input_tokens": 0, "output_tokens": 0}
        result = None
        for attempt_number in range(1, max_retries + 2):
            attempt_ns = time.monotonic_ns()

            def call(request: dict[str, Any]) -> dict[str, Any]:
                nonlocal last_usage
                response = dict(transport(request, force_tool_call=True))
                raw_usage = response.get("usage") or {}
                last_usage = {
                    "input_tokens": int(raw_usage.get("input_tokens", 0)),
                    "output_tokens": int(raw_usage.get("output_tokens", 0)),
                }
                return response

            result = adapter.preflight(call)
            duration_ms = max(0, (time.monotonic_ns() - attempt_ns) // 1_000_000)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "duration_ms": duration_ms,
                    "valid": result.valid,
                    "failure_type": result.failure_type,
                    "retryable": result.retryable,
                }
            )
            if result.valid or not result.retryable or attempt_number > max_retries:
                break
            sleeper(backoffs[attempt_number - 1] / 1000)

        assert result is not None
        row_status = (
            "passed"
            if result.valid
            else "invalidated"
            if result.failure_type in INVALIDATING_FAILURES
            else "blocked"
        )
        models.append(
            {
                "requested_model_id": adapter.model_id,
                "response_model_id": result.response_model_id,
                "status": row_status,
                "identity_match": result.response_model_id == adapter.model_id,
                "tool_call_supported": result.valid,
                "parameters_accepted": result.failure_type != "parameters_ignored",
                "parameter_evidence_limit": "HTTP acceptance detects rejection, not silent semantic ignoring",
                "fallback_detected": result.failure_type == "fallback_detected",
                "failure_type": result.failure_type,
                "provider_error_code": result.provider_error_code,
                "http_status": result.http_status,
                "retryable": result.retryable,
                "attempt_count": len(attempts),
                "attempts": attempts,
                "usage": {
                    **last_usage,
                    "total_tokens": last_usage["input_tokens"] + last_usage["output_tokens"],
                },
                "cost_usd": None,
                "cost_status": "provider_response_does_not_supply_cost",
            }
        )

    counts = {
        "requested": len(models),
        "passed": sum(row["status"] == "passed" for row in models),
        "invalidated": sum(row["status"] == "invalidated" for row in models),
        "blocked": sum(row["status"] == "blocked" for row in models),
    }
    return {
        "contract_type": "stage3_live_preflight",
        "contract_version": "1.0.0",
        "started_at": started_at,
        "finished_at": _timestamp(),
        "status": "passed" if counts["passed"] == counts["requested"] else "blocked",
        "provider": "bailian",
        "endpoint_id": settings.endpoint_id,
        "harness_config_sha256": file_sha256(CONFIG_PATH),
        "model_manifest_sha256": file_sha256(MODEL_MANIFEST_PATH),
        "counts": counts,
        "models": models,
        "security": {
            "credentials_persisted": False,
            "raw_provider_responses_persisted": False,
            "real_trading_permitted": False,
        },
    }


def freeze_preflight_evidence(
    preflight_paths: list[pathlib.Path], destination: pathlib.Path
) -> ImmutableBundle:
    if not preflight_paths:
        raise ValueError("at least one preflight report is required")
    expected_models = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]
    reports: list[tuple[pathlib.Path, dict[str, Any]]] = []
    provider_requests = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for path in preflight_paths:
        path = pathlib.Path(path)
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("contract_type") != "stage3_live_preflight":
            raise ValueError(f"not a Stage 3 preflight report: {path.name}")
        rows = report.get("models") or []
        if [row.get("requested_model_id") for row in rows] != expected_models:
            raise ValueError(f"preflight model reconciliation failed: {path.name}")
        counts = report.get("counts") or {}
        if counts.get("requested") != len(rows):
            raise ValueError(f"preflight count reconciliation failed: {path.name}")
        provider_requests += sum(int(row.get("attempt_count", 0)) for row in rows)
        for row in rows:
            row_usage = row.get("usage") or {}
            for key in usage:
                usage[key] += int(row_usage.get(key, 0))
        reports.append((path, report))

    authoritative = reports[-1][1]
    decision = {
        "contract_type": "stage3_execution_decision",
        "contract_version": "1.0.0",
        "status": "blocked" if authoritative.get("status") != "passed" else "preflight_passed",
        "stop_reason": (
            "preflight_hard_gate_failed"
            if authoritative.get("status") != "passed"
            else None
        ),
        "preflight_sessions": len(reports),
        "provider_requests": provider_requests,
        "usage": usage,
        "cost_usd": None,
        "cost_status": "provider_response_does_not_supply_cost",
        "smoke_started": False,
        "smoke_runs": 0,
        "full_matrix_started": False,
        "completed_matrix_runs": 0,
        "planned_matrix_runs": 810,
        "checkpoint_resume_available": True,
        "authoritative_counts": authoritative["counts"],
        "harness_config_sha256": file_sha256(CONFIG_PATH),
        "model_manifest_sha256": file_sha256(MODEL_MANIFEST_PATH),
        "run_manifest_sha256": file_sha256(ROOT / "harness" / "run_manifest.v4.json"),
    }
    with tempfile.TemporaryDirectory() as directory:
        source = pathlib.Path(directory) / "source"
        (source / "preflights").mkdir(parents=True)
        (source / "contracts").mkdir(parents=True)
        (source / "harness").mkdir(parents=True)
        for index, (path, _report) in enumerate(reports, start=1):
            shutil.copyfile(path, source / "preflights" / f"preflight.{index:03d}.json")
        shutil.copyfile(MODEL_MANIFEST_PATH, source / "contracts" / MODEL_MANIFEST_PATH.name)
        shutil.copyfile(CONFIG_PATH, source / "contracts" / CONFIG_PATH.name)
        shutil.copyfile(
            ROOT / "harness" / "run_manifest.v4.json",
            source / "harness" / "run_manifest.v4.json",
        )
        (source / "execution_decision.json").write_text(
            json.dumps(decision, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return ImmutableBundle.create(source, destination)
