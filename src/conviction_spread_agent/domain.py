"""Broker-independent domain objects and defined-risk spread mathematics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


CONTRACT_MULTIPLIER = Decimal("100")


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    PASS = "pass"


class OptionRight(StrEnum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True)
class Quote:
    bid: Decimal
    ask: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.bid < 0 or self.ask <= 0:
            raise ValueError("quote prices must be non-negative with a positive ask")
        if self.bid > self.ask:
            raise ValueError("crossed quote: bid cannot exceed ask")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("quote timestamp must be timezone-aware")

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def relative_width(self) -> Decimal:
        if self.midpoint <= 0:
            raise ValueError("relative width is undefined for a zero midpoint")
        return (self.ask - self.bid) / self.midpoint


@dataclass(frozen=True)
class OptionLeg:
    symbol: str
    underlying: str
    right: OptionRight
    expiration: date
    strike: Decimal
    quote: Quote

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.underlying.strip():
            raise ValueError("leg symbol and underlying are required")
        if self.strike <= 0:
            raise ValueError("strike must be positive")


@dataclass(frozen=True)
class Thesis:
    thesis_id: str
    underlying: str
    direction: Direction
    confidence: Decimal
    summary: str
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    invalidation: str
    created_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not self.thesis_id.strip() or not self.underlying.strip():
            raise ValueError("thesis id and underlying are required")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("thesis timestamps must be timezone-aware")
        if self.valid_until.tzinfo is None or self.valid_until.utcoffset() is None:
            raise ValueError("thesis timestamps must be timezone-aware")
        if self.valid_until <= self.created_at:
            raise ValueError("thesis expiry must be after creation")
        if not self.summary.strip() or not self.invalidation.strip():
            raise ValueError("summary and invalidation are required")
        if not self.evidence:
            raise ValueError("at least one evidence item is required")


@dataclass(frozen=True)
class VerticalSpread:
    """A long-debit vertical; prices are option premiums per underlying share."""

    long_leg: OptionLeg
    short_leg: OptionLeg
    net_debit: Decimal
    quantity: int

    def __post_init__(self) -> None:
        if self.long_leg.underlying != self.short_leg.underlying:
            raise ValueError("vertical legs must share an underlying")
        if self.long_leg.right is not self.short_leg.right:
            raise ValueError("vertical legs must have the same option right")
        if self.long_leg.expiration != self.short_leg.expiration:
            raise ValueError("vertical legs must share an expiration")
        if self.long_leg.symbol == self.short_leg.symbol:
            raise ValueError("vertical legs must be different contracts")
        if self.long_leg.right is OptionRight.CALL and not (
            self.long_leg.strike < self.short_leg.strike
        ):
            raise ValueError("a bull call debit spread buys the lower strike")
        if self.long_leg.right is OptionRight.PUT and not (
            self.long_leg.strike > self.short_leg.strike
        ):
            raise ValueError("a bear put debit spread buys the higher strike")
        if self.net_debit <= 0:
            raise ValueError("net debit must be positive")
        if self.net_debit >= self.width:
            raise ValueError("net debit must be less than the strike width")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

    @property
    def direction(self) -> Direction:
        return Direction.BULLISH if self.long_leg.right is OptionRight.CALL else Direction.BEARISH

    @property
    def width(self) -> Decimal:
        return abs(self.long_leg.strike - self.short_leg.strike)

    @property
    def max_loss(self) -> Decimal:
        return self.net_debit * CONTRACT_MULTIPLIER * self.quantity

    @property
    def max_profit(self) -> Decimal:
        return (self.width - self.net_debit) * CONTRACT_MULTIPLIER * self.quantity

    @property
    def breakeven(self) -> Decimal:
        if self.direction is Direction.BULLISH:
            return self.long_leg.strike + self.net_debit
        return self.long_leg.strike - self.net_debit

    @property
    def worst_relative_quote_width(self) -> Decimal:
        return max(self.long_leg.quote.relative_width, self.short_leg.quote.relative_width)
