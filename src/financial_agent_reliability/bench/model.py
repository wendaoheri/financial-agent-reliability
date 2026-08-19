"""Input loading and validation for the lightweight benchmark protocol."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from financial_agent_reliability.bench.oracle import OracleError, evaluate, matches


class BenchInputError(ValueError):
    """Raised when a task or candidate file violates the v0.1 protocol."""


TASK_SCHEMA_PATH = pathlib.Path(__file__).parent / "contracts" / "task.schema.v0.1.json"


def task_validator() -> Draft202012Validator:
    schema = json.loads(TASK_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@dataclass(frozen=True)
class Candidate:
    id: str
    model: str
    agent: str
    adapter: str
    config: dict[str, Any]

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
            document = _object(json.loads(fixture_path.read_text(encoding="utf-8")), fixture["path"])
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
        tasks.append(
            {
                "task_id": task_id,
                "input": {
                    "prompt": card["prompt"],
                    "variant": variant["input"],
                    "fixture_ids": card["checks"]["evidence"]["required_fixture_ids"],
                },
                "expected_output": variant["expected"],
                "task_card": {"id": card["id"], "slice": card["slice"], "variant": variant["id"]},
            }
        )
    return tasks


def audit_taskset(path: pathlib.Path) -> dict[str, Any]:
    """Run deterministic curation checks over a task-card JSONL file."""

    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
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
            findings["duplicates"].append(f"{card_id}: prompt duplicates {seen_prompts[normalized_prompt]}")
        seen_prompts[normalized_prompt] = card_id
        variants = card.get("variants", [])
        designs = {variant.get("design") for variant in variants}
        inputs = {json.dumps(variant.get("input"), sort_keys=True) for variant in variants}
        if len(designs) != len(variants) or len(inputs) != len(variants):
            findings["low_information"].append(f"{card_id}: variants are not distinct")
        if len({signal for variant in variants for signal in variant.get("expected_signals", [])}) < 2:
            findings["low_information"].append(f"{card_id}: fewer than two diagnostic signals")
        for variant in variants:
            variant_key = json.dumps(
                {"prompt": normalized_prompt, "input": variant.get("input")}, sort_keys=True
            )
            variant_id = f"{card_id}::{variant.get('id')}"
            if variant_key in seen_variants:
                findings["duplicates"].append(f"{variant_id}: duplicates {seen_variants[variant_key]}")
            seen_variants[variant_key] = variant_id
            expected = variant.get("expected", {})
            for reason_code in expected.get("reason_codes", []):
                if reason_code.lower() in normalized_prompt:
                    findings["leakage"].append(f"{variant_id}: reason code appears in prompt")
            expected_value = expected.get("value")
            if isinstance(expected_value, (str, int, float)) and not isinstance(expected_value, bool):
                rendered = str(expected_value).lower()
                if len(rendered) >= 3 and rendered in normalized_prompt:
                    findings["leakage"].append(f"{variant_id}: Gold value appears in prompt")
            payload = variant.get("input", {})
            if "published_at" in payload and "cutoff_at" in payload:
                is_future = _audit_timestamp(payload["published_at"]) > _audit_timestamp(payload["cutoff_at"])
                safely_blocked = expected.get("status") == "abstain" and "FUTURE_INFORMATION" in expected.get("reason_codes", [])
                if is_future != safely_blocked:
                    findings["future_information"].append(f"{variant_id}: cutoff expectation is inconsistent")
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
        if values["adapter"] != "mock":
            raise BenchInputError("v0.1 only permits the offline mock adapter")
        config = item.get("config", {})
        if not isinstance(config, dict):
            raise BenchInputError(f"candidate {values['id']} config must be an object")
        candidates.append(Candidate(config=config, **values))
        seen.add(values["id"])
    return candidates
