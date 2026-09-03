"""Sanitized, reproducible performance reporting from Alpaca paper state."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _string(value: object) -> str | None:
    parsed = str(value).strip() if value is not None else ""
    return parsed or None


def _public_leg(leg: dict[str, Any]) -> dict[str, object]:
    return {
        "symbol": _string(leg.get("symbol")),
        "side": _string(leg.get("side")),
        "position_intent": _string(leg.get("position_intent")),
        "status": _string(leg.get("status")),
        "qty": _string(leg.get("qty")),
        "filled_qty": _string(leg.get("filled_qty")),
        "filled_avg_price": _string(leg.get("filled_avg_price")),
    }


def _public_order(order: dict[str, Any]) -> dict[str, object]:
    broker_id = _string(order.get("id"))
    legs = order.get("legs")
    public_legs = legs if isinstance(legs, list) else []
    return {
        "client_order_id": _string(order.get("client_order_id")),
        "broker_order_fingerprint": (
            hashlib.sha256(broker_id.encode("utf-8")).hexdigest()[:12]
            if broker_id
            else None
        ),
        "status": _string(order.get("status")),
        "order_class": _string(order.get("order_class")),
        "type": _string(order.get("type")),
        "time_in_force": _string(order.get("time_in_force")),
        "qty": _string(order.get("qty")),
        "filled_qty": _string(order.get("filled_qty")),
        "limit_price": _string(order.get("limit_price")),
        "filled_avg_price": _string(order.get("filled_avg_price")),
        "submitted_at": _string(order.get("submitted_at")),
        "filled_at": _string(order.get("filled_at")),
        "canceled_at": _string(order.get("canceled_at")),
        "expired_at": _string(order.get("expired_at")),
        "legs": [
            _public_leg(leg)
            for leg in public_legs
            if isinstance(leg, dict)
        ],
    }


def _public_position(position: dict[str, Any]) -> dict[str, object]:
    return {
        "symbol": _string(position.get("symbol")),
        "asset_class": _string(position.get("asset_class")),
        "qty": _string(position.get("qty")),
        "side": _string(position.get("side")),
        "avg_entry_price": _string(position.get("avg_entry_price")),
        "current_price": _string(position.get("current_price")),
        "market_value": _string(position.get("market_value")),
        "cost_basis": _string(position.get("cost_basis")),
        "unrealized_pl": _string(position.get("unrealized_pl")),
        "unrealized_plpc": _string(position.get("unrealized_plpc")),
    }


def _history_points(history: dict[str, Any]) -> list[dict[str, object]]:
    timestamps = history.get("timestamp")
    equities = history.get("equity")
    pnl = history.get("profit_loss")
    pnl_pct = history.get("profit_loss_pct")
    if not all(isinstance(items, list) for items in (timestamps, equities, pnl, pnl_pct)):
        return []
    length = min(len(timestamps), len(equities), len(pnl), len(pnl_pct))
    return [
        {
            "timestamp": timestamps[index],
            "equity": equities[index],
            "profit_loss": pnl[index],
            "profit_loss_pct": pnl_pct[index],
        }
        for index in range(max(0, length - 100), length)
    ]


def build_paper_performance_report(
    *,
    account: dict[str, Any],
    positions: tuple[dict[str, Any], ...],
    orders: tuple[dict[str, Any], ...],
    history: dict[str, Any],
    generated_at: datetime,
    requested_client_order_id: str | None = None,
) -> dict[str, object]:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("performance timestamp must be timezone-aware")
    raw_account_id = _string(account.get("id"))
    account_fingerprint = (
        hashlib.sha256(raw_account_id.encode("utf-8")).hexdigest()[:12]
        if raw_account_id
        else None
    )
    equity = _decimal(account.get("equity"))
    previous_equity = _decimal(account.get("last_equity"))
    day_pnl = (
        equity - previous_equity
        if equity is not None and previous_equity not in {None, Decimal("0")}
        else None
    )
    day_return = (
        day_pnl / previous_equity
        if day_pnl is not None and previous_equity not in {None, Decimal("0")}
        else None
    )

    strategy_orders = tuple(
        order
        for order in orders
        if str(order.get("client_order_id", "")).startswith("csa-")
    )
    if requested_client_order_id is not None:
        strategy_orders = tuple(
            order
            for order in strategy_orders
            if str(order.get("client_order_id", "")) == requested_client_order_id
        )
    statuses = Counter(
        str(order.get("status", "unknown")).strip().lower() or "unknown"
        for order in strategy_orders
    )
    total_unrealized = sum(
        (_decimal(position.get("unrealized_pl")) or Decimal("0"))
        for position in positions
    )
    filled = statuses.get("filled", 0)
    terminal = (
        filled
        + statuses.get("canceled", 0)
        + statuses.get("expired", 0)
        + statuses.get("rejected", 0)
    )
    fill_rate = Decimal(filled) / Decimal(terminal) if terminal else None

    return {
        "schema_version": "phase-7c.paper-performance.v1",
        "mode": "paper-read-only",
        "generated_at": generated_at.isoformat(),
        "account": {
            "account_fingerprint": account_fingerprint,
            "account_identifier_emitted": False,
            "status": _string(account.get("status")),
            "equity": str(equity) if equity is not None else None,
            "previous_equity": (
                str(previous_equity) if previous_equity is not None else None
            ),
            "day_pnl": str(day_pnl) if day_pnl is not None else None,
            "day_return": str(day_return) if day_return is not None else None,
        },
        "strategy_orders": {
            "requested_client_order_id": requested_client_order_id,
            "count": len(strategy_orders),
            "status_counts": dict(sorted(statuses.items())),
            "terminal_fill_rate": str(fill_rate) if fill_rate is not None else None,
            "items": [_public_order(order) for order in strategy_orders],
        },
        "positions": {
            "count": len(positions),
            "total_unrealized_pnl": str(total_unrealized),
            "items": [_public_position(position) for position in positions],
        },
        "portfolio_history": {
            "base_value": history.get("base_value"),
            "base_value_asof": history.get("base_value_asof"),
            "timeframe": history.get("timeframe"),
            "points": _history_points(history),
        },
        "interpretation": {
            "broker_confirmed_only": True,
            "paper_trading_only": True,
            "sample_size_warning": (
                "A small live paper sample demonstrates execution, not durable "
                "profitability or future performance."
            ),
        },
        "safety": {
            "get_requests_only": True,
            "broker_write_performed": False,
            "credentials_emitted": False,
            "account_identifier_emitted": False,
        },
    }
