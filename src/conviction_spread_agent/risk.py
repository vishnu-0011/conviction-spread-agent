"""Fail-closed, broker-independent pre-trade risk policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_FLOOR

from .domain import Direction, Thesis, VerticalSpread


@dataclass(frozen=True)
class RiskLimits:
    per_trade_risk_fraction: Decimal = Decimal("0.005")
    aggregate_risk_fraction: Decimal = Decimal("0.02")
    daily_loss_fraction: Decimal = Decimal("0.015")
    weekly_loss_fraction: Decimal = Decimal("0.04")
    minimum_confidence: Decimal = Decimal("0.72")
    maximum_relative_quote_width: Decimal = Decimal("0.15")
    minimum_dte: int = 7
    maximum_dte: int = 45
    maximum_open_positions: int = 3
    maximum_quote_age_seconds: int = 15

    def __post_init__(self) -> None:
        fractions = (
            self.per_trade_risk_fraction,
            self.aggregate_risk_fraction,
            self.daily_loss_fraction,
            self.weekly_loss_fraction,
            self.minimum_confidence,
            self.maximum_relative_quote_width,
        )
        if any(value <= 0 or value > 1 for value in fractions):
            raise ValueError("risk fractions and thresholds must be in (0, 1]")
        if self.per_trade_risk_fraction > self.aggregate_risk_fraction:
            raise ValueError("per-trade risk cannot exceed aggregate risk")
        if self.minimum_dte < 0 or self.maximum_dte < self.minimum_dte:
            raise ValueError("invalid DTE range")
        if self.maximum_open_positions <= 0 or self.maximum_quote_age_seconds <= 0:
            raise ValueError("position and quote-age limits must be positive")


@dataclass(frozen=True)
class PortfolioState:
    equity: Decimal
    start_of_day_equity: Decimal
    start_of_week_equity: Decimal
    realized_daily_pnl: Decimal
    realized_weekly_pnl: Decimal
    current_open_risk: Decimal
    open_positions: int
    market_open: bool
    data_healthy: bool
    broker_reconciled: bool
    execution_enabled: bool
    dry_run: bool
    kill_switch: bool
    active_underlyings: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.current_open_risk < 0:
            raise ValueError("current open risk cannot be negative")
        if self.open_positions < 0:
            raise ValueError("open-position count cannot be negative")


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    maximum_allowed_quantity: int
    assessed_at: datetime


def _floor_contracts(amount: Decimal, loss_per_contract: Decimal) -> int:
    if amount <= 0 or loss_per_contract <= 0:
        return 0
    return int((amount / loss_per_contract).to_integral_value(rounding=ROUND_FLOOR))


def assess_trade(
    thesis: Thesis,
    spread: VerticalSpread,
    portfolio: PortfolioState,
    limits: RiskLimits = RiskLimits(),
    *,
    market_date: date,
    as_of: datetime | None = None,
) -> RiskDecision:
    """Assess a proposed spread. Any failing invariant rejects the order."""

    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("assessment timestamp must be timezone-aware")
    reasons: list[str] = []

    if portfolio.kill_switch:
        reasons.append("kill switch is active")
    if not portfolio.execution_enabled:
        reasons.append("execution is disabled")
    if portfolio.dry_run:
        reasons.append("dry-run mode cannot submit orders")
    if not portfolio.market_open:
        reasons.append("market is closed")
    if not portfolio.data_healthy:
        reasons.append("market data is unhealthy or stale")
    if not portfolio.broker_reconciled:
        reasons.append("local and broker state are not reconciled")
    if portfolio.equity <= 0:
        reasons.append("account equity must be positive")
    if thesis.valid_until <= now:
        reasons.append("thesis has expired")
    if thesis.direction is Direction.PASS:
        reasons.append("a PASS thesis cannot create an order")
    if thesis.direction is not spread.direction:
        reasons.append("thesis direction does not match spread direction")
    if thesis.underlying != spread.long_leg.underlying:
        reasons.append("thesis underlying does not match spread underlying")
    if thesis.confidence < limits.minimum_confidence:
        reasons.append("thesis confidence is below the configured minimum")
    if spread.long_leg.underlying in portfolio.active_underlyings:
        reasons.append("an active position already exists for this underlying")
    if portfolio.open_positions >= limits.maximum_open_positions:
        reasons.append("maximum open-position count has been reached")

    dte = (spread.long_leg.expiration - market_date).days
    if dte < limits.minimum_dte or dte > limits.maximum_dte:
        reasons.append("expiration is outside the permitted DTE range")
    if spread.worst_relative_quote_width > limits.maximum_relative_quote_width:
        reasons.append("an option leg exceeds the quote-width limit")
    for leg in (spread.long_leg, spread.short_leg):
        quote_age = (now - leg.quote.observed_at).total_seconds()
        if quote_age < -5 or quote_age > limits.maximum_quote_age_seconds:
            reasons.append(f"quote for {leg.symbol} is stale or future-dated")

    if portfolio.start_of_day_equity <= 0 or (
        portfolio.realized_daily_pnl
        <= -(portfolio.start_of_day_equity * limits.daily_loss_fraction)
    ):
        reasons.append("daily loss halt is active")
    if portfolio.start_of_week_equity <= 0 or (
        portfolio.realized_weekly_pnl
        <= -(portfolio.start_of_week_equity * limits.weekly_loss_fraction)
    ):
        reasons.append("weekly loss halt is active")

    per_contract_loss = spread.max_loss / spread.quantity
    per_trade_budget = max(Decimal("0"), portfolio.equity * limits.per_trade_risk_fraction)
    aggregate_budget = max(
        Decimal("0"),
        portfolio.equity * limits.aggregate_risk_fraction - portfolio.current_open_risk,
    )
    maximum_allowed_quantity = _floor_contracts(
        min(per_trade_budget, aggregate_budget), per_contract_loss
    )
    if maximum_allowed_quantity <= 0:
        reasons.append("no remaining risk budget for one contract")
    elif spread.quantity > maximum_allowed_quantity:
        reasons.append("proposed quantity exceeds the risk budget")

    return RiskDecision(
        approved=not reasons,
        reasons=tuple(reasons),
        maximum_allowed_quantity=maximum_allowed_quantity,
        assessed_at=now,
    )
