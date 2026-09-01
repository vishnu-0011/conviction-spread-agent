"""Pure orchestration for a sanitized, non-executable shadow decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

from .agent import (
    deterministic_shadow_critic,
    deterministic_shadow_proposal,
    finalize_thesis,
)
from .domain import Direction, VerticalSpread
from .features.engine import FeatureSnapshot
from .phase4_risk import ExecutionRiskContext, assess_phase4_trade
from .risk import PortfolioState
from .spreads import OptionCandidate, SpreadConstructionResult, construct_vertical_spread


SHADOW_MODE = "paper-shadow-read-only"
SHADOW_PROVIDER = "deterministic-shadow-v1"


@dataclass(frozen=True)
class ShadowBrokerContext:
    """Minimum broker observations used for a deliberately blocked risk preview."""

    equity: Decimal | None
    options_buying_power: Decimal | None
    market_open: bool
    minutes_since_market_open: int | None
    minutes_until_market_close: int | None
    data_healthy: bool

    def __post_init__(self) -> None:
        for value, name in (
            (self.equity, "equity"),
            (self.options_buying_power, "options buying power"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


def _candidate_identity(candidate: OptionCandidate) -> dict[str, object]:
    return {
        "symbol": candidate.leg.symbol,
        "expiration": candidate.leg.expiration.isoformat(),
        "strike": str(candidate.leg.strike),
        "right": candidate.leg.right.value,
        "bid": str(candidate.leg.quote.bid),
        "ask": str(candidate.leg.quote.ask),
        "quote_at": candidate.leg.quote.observed_at.isoformat(),
        "delta": str(candidate.delta) if candidate.delta is not None else None,
    }


def _decision_id(
    features: FeatureSnapshot,
    *,
    underlying_price: Decimal,
    proposal: dict[str, Any],
    critic: dict[str, Any],
    candidates: tuple[OptionCandidate, ...],
) -> str:
    identity = {
        "feature_set": features.feature_set_version,
        "feature_as_of": features.as_of.isoformat(),
        "symbol": features.symbol,
        "underlying_price": str(underlying_price),
        "proposal": proposal,
        "critic": critic,
        "candidates": sorted(
            (_candidate_identity(candidate) for candidate in candidates),
            key=lambda item: str(item["symbol"]),
        ),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return f"shadow-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _feature_record(features: FeatureSnapshot) -> dict[str, object]:
    return {
        "symbol": features.symbol,
        "as_of": features.as_of.isoformat(),
        "feature_set_version": features.feature_set_version,
        "regime": features.regime.value,
        "trend_fast": str(features.trend_fast),
        "trend_slow": str(features.trend_slow),
        "realized_vol": str(features.realized_vol),
        "relative_volume": str(features.relative_volume),
        "atr": str(features.atr),
        "relative_strength": str(features.relative_strength),
        "source_bar_count": len(features.source_bar_timestamps),
        "source_bar_first": features.source_bar_timestamps[0].isoformat(),
        "source_bar_last": features.source_bar_timestamps[-1].isoformat(),
    }


def _spread_record(spread: VerticalSpread) -> dict[str, object]:
    return {
        "structure": "bull_call_debit_spread"
        if spread.direction is Direction.BULLISH
        else "bear_put_debit_spread",
        "long_symbol": spread.long_leg.symbol,
        "short_symbol": spread.short_leg.symbol,
        "expiration": spread.long_leg.expiration.isoformat(),
        "long_strike": str(spread.long_leg.strike),
        "short_strike": str(spread.short_leg.strike),
        "quantity": spread.quantity,
        "conservative_net_debit": str(spread.net_debit),
        "width": str(spread.width),
        "maximum_loss": str(spread.max_loss),
        "maximum_profit": str(spread.max_profit),
        "breakeven": str(spread.breakeven),
    }


def _selection_record(result: SpreadConstructionResult) -> dict[str, object]:
    return {
        "selected": result.selected,
        "method": result.method.value if result.method is not None else None,
        "candidates_considered": result.candidates_considered,
        "eligible_contracts": result.eligible_contracts,
        "pairs_considered": result.pairs_considered,
        "selection_score": str(result.selection_score)
        if result.selection_score is not None
        else None,
        "rejection_reasons": list(result.rejection_reasons),
        "spread": _spread_record(result.spread) if result.spread is not None else None,
    }


def build_shadow_decision(
    features: FeatureSnapshot,
    *,
    underlying_price: Decimal,
    candidates: tuple[OptionCandidate, ...],
    broker: ShadowBrokerContext,
    generated_at: datetime,
    market_date: date | None = None,
    stock_feed: str,
    option_feed: str,
) -> dict[str, object]:
    """Build one public-safe shadow record; no order intent is ever constructed."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("shadow generation time must be timezone-aware")
    if underlying_price <= 0:
        raise ValueError("underlying price must be positive")

    decision_market_date = market_date or generated_at.date()
    proposal = deterministic_shadow_proposal(
        features, underlying_price=underlying_price
    )
    critic = deterministic_shadow_critic(proposal, features)
    decision_id = _decision_id(
        features,
        underlying_price=underlying_price,
        proposal=proposal.as_mapping(),
        critic=critic.as_mapping(),
        candidates=candidates,
    )
    thesis = finalize_thesis(
        proposal,
        critic,
        thesis_id=decision_id,
        underlying=features.symbol,
        created_at=generated_at,
    )
    selection = construct_vertical_spread(
        underlying=features.symbol,
        direction=thesis.direction,
        underlying_price=underlying_price,
        candidates=candidates,
        market_date=decision_market_date,
        as_of=generated_at,
    )

    risk_record: dict[str, object] | None = None
    outcome = "pass" if thesis.direction is Direction.PASS else "no_eligible_spread"
    if selection.spread is not None:
        equity = broker.equity if broker.equity is not None else Decimal("0")
        portfolio = PortfolioState(
            equity=equity,
            start_of_day_equity=equity,
            start_of_week_equity=equity,
            realized_daily_pnl=Decimal("0"),
            realized_weekly_pnl=Decimal("0"),
            current_open_risk=Decimal("0"),
            open_positions=0,
            market_open=broker.market_open,
            data_healthy=broker.data_healthy,
            broker_reconciled=False,
            execution_enabled=False,
            dry_run=True,
            kill_switch=False,
        )
        risk = assess_phase4_trade(
            thesis,
            selection.spread,
            ExecutionRiskContext(
                portfolio=portfolio,
                options_buying_power=broker.options_buying_power,
                minutes_since_market_open=broker.minutes_since_market_open,
                minutes_until_market_close=broker.minutes_until_market_close,
                decision_id=decision_id,
            ),
            market_date=decision_market_date,
            as_of=generated_at,
        )
        if risk.approved:
            raise RuntimeError("shadow risk unexpectedly approved an executable decision")
        risk_record = {
            "approved": False,
            "maximum_allowed_quantity": risk.maximum_allowed_quantity,
            "reasons": list(risk.reasons),
            "assessed_at": risk.assessed_at.isoformat(),
        }
        outcome = "candidate_blocked"

    return {
        "schema_version": "phase-5a.shadow.v1",
        "mode": SHADOW_MODE,
        "generated_at": generated_at.isoformat(),
        "decision_id": decision_id,
        "outcome": outcome,
        "data": {
            "stock_feed": stock_feed,
            "option_feed": option_feed,
            "underlying_price": str(underlying_price),
            "candidate_count": len(candidates),
            "market_open": broker.market_open,
            "data_healthy": broker.data_healthy,
        },
        "features": _feature_record(features),
        "agent": {
            "provider": SHADOW_PROVIDER,
            "provider_role": "transparent test double; external AI adapter pending",
            "proposal": proposal.as_mapping(),
            "critic": critic.as_mapping(),
            "final_direction": thesis.direction.value,
            "final_confidence": str(thesis.confidence),
            "valid_until": thesis.valid_until.isoformat(),
        },
        "selection": _selection_record(selection),
        "risk": risk_record,
        "safety": {
            "paper_only": True,
            "read_only_client": True,
            "broker_writes_possible": False,
            "execution_enabled": False,
            "dry_run": True,
            "broker_reconciled": False,
            "order_payload_emitted": False,
            "account_identifier_emitted": False,
            "equity_value_emitted": False,
            "equity_available_for_internal_sizing": broker.equity is not None,
            "options_buying_power_available": broker.options_buying_power is not None,
        },
    }
