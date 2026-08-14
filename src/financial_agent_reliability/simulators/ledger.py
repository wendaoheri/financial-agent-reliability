"""Permissioned and idempotent synthetic transaction state machine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    operation: str
    instrument: str
    quantity: str
    idempotency_key: str
    state: str


class SimulatedLedger:
    """A run-local ledger with no network or real execution capability."""

    def __init__(self, ledger_id: str, *, allowed_instruments: set[str]):
        if not ledger_id or not allowed_instruments:
            raise LedgerError("ledger identity and permissions are required")
        self.ledger_id = ledger_id
        self.allowed_instruments = frozenset(allowed_instruments)
        self.positions: dict[str, str] = {}
        self._events: dict[str, LedgerEvent] = {}
        self._committed: set[str] = set()

    @staticmethod
    def _quantity(value: str) -> str:
        try:
            parsed = Decimal(value)
        except (InvalidOperation, TypeError):
            raise LedgerError("quantity must be a canonical positive decimal string")
        if not parsed.is_finite() or parsed <= 0 or str(parsed) != value:
            raise LedgerError("quantity must be a canonical positive decimal string")
        return value

    def _event_id(self, key: str) -> str:
        digest = hashlib.sha256(f"{self.ledger_id}:{key}".encode()).hexdigest()[:24]
        return f"sim_{digest}"

    def apply(
        self,
        operation: str,
        instrument: str,
        quantity: str,
        idempotency_key: str,
        *,
        timeout: bool = False,
    ) -> LedgerEvent:
        if operation not in {"preview", "buy", "sell"}:
            raise LedgerError("unsupported simulated operation")
        if instrument not in self.allowed_instruments:
            raise LedgerError("permission denied for instrument")
        quantity = self._quantity(quantity)
        prior = self._events.get(idempotency_key)
        if prior:
            if (prior.operation, prior.instrument, prior.quantity) != (
                operation, instrument, quantity
            ):
                raise LedgerError("idempotency key reused with different request")
            return prior
        state = "previewed" if operation == "preview" else ("unknown" if timeout else "committed")
        event = LedgerEvent(
            self._event_id(idempotency_key), operation, instrument, quantity,
            idempotency_key, state,
        )
        self._events[idempotency_key] = event
        if state == "committed":
            self._commit_once(event)
        return event

    def confirm(self, idempotency_key: str, final_state: str) -> LedgerEvent:
        if final_state not in {"committed", "rejected"}:
            raise LedgerError("final state must be committed or rejected")
        event = self._events.get(idempotency_key)
        if event is None:
            raise LedgerError("unknown idempotency key")
        if event.state == "previewed":
            raise LedgerError("preview cannot be committed")
        if event.state in {"committed", "rejected"}:
            if event.state != final_state:
                raise LedgerError("conflicting duplicate callback")
            return event
        finalized = LedgerEvent(
            event.event_id, event.operation, event.instrument, event.quantity,
            event.idempotency_key, final_state,
        )
        self._events[idempotency_key] = finalized
        if final_state == "committed":
            self._commit_once(finalized)
        return finalized

    def _commit_once(self, event: LedgerEvent) -> None:
        if event.event_id in self._committed:
            return
        current = Decimal(self.positions.get(event.instrument, "0"))
        delta = Decimal(event.quantity) if event.operation == "buy" else -Decimal(event.quantity)
        next_value = current + delta
        if next_value < 0:
            raise LedgerError("simulated position cannot become negative")
        self.positions[event.instrument] = str(next_value)
        self._committed.add(event.event_id)
