"""Semantic validator for the prospective v3.11 Stage-3 run trace.

Supersedes the v3.10 validator. PER-61 repairs the token-budget consistency
defect: the cumulative ``usage.total_tokens`` ceiling now reflects the true
session-cumulative semantics (``max_model_requests x single_request_context_window``
= 8 x 32768 = 262144, budget-design derived, three-model symmetric). Trace
semantics, request/phase budgets, ledger replay, and terminal-status rules are
otherwise unchanged from v3.10.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from contracts.run_trace_validator_v3_7 import canonical, scan_persisted_value_for_secrets
from contracts.run_trace_validator_v3_8 import build_run_id, classify_attempt_v38, content_sha256, file_sha256


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "contracts" / "run_trace_harness_config.v3.11.json"
PLAN_PATH = ROOT / "contracts" / "stage3_acceptance_plan.v3.11.json"
SCHEMA_PATH = ROOT / "contracts" / "run_trace.schema.v3.11.json"
MODELS = ["qwen3.8-max", "glm-5.2", "deepseek-v4-pro"]


class HarnessContractV311Error(ValueError):
    pass


def classify_attempt_v311(attempt: Mapping[str, Any], requested_model_id: str) -> str:
    return classify_attempt_v38(attempt, requested_model_id)


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal_string(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def validate_run_trace_v311(trace: Mapping[str, Any], *, plan: Mapping[str, Any] | None = None, scan_companions: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    findings = scan_persisted_value_for_secrets(trace)
    for index, value in enumerate(scan_companions or []):
        findings += [f"companion[{index}]{item[1:]}" for item in scan_persisted_value_for_secrets(value)]
    if findings:
        raise HarnessContractV311Error(f"secret-like persisted value:{sorted(findings)}")
    schema_errors = sorted(Draft202012Validator(_load(SCHEMA_PATH)).iter_errors(trace), key=lambda item: list(item.path))
    if schema_errors:
        raise HarnessContractV311Error("; ".join(f"schema:{'/'.join(map(str, item.path)) or '$'}:{item.message}" for item in schema_errors))

    config = _load(CONFIG_PATH)
    plan = dict(plan or _load(PLAN_PATH))
    identity = trace["run_identity"]
    requested = identity["requested_model_id"]
    row = next((item for item in plan["runs"] if item["run_id"] == trace["run_id"]), None)
    task = next((item for item in plan["tasks"] if trace["run_id"] in item["run_ids"]), None)
    if trace["run_id"] != build_run_id(identity) or row is None or row["run_identity"] != identity:
        errors.append("run identity is not exact plan membership")
    if requested not in MODELS or trace["provider"]["requested_model_id"] != requested or trace["provider"]["response_model_id"] != requested:
        errors.append("top-level response model mismatch")
    if identity["harness_config_sha256"] != file_sha256(CONFIG_PATH) or identity["plan_core_sha256"] != plan["plan_core_sha256"]:
        errors.append("config or plan commitment mismatch")

    requests = trace["logical_requests"]
    phases = [item["phase"] for item in requests]
    if phases[0] != "initial":
        errors.append("first request must be initial")
    if phases.count("initial") > config["resource_budget"]["initial_model_requests"] or phases.count("repair") > config["resource_budget"]["repair_model_requests"]:
        errors.append("phase budget exceeded")
    if "repair" in phases and "initial" in phases[phases.index("repair"):]:
        errors.append("phase order must be an initial prefix followed by repair suffix")
    attempts_total = 0
    for request_index, request in enumerate(requests, 1):
        if request["request_index"] != request_index or request["model_id"] != requested or request["seed"] != identity["seed"]:
            errors.append(f"request {request_index} identity/index mismatch")
        if task is None or request["tool_schema_sha256"] != task["tool_schema_sha256"]:
            errors.append(f"request {request_index} tool schema hash mismatch")
        if request["parameters_sha256"] != config["request_commitments"]["parameters_sha256_by_model"][requested]:
            errors.append(f"request {request_index} parameters hash mismatch")
        attempts = request["attempts"]
        attempts_total += len(attempts)
        for attempt_index, attempt in enumerate(attempts):
            if attempt["attempt_index"] != attempt_index or attempt["model_id"] != requested:
                errors.append(f"request {request_index} attempt identity/index mismatch")
            status = attempt["http_status"]
            if attempt["response_model_id"] not in {None, requested} or (isinstance(status, int) and 200 <= status <= 299 and attempt["response_model_id"] != requested):
                errors.append(f"request {request_index} attempt response model mismatch")
            if attempt["payload_sha256"] != request["payload_sha256"] or attempt["seed"] != request["seed"]:
                errors.append(f"request {request_index} provider retry is not identical replay")
            derived = classify_attempt_v311(attempt, requested)
            if attempt["classification"] != derived:
                errors.append(f"request {request_index} HTTP classification mismatch")
        if len(attempts) == 2 and attempts[0]["classification"] != "provider_or_runtime_failure":
            errors.append(f"request {request_index} semantic retry forbidden")
        if request["retries_used"] != len(attempts) - 1 or request["classification"] != attempts[-1]["classification"]:
            errors.append(f"request {request_index} retry/final classification mismatch")

    usage = trace["usage"]
    if usage["model_requests"] != len(requests) or usage["provider_attempts"] != attempts_total:
        errors.append("request/attempt accounting mismatch")
    if usage["tool_calls"] != len(trace["tool_events"]):
        errors.append("tool event accounting mismatch")
    cumulative_ceiling = config["resource_budget"]["max_total_tokens"]
    if usage["total_tokens"] > cumulative_ceiling:
        errors.append(f"cumulative total_tokens {usage['total_tokens']} exceeds budget-design ceiling {cumulative_ceiling}")

    ledger_events = [item for item in trace["tool_events"] if item["tool_name"] == "simulated_ledger" and item["success"]]
    ledger: dict[str, str] = {}
    expected_root = content_sha256(ledger)
    if trace["environment"]["initial_ledger_sha256"] != expected_root:
        errors.append("ledger initial state is not independently reproducible")
    for event in ledger_events:
        transition = event.get("ledger_transition")
        if not isinstance(transition, Mapping):
            errors.append("ledger transition is not independently replayable")
            continue
        if event.get("state_before_sha256") != expected_root:
            errors.append("ledger state chain mismatch")
        operation, instrument = event.get("operation"), transition.get("instrument")
        try:
            current = Decimal(ledger.get(str(instrument), "0"))
            quantity = Decimal(str(transition.get("quantity")))
            resulting = current + quantity if operation == "buy" else current - quantity if operation == "sell" else current
            normalized = _decimal_string(resulting)
            if normalized != transition.get("resulting_quantity"):
                errors.append("ledger resulting quantity mismatch")
            if operation != "preview":
                if resulting == 0:
                    ledger.pop(str(instrument), None)
                else:
                    ledger[str(instrument)] = normalized
            expected_root = content_sha256(ledger)
            if event.get("state_after_sha256") != expected_root:
                errors.append("ledger state chain mismatch")
        except Exception:
            errors.append("ledger transition arithmetic invalid")
    environment = trace["environment"]
    if expected_root != environment["final_ledger_sha256"] or environment["final_state_matches_initial"] is not (environment["initial_ledger_sha256"] == environment["final_ledger_sha256"]):
        errors.append("ledger terminal state mismatch")
    if environment["real_side_effects"]:
        errors.append("real side effects forbidden")

    final_class = requests[-1]["classification"]
    expected = {
        "success": ("succeeded", None, True),
        "candidate_failure": ("candidate_failed", "candidate_failure", True),
        "provider_or_runtime_failure": ("invalid_provider_or_runtime", "provider_or_runtime_failure", False),
        "indeterminate": ("invalid_provider_or_runtime", "indeterminate", False),
    }[final_class]
    if (trace["status"], trace["failure"]["class"], trace["result"]["candidate_scored"]) != expected:
        errors.append("terminal status/scoring mismatch")
    if errors:
        raise HarnessContractV311Error("; ".join(errors))
    return {"status": trace["status"], "logical_requests": len(requests), "provider_attempts": attempts_total}
