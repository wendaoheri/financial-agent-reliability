"""Input loading and validation for the lightweight benchmark protocol."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from financial_agent_reliability.config import ConfigError, load_run_config
from financial_agent_reliability.contracts import (
    candidate_output_contract,
    contains_gold_key,
    validate_candidate_contract,
)
from financial_agent_reliability.oracle import OracleError, evaluate, matches


class BenchInputError(ValueError):
    """Raised when a task or run configuration violates the current contract."""


def task_validator() -> Draft202012Validator:
    schema_path = resources.files("financial_agent_reliability.schemas").joinpath(
        "task.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@dataclass(frozen=True)
class Candidate:
    id: str
    model: str
    agent: str
    adapter: str
    config: dict[str, Any]
    source_path: pathlib.Path = pathlib.Path(".")

    @property
    def config_sha256(self) -> str:
        payload = json.dumps(self.config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchInputError(f"{label} must be a JSON object")
    return value


def _format_schema_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "$"
    return f"{location}: {error.message}"


def _validate_card(card: dict[str, Any], *, source: pathlib.Path, line_number: int) -> None:
    errors = sorted(task_validator().iter_errors(card), key=lambda item: list(item.absolute_path))
    if errors:
        raise BenchInputError(
            f"task line {line_number} violates task schema: {_format_schema_error(errors[0])}"
        )
    fixture_ids: set[str] = set()
    for fixture in card["fixtures"]:
        fixture_id = fixture["id"]
        if fixture_id in fixture_ids:
            raise BenchInputError(f"task {card['id']} has duplicate fixture id: {fixture_id}")
        fixture_ids.add(fixture_id)
        fixture_path = (source.parent / fixture["path"]).resolve()
        try:
            fixture_path.relative_to(source.parent.resolve())
        except ValueError as exc:
            raise BenchInputError(f"task {card['id']} fixture escapes task directory") from exc
        if not fixture_path.is_file():
            raise BenchInputError(f"task {card['id']} fixture does not exist: {fixture['path']}")
        try:
            document = _object(
                json.loads(fixture_path.read_text(encoding="utf-8")), fixture["path"]
            )
        except json.JSONDecodeError as exc:
            raise BenchInputError(f"fixture {fixture['path']} is invalid JSON: {exc.msg}") from exc
        if document.get("fixture_id") != fixture_id:
            raise BenchInputError(f"fixture {fixture['path']} id does not match {fixture_id}")
        for field in ("as_of", "market"):
            if document.get(field) != fixture[field]:
                raise BenchInputError(
                    f"fixture {fixture['path']} {field} does not match task declaration"
                )
    required_ids = set(card["checks"]["evidence"]["required_fixture_ids"])
    if not required_ids <= fixture_ids:
        missing = ", ".join(sorted(required_ids - fixture_ids))
        raise BenchInputError(f"task {card['id']} requires undeclared fixtures: {missing}")

    seen_variants: set[str] = set()
    operation = card["checks"]["oracle"]["operation"]
    for variant in card["variants"]:
        variant_id = variant["id"]
        if variant_id in seen_variants:
            raise BenchInputError(f"task {card['id']} has duplicate variant id: {variant_id}")
        seen_variants.add(variant_id)
        try:
            actual = evaluate(operation, variant["input"])
        except OracleError as exc:
            raise BenchInputError(f"task {card['id']} variant {variant_id}: {exc}") from exc
        if not matches(variant["expected"], actual, variant["tolerance"]["absolute"]):
            raise BenchInputError(
                f"task {card['id']} variant {variant_id} expected value does not recompute"
            )


def _expand_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for variant in card["variants"]:
        task_id = f"{card['id']}::{variant['id']}"
        operation = card["checks"]["oracle"]["operation"]
        tasks.append(
            {
                "task_id": task_id,
                "input": {
                    "prompt": card["prompt"],
                    "variant": variant["input"],
                    "fixture_ids": card["checks"]["evidence"]["required_fixture_ids"],
                },
                "candidate_payload": {
                    "task_id": task_id,
                    "input": {
                        "prompt": card["prompt"],
                        "variant": variant["input"],
                        "fixture_ids": card["checks"]["evidence"]["required_fixture_ids"],
                    },
                    "tools": list(card["tools"]),
                    "resources": [
                        {
                            "fixture_id": fixture["id"],
                            "as_of": fixture["as_of"],
                            "market": fixture["market"],
                        }
                        for fixture in card["fixtures"]
                    ],
                    "budget": card["budget"],
                    "output_contract": candidate_output_contract(operation),
                },
                "expected_output": variant["expected"],
                "tolerance": variant["tolerance"]["absolute"],
                "required_evidence": card["checks"]["evidence"]["required_fixture_ids"],
                "safety_policy": card["checks"]["safety"],
                "budget": card["budget"],
                "grader_contract": {"operation": operation},
                "task_card": {
                    "id": card["id"],
                    "slice": card["slice"],
                    "variant": variant["id"],
                },
            }
        )
        if contains_gold_key(tasks[-1]["candidate_payload"]):
            raise BenchInputError(f"task {task_id} leaks evaluator-owned fields to the candidate")
        problems = validate_candidate_contract(tasks[-1])
        if problems:
            raise BenchInputError(f"task {task_id} contract consistency failed: {problems[0]}")
    return tasks


def audit_taskset(path: pathlib.Path) -> dict[str, Any]:
    """Run deterministic curation checks over a task-card JSONL file."""

    items = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    cards = [item for item in items if "id" in item]
    findings: dict[str, list[str]] = {
        "duplicates": [],
        "leakage": [],
        "future_information": [],
        "low_information": [],
        "eval_without_pilot": [],
    }
    seen_prompts: dict[str, str] = {}
    seen_variants: dict[str, str] = {}
    for card in cards:
        card_id = str(card.get("id", "<missing>"))
        prompt = str(card.get("prompt", ""))
        normalized_prompt = re.sub(r"\s+", " ", prompt.strip().lower())
        if normalized_prompt in seen_prompts:
            findings["duplicates"].append(
                f"{card_id}: prompt duplicates {seen_prompts[normalized_prompt]}"
            )
        seen_prompts[normalized_prompt] = card_id
        variants = card.get("variants", [])
        designs = {variant.get("design") for variant in variants}
        inputs = {json.dumps(variant.get("input"), sort_keys=True) for variant in variants}
        if len(designs) != len(variants) or len(inputs) != len(variants):
            findings["low_information"].append(f"{card_id}: variants are not distinct")
        if (
            len({signal for variant in variants for signal in variant.get("expected_signals", [])})
            < 2
        ):
            findings["low_information"].append(f"{card_id}: fewer than two diagnostic signals")
        for variant in variants:
            variant_key = json.dumps(
                {"prompt": normalized_prompt, "input": variant.get("input")}, sort_keys=True
            )
            variant_id = f"{card_id}::{variant.get('id')}"
            if variant_key in seen_variants:
                findings["duplicates"].append(
                    f"{variant_id}: duplicates {seen_variants[variant_key]}"
                )
            seen_variants[variant_key] = variant_id
            expected = variant.get("expected", {})
            for reason_code in expected.get("reason_codes", []):
                if reason_code.lower() in normalized_prompt:
                    findings["leakage"].append(f"{variant_id}: reason code appears in prompt")
            expected_value = expected.get("value")
            if isinstance(expected_value, (str, int, float)) and not isinstance(
                expected_value, bool
            ):
                rendered = str(expected_value).lower()
                if len(rendered) >= 3 and rendered in normalized_prompt:
                    findings["leakage"].append(f"{variant_id}: Gold value appears in prompt")
            payload = variant.get("input", {})
            if "published_at" in payload and "cutoff_at" in payload:
                is_future = _audit_timestamp(payload["published_at"]) > _audit_timestamp(
                    payload["cutoff_at"]
                )
                safely_blocked = expected.get(
                    "status"
                ) == "abstain" and "FUTURE_INFORMATION" in expected.get("reason_codes", [])
                if is_future != safely_blocked:
                    findings["future_information"].append(
                        f"{variant_id}: cutoff expectation is inconsistent"
                    )
        lifecycle = card.get("tags", {}).get("lifecycle")
        changes = " ".join(card.get("notes", {}).get("change_log", [])).lower()
        if lifecycle == "eval" and "pilot" not in changes:
            findings["eval_without_pilot"].append(f"{card_id}: eval lacks pilot evidence")
    return {
        "cards": len(cards),
        "variants": sum(len(card.get("variants", [])) for card in cards),
        "slices": sorted({card.get("slice") for card in cards}),
        "lifecycles": {
            lifecycle: sum(card.get("tags", {}).get("lifecycle") == lifecycle for card in cards)
            for lifecycle in ("dev", "pilot", "eval")
        },
        "checks": {
            name: {"passed": not items, "findings": items} for name, items in findings.items()
        },
    }


def _audit_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise BenchInputError("audit timestamp must be a string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BenchInputError("audit timestamp must be ISO-8601") from exc


def load_tasks(path: pathlib.Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            task = _object(json.loads(raw), f"task line {line_number}")
        except json.JSONDecodeError as exc:
            raise BenchInputError(f"task line {line_number} is invalid JSON: {exc.msg}") from exc
        if "id" in task:
            _validate_card(task, source=path, line_number=line_number)
            expanded = _expand_card(task)
            for runnable in expanded:
                task_id = runnable["task_id"]
                if task_id in seen:
                    raise BenchInputError(f"duplicate task_id: {task_id}")
                seen.add(task_id)
                tasks.append(runnable)
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise BenchInputError(f"task line {line_number} requires non-empty task_id")
        if task_id in seen:
            raise BenchInputError(f"duplicate task_id: {task_id}")
        if "input" not in task:
            raise BenchInputError(f"task {task_id} requires input")
        seen.add(task_id)
        tasks.append(task)
    if not tasks:
        raise BenchInputError("task file must contain at least one task")
    return tasks


def load_candidates(path: pathlib.Path) -> list[Candidate]:
    try:
        load_run_config(path)
    except ConfigError as exc:
        raise BenchInputError(str(exc)) from exc
    try:
        document = _object(json.loads(path.read_text(encoding="utf-8")), "candidate file")
    except json.JSONDecodeError as exc:
        raise BenchInputError(f"candidate file is invalid JSON: {exc.msg}") from exc
    raw_candidates = document.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise BenchInputError("candidate file requires a non-empty candidates array")
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_candidates):
        item = _object(raw, f"candidate {index}")
        values = {key: item.get(key) for key in ("id", "model", "agent", "adapter")}
        for key, value in values.items():
            if not isinstance(value, str) or not value:
                raise BenchInputError(f"candidate {index} requires non-empty {key}")
        if values["id"] in seen:
            raise BenchInputError(f"duplicate candidate id: {values['id']}")
        if values["adapter"] not in {
            "mock",
            "pi-agent-offline",
            "pi-agent-live",
            "bailian-live",
        }:
            raise BenchInputError(f"unsupported candidate adapter: {values['adapter']}")
        config = item.get("config", {})
        if not isinstance(config, dict):
            raise BenchInputError(f"candidate {values['id']} config must be an object")
        if values["adapter"] == "mock":
            behavior = config.get("behavior", "pass")
            if behavior not in {
                "pass",
                "failure",
                "timeout",
                "tool_error",
                "missing_evidence",
                "forbidden_action",
                "safety_violation",
                "wrong_answer",
                "wrong_action",
                "wrong_value",
                "wrong_reason",
                "invalid_protocol",
                "provider_failure",
            }:
                raise BenchInputError(
                    f"candidate {values['id']} has unsupported mock behavior: {behavior}"
                )
        elif values["adapter"] == "pi-agent-offline":
            if values["agent"] != "pi-agent-0.73.1":
                raise BenchInputError("pi-agent-offline requires pi-agent-0.73.1")
            if set(config) - {"behavior"}:
                raise BenchInputError(
                    f"candidate {values['id']} has unsupported pi-agent-offline config keys"
                )
            if config.get("behavior", "pass") not in {"pass", "wrong_answer"}:
                raise BenchInputError(
                    f"candidate {values['id']} has unsupported pi-agent-offline behavior"
                )
        else:
            expected_agent = (
                "pi-agent-0.73.1" if values["adapter"] == "pi-agent-live" else "plain-agent"
            )
            if values["agent"] != expected_agent:
                raise BenchInputError(f"{values['adapter']} requires {expected_agent}")
            allowed_keys = {"seed", "profile", "generation"}
            if values["adapter"] == "pi-agent-live":
                allowed_keys.update(
                    {
                        "max_provider_turns",
                        "output_contract_version",
                        "calibration_case_ids",
                        "live_eval_stages",
                    }
                )
            if set(config) - allowed_keys:
                raise BenchInputError(
                    f"candidate {values['id']} has unsupported {values['adapter']} config keys"
                )
            if "seed" in config and not isinstance(config["seed"], int):
                raise BenchInputError(f"candidate {values['id']} seed must be an integer")
            if "profile" in config and not isinstance(config["profile"], str):
                raise BenchInputError(f"candidate {values['id']} profile must be a string")
            if "generation" in config and not isinstance(config["generation"], dict):
                raise BenchInputError(f"candidate {values['id']} generation must be an object")
            if values["adapter"] == "pi-agent-live" and config.get("max_provider_turns", 2) != 2:
                raise BenchInputError("pi-agent-live requires exactly two provider turns per cell")
            if (
                values["adapter"] == "pi-agent-live"
                and config.get("output_contract_version") != "3.0.0"
            ):
                raise BenchInputError("pi-agent-live output contract must be 3.0.0")
            calibration_case_ids = config.get("calibration_case_ids")
            if calibration_case_ids is not None and (
                not isinstance(calibration_case_ids, list)
                or len(calibration_case_ids) != 10
                or len(set(calibration_case_ids)) != 10
                or any(
                    not isinstance(case_id, str) or not case_id for case_id in calibration_case_ids
                )
            ):
                raise BenchInputError(
                    "pi-agent-live calibration_case_ids must contain 10 unique case ids"
                )
            live_eval_stages = config.get("live_eval_stages")
            if live_eval_stages is not None and (
                not isinstance(live_eval_stages, list)
                or len(live_eval_stages) != len(set(live_eval_stages))
                or set(live_eval_stages) != {"smoke", "calibration", "baseline", "supplemental"}
            ):
                raise BenchInputError(
                    "pi-agent-live live_eval_stages must register all four live stages"
                )
        candidates.append(Candidate(config=config, source_path=path.resolve(), **values))
        seen.add(values["id"])
    coordinates = {(candidate.model, candidate.agent) for candidate in candidates}
    expected = {
        (model, agent)
        for model in {candidate.model for candidate in candidates}
        for agent in {candidate.agent for candidate in candidates}
    }
    if coordinates != expected:
        missing = ", ".join(f"{model}×{agent}" for model, agent in sorted(expected - coordinates))
        raise BenchInputError(f"candidate model × agent matrix is incomplete: {missing}")
    return candidates
