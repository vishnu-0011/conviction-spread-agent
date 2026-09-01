"""Pure, replayable lifecycle for one defined-risk spread position.

This module performs no broker I/O. It records the only legal state transitions so
REST responses and trade-update events can be applied idempotently after a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from .orders import MlegOrderIntent, OrderPurpose


class LifecycleState(StrEnum):
    INTENT = "intent"
    APPROVED = "approved"
    ENTRY_SUBMITTING = "entry_submitting"
    ENTRY_ACKNOWLEDGED = "entry_acknowledged"
    ENTRY_PARTIALLY_FILLED = "entry_partially_filled"
    ENTRY_CANCEL_PENDING = "entry_cancel_pending"
    OPEN = "open"
    CLOSE_SUBMITTING = "close_submitting"
    CLOSE_ACKNOWLEDGED = "close_acknowledged"
    CLOSE_PARTIALLY_FILLED = "close_partially_filled"
    CLOSE_CANCEL_PENDING = "close_cancel_pending"
    CANCELED = "canceled"
    CLOSED = "closed"
    REJECTED = "rejected"
    RECONCILE_REQUIRED = "reconcile_required"
    FAILED = "failed"


class LifecycleEventType(StrEnum):
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    ENTRY_SUBMIT_REQUESTED = "entry_submit_requested"
    ENTRY_ACKNOWLEDGED = "entry_acknowledged"
    ENTRY_PARTIAL_FILL = "entry_partial_fill"
    ENTRY_FILLED = "entry_filled"
    ENTRY_CANCEL_REQUESTED = "entry_cancel_requested"
    ENTRY_CANCELED = "entry_canceled"
    CLOSE_SUBMIT_REQUESTED = "close_submit_requested"
    CLOSE_ACKNOWLEDGED = "close_acknowledged"
    EXIT_PARTIAL_FILL = "exit_partial_fill"
    EXIT_FILLED = "exit_filled"
    CLOSE_CANCEL_REQUESTED = "close_cancel_requested"
    CLOSE_CANCELED = "close_canceled"
    BROKER_MISMATCH = "broker_mismatch"
    RECONCILED = "reconciled"
    TERMINAL_FAILURE = "terminal_failure"


class BrokerOrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


TERMINAL_STATES = frozenset(
    {
        LifecycleState.CANCELED,
        LifecycleState.CLOSED,
        LifecycleState.REJECTED,
        LifecycleState.FAILED,
    }
)


class InvalidLifecycleTransition(ValueError):
    """Raised when an event cannot legally follow the current state."""


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    event_type: LifecycleEventType
    occurred_at: datetime
    broker_order_id: str | None = None
    cumulative_filled_quantity: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event id is required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("event timestamp must be timezone-aware")
        if self.cumulative_filled_quantity is not None and self.cumulative_filled_quantity < 0:
            raise ValueError("cumulative filled quantity cannot be negative")


@dataclass(frozen=True)
class LifecycleSnapshot:
    client_order_id: str
    payload_sha256: str
    intended_quantity: int
    state: LifecycleState
    created_at: datetime
    updated_at: datetime
    version: int = 0
    entry_filled_quantity: int = 0
    exit_filled_quantity: int = 0
    entry_broker_order_id: str | None = None
    exit_broker_order_id: str | None = None
    resume_state: LifecycleState | None = None
    failure_reason: str | None = None
    applied_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.client_order_id.strip() or len(self.payload_sha256) != 64:
            raise ValueError("client order id and SHA-256 payload hash are required")
        if self.intended_quantity <= 0:
            raise ValueError("intended quantity must be positive")
        if not 0 <= self.entry_filled_quantity <= self.intended_quantity:
            raise ValueError("entry filled quantity is outside the intended quantity")
        if not 0 <= self.exit_filled_quantity <= self.entry_filled_quantity:
            raise ValueError("exit filled quantity cannot exceed entry filled quantity")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("lifecycle timestamps must be timezone-aware")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("lifecycle timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated timestamp cannot precede creation")
        if self.version != len(self.applied_event_ids):
            raise ValueError("lifecycle version must equal the applied-event count")
        if len(set(self.applied_event_ids)) != len(self.applied_event_ids):
            raise ValueError("applied event ids must be unique")
        if self.state is LifecycleState.RECONCILE_REQUIRED and self.resume_state is None:
            raise ValueError("reconciliation state requires a resume state")
        if self.state is not LifecycleState.RECONCILE_REQUIRED and self.resume_state is not None:
            raise ValueError("resume state is only valid during reconciliation")

    @property
    def active_quantity(self) -> int:
        return self.entry_filled_quantity - self.exit_filled_quantity

    def to_record(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "payload_sha256": self.payload_sha256,
            "intended_quantity": self.intended_quantity,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "entry_filled_quantity": self.entry_filled_quantity,
            "exit_filled_quantity": self.exit_filled_quantity,
            "entry_broker_order_id": self.entry_broker_order_id,
            "exit_broker_order_id": self.exit_broker_order_id,
            "resume_state": self.resume_state.value if self.resume_state else None,
            "failure_reason": self.failure_reason,
            "applied_event_ids": list(self.applied_event_ids),
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> LifecycleSnapshot:
        resume = record.get("resume_state")
        return cls(
            client_order_id=str(record["client_order_id"]),
            payload_sha256=str(record["payload_sha256"]),
            intended_quantity=int(record["intended_quantity"]),
            state=LifecycleState(str(record["state"])),
            created_at=datetime.fromisoformat(str(record["created_at"])),
            updated_at=datetime.fromisoformat(str(record["updated_at"])),
            version=int(record.get("version", 0)),
            entry_filled_quantity=int(record.get("entry_filled_quantity", 0)),
            exit_filled_quantity=int(record.get("exit_filled_quantity", 0)),
            entry_broker_order_id=record.get("entry_broker_order_id"),
            exit_broker_order_id=record.get("exit_broker_order_id"),
            resume_state=LifecycleState(str(resume)) if resume is not None else None,
            failure_reason=record.get("failure_reason"),
            applied_event_ids=tuple(str(item) for item in record.get("applied_event_ids", [])),
        )


@dataclass(frozen=True)
class BrokerOrderView:
    client_order_id: str
    broker_order_id: str | None
    status: BrokerOrderStatus
    filled_quantity: int

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("broker view requires a client order id")
        if self.filled_quantity < 0:
            raise ValueError("broker filled quantity cannot be negative")


@dataclass(frozen=True)
class ReconciliationAssessment:
    consistent: bool
    broker_ahead: bool
    reasons: tuple[str, ...]


def start_lifecycle(intent: MlegOrderIntent) -> LifecycleSnapshot:
    if intent.purpose is not OrderPurpose.ENTRY:
        raise ValueError("a strategy lifecycle must start from an entry intent")
    return LifecycleSnapshot(
        client_order_id=intent.client_order_id,
        payload_sha256=intent.payload_sha256,
        intended_quantity=intent.spread.quantity,
        state=LifecycleState.INTENT,
        created_at=intent.created_at,
        updated_at=intent.created_at,
    )


def _require_reason(event: LifecycleEvent) -> str:
    if event.reason is None or not event.reason.strip():
        raise InvalidLifecycleTransition(f"{event.event_type.value} requires a reason")
    return event.reason.strip()


def _require_broker_id(
    event: LifecycleEvent, existing: str | None
) -> str:
    if event.broker_order_id is None or not event.broker_order_id.strip():
        raise InvalidLifecycleTransition(f"{event.event_type.value} requires a broker order id")
    if existing is not None and existing != event.broker_order_id:
        raise InvalidLifecycleTransition("broker order id does not match the lifecycle")
    return event.broker_order_id


def _advance(
    snapshot: LifecycleSnapshot,
    event: LifecycleEvent,
    *,
    state: LifecycleState,
    **changes: object,
) -> LifecycleSnapshot:
    return replace(
        snapshot,
        state=state,
        updated_at=event.occurred_at,
        version=snapshot.version + 1,
        applied_event_ids=snapshot.applied_event_ids + (event.event_id,),
        **changes,
    )


def _entry_fill_quantity(snapshot: LifecycleSnapshot, event: LifecycleEvent, *, final: bool) -> int:
    quantity = event.cumulative_filled_quantity
    if quantity is None:
        raise InvalidLifecycleTransition(f"{event.event_type.value} requires filled quantity")
    if quantity <= snapshot.entry_filled_quantity:
        raise InvalidLifecycleTransition("entry cumulative fill must move forward")
    if final and quantity != snapshot.intended_quantity:
        raise InvalidLifecycleTransition("final entry fill must equal intended quantity")
    if not final and quantity >= snapshot.intended_quantity:
        raise InvalidLifecycleTransition("partial entry fill must be below intended quantity")
    return quantity


def _exit_fill_quantity(snapshot: LifecycleSnapshot, event: LifecycleEvent, *, final: bool) -> int:
    quantity = event.cumulative_filled_quantity
    if quantity is None:
        raise InvalidLifecycleTransition(f"{event.event_type.value} requires filled quantity")
    if quantity <= snapshot.exit_filled_quantity:
        raise InvalidLifecycleTransition("exit cumulative fill must move forward")
    if final and quantity != snapshot.entry_filled_quantity:
        raise InvalidLifecycleTransition("final exit fill must equal the open quantity")
    if not final and quantity >= snapshot.entry_filled_quantity:
        raise InvalidLifecycleTransition("partial exit fill must be below the open quantity")
    return quantity


def apply_event(snapshot: LifecycleSnapshot, event: LifecycleEvent) -> LifecycleSnapshot:
    """Apply one event exactly once, rejecting every illegal transition."""

    if event.event_id in snapshot.applied_event_ids:
        return snapshot
    if event.occurred_at < snapshot.updated_at:
        raise InvalidLifecycleTransition("event timestamp precedes the current snapshot")
    if snapshot.state in TERMINAL_STATES:
        raise InvalidLifecycleTransition(f"cannot advance terminal state {snapshot.state.value}")

    if event.event_type is LifecycleEventType.BROKER_MISMATCH:
        reason = _require_reason(event)
        if snapshot.state is LifecycleState.RECONCILE_REQUIRED:
            return _advance(
                snapshot,
                event,
                state=LifecycleState.RECONCILE_REQUIRED,
                resume_state=snapshot.resume_state,
                failure_reason=reason,
            )
        return _advance(
            snapshot,
            event,
            state=LifecycleState.RECONCILE_REQUIRED,
            resume_state=snapshot.state,
            failure_reason=reason,
        )

    if event.event_type is LifecycleEventType.RECONCILED:
        if snapshot.state is not LifecycleState.RECONCILE_REQUIRED:
            raise InvalidLifecycleTransition("reconciled event requires reconciliation state")
        assert snapshot.resume_state is not None
        return _advance(
            snapshot,
            event,
            state=snapshot.resume_state,
            resume_state=None,
            failure_reason=None,
        )

    if event.event_type is LifecycleEventType.TERMINAL_FAILURE:
        reason = _require_reason(event)
        if snapshot.active_quantity > 0:
            return _advance(
                snapshot,
                event,
                state=LifecycleState.RECONCILE_REQUIRED,
                resume_state=snapshot.state,
                failure_reason=reason,
            )
        return _advance(
            snapshot,
            event,
            state=LifecycleState.FAILED,
            failure_reason=reason,
        )

    state = snapshot.state
    event_type = event.event_type

    if state is LifecycleState.INTENT:
        if event_type is LifecycleEventType.RISK_APPROVED:
            return _advance(snapshot, event, state=LifecycleState.APPROVED)
        if event_type is LifecycleEventType.RISK_REJECTED:
            return _advance(
                snapshot,
                event,
                state=LifecycleState.REJECTED,
                failure_reason=_require_reason(event),
            )

    elif state is LifecycleState.APPROVED:
        if event_type is LifecycleEventType.ENTRY_SUBMIT_REQUESTED:
            return _advance(snapshot, event, state=LifecycleState.ENTRY_SUBMITTING)

    elif state is LifecycleState.ENTRY_SUBMITTING:
        if event_type is LifecycleEventType.ENTRY_ACKNOWLEDGED:
            broker_id = _require_broker_id(event, snapshot.entry_broker_order_id)
            return _advance(
                snapshot,
                event,
                state=LifecycleState.ENTRY_ACKNOWLEDGED,
                entry_broker_order_id=broker_id,
            )
        if event_type is LifecycleEventType.ENTRY_FILLED:
            broker_id = _require_broker_id(event, snapshot.entry_broker_order_id)
            quantity = _entry_fill_quantity(snapshot, event, final=True)
            return _advance(
                snapshot,
                event,
                state=LifecycleState.OPEN,
                entry_broker_order_id=broker_id,
                entry_filled_quantity=quantity,
            )

    elif state in {
        LifecycleState.ENTRY_ACKNOWLEDGED,
        LifecycleState.ENTRY_PARTIALLY_FILLED,
        LifecycleState.ENTRY_CANCEL_PENDING,
    }:
        if event_type is LifecycleEventType.ENTRY_PARTIAL_FILL:
            broker_id = _require_broker_id(event, snapshot.entry_broker_order_id)
            quantity = _entry_fill_quantity(snapshot, event, final=False)
            next_state = (
                LifecycleState.ENTRY_CANCEL_PENDING
                if state is LifecycleState.ENTRY_CANCEL_PENDING
                else LifecycleState.ENTRY_PARTIALLY_FILLED
            )
            return _advance(
                snapshot,
                event,
                state=next_state,
                entry_broker_order_id=broker_id,
                entry_filled_quantity=quantity,
            )
        if event_type is LifecycleEventType.ENTRY_FILLED:
            broker_id = _require_broker_id(event, snapshot.entry_broker_order_id)
            quantity = _entry_fill_quantity(snapshot, event, final=True)
            return _advance(
                snapshot,
                event,
                state=LifecycleState.OPEN,
                entry_broker_order_id=broker_id,
                entry_filled_quantity=quantity,
            )
        if (
            event_type is LifecycleEventType.ENTRY_CANCEL_REQUESTED
            and state is not LifecycleState.ENTRY_CANCEL_PENDING
        ):
            return _advance(snapshot, event, state=LifecycleState.ENTRY_CANCEL_PENDING)
        if event_type is LifecycleEventType.ENTRY_CANCELED:
            if state is not LifecycleState.ENTRY_CANCEL_PENDING:
                raise InvalidLifecycleTransition("entry cancellation was not requested")
            next_state = (
                LifecycleState.OPEN
                if snapshot.entry_filled_quantity > 0
                else LifecycleState.CANCELED
            )
            return _advance(snapshot, event, state=next_state)

    elif state is LifecycleState.OPEN:
        if event_type is LifecycleEventType.CLOSE_SUBMIT_REQUESTED:
            if snapshot.active_quantity <= 0:
                raise InvalidLifecycleTransition("no active quantity remains to close")
            return _advance(snapshot, event, state=LifecycleState.CLOSE_SUBMITTING)

    elif state is LifecycleState.CLOSE_SUBMITTING:
        if event_type is LifecycleEventType.CLOSE_ACKNOWLEDGED:
            broker_id = _require_broker_id(event, snapshot.exit_broker_order_id)
            return _advance(
                snapshot,
                event,
                state=LifecycleState.CLOSE_ACKNOWLEDGED,
                exit_broker_order_id=broker_id,
            )
        if event_type is LifecycleEventType.EXIT_FILLED:
            broker_id = _require_broker_id(event, snapshot.exit_broker_order_id)
            quantity = _exit_fill_quantity(snapshot, event, final=True)
            return _advance(
                snapshot,
                event,
                state=LifecycleState.CLOSED,
                exit_broker_order_id=broker_id,
                exit_filled_quantity=quantity,
            )

    elif state in {
        LifecycleState.CLOSE_ACKNOWLEDGED,
        LifecycleState.CLOSE_PARTIALLY_FILLED,
        LifecycleState.CLOSE_CANCEL_PENDING,
    }:
        if event_type is LifecycleEventType.EXIT_PARTIAL_FILL:
            broker_id = _require_broker_id(event, snapshot.exit_broker_order_id)
            quantity = _exit_fill_quantity(snapshot, event, final=False)
            next_state = (
                LifecycleState.CLOSE_CANCEL_PENDING
                if state is LifecycleState.CLOSE_CANCEL_PENDING
                else LifecycleState.CLOSE_PARTIALLY_FILLED
            )
            return _advance(
                snapshot,
                event,
                state=next_state,
                exit_broker_order_id=broker_id,
                exit_filled_quantity=quantity,
            )
        if event_type is LifecycleEventType.EXIT_FILLED:
            broker_id = _require_broker_id(event, snapshot.exit_broker_order_id)
            quantity = _exit_fill_quantity(snapshot, event, final=True)
            return _advance(
                snapshot,
                event,
                state=LifecycleState.CLOSED,
                exit_broker_order_id=broker_id,
                exit_filled_quantity=quantity,
            )
        if (
            event_type is LifecycleEventType.CLOSE_CANCEL_REQUESTED
            and state is not LifecycleState.CLOSE_CANCEL_PENDING
        ):
            return _advance(snapshot, event, state=LifecycleState.CLOSE_CANCEL_PENDING)
        if event_type is LifecycleEventType.CLOSE_CANCELED:
            if state is not LifecycleState.CLOSE_CANCEL_PENDING:
                raise InvalidLifecycleTransition("close cancellation was not requested")
            next_state = (
                LifecycleState.CLOSED
                if snapshot.active_quantity == 0
                else LifecycleState.OPEN
            )
            return _advance(snapshot, event, state=next_state)

    raise InvalidLifecycleTransition(
        f"event {event_type.value} is not valid from state {state.value}"
    )


def assess_entry_reconciliation(
    snapshot: LifecycleSnapshot, broker: BrokerOrderView
) -> ReconciliationAssessment:
    """Detect broker/local disagreement without mutating lifecycle state."""

    reasons: list[str] = []
    if broker.client_order_id != snapshot.client_order_id:
        reasons.append("broker client order id does not match local intent")
    if (
        snapshot.entry_broker_order_id is not None
        and broker.broker_order_id != snapshot.entry_broker_order_id
    ):
        reasons.append("broker order id does not match the acknowledged entry")
    if broker.filled_quantity < snapshot.entry_filled_quantity:
        reasons.append("broker filled quantity is behind local state")
    if broker.filled_quantity > snapshot.intended_quantity:
        reasons.append("broker filled quantity exceeds intended quantity")
    if snapshot.state is LifecycleState.CANCELED and broker.status is not BrokerOrderStatus.CANCELED:
        reasons.append("local entry is canceled but broker entry is not canceled")
    if snapshot.state is LifecycleState.OPEN and broker.status not in {
        BrokerOrderStatus.FILLED,
        BrokerOrderStatus.CANCELED,
    }:
        reasons.append("local position is open but broker entry is not terminal")
    if snapshot.state in {LifecycleState.REJECTED, LifecycleState.FAILED} and broker.status in {
        BrokerOrderStatus.NEW,
        BrokerOrderStatus.PARTIALLY_FILLED,
        BrokerOrderStatus.FILLED,
    }:
        reasons.append("local terminal failure conflicts with a live broker order")

    return ReconciliationAssessment(
        consistent=not reasons,
        broker_ahead=not reasons and broker.filled_quantity > snapshot.entry_filled_quantity,
        reasons=tuple(reasons),
    )
