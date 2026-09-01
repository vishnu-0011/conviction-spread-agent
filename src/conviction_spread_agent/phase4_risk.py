"""Phase 4 risk gates layered on the existing broker-independent policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR

from .domain import Thesis, VerticalSpread
from .risk import PortfolioState, RiskDecision, RiskLimits, assess_trade


@dataclass(frozen=True)
class ExecutionRiskContext:
    """Inputs required only at the final order-admission boundary."""

    portfolio: PortfolioState
    options_buying_power: Decimal | None
    minutes_since_market_open: int | None
    minutes_until_market_close: int | None
    decision_id: str
    processed_decision_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.options_buying_power is not None and self.options_buying_power < 0:
            raise ValueError("options buying power cannot be negative")
        for value, field in (
            (self.minutes_since_market_open, "minutes since market open"),
            (self.minutes_until_market_close, "minutes until market close"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{field} cannot be negative")


@dataclass(frozen=True)
class Phase4RiskLimits:
    base: RiskLimits = RiskLimits()
    minimum_minutes_after_open: int = 15
    minimum_minutes_before_close: int = 30

    def __post_init__(self) -> None:
        if self.minimum_minutes_after_open < 0 or self.minimum_minutes_before_close < 0:
            raise ValueError("session timing limits cannot be negative")


def _floor_contracts(amount: Decimal, loss_per_contract: Decimal) -> int:
    if amount <= 0 or loss_per_contract <= 0:
        return 0
    return int((amount / loss_per_contract).to_integral_value(rounding=ROUND_FLOOR))


def assess_phase4_trade(
    thesis: Thesis,
    spread: VerticalSpread,
    context: ExecutionRiskContext,
    limits: Phase4RiskLimits = Phase4RiskLimits(),
    *,
    market_date: date,
    as_of: datetime | None = None,
) -> RiskDecision:
    """Apply account, session, idempotency, and buying-power checks.

    The existing risk policy remains authoritative. This layer can only add rejection
    reasons or reduce the allowable quantity; it can never override a base rejection.
    """

    base_decision = assess_trade(
        thesis,
        spread,
        context.portfolio,
        limits.base,
        market_date=market_date,
        as_of=as_of,
    )
    reasons = list(base_decision.reasons)

    decision_id = context.decision_id.strip()
    if not decision_id:
        reasons.append("decision id is required")
    elif decision_id in context.processed_decision_ids:
        reasons.append("decision id has already been processed")

    if context.minutes_since_market_open is None:
        reasons.append("minutes since market open are unavailable")
    elif context.minutes_since_market_open < limits.minimum_minutes_after_open:
        reasons.append("entry is blocked during the opening window")

    if context.minutes_until_market_close is None:
        reasons.append("minutes until market close are unavailable")
    elif context.minutes_until_market_close < limits.minimum_minutes_before_close:
        reasons.append("entry is blocked near market close")

    per_contract_loss = spread.max_loss / spread.quantity
    if context.options_buying_power is None:
        buying_power_quantity = 0
        reasons.append("options buying power is unavailable")
    else:
        buying_power_quantity = _floor_contracts(
            context.options_buying_power, per_contract_loss
        )
        if buying_power_quantity <= 0:
            reasons.append("options buying power cannot support one contract")

    maximum_allowed_quantity = min(
        base_decision.maximum_allowed_quantity, buying_power_quantity
    )
    if buying_power_quantity > 0 and spread.quantity > buying_power_quantity:
        reasons.append("proposed quantity exceeds options buying power")

    return RiskDecision(
        approved=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        maximum_allowed_quantity=maximum_allowed_quantity,
        assessed_at=base_decision.assessed_at,
    )
