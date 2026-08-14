"""Append-only, hash-chained checkpoints with strict resume validation."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class CheckpointError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class Checkpoint:
    offset: int
    event_type: str
    state_sha256: str
    event_sha256: str


class CheckpointStore:
    def __init__(self, directory: pathlib.Path, run_id: str):
        if not run_id.startswith("run_") or len(run_id) != 36:
            raise CheckpointError("invalid run_id")
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.path = self.directory / f"{run_id}.jsonl"
        self._offset = 0
        self._previous = "0" * 64

    @classmethod
    def resume(cls, directory: pathlib.Path, run_id: str) -> "CheckpointStore":
        store = cls(directory, run_id)
        if not store.path.is_file():
            raise CheckpointError("checkpoint does not exist")
        previous = "0" * 64
        expected_offset = 0
        for line_number, line in enumerate(
            store.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CheckpointError(f"invalid checkpoint JSON at line {line_number}") from exc
            required = {
                "run_id", "offset", "event_type", "payload", "previous_event_sha256",
                "state_sha256", "created_at", "event_sha256",
            }
            if set(event) != required:
                raise CheckpointError(f"checkpoint fields changed at line {line_number}")
            if event["run_id"] != run_id or event["offset"] != expected_offset:
                raise CheckpointError(f"checkpoint identity or offset mismatch at line {line_number}")
            if event["previous_event_sha256"] != previous:
                raise CheckpointError(f"checkpoint hash chain mismatch at line {line_number}")
            stored_hash = event.pop("event_sha256")
            actual_hash = _hash(event)
            if stored_hash != actual_hash:
                raise CheckpointError(f"checkpoint event hash mismatch at line {line_number}")
            previous = stored_hash
            expected_offset += 1
        store._offset = expected_offset
        store._previous = previous
        return store

    def append(self, event_type: str, payload: dict[str, Any]) -> Checkpoint:
        if not event_type or not isinstance(payload, dict):
            raise CheckpointError("checkpoint event requires type and object payload")
        state_hash = _hash(payload)
        event = {
            "run_id": self.run_id,
            "offset": self._offset,
            "event_type": event_type,
            "payload": payload,
            "previous_event_sha256": self._previous,
            "state_sha256": state_hash,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        event_hash = _hash(event)
        persisted = dict(event, event_sha256=event_hash)
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.write(descriptor, _canonical(persisted) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        checkpoint = Checkpoint(self._offset, event_type, state_hash, event_hash)
        self._offset += 1
        self._previous = event_hash
        return checkpoint
