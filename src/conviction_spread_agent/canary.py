"""Pure preparation of an exact, risk-assessed one-contract paper canary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .domain import Direction, OptionLeg, OptionRight, Quote, Thesis, VerticalSpread
from .orders import MlegOrderIntent, OrderPurpose, build_mleg_order_intent
from .phase4_risk import ExecutionRiskContext, assess_phase4_trade
from .reconciliation import CanaryBrokerState
from .risk import PortfolioState, RiskDecision


def _mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _strings(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    parsed = tuple(item.strip() for item in value)
    if not parsed or any(not item for item in parsed):
        raise ValueError(f"{field} cannot be empty")
    return parsed


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not numeric") from exc


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} is not a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _quote(value: object, *, field: str) -> Quote:
    payload = _mapping(value, field=field)
    return Quote(
        bid=_decimal(payload.get("bid"), field=f"{field} bid"),
        ask=_decimal(payload.get("ask"), field=f"{field} ask"),
        observed_at=_timestamp(
            payload.get("observed_at"), field=f"{field} observed_at"
        ),
    )


def _thesis(record: dict[str, Any]) -> Thesis:
    agent = _mapping(record.get("agent"), field="agent")
    proposal = _mapping(agent.get("proposal"), field="agent proposal")
    critic = _mapping(agent.get("critic"), field="agent critic")
    features = _mapping(record.get("features"), field="features")
    created_at = _timestamp(record.get("generated_at"), field="generated_at")
    try:
        direction = Direction(str(agent.get("final_direction", "")).lower())
    except ValueError as exc:
        raise ValueError("final direction is unsupported") from exc
    counter_evidence = _strings(
        proposal.get("counter_evidence"), field="proposal counter_evidence"
    ) + tuple(
        f"critic: {reason}"
        for reason in _strings(critic.get("reasons"), field="critic reasons")
    )
    return Thesis(
        thesis_id=str(record.get("decision_id", "")).strip(),
        underlying=str(features.get("symbol", "")).strip().upper(),
        direction=direction,
        confidence=_decimal(agent.get("final_confidence"), field="final confidence"),
        summary=str(proposal.get("summary", "")).strip(),
        evidence=_strings(proposal.get("evidence"), field="proposal evidence"),
        counter_evidence=counter_evidence,
        invalidation=str(proposal.get("invalidation", "")).strip(),
        created_at=created_at,
        valid_until=_timestamp(agent.get("valid_until"), field="valid_until"),
    )


def _spread(record: dict[str, Any], thesis: Thesis) -> VerticalSpread | None:
    selection = _mapping(record.get("selection"), field="selection")
    if not bool(selection.get("selected")):
        return None
    payload = _mapping(selection.get("spread"), field="selected spread")
    right = OptionRight.CALL if thesis.direction is Direction.BULLISH else OptionRight.PUT
    expiration = date.fromisoformat(str(payload.get("expiration", "")))
    long_quote = _quote(payload.get("long_quote"), field="long quote")
    short_quote = _quote(payload.get("short_quote"), field="short quote")
    spread = VerticalSpread(
        long_leg=OptionLeg(
            symbol=str(payload.get("long_symbol", "")).strip().upper(),
            underlying=thesis.underlying,
            right=right,
            expiration=expiration,
            strike=_decimal(payload.get("long_strike"), field="long strike"),
            quote=long_quote,
        ),
        short_leg=OptionLeg(
            symbol=str(payload.get("short_symbol", "")).strip().upper(),
            underlying=thesis.underlying,
            right=right,
            expiration=expiration,
            strike=_decimal(payload.get("short_strike"), field="short strike"),
            quote=short_quote,
        ),
        net_debit=_decimal(
            payload.get("conservative_net_debit"), field="conservative net debit"
        ),
        quantity=int(payload.get("quantity", 0)),
    )
    if spread.net_debit != spread.long_leg.quote.ask - spread.short_leg.quote.bid:
        raise ValueError("selected spread debit does not match its executable quotes")
    if spread.direction is not thesis.direction:
        raise ValueError("selected spread direction does not match the final thesis")
    return spread


@dataclass(frozen=True)
class CanaryPreparation:
    record: dict[str, object]
    thesis: Thesis
    spread: VerticalSpread | None
    intent: MlegOrderIntent | None
    risk: RiskDecision | None

    @property
    def ready(self) -> bool:
        return self.intent is not None and self.risk is not None and self.risk.approved


def prepare_canary(
    shadow_record: dict[str, Any],
    broker: CanaryBrokerState,
    *,
    prepared_at: datetime,
    minutes_since_market_open: int | None,
    minutes_until_market_close: int | None,
) -> CanaryPreparation:
    """Build the exact order preview and final deterministic risk decision."""

    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("canary preparation time must be timezone-aware")
    thesis = _thesis(shadow_record)
    spread = _spread(shadow_record, thesis)
    blocking_reasons: list[str] = list(broker.reasons)
    if spread is None:
        selection = _mapping(shadow_record.get("selection"), field="selection")
        raw_reasons = selection.get("rejection_reasons", [])
        if isinstance(raw_reasons, list):
            blocking_reasons.extend(str(reason) for reason in raw_reasons)
        blocking_reasons.append("shadow decision did not select an executable spread")

    intent: MlegOrderIntent | None = None
    risk: RiskDecision | None = None
    if spread is not None:
        intent = build_mleg_order_intent(
            thesis_id=thesis.thesis_id,
            spread=spread,
            purpose=OrderPurpose.ENTRY,
            limit_price=spread.net_debit,
            created_at=prepared_at,
        )
        if intent.limit_price != spread.net_debit:
            spread = VerticalSpread(
                long_leg=spread.long_leg,
                short_leg=spread.short_leg,
                net_debit=intent.limit_price,
                quantity=spread.quantity,
            )
            intent = build_mleg_order_intent(
                thesis_id=thesis.thesis_id,
                spread=spread,
                purpose=OrderPurpose.ENTRY,
                limit_price=spread.net_debit,
                created_at=prepared_at,
            )
        if broker.equity is None or broker.previous_equity is None:
            raise ValueError("reconciled equity observations are required")
        daily_pnl = broker.equity - broker.previous_equity
        portfolio = PortfolioState(
            equity=broker.equity,
            start_of_day_equity=broker.previous_equity,
            start_of_week_equity=broker.previous_equity,
            realized_daily_pnl=daily_pnl,
            realized_weekly_pnl=daily_pnl,
            current_open_risk=Decimal("0"),
            open_positions=broker.open_position_count,
            market_open=bool(
                _mapping(shadow_record.get("data"), field="data").get("market_open")
            ),
            data_healthy=bool(
                _mapping(shadow_record.get("data"), field="data").get("data_healthy")
            ),
            broker_reconciled=broker.reconciled,
            execution_enabled=True,
            dry_run=False,
            kill_switch=False,
        )
        risk = assess_phase4_trade(
            thesis,
            spread,
            ExecutionRiskContext(
                portfolio=portfolio,
                options_buying_power=broker.options_buying_power,
                minutes_since_market_open=minutes_since_market_open,
                minutes_until_market_close=minutes_until_market_close,
                decision_id=thesis.thesis_id,
            ),
            market_date=prepared_at.date(),
            as_of=prepared_at,
        )
        blocking_reasons.extend(risk.reasons)

    unique_reasons = tuple(dict.fromkeys(blocking_reasons))
    order_record: dict[str, object] | None = None
    if intent is not None and spread is not None:
        order_record = {
            "client_order_id": intent.client_order_id,
            "payload_sha256": intent.payload_sha256,
            "order_class": "mleg",
            "structure": (
                "bull_call_debit_spread"
                if spread.direction is Direction.BULLISH
                else "bear_put_debit_spread"
            ),
            "direction": spread.direction.value,
            "quantity": spread.quantity,
            "limit_debit": str(intent.limit_price),
            "maximum_loss": str(spread.max_loss),
            "maximum_profit": str(spread.max_profit),
            "breakeven": str(spread.breakeven),
            "expiration": spread.long_leg.expiration.isoformat(),
            "legs": [
                {
                    "action": "buy_to_open",
                    "symbol": spread.long_leg.symbol,
                    "strike": str(spread.long_leg.strike),
                    "bid": str(spread.long_leg.quote.bid),
                    "ask": str(spread.long_leg.quote.ask),
                },
                {
                    "action": "sell_to_open",
                    "symbol": spread.short_leg.symbol,
                    "strike": str(spread.short_leg.strike),
                    "bid": str(spread.short_leg.quote.bid),
                    "ask": str(spread.short_leg.quote.ask),
                },
            ],
            "alpaca_payload": intent.as_alpaca_payload(),
        }

    ready = intent is not None and risk is not None and risk.approved
    public_record: dict[str, object] = {
        "schema_version": "phase-7b.canary-preview.v1",
        "mode": "paper-canary-preview",
        "prepared_at": prepared_at.isoformat(),
        "decision_id": thesis.thesis_id,
        "ready_for_operator_approval": ready,
        "blocking_reasons": list(unique_reasons),
        "broker_reconciliation": broker.public_record(),
        "agent": {
            "final_direction": thesis.direction.value,
            "final_confidence": str(thesis.confidence),
            "summary": thesis.summary,
            "invalidation": thesis.invalidation,
            "valid_until": thesis.valid_until.isoformat(),
        },
        "order": order_record,
        "risk": (
            {
                "approved": risk.approved,
                "reasons": list(risk.reasons),
                "maximum_allowed_quantity": risk.maximum_allowed_quantity,
                "assessed_at": risk.assessed_at.isoformat(),
            }
            if risk is not None
            else None
        ),
        "safety": {
            "paper_only": True,
            "preview_only": True,
            "broker_write_performed": False,
            "operator_confirmation_required": True,
            "one_contract_limit": True,
            "account_identifier_emitted": False,
        },
    }
    return CanaryPreparation(
        record=public_record,
        thesis=thesis,
        spread=spread,
        intent=intent,
        risk=risk,
    )
