"""Pure preparation and reconciliation for an exact paper MLeg close."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .domain import OptionLeg, OptionRight, Quote, VerticalSpread
from .option_data import parse_alpaca_option_candidate
from .orders import MlegOrderIntent, OrderPurpose, build_mleg_order_intent


def _mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _nonnegative_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if parsed < 0:
        raise ValueError(f"{field} cannot be negative")
    return parsed


def _quantity(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("entry quantity must be a whole number") from exc
    return parsed


def _right(order: dict[str, Any]) -> OptionRight:
    raw = str(order.get("right", "")).strip().lower()
    if raw:
        return OptionRight(raw)
    structure = str(order.get("structure", "")).strip().lower()
    if structure == "bull_call_debit_spread":
        return OptionRight.CALL
    if structure == "bear_put_debit_spread":
        return OptionRight.PUT
    raise ValueError("entry record does not identify the option right")


def entry_intent_from_record(
    record: dict[str, Any], *, fallback_underlying: str | None = None
) -> MlegOrderIntent:
    """Reconstruct and verify the exact original entry intent from its evidence."""

    order = _mapping(record.get("order"), field="order")
    if _quantity(order.get("quantity", 0)) != 1:
        raise ValueError("controlled close requires a one-contract entry record")
    underlying = str(order.get("underlying") or fallback_underlying or "").strip().upper()
    if not underlying:
        raise ValueError("entry record does not identify the underlying")
    right = _right(order)
    try:
        expiration = date.fromisoformat(str(order.get("expiration", "")))
    except ValueError as exc:
        raise ValueError("entry record has an invalid expiration") from exc
    created_at = _timestamp(record.get("prepared_at"), field="prepared_at")
    raw_legs = order.get("legs")
    if not isinstance(raw_legs, list) or len(raw_legs) != 2:
        raise ValueError("entry record must contain exactly two legs")
    by_action = {
        str(leg.get("action", "")): leg
        for leg in raw_legs
        if isinstance(leg, dict)
    }
    long_record = _mapping(by_action.get("buy_to_open"), field="long entry leg")
    short_record = _mapping(by_action.get("sell_to_open"), field="short entry leg")

    def leg(payload: dict[str, Any]) -> OptionLeg:
        observed = (
            _timestamp(payload["observed_at"], field="leg observed_at")
            if payload.get("observed_at") is not None
            else created_at
        )
        symbol = str(payload.get("symbol", "")).strip().upper()
        if not symbol or not symbol.startswith(underlying):
            raise ValueError("entry leg symbol does not match the underlying")
        return OptionLeg(
            symbol=symbol,
            underlying=underlying,
            right=right,
            expiration=expiration,
            strike=_decimal(payload.get("strike"), field="leg strike"),
            quote=Quote(
                bid=_nonnegative_decimal(payload.get("bid"), field="leg bid"),
                ask=_decimal(payload.get("ask"), field="leg ask"),
                observed_at=observed,
            ),
        )

    spread = VerticalSpread(
        long_leg=leg(long_record),
        short_leg=leg(short_record),
        net_debit=_decimal(order.get("limit_debit"), field="entry limit debit"),
        quantity=1,
    )
    intent = build_mleg_order_intent(
        thesis_id=str(record.get("decision_id", "")),
        spread=spread,
        purpose=OrderPurpose.ENTRY,
        limit_price=spread.net_debit,
        created_at=created_at,
    )
    if intent.client_order_id != str(order.get("client_order_id", "")):
        raise ValueError("entry client order ID cannot be reproduced from the record")
    if intent.payload_sha256 != str(order.get("payload_sha256", "")):
        raise ValueError("entry payload hash cannot be reproduced from the record")
    return intent


def exit_intent_from_record(
    record: dict[str, Any], *, entry_intent: MlegOrderIntent
) -> MlegOrderIntent:
    """Reconstruct an exact saved exit for lookup-only recovery."""

    if entry_intent.purpose is not OrderPurpose.ENTRY:
        raise ValueError("exit recovery requires the original entry intent")
    order = _mapping(record.get("order"), field="exit order")
    if str(order.get("entry_client_order_id", "")) != entry_intent.client_order_id:
        raise ValueError("exit record does not belong to the supplied entry")
    if _quantity(order.get("quantity", 0)) != entry_intent.spread.quantity:
        raise ValueError("exit quantity does not match the open entry")
    created_at = _timestamp(record.get("prepared_at"), field="exit prepared_at")
    intent = build_mleg_order_intent(
        thesis_id=entry_intent.client_order_id,
        spread=entry_intent.spread,
        purpose=OrderPurpose.EXIT,
        limit_price=_decimal(order.get("limit_credit"), field="exit limit credit"),
        created_at=created_at,
    )
    if intent.client_order_id != str(order.get("client_order_id", "")):
        raise ValueError("exit client order ID cannot be reproduced from the record")
    if intent.payload_sha256 != str(order.get("payload_sha256", "")):
        raise ValueError("exit payload hash cannot be reproduced from the record")
    return intent


def _position_reasons(
    positions: tuple[dict[str, Any], ...], spread: VerticalSpread
) -> tuple[str, ...]:
    reasons: list[str] = []
    expected = {
        spread.long_leg.symbol: "long",
        spread.short_leg.symbol: "short",
    }
    if len(positions) != 2:
        reasons.append("dedicated canary account must contain exactly two option positions")
    by_symbol = {
        str(position.get("symbol", "")).strip().upper(): position
        for position in positions
    }
    if set(by_symbol) != set(expected):
        reasons.append("broker positions do not exactly match the entry spread legs")
    for symbol, expected_side in expected.items():
        position = by_symbol.get(symbol)
        if position is None:
            continue
        try:
            quantity = abs(Decimal(str(position.get("qty"))))
        except (InvalidOperation, TypeError, ValueError):
            reasons.append(f"broker position quantity for {symbol} is invalid")
            continue
        if quantity != Decimal("1"):
            reasons.append(f"broker position quantity for {symbol} is not one contract")
        if str(position.get("side", "")).strip().lower() != expected_side:
            reasons.append(f"broker position side for {symbol} is not {expected_side}")
    return tuple(dict.fromkeys(reasons))


@dataclass(frozen=True)
class ClosePreparation:
    record: dict[str, object]
    exit_intent: MlegOrderIntent | None

    @property
    def ready(self) -> bool:
        return self.exit_intent is not None and not self.record["blocking_reasons"]


def prepare_close(
    *,
    entry_intent: MlegOrderIntent,
    snapshots: dict[str, dict[str, Any]],
    positions: tuple[dict[str, Any], ...],
    market_open: bool,
    prepared_at: datetime,
) -> ClosePreparation:
    """Build a close preview only after exact positions and fresh quotes agree."""

    if entry_intent.purpose is not OrderPurpose.ENTRY:
        raise ValueError("close preparation requires the original entry intent")
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("close preparation timestamp must be timezone-aware")
    reasons = list(_position_reasons(positions, entry_intent.spread))
    if not market_open:
        reasons.append("paper close requires an open market session")

    current_legs: list[OptionLeg] = []
    for original in (entry_intent.spread.long_leg, entry_intent.spread.short_leg):
        snapshot = snapshots.get(original.symbol)
        if snapshot is None:
            reasons.append(f"current snapshot is missing for {original.symbol}")
            continue
        contract = {
            "tradable": True,
            "symbol": original.symbol,
            "underlying_symbol": original.underlying,
            "type": original.right.value,
            "expiration_date": original.expiration.isoformat(),
            "strike_price": str(original.strike),
        }
        try:
            current = parse_alpaca_option_candidate(contract, snapshot).leg
        except ValueError as exc:
            reasons.append(f"invalid current snapshot for {original.symbol}: {exc}")
            continue
        age = (prepared_at - current.quote.observed_at).total_seconds()
        if age < -5 or age > 15:
            reasons.append(f"exit quote for {original.symbol} is stale or future-dated")
        current_legs.append(current)

    exit_intent: MlegOrderIntent | None = None
    close_credit: Decimal | None = None
    if len(current_legs) == 2:
        current_spread = VerticalSpread(
            long_leg=current_legs[0],
            short_leg=current_legs[1],
            net_debit=entry_intent.spread.net_debit,
            quantity=entry_intent.spread.quantity,
        )
        close_credit = current_spread.long_leg.quote.bid - current_spread.short_leg.quote.ask
        if close_credit <= 0:
            reasons.append("conservative close credit is not positive")
        elif close_credit >= current_spread.width:
            reasons.append("conservative close credit is not below spread width")
        else:
            exit_intent = build_mleg_order_intent(
                thesis_id=str(entry_intent.client_order_id),
                spread=current_spread,
                purpose=OrderPurpose.EXIT,
                limit_price=close_credit,
                created_at=prepared_at,
            )

    unique_reasons = tuple(dict.fromkeys(reasons))
    order_record: dict[str, object] | None = None
    if exit_intent is not None:
        order_record = {
            "client_order_id": exit_intent.client_order_id,
            "payload_sha256": exit_intent.payload_sha256,
            "entry_client_order_id": entry_intent.client_order_id,
            "order_class": "mleg",
            "quantity": exit_intent.spread.quantity,
            "limit_credit": str(exit_intent.limit_price),
            "legs": [
                {
                    "action": "sell_to_close",
                    "symbol": exit_intent.spread.long_leg.symbol,
                    "bid": str(exit_intent.spread.long_leg.quote.bid),
                    "ask": str(exit_intent.spread.long_leg.quote.ask),
                },
                {
                    "action": "buy_to_close",
                    "symbol": exit_intent.spread.short_leg.symbol,
                    "bid": str(exit_intent.spread.short_leg.quote.bid),
                    "ask": str(exit_intent.spread.short_leg.quote.ask),
                },
            ],
            "alpaca_payload": exit_intent.as_alpaca_payload(),
        }
    record: dict[str, object] = {
        "schema_version": "phase-7d.paper-close-preview.v1",
        "mode": "paper-close-preview",
        "prepared_at": prepared_at.isoformat(),
        "ready_for_operator_approval": exit_intent is not None and not unique_reasons,
        "blocking_reasons": list(unique_reasons),
        "market_open": market_open,
        "broker_positions_reconciled": not _position_reasons(
            positions, entry_intent.spread
        ),
        "order": order_record,
        "safety": {
            "paper_only": True,
            "preview_only": True,
            "broker_write_performed": False,
            "operator_confirmation_required": True,
            "one_contract_limit": True,
        },
    }
    return ClosePreparation(record=record, exit_intent=exit_intent)
