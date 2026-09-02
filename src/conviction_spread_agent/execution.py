"""Fail-closed Alpaca paper MLeg submission and reconciliation boundary.

The module is intentionally separate from the GET-only shadow client. It can only
target Alpaca's paper host, persists the submit-requested state before network I/O,
and refuses to retry an uncertain submission. Recovery always looks up the original
client order ID instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .lifecycle import (
    BrokerOrderStatus,
    BrokerOrderView,
    LifecycleEvent,
    LifecycleEventType,
    LifecycleSnapshot,
    LifecycleState,
    apply_event,
)
from .orders import MlegOrderIntent, OrderPurpose
from .risk import RiskDecision


PAPER_API_HOST = "https://paper-api.alpaca.markets"
USER_AGENT = "conviction-spread-agent-paper-canary/0.1"
_ACTIVE_STATUSES = frozenset(
    {
        "accepted",
        "accepted_for_bidding",
        "calculated",
        "done_for_day",
        "held",
        "new",
        "pending_cancel",
        "pending_new",
        "pending_replace",
        "stopped",
    }
)
_CANCELED_STATUSES = frozenset({"canceled", "expired", "replaced"})
_REJECTED_STATUSES = frozenset({"rejected", "suspended"})


class ExecutionBlocked(RuntimeError):
    """The local safety boundary refused to contact Alpaca."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__("paper execution blocked: " + "; ".join(reasons))


class AlpacaExecutionError(RuntimeError):
    """A sanitized broker or transport failure."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        outcome_unknown: bool,
    ) -> None:
        self.status = status
        self.outcome_unknown = outcome_unknown
        super().__init__(message)


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Short-lived operator and runtime authorization for one paper canary."""

    paper_trading: bool = True
    submission_enabled: bool = False
    dry_run: bool = True
    broker_reconciled: bool = False
    kill_switch: bool = True
    operator_canary_approved: bool = False
    maximum_contracts: int = 1
    valid_until: datetime | None = None
    client_order_id: str | None = None
    payload_sha256: str | None = None

    def __post_init__(self) -> None:
        for value, field in (
            (self.paper_trading, "paper trading"),
            (self.submission_enabled, "submission enabled"),
            (self.dry_run, "dry run"),
            (self.broker_reconciled, "broker reconciled"),
            (self.kill_switch, "kill switch"),
            (self.operator_canary_approved, "operator canary approved"),
        ):
            if type(value) is not bool:
                raise TypeError(f"{field} authorization must be boolean")
        if type(self.maximum_contracts) is not int or self.maximum_contracts <= 0:
            raise ValueError("maximum contracts must be positive")
        if self.valid_until is not None and (
            self.valid_until.tzinfo is None or self.valid_until.utcoffset() is None
        ):
            raise ValueError("authorization expiry must be timezone-aware")
        if self.payload_sha256 is not None and (
            len(self.payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.payload_sha256
            )
        ):
            raise ValueError("authorized payload hash must be lowercase SHA-256")


@dataclass(frozen=True)
class BrokerOrderReceipt:
    view: BrokerOrderView
    requested_quantity: int
    leg_symbols: tuple[str, ...]
    response_sha256: str


@dataclass(frozen=True)
class SubmissionResult:
    lifecycle: LifecycleSnapshot
    broker_order_id: str
    broker_status: BrokerOrderStatus
    response_sha256: str


@dataclass(frozen=True)
class ReconciliationResult:
    lifecycle: LifecycleSnapshot
    broker_status: BrokerOrderStatus
    consistent: bool
    reasons: tuple[str, ...]


class LifecycleStore(Protocol):
    def load(self, client_order_id: str) -> LifecycleSnapshot | None: ...

    def save(self, snapshot: LifecycleSnapshot) -> None: ...


class JsonLifecycleStore:
    """Atomic, monotonic JSON persistence for restart-safe recovery."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def _path(self, client_order_id: str) -> Path:
        digest = hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"

    def load(self, client_order_id: str) -> LifecycleSnapshot | None:
        path = self._path(client_order_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("stored lifecycle must be a JSON object")
        snapshot = LifecycleSnapshot.from_record(raw)
        if snapshot.client_order_id != client_order_id:
            raise ValueError("stored lifecycle client order id does not match its key")
        return snapshot

    def save(self, snapshot: LifecycleSnapshot) -> None:
        path = self._path(snapshot.client_order_id)
        existing = self.load(snapshot.client_order_id)
        if existing is not None:
            if snapshot.version < existing.version:
                raise ValueError("lifecycle persistence cannot move backward")
            if snapshot.version == existing.version:
                if snapshot != existing:
                    raise ValueError("same lifecycle version contains different state")
                return

        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        serialized = json.dumps(
            snapshot.to_record(), sort_keys=True, separators=(",", ":")
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


JsonTransport = Callable[[Request, int], dict[str, Any]]


def _default_transport(request: Request, timeout_seconds: int) -> dict[str, Any]:
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise AlpacaExecutionError(
            "Alpaca returned a non-object JSON response", outcome_unknown=True
        )
    return payload


class AlpacaPaperOrderClient:
    """Narrow client fixed to paper order submit and lookup endpoints."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        timeout_seconds: int = 10,
        transport: JsonTransport = _default_transport,
    ) -> None:
        if not api_key.strip() or not secret_key.strip():
            raise ValueError("Alpaca API key and secret are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        self.__api_key = api_key
        self.__secret_key = secret_key
        self.__timeout_seconds = timeout_seconds
        self.__transport = transport

    def __request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{PAPER_API_HOST}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = None
        headers = {
            "APCA-API-KEY-ID": self.__api_key,
            "APCA-API-SECRET-KEY": self.__secret_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, method=method, headers=headers)
        try:
            result = self.__transport(request, self.__timeout_seconds)
        except HTTPError as exc:
            request_id = exc.headers.get("X-Request-ID") if exc.headers else None
            suffix = f" (request id {request_id})" if request_id else ""
            outcome_unknown = method == "POST" and exc.code not in {400, 403, 404, 422}
            raise AlpacaExecutionError(
                f"Alpaca {method} returned HTTP {exc.code}{suffix}",
                status=exc.code,
                outcome_unknown=outcome_unknown,
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise AlpacaExecutionError(
                f"Alpaca {method} transport failed",
                outcome_unknown=method == "POST",
            ) from exc
        if not isinstance(result, dict):
            raise AlpacaExecutionError(
                f"Alpaca {method} returned a non-object JSON response",
                outcome_unknown=method == "POST",
            )
        return result

    def submit_mleg(self, intent: MlegOrderIntent) -> dict[str, Any]:
        return self.__request(
            method="POST", path="/v2/orders", payload=intent.as_alpaca_payload()
        )

    def get_by_client_order_id(self, client_order_id: str) -> dict[str, Any] | None:
        if not client_order_id.strip():
            raise ValueError("client order id is required")
        try:
            return self.__request(
                method="GET",
                path="/v2/orders:by_client_order_id",
                query={"client_order_id": client_order_id},
            )
        except AlpacaExecutionError as exc:
            if exc.status == 404:
                return None
            raise


def _whole_quantity(value: object, *, field: str) -> int:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"broker {field} is not numeric") from exc
    if parsed < 0 or parsed != parsed.to_integral_value():
        raise ValueError(f"broker {field} must be a non-negative whole number")
    return int(parsed)


def _map_status(value: object) -> BrokerOrderStatus:
    status = str(value).strip().lower()
    if status in _ACTIVE_STATUSES:
        return BrokerOrderStatus.NEW
    if status == "partially_filled":
        return BrokerOrderStatus.PARTIALLY_FILLED
    if status == "filled":
        return BrokerOrderStatus.FILLED
    if status in _CANCELED_STATUSES:
        return BrokerOrderStatus.CANCELED
    if status in _REJECTED_STATUSES:
        return BrokerOrderStatus.REJECTED
    raise ValueError(f"unsupported broker order status: {status or '<missing>'}")


def parse_broker_order(
    payload: dict[str, Any], intent: MlegOrderIntent
) -> BrokerOrderReceipt:
    """Validate that a broker response describes the exact intended MLeg order."""

    broker_id = str(payload.get("id", "")).strip()
    client_order_id = str(payload.get("client_order_id", "")).strip()
    if not broker_id:
        raise ValueError("broker order id is missing")
    if client_order_id != intent.client_order_id:
        raise ValueError("broker client order id does not match the submitted intent")
    if str(payload.get("order_class", "")).lower() != "mleg":
        raise ValueError("broker response is not an MLeg order")

    requested_quantity = _whole_quantity(payload.get("qty"), field="quantity")
    filled_quantity = _whole_quantity(
        payload.get("filled_qty", 0), field="filled quantity"
    )
    if requested_quantity != intent.spread.quantity:
        raise ValueError("broker quantity does not match the submitted intent")
    if filled_quantity > requested_quantity:
        raise ValueError("broker filled quantity exceeds requested quantity")

    raw_legs = payload.get("legs")
    if not isinstance(raw_legs, list):
        raise ValueError("broker MLeg response is missing its legs")
    leg_symbols = tuple(
        sorted(
            str(leg.get("symbol", "")).strip().upper()
            for leg in raw_legs
            if isinstance(leg, dict)
        )
    )
    intended_symbols = tuple(
        sorted(
            (
                intent.spread.long_leg.symbol.upper(),
                intent.spread.short_leg.symbol.upper(),
            )
        )
    )
    if leg_symbols != intended_symbols:
        raise ValueError("broker legs do not match the submitted spread")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return BrokerOrderReceipt(
        view=BrokerOrderView(
            client_order_id=client_order_id,
            broker_order_id=broker_id,
            status=_map_status(payload.get("status")),
            filled_quantity=filled_quantity,
        ),
        requested_quantity=requested_quantity,
        leg_symbols=leg_symbols,
        response_sha256=hashlib.sha256(canonical).hexdigest(),
    )


class PaperExecutionGateway:
    """Durable one-contract canary boundary with submission off by default."""

    def __init__(
        self,
        client: AlpacaPaperOrderClient,
        store: LifecycleStore,
        *,
        submission_enabled: bool = False,
        maximum_risk_age_seconds: int = 10,
        maximum_authorization_horizon_seconds: int = 120,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if type(submission_enabled) is not bool:
            raise TypeError("submission enabled must be boolean")
        if maximum_risk_age_seconds <= 0:
            raise ValueError("maximum risk age must be positive")
        if maximum_authorization_horizon_seconds <= 0:
            raise ValueError("maximum authorization horizon must be positive")
        self._client = client
        self._store = store
        self._submission_enabled = submission_enabled
        self._maximum_risk_age_seconds = maximum_risk_age_seconds
        self._maximum_authorization_horizon_seconds = (
            maximum_authorization_horizon_seconds
        )
        self._clock = clock

    def _authorization_reasons(
        self,
        intent: MlegOrderIntent,
        risk: RiskDecision,
        authorization: ExecutionAuthorization,
        lifecycle: LifecycleSnapshot,
        now: datetime,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        clock_is_aware = now.tzinfo is not None and now.utcoffset() is not None
        if not clock_is_aware:
            reasons.append("gateway clock is not timezone-aware")
        if not self._submission_enabled:
            reasons.append("paper submission gateway is disabled")
        if not authorization.paper_trading:
            reasons.append("authorization is not restricted to paper trading")
        if not authorization.submission_enabled:
            reasons.append("authorization does not enable submission")
        if authorization.dry_run:
            reasons.append("authorization remains in dry-run mode")
        if not authorization.broker_reconciled:
            reasons.append("authorization lacks broker reconciliation")
        if authorization.kill_switch:
            reasons.append("authorization kill switch is active")
        if not authorization.operator_canary_approved:
            reasons.append("operator has not approved the paper canary")
        if authorization.maximum_contracts != 1:
            reasons.append("paper canary authorization must be exactly one contract")
        if authorization.valid_until is None:
            reasons.append("authorization expiry is required")
        elif clock_is_aware:
            authorization_horizon = (authorization.valid_until - now).total_seconds()
            if authorization_horizon <= 0:
                reasons.append("paper canary authorization has expired")
            elif authorization_horizon > self._maximum_authorization_horizon_seconds:
                reasons.append("paper canary authorization is not short-lived")
        if authorization.client_order_id != intent.client_order_id:
            reasons.append("authorization client order id does not match the intent")
        if authorization.payload_sha256 != intent.payload_sha256:
            reasons.append("authorization payload hash does not match the intent")
        if intent.purpose is not OrderPurpose.ENTRY:
            reasons.append("entry gateway cannot submit an exit intent")
        if intent.spread.quantity != 1:
            reasons.append("paper canary is limited to one contract")
        if risk.approved is not True:
            reasons.append("deterministic risk decision is not approved")
        if risk.maximum_allowed_quantity < intent.spread.quantity:
            reasons.append("risk decision quantity is below the intent quantity")
        risk_time_is_aware = (
            risk.assessed_at.tzinfo is not None
            and risk.assessed_at.utcoffset() is not None
        )
        if not risk_time_is_aware:
            reasons.append("deterministic risk decision timestamp is not timezone-aware")
        elif clock_is_aware:
            risk_age = (now - risk.assessed_at).total_seconds()
            if risk_age < -2 or risk_age > self._maximum_risk_age_seconds:
                reasons.append("deterministic risk decision is stale or future-dated")
        if lifecycle.state is not LifecycleState.APPROVED:
            reasons.append("lifecycle is not in the approved state")
        if lifecycle.client_order_id != intent.client_order_id:
            reasons.append("lifecycle client order id does not match the intent")
        if lifecycle.payload_sha256 != intent.payload_sha256:
            reasons.append("lifecycle payload hash does not match the intent")
        if lifecycle.intended_quantity != intent.spread.quantity:
            reasons.append("lifecycle quantity does not match the intent")
        stored = self._store.load(intent.client_order_id)
        if stored is None:
            reasons.append("approved lifecycle is not durably stored")
        elif stored != lifecycle:
            reasons.append("stored lifecycle differs from the submitted snapshot")
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _event(
        snapshot: LifecycleSnapshot,
        event_type: LifecycleEventType,
        occurred_at: datetime,
        *,
        broker_order_id: str | None = None,
        filled: int | None = None,
        reason: str | None = None,
    ) -> LifecycleEvent:
        identity = "|".join(
            (
                snapshot.client_order_id,
                str(snapshot.version + 1),
                event_type.value,
                broker_order_id or "",
                str(filled) if filled is not None else "",
                reason or "",
            )
        )
        return LifecycleEvent(
            event_id="gateway-"
            + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            event_type=event_type,
            occurred_at=occurred_at,
            broker_order_id=broker_order_id,
            cumulative_filled_quantity=filled,
            reason=reason,
        )

    def _persist_event(
        self,
        snapshot: LifecycleSnapshot,
        event_type: LifecycleEventType,
        now: datetime,
        **values: object,
    ) -> LifecycleSnapshot:
        updated = apply_event(
            snapshot,
            self._event(snapshot, event_type, now, **values),
        )
        self._store.save(updated)
        return updated

    def _apply_receipt(
        self,
        snapshot: LifecycleSnapshot,
        receipt: BrokerOrderReceipt,
        now: datetime,
    ) -> LifecycleSnapshot:
        view = receipt.view
        broker_id = view.broker_order_id
        assert broker_id is not None

        if view.status is BrokerOrderStatus.NEW:
            if snapshot.state is LifecycleState.ENTRY_SUBMITTING:
                snapshot = self._persist_event(
                    snapshot,
                    LifecycleEventType.ENTRY_ACKNOWLEDGED,
                    now,
                    broker_order_id=broker_id,
                )
            if view.filled_quantity > snapshot.entry_filled_quantity:
                event_type = (
                    LifecycleEventType.ENTRY_FILLED
                    if view.filled_quantity == snapshot.intended_quantity
                    else LifecycleEventType.ENTRY_PARTIAL_FILL
                )
                snapshot = self._persist_event(
                    snapshot,
                    event_type,
                    now,
                    broker_order_id=broker_id,
                    filled=view.filled_quantity,
                )
            return snapshot

        if view.status is BrokerOrderStatus.PARTIALLY_FILLED:
            if view.filled_quantity <= 0:
                raise ValueError("partially filled broker order has zero filled quantity")
            if snapshot.state is LifecycleState.ENTRY_SUBMITTING:
                snapshot = self._persist_event(
                    snapshot,
                    LifecycleEventType.ENTRY_ACKNOWLEDGED,
                    now,
                    broker_order_id=broker_id,
                )
            if view.filled_quantity > snapshot.entry_filled_quantity:
                snapshot = self._persist_event(
                    snapshot,
                    LifecycleEventType.ENTRY_PARTIAL_FILL,
                    now,
                    broker_order_id=broker_id,
                    filled=view.filled_quantity,
                )
            return snapshot

        if view.status is BrokerOrderStatus.FILLED:
            if view.filled_quantity != snapshot.intended_quantity:
                raise ValueError("filled broker order does not equal intended quantity")
            if snapshot.state is LifecycleState.OPEN:
                return snapshot
            return self._persist_event(
                snapshot,
                LifecycleEventType.ENTRY_FILLED,
                now,
                broker_order_id=broker_id,
                filled=view.filled_quantity,
            )

        if view.status in {BrokerOrderStatus.CANCELED, BrokerOrderStatus.REJECTED}:
            if view.filled_quantity > snapshot.entry_filled_quantity:
                if snapshot.state is LifecycleState.ENTRY_SUBMITTING:
                    snapshot = self._persist_event(
                        snapshot,
                        LifecycleEventType.ENTRY_ACKNOWLEDGED,
                        now,
                        broker_order_id=broker_id,
                    )
                fill_event = (
                    LifecycleEventType.ENTRY_FILLED
                    if view.filled_quantity == snapshot.intended_quantity
                    else LifecycleEventType.ENTRY_PARTIAL_FILL
                )
                snapshot = self._persist_event(
                    snapshot,
                    fill_event,
                    now,
                    broker_order_id=broker_id,
                    filled=view.filled_quantity,
                )
            if snapshot.active_quantity > 0:
                return self._persist_event(
                    snapshot,
                    LifecycleEventType.BROKER_MISMATCH,
                    now,
                    reason="broker entry became terminal with unresolved exposure",
                )
            return self._persist_event(
                snapshot,
                LifecycleEventType.TERMINAL_FAILURE,
                now,
                reason=f"broker entry became {view.status.value}",
            )

        raise ValueError(f"cannot apply broker status {view.status.value}")

    def submit_entry(
        self,
        intent: MlegOrderIntent,
        risk: RiskDecision,
        authorization: ExecutionAuthorization,
        lifecycle: LifecycleSnapshot,
    ) -> SubmissionResult:
        """Submit once after durable intent persistence; never retry uncertainty."""

        now = self._clock()
        reasons = self._authorization_reasons(
            intent, risk, authorization, lifecycle, now
        )
        if reasons:
            raise ExecutionBlocked(reasons)

        submitting = self._persist_event(
            lifecycle, LifecycleEventType.ENTRY_SUBMIT_REQUESTED, now
        )
        try:
            raw = self._client.submit_mleg(intent)
            receipt = parse_broker_order(raw, intent)
            updated = self._apply_receipt(submitting, receipt, self._clock())
        except AlpacaExecutionError as exc:
            event_type = (
                LifecycleEventType.BROKER_MISMATCH
                if exc.outcome_unknown
                else LifecycleEventType.TERMINAL_FAILURE
            )
            reason = (
                "submission outcome is unknown; reconcile by client order id"
                if exc.outcome_unknown
                else "Alpaca rejected the paper order request"
            )
            self._persist_event(submitting, event_type, self._clock(), reason=reason)
            raise
        except (ValueError, KeyError) as exc:
            self._persist_event(
                submitting,
                LifecycleEventType.BROKER_MISMATCH,
                self._clock(),
                reason="broker response could not be matched to the submitted intent",
            )
            raise AlpacaExecutionError(
                "Alpaca POST returned an invalid order response",
                outcome_unknown=True,
            ) from exc

        broker_id = receipt.view.broker_order_id
        assert broker_id is not None
        return SubmissionResult(
            lifecycle=updated,
            broker_order_id=broker_id,
            broker_status=receipt.view.status,
            response_sha256=receipt.response_sha256,
        )

    def reconcile_entry(
        self,
        intent: MlegOrderIntent,
        lifecycle: LifecycleSnapshot,
    ) -> ReconciliationResult:
        """Recover by lookup only; this method can never submit an order."""

        stored = self._store.load(intent.client_order_id)
        if stored is None or stored != lifecycle:
            raise ExecutionBlocked(
                ("lifecycle must match durable state before reconciliation",)
            )
        raw = self._client.get_by_client_order_id(intent.client_order_id)
        if raw is None:
            return ReconciliationResult(
                lifecycle=lifecycle,
                broker_status=BrokerOrderStatus.NOT_FOUND,
                consistent=False,
                reasons=(
                    "broker order was not found; automatic resubmission is prohibited",
                ),
            )
        try:
            receipt = parse_broker_order(raw, intent)
        except (ValueError, KeyError) as exc:
            if lifecycle.state is not LifecycleState.RECONCILE_REQUIRED:
                lifecycle = self._persist_event(
                    lifecycle,
                    LifecycleEventType.BROKER_MISMATCH,
                    self._clock(),
                    reason="broker order does not match the durable intent",
                )
            return ReconciliationResult(
                lifecycle=lifecycle,
                broker_status=BrokerOrderStatus.NOT_FOUND,
                consistent=False,
                reasons=(str(exc),),
            )

        working = lifecycle
        if working.state is LifecycleState.RECONCILE_REQUIRED:
            working = self._persist_event(
                working, LifecycleEventType.RECONCILED, self._clock()
            )
        try:
            updated = self._apply_receipt(working, receipt, self._clock())
        except ValueError as exc:
            if working.state is not LifecycleState.RECONCILE_REQUIRED:
                working = self._persist_event(
                    working,
                    LifecycleEventType.BROKER_MISMATCH,
                    self._clock(),
                    reason="broker lifecycle cannot be applied safely",
                )
            return ReconciliationResult(
                lifecycle=working,
                broker_status=receipt.view.status,
                consistent=False,
                reasons=(str(exc),),
            )
        if updated.state is LifecycleState.RECONCILE_REQUIRED:
            return ReconciliationResult(
                lifecycle=updated,
                broker_status=receipt.view.status,
                consistent=False,
                reasons=(
                    updated.failure_reason
                    or "broker order still requires manual reconciliation",
                ),
            )
        return ReconciliationResult(
            lifecycle=updated,
            broker_status=receipt.view.status,
            consistent=True,
            reasons=(),
        )
