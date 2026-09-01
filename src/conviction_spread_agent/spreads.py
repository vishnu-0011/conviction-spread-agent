"""Deterministic construction of defined-risk vertical debit spreads.

The selector consumes normalized option candidates and performs no I/O.  It prefers
the declared delta bands when both legs have usable Greeks, then falls back to a
documented moneyness ranking only when at least one leg is missing delta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .domain import Direction, OptionLeg, OptionRight, VerticalSpread


class SelectionMethod(StrEnum):
    DELTA = "delta"
    MONEYNESS = "moneyness"


@dataclass(frozen=True)
class OptionCandidate:
    """An option leg plus optional liquidity and Greek observations."""

    leg: OptionLeg
    delta: Decimal | None = None
    open_interest: int | None = None
    volume: int | None = None

    def __post_init__(self) -> None:
        if self.delta is not None and not Decimal("-1") <= self.delta <= Decimal("1"):
            raise ValueError("option delta must be between -1 and 1")
        if self.delta is not None and self.leg.right is OptionRight.CALL and self.delta < 0:
            raise ValueError("call delta cannot be negative")
        if self.delta is not None and self.leg.right is OptionRight.PUT and self.delta > 0:
            raise ValueError("put delta cannot be positive")
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError("open interest cannot be negative")
        if self.volume is not None and self.volume < 0:
            raise ValueError("volume cannot be negative")


@dataclass(frozen=True)
class SpreadSelectionPolicy:
    minimum_dte: int = 14
    maximum_dte: int = 35
    target_dte: int = 24
    minimum_width: Decimal = Decimal("1")
    maximum_width: Decimal = Decimal("10")
    maximum_debit_fraction: Decimal = Decimal("0.80")
    maximum_relative_quote_width: Decimal = Decimal("0.15")
    maximum_quote_age_seconds: int = 15
    long_delta_minimum: Decimal = Decimal("0.55")
    long_delta_maximum: Decimal = Decimal("0.65")
    short_delta_minimum: Decimal = Decimal("0.25")
    short_delta_maximum: Decimal = Decimal("0.40")
    short_moneyness_fraction: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if self.minimum_dte < 1 or self.maximum_dte < self.minimum_dte:
            raise ValueError("invalid DTE range")
        if not self.minimum_dte <= self.target_dte <= self.maximum_dte:
            raise ValueError("target DTE must be inside the allowed range")
        if self.minimum_width <= 0 or self.maximum_width < self.minimum_width:
            raise ValueError("invalid spread-width range")
        fractions = (
            self.maximum_debit_fraction,
            self.maximum_relative_quote_width,
            self.long_delta_minimum,
            self.long_delta_maximum,
            self.short_delta_minimum,
            self.short_delta_maximum,
            self.short_moneyness_fraction,
        )
        if any(value <= 0 or value > 1 for value in fractions):
            raise ValueError("selection fractions must be in (0, 1]")
        if self.long_delta_maximum < self.long_delta_minimum:
            raise ValueError("invalid long-delta range")
        if self.short_delta_maximum < self.short_delta_minimum:
            raise ValueError("invalid short-delta range")
        if self.maximum_quote_age_seconds <= 0:
            raise ValueError("maximum quote age must be positive")


@dataclass(frozen=True)
class SpreadConstructionResult:
    spread: VerticalSpread | None
    method: SelectionMethod | None
    candidates_considered: int
    eligible_contracts: int
    pairs_considered: int
    selection_score: Decimal | None
    rejection_reasons: tuple[str, ...]

    @property
    def selected(self) -> bool:
        return self.spread is not None


def _required_right(direction: Direction) -> OptionRight | None:
    if direction is Direction.BULLISH:
        return OptionRight.CALL
    if direction is Direction.BEARISH:
        return OptionRight.PUT
    return None


def _eligible_candidate(
    candidate: OptionCandidate,
    *,
    underlying: str,
    right: OptionRight,
    market_date: date,
    as_of: datetime,
    policy: SpreadSelectionPolicy,
) -> str | None:
    leg = candidate.leg
    if leg.underlying.upper() != underlying:
        return "candidate underlying does not match the requested underlying"
    if leg.right is not right:
        return "candidate option right does not match the thesis direction"
    dte = (leg.expiration - market_date).days
    if dte < policy.minimum_dte or dte > policy.maximum_dte:
        return "candidate expiration is outside the permitted DTE range"
    if leg.quote.bid <= 0:
        return "candidate has no positive bid"
    quote_age = (as_of - leg.quote.observed_at).total_seconds()
    if quote_age < -5 or quote_age > policy.maximum_quote_age_seconds:
        return "candidate quote is stale or future-dated"
    if leg.quote.relative_width > policy.maximum_relative_quote_width:
        return "candidate quote exceeds the relative-width limit"
    return None


def _delta_in_range(value: Decimal | None, minimum: Decimal, maximum: Decimal) -> bool:
    return value is not None and minimum <= abs(value) <= maximum


def _pair_orientation_is_valid(
    direction: Direction, long_leg: OptionLeg, short_leg: OptionLeg
) -> bool:
    if direction is Direction.BULLISH:
        return long_leg.strike < short_leg.strike
    return long_leg.strike > short_leg.strike


def construct_vertical_spread(
    *,
    underlying: str,
    direction: Direction,
    underlying_price: Decimal,
    candidates: tuple[OptionCandidate, ...],
    market_date: date,
    as_of: datetime,
    quantity: int = 1,
    policy: SpreadSelectionPolicy = SpreadSelectionPolicy(),
) -> SpreadConstructionResult:
    """Select one deterministic vertical from a normalized option chain.

    Entry debit is conservatively estimated as the long ask less the short bid.  A
    missing or unusable input produces a result with no spread rather than a guess.
    """

    normalized_underlying = underlying.strip().upper()
    if not normalized_underlying:
        raise ValueError("underlying is required")
    if underlying_price <= 0:
        raise ValueError("underlying price must be positive")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("selection timestamp must be timezone-aware")
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    required_right = _required_right(direction)
    if required_right is None:
        return SpreadConstructionResult(
            spread=None,
            method=None,
            candidates_considered=len(candidates),
            eligible_contracts=0,
            pairs_considered=0,
            selection_score=None,
            rejection_reasons=("a PASS direction cannot construct a spread",),
        )

    rejection_reasons: set[str] = set()
    eligible: list[OptionCandidate] = []
    for candidate in candidates:
        reason = _eligible_candidate(
            candidate,
            underlying=normalized_underlying,
            right=required_right,
            market_date=market_date,
            as_of=as_of,
            policy=policy,
        )
        if reason is None:
            eligible.append(candidate)
        else:
            rejection_reasons.add(reason)

    ranked_pairs: list[
        tuple[
            tuple[object, ...],
            Decimal,
            SelectionMethod,
            VerticalSpread,
        ]
    ] = []
    pairs_considered = 0
    long_delta_target = (policy.long_delta_minimum + policy.long_delta_maximum) / Decimal("2")
    short_delta_target = (
        policy.short_delta_minimum + policy.short_delta_maximum
    ) / Decimal("2")

    for long_candidate in eligible:
        for short_candidate in eligible:
            long_leg = long_candidate.leg
            short_leg = short_candidate.leg
            if long_leg.symbol == short_leg.symbol:
                continue
            if long_leg.expiration != short_leg.expiration:
                continue
            if not _pair_orientation_is_valid(direction, long_leg, short_leg):
                continue
            pairs_considered += 1

            width = abs(long_leg.strike - short_leg.strike)
            if width < policy.minimum_width or width > policy.maximum_width:
                rejection_reasons.add("candidate pair is outside the permitted width range")
                continue
            net_debit = long_leg.quote.ask - short_leg.quote.bid
            if net_debit <= 0:
                rejection_reasons.add("candidate pair has a zero or negative executable debit")
                continue
            if net_debit >= width:
                rejection_reasons.add("candidate pair debit is not below its width")
                continue
            if net_debit > width * policy.maximum_debit_fraction:
                rejection_reasons.add("candidate pair exceeds the maximum debit-to-width ratio")
                continue

            spread = VerticalSpread(
                long_leg=long_leg,
                short_leg=short_leg,
                net_debit=net_debit,
                quantity=quantity,
            )
            dte_distance = abs((long_leg.expiration - market_date).days - policy.target_dte)
            liquidity_score = (
                long_leg.quote.relative_width + short_leg.quote.relative_width
            )

            long_delta_ok = _delta_in_range(
                long_candidate.delta,
                policy.long_delta_minimum,
                policy.long_delta_maximum,
            )
            short_delta_ok = _delta_in_range(
                short_candidate.delta,
                policy.short_delta_minimum,
                policy.short_delta_maximum,
            )
            if long_delta_ok and short_delta_ok:
                delta_score = abs(abs(long_candidate.delta) - long_delta_target) + abs(
                    abs(short_candidate.delta) - short_delta_target
                )
                rank_key = (
                    0,
                    delta_score,
                    dte_distance,
                    liquidity_score,
                    width,
                    long_leg.expiration,
                    long_leg.symbol,
                    short_leg.symbol,
                )
                ranked_pairs.append((rank_key, delta_score, SelectionMethod.DELTA, spread))
                continue

            if long_candidate.delta is not None and short_candidate.delta is not None:
                rejection_reasons.add("available deltas are outside the target bands")
                continue

            target_short_strike = (
                underlying_price * (Decimal("1") + policy.short_moneyness_fraction)
                if direction is Direction.BULLISH
                else underlying_price * (Decimal("1") - policy.short_moneyness_fraction)
            )
            moneyness_score = (
                abs(long_leg.strike - underlying_price)
                + abs(short_leg.strike - target_short_strike)
            ) / underlying_price
            rank_key = (
                1,
                moneyness_score,
                dte_distance,
                liquidity_score,
                width,
                long_leg.expiration,
                long_leg.symbol,
                short_leg.symbol,
            )
            ranked_pairs.append(
                (rank_key, moneyness_score, SelectionMethod.MONEYNESS, spread)
            )

    if not ranked_pairs:
        if not eligible:
            rejection_reasons.add("no contracts passed the eligibility gates")
        else:
            rejection_reasons.add("no eligible pair satisfied the spread rules")
        return SpreadConstructionResult(
            spread=None,
            method=None,
            candidates_considered=len(candidates),
            eligible_contracts=len(eligible),
            pairs_considered=pairs_considered,
            selection_score=None,
            rejection_reasons=tuple(sorted(rejection_reasons)),
        )

    _, score, method, spread = min(ranked_pairs, key=lambda item: item[0])
    return SpreadConstructionResult(
        spread=spread,
        method=method,
        candidates_considered=len(candidates),
        eligible_contracts=len(eligible),
        pairs_considered=pairs_considered,
        selection_score=score,
        rejection_reasons=tuple(sorted(rejection_reasons)),
    )
