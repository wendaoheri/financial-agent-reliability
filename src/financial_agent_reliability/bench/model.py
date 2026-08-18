"""Input loading and validation for the lightweight benchmark protocol."""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any


class BenchInputError(ValueError):
    """Raised when a task or candidate file violates the v0.1 protocol."""


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
