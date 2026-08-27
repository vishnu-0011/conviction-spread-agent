"""Simplified vertical-spread outcome model for research simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from ..domain import CONTRACT_MULTIPLIER, Direction, OptionLeg, OptionRight, Quote, VerticalSpread
from ..features.engine import FeatureSnapshot
from .fills import FillAssumptions


@dataclass(frozen=True)
class SpreadSimulationConfig:
    spread_width: Decimal = Decimal("5")
    holding_days: int = 10
    profit_capture_fraction: Decimal = Decimal("0.50")
    stop_loss_fraction: Decimal = Decimal("0.50")
    dte_at_entry: int = 21
    quantity: int = 1

    def __post_init__(self) -> None:
        if self.spread_width <= 0:
            raise ValueError("spread_width must be positive")
        if self.holding_days <= 0:
            raise ValueError("holding_days must be positive")
        for name in ("profit_capture_fraction", "stop_loss_fraction"):
            value = getattr(self, name)
            if value <= 0 or value > 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.dte_at_entry <= 0 or self.quantity <= 0:
            raise ValueError("dte_at_entry and quantity must be positive")


@dataclass(frozen=True)
class SimulatedTrade:
    symbol: str
    direction: Direction
    entry_time: datetime
    exit_time: datetime
    entry_debit: Decimal
    exit_value: Decimal
    pnl: Decimal
    max_loss: Decimal
    exit_reason: str
    filled: bool


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _intrinsic_spread_value(underlying: Decimal, spread: VerticalSpread) -> Decimal:
    if spread.direction is Direction.BULLISH:
        long_intrinsic = max(Decimal("0"), underlying - spread.long_leg.strike)
        short_intrinsic = max(Decimal("0"), underlying - spread.short_leg.strike)
    else:
        long_intrinsic = max(Decimal("0"), spread.long_leg.strike - underlying)
        short_intrinsic = max(Decimal("0"), spread.short_leg.strike - underlying)
    return _quantize_money(long_intrinsic - short_intrinsic)


def _synthetic_quotes(
    underlying: Decimal,
    *,
    long_strike: Decimal,
    short_strike: Decimal,
    right: OptionRight,
    observed_at: datetime,
) -> tuple[Quote, Quote]:
    """Generate conservative synthetic quotes around intrinsic value."""

    if right is OptionRight.CALL:
        long_mid = max(Decimal("0.50"), underlying - long_strike + Decimal("1.50"))
        short_mid = max(Decimal("0.25"), underlying - short_strike + Decimal("0.75"))
    else:
        long_mid = max(Decimal("0.50"), long_strike - underlying + Decimal("1.50"))
        short_mid = max(Decimal("0.25"), short_strike - underlying + Decimal("0.75"))
    long_spread = max(Decimal("0.05"), long_mid * Decimal("0.08"))
    short_spread = max(Decimal("0.05"), short_mid * Decimal("0.08"))
    long_quote = Quote(
        long_mid - long_spread / 2,
        long_mid + long_spread / 2,
        observed_at,
    )
    short_quote = Quote(
        short_mid - short_spread / 2,
        short_mid + short_spread / 2,
        observed_at,
    )
    return long_quote, short_quote


def _build_spread(
    symbol: str,
    direction: Direction,
    underlying: Decimal,
    *,
    market_date: date,
    config: SpreadSimulationConfig,
    observed_at: datetime,
) -> VerticalSpread:
    long_strike = _quantize_money(underlying // Decimal("1"))
    if direction is Direction.BULLISH:
        short_strike = long_strike + config.spread_width
        right = OptionRight.CALL
    else:
        short_strike = long_strike - config.spread_width
        right = OptionRight.PUT
    long_quote, short_quote = _synthetic_quotes(
        underlying,
        long_strike=long_strike,
        short_strike=short_strike,
        right=right,
        observed_at=observed_at,
    )
    long_leg = OptionLeg(
        symbol=f"{symbol}{market_date:%y%m%d}{right.value[0].upper()}{int(long_strike * 1000):08d}",
        underlying=symbol,
        right=right,
        expiration=market_date + timedelta(days=config.dte_at_entry),
        strike=long_strike,
        quote=long_quote,
    )
    short_leg = OptionLeg(
        symbol=f"{symbol}{market_date:%y%m%d}{right.value[0].upper()}{int(short_strike * 1000):08d}",
        underlying=symbol,
        right=right,
        expiration=market_date + timedelta(days=config.dte_at_entry),
        strike=short_strike,
        quote=short_quote,
    )
    from .fills import SpreadFillModel

    debit = SpreadFillModel().entry_debit(long_quote, short_quote)
    return VerticalSpread(long_leg=long_leg, short_leg=short_leg, net_debit=debit, quantity=config.quantity)


def simulate_spread_trade(
    features: FeatureSnapshot,
    *,
    direction: Direction,
    future_closes: list[tuple[datetime, Decimal]],
    assumptions: FillAssumptions = FillAssumptions(),
    config: SpreadSimulationConfig = SpreadSimulationConfig(),
) -> SimulatedTrade:
    """Simulate one defined-risk spread using only information available at entry."""

    if direction is Direction.PASS:
        raise ValueError("PASS direction cannot create a simulated trade")
    if not future_closes:
        raise ValueError("future closes are required")

    entry_time = features.as_of
    market_date = entry_time.date()
    entry_underlying = future_closes[0][1]
    spread = _build_spread(
        features.symbol,
        direction,
        entry_underlying,
        market_date=market_date,
        config=config,
        observed_at=entry_time,
    )
    max_loss = spread.max_loss
    max_profit = spread.max_profit
    profit_target = max_loss * config.profit_capture_fraction
    stop_loss = -max_loss * config.stop_loss_fraction

    digest = f"{features.symbol}|{entry_time.isoformat()}|{direction.value}"
    rejection_roll = int.from_bytes(digest.encode("utf-8")[:8], "big") % 1000
    rejection_threshold = int(assumptions.rejection_probability * 1000)
    if rejection_roll < rejection_threshold:
        return SimulatedTrade(
            symbol=features.symbol,
            direction=direction,
            entry_time=entry_time,
            exit_time=entry_time,
            entry_debit=spread.net_debit,
            exit_value=Decimal("0"),
            pnl=Decimal("0"),
            max_loss=max_loss,
            exit_reason="order rejected at entry",
            filled=False,
        )

    fees = assumptions.fee_per_contract * Decimal("2") * config.quantity
    holding_limit = entry_time + timedelta(days=config.holding_days)
    exit_time = future_closes[-1][0]
    exit_value = spread.net_debit
    exit_reason = "time stop at final bar"

    for timestamp, close in future_closes[1:]:
        intrinsic = _intrinsic_spread_value(close, spread)
        unrealized = (intrinsic - spread.net_debit) * CONTRACT_MULTIPLIER * config.quantity - fees
        if unrealized >= profit_target:
            exit_time = timestamp
            exit_value = intrinsic
            exit_reason = "profit capture threshold reached"
            break
        if unrealized <= stop_loss:
            exit_time = timestamp
            exit_value = intrinsic
            exit_reason = "stop loss threshold reached"
            break
        if timestamp >= holding_limit:
            exit_time = timestamp
            exit_value = intrinsic
            exit_reason = "maximum holding period reached"
            break

    pnl = (exit_value - spread.net_debit) * CONTRACT_MULTIPLIER * config.quantity - fees
    return SimulatedTrade(
        symbol=features.symbol,
        direction=direction,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_debit=spread.net_debit,
        exit_value=_quantize_money(exit_value),
        pnl=_quantize_money(pnl),
        max_loss=max_loss,
        exit_reason=exit_reason,
        filled=True,
    )


def simulate_underlying_trade(
    features: FeatureSnapshot,
    *,
    direction: Direction,
    future_closes: list[tuple[datetime, Decimal]],
    assumptions: FillAssumptions = FillAssumptions(),
) -> SimulatedTrade:
    """Simulate an underlying-only baseline position."""

    if direction is Direction.PASS:
        raise ValueError("PASS direction cannot create a simulated trade")
    if len(future_closes) < 2:
        raise ValueError("at least two prices are required")

    entry_time, entry_price = future_closes[0]
    exit_time, exit_price = future_closes[-1]
    sign = Decimal("1") if direction is Direction.BULLISH else Decimal("-1")
    slippage = entry_price * assumptions.slippage_fraction
    effective_entry = entry_price + slippage if sign > 0 else entry_price - slippage
    effective_exit = exit_price - slippage if sign > 0 else exit_price + slippage
    pnl = (effective_exit - effective_entry) * sign - assumptions.fee_per_contract
    return SimulatedTrade(
        symbol=features.symbol,
        direction=direction,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_debit=effective_entry,
        exit_value=effective_exit,
        pnl=_quantize_money(pnl),
        max_loss=abs(pnl),
        exit_reason="underlying baseline hold",
        filled=True,
    )
