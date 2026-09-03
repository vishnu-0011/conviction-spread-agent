"""Construction of broker payloads from already validated spread intents.

This module deliberately performs no I/O. Submission belongs to an execution gateway
that re-checks risk approval, environment mode, and broker reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import StrEnum
import hashlib
import json

from .domain import VerticalSpread


class OrderPurpose(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


def _decimal_string(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _alpaca_limit_price(value: Decimal, purpose: OrderPurpose) -> Decimal:
    """Normalize to Alpaca's documented limit-price decimal precision."""

    increment = Decimal("0.01") if value >= Decimal("1") else Decimal("0.0001")
    rounding = ROUND_CEILING if purpose is OrderPurpose.ENTRY else ROUND_FLOOR
    return value.quantize(increment, rounding=rounding)


@dataclass(frozen=True)
class MlegOrderIntent:
    client_order_id: str
    purpose: OrderPurpose
    spread: VerticalSpread
    limit_price: Decimal
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.client_order_id or len(self.client_order_id) > 128:
            raise ValueError("client order id must contain 1–128 characters")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("order timestamp must be timezone-aware")
        if self.limit_price <= 0:
            raise ValueError("the human-facing debit or credit limit must be positive")
        if self.limit_price >= self.spread.width:
            raise ValueError("order price must be less than the spread width")

    def as_alpaca_payload(self) -> dict[str, object]:
        """Return the current Alpaca MLeg REST shape.

        Alpaca represents a strategy debit as a positive parent price and a strategy
        credit as a negative parent price. The public field here remains a positive,
        human-facing amount for both entry debit and exit credit.
        """

        if self.purpose is OrderPurpose.ENTRY:
            parent_price = self.limit_price
            long_side, long_intent = "buy", "buy_to_open"
            short_side, short_intent = "sell", "sell_to_open"
        else:
            parent_price = -self.limit_price
            long_side, long_intent = "sell", "sell_to_close"
            short_side, short_intent = "buy", "buy_to_close"

        return {
            "client_order_id": self.client_order_id,
            "order_class": "mleg",
            "qty": str(self.spread.quantity),
            "type": "limit",
            "limit_price": _decimal_string(parent_price),
            "time_in_force": "day",
            "legs": [
                {
                    "symbol": self.spread.long_leg.symbol,
                    "ratio_qty": "1",
                    "side": long_side,
                    "position_intent": long_intent,
                },
                {
                    "symbol": self.spread.short_leg.symbol,
                    "ratio_qty": "1",
                    "side": short_side,
                    "position_intent": short_intent,
                },
            ],
        }

    @property
    def payload_sha256(self) -> str:
        canonical = json.dumps(
            self.as_alpaca_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def build_mleg_order_intent(
    *,
    thesis_id: str,
    spread: VerticalSpread,
    purpose: OrderPurpose,
    limit_price: Decimal,
    created_at: datetime,
) -> MlegOrderIntent:
    """Create a deterministic idempotency key for one logical order intent."""

    if not thesis_id.strip():
        raise ValueError("thesis id is required")
    normalized_limit_price = _alpaca_limit_price(limit_price, purpose)
    identity = "|".join(
        (
            thesis_id,
            purpose.value,
            spread.long_leg.symbol,
            spread.short_leg.symbol,
            str(spread.quantity),
            _decimal_string(normalized_limit_price),
        )
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    purpose_code = "e" if purpose is OrderPurpose.ENTRY else "x"
    client_order_id = f"csa-{purpose_code}-{created_at:%Y%m%d}-{suffix}"
    return MlegOrderIntent(
        client_order_id=client_order_id,
        purpose=purpose,
        spread=spread,
        limit_price=normalized_limit_price,
        created_at=created_at,
    )
