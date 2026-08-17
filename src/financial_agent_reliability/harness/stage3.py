"""Live Stage 3 preflight orchestration with bounded retries and safe evidence.

PER-323 Stage 2: contract pins moved from the removed frozen directory to
``configs/harness_contract.v1.json`` (budgets, seed policy) and
``configs/inference.json`` (provider/model lineage). Evidence bundles now
carry those two contract hashes instead of the retired harness-config /
model-manifest pins.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable

from financial_agent_reliability.harness.bundle import ImmutableBundle
from financial_agent_reliability.harness.hashing import file_sha256
from financial_agent_reliability.inference_config import (
    InferenceConfig,
    InferenceConfigError,
    load_inference_config,
)
from financial_agent_reliability.providers.bailian import (
    BailianSettings,
    build_all_adapters,
)
from financial_agent_reliability.providers.bailian_http import BailianHTTPTransport


ROOT = pathlib.Path(__file__).resolve().parents[3]
HARNESS_CONTRACT_PATH = ROOT / "configs" / "harness_contract.v1.json"
INVALIDATING_FAILURES = {
    "identity_mismatch",
    "fallback_detected",
    "parameters_ignored",
    "tool_capability_unverified",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_live_preflights(
    settings: BailianSettings | tuple[BailianSettings, ...],
    *,
    config: InferenceConfig | None = None,
    transport_factory: Callable[..., Any] = BailianHTTPTransport,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    config = config or load_inference_config()
    harness_contract = json.loads(HARNESS_CONTRACT_PATH.read_text(encoding="utf-8"))
    budget = harness_contract["resource_budget"]
    max_retries = int(budget["max_retries"])
    backoffs = list(budget["retry_backoff_ms"])
    models: list[dict[str, Any]] = []
    started_at = _timestamp()

    provider_settings = (settings,) if isinstance(settings, BailianSettings) else settings
    required_provider_names = tuple(
        provider.name
        for provider in config.providers
        if any(
            model.live_preflight_required
            for model in config.models_for_provider(provider.name)
        )
    )
    if tuple(item.provider_name for item in provider_settings) != required_provider_names:
        raise InferenceConfigError(
            "provider settings must match configured providers that require live preflight"
        )
    providers: list[dict[str, str]] = []
    for provider_settings_item in provider_settings:
        adapters = build_all_adapters(
            provider_settings_item,
            config=config,
            harness_contract=harness_contract,
        )
        if not adapters:
            continue
        providers.append(
            {
                "name": provider_settings_item.provider_name,
                "endpoint_id": provider_settings_item.endpoint_id,
            }
        )
        for adapter in adapters:
            transport = transport_factory(
                provider_settings_item,
                timeout_seconds=float(budget["wall_clock_ms"]) / 1000,
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
                    "provider": provider_settings_item.provider_name,
                    "endpoint_id": provider_settings_item.endpoint_id,
                    "requested_model_id": adapter.model_id,
                    "response_model_id": result.response_model_id,
                    "status": row_status,
                    "identity_match": result.response_model_id
                    in adapter.model_config.allowed_response_model_ids,
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
                        "total_tokens": last_usage["input_tokens"]
                        + last_usage["output_tokens"],
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
        "contract_version": "1.1.0",
        "started_at": started_at,
        "finished_at": _timestamp(),
        "status": "passed" if counts["passed"] == counts["requested"] else "blocked",
        "provider": providers[0]["name"] if len(providers) == 1 else "multiple",
        "providers": providers,
        "endpoint_id": providers[0]["endpoint_id"] if len(providers) == 1 else None,
        "inference_config_path": config.source_path.as_posix(),
        "inference_config_sha256": config.source_sha256,
        "harness_contract_sha256": file_sha256(HARNESS_CONTRACT_PATH),
        "counts": counts,
        "models": models,
        "security": {
            "credentials_persisted": False,
            "raw_provider_responses_persisted": False,
            "real_trading_permitted": False,
        },
    }


def freeze_preflight_evidence(
    preflight_paths: list[pathlib.Path],
    destination: pathlib.Path,
    *,
    config: InferenceConfig | None = None,
) -> ImmutableBundle:
    if not preflight_paths:
        raise ValueError("at least one preflight report is required")
    config = config or load_inference_config()
    expected_models = [
        (model.provider, model.model_id)
        for model in config.models
        if model.live_preflight_required
    ]
    reports: list[tuple[pathlib.Path, dict[str, Any]]] = []
    provider_requests = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for path in preflight_paths:
        path = pathlib.Path(path)
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("contract_type") != "stage3_live_preflight":
            raise ValueError(f"not a Stage 3 preflight report: {path.name}")
        if report.get("inference_config_path") != config.source_path.as_posix():
            raise ValueError(f"preflight config path reconciliation failed: {path.name}")
        if report.get("inference_config_sha256") != config.source_sha256:
            raise ValueError(f"preflight config hash reconciliation failed: {path.name}")
        rows = report.get("models") or []
        if [
            (row.get("provider"), row.get("requested_model_id")) for row in rows
        ] != expected_models:
            raise ValueError(f"preflight model reconciliation failed: {path.name}")
        statuses = [row.get("status") for row in rows]
        if any(status not in {"passed", "invalidated", "blocked"} for status in statuses):
            raise ValueError(f"preflight row status invalid: {path.name}")
        recomputed_counts = {
            "requested": len(rows),
            "passed": statuses.count("passed"),
            "invalidated": statuses.count("invalidated"),
            "blocked": statuses.count("blocked"),
        }
        counts = report.get("counts")
        if counts != recomputed_counts:
            raise ValueError(f"preflight count reconciliation failed: {path.name}")
        recomputed_status = (
            "passed" if recomputed_counts["passed"] == recomputed_counts["requested"] else "blocked"
        )
        if report.get("status") != recomputed_status:
            raise ValueError(f"preflight status reconciliation failed: {path.name}")
        expected_providers = list(dict.fromkeys(provider for provider, _model in expected_models))
        provider_entries = report.get("providers")
        if (
            not isinstance(provider_entries, list)
            or not all(isinstance(entry, dict) for entry in provider_entries)
            or [entry.get("name") for entry in provider_entries] != expected_providers
        ):
            raise ValueError(f"preflight provider reconciliation failed: {path.name}")
        expected_provider_summary = (
            expected_providers[0] if len(expected_providers) == 1 else "multiple"
        )
        if report.get("provider") != expected_provider_summary:
            raise ValueError(f"preflight provider summary mismatch: {path.name}")
        if recomputed_status != "passed":
            raise ValueError(f"preflight model row hard gate failed: {path.name}")
        provider_requests += sum(int(row.get("attempt_count", 0)) for row in rows)
        for row in rows:
            row_usage = row.get("usage") or {}
            for key in usage:
                usage[key] += int(row_usage.get(key, 0))
        reports.append((path, report))

    authoritative = reports[-1][1]
    decision = {
        "contract_type": "stage3_execution_decision",
        "contract_version": "1.1.0",
        "status": "preflight_passed",
        "stop_reason": None,
        "preflight_sessions": len(reports),
        "provider_requests": provider_requests,
        "usage": usage,
        "cost_usd": None,
        "cost_status": "provider_response_does_not_supply_cost",
        "smoke_started": False,
        "smoke_runs": 0,
        "full_matrix_started": False,
        "completed_matrix_runs": 0,
        "planned_matrix_runs": 0,
        "matrix_plan_status": "baseline v1 matrix retired with PER-323 cleanup; baseline v2 (PER-328) redefines the run plan",
        "checkpoint_resume_available": True,
        "authoritative_counts": authoritative["counts"],
        "inference_config_path": config.source_path.as_posix(),
        "inference_config_sha256": config.source_sha256,
        "harness_contract_sha256": file_sha256(HARNESS_CONTRACT_PATH),
    }
    with tempfile.TemporaryDirectory() as directory:
        source = pathlib.Path(directory) / "source"
        (source / "preflights").mkdir(parents=True)
        (source / "contracts").mkdir(parents=True)
        for index, (path, _report) in enumerate(reports, start=1):
            shutil.copyfile(path, source / "preflights" / f"preflight.{index:03d}.json")
        shutil.copyfile(config.source_path, source / "contracts" / "inference.json")
        shutil.copyfile(
            HARNESS_CONTRACT_PATH, source / "contracts" / HARNESS_CONTRACT_PATH.name
        )
        (source / "execution_decision.json").write_text(
            json.dumps(decision, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return ImmutableBundle.create(source, destination)
