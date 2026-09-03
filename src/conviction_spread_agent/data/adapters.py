"""Convert provider bar payloads into internal immutable records."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .bars import Bar


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    else:
        raise ValueError("bar timestamp must be an ISO string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def parse_alpaca_bar(symbol: str, payload: dict[str, Any]) -> Bar:
    """Parse one Alpaca historical or latest bar object."""

    if not symbol.strip():
        raise ValueError("symbol is required")
    timestamp = _parse_timestamp(payload["t"])
    return Bar(
        symbol=symbol.strip().upper(),
        timestamp=timestamp,
        open=_parse_decimal(payload["o"], field="open"),
        high=_parse_decimal(payload["h"], field="high"),
        low=_parse_decimal(payload["l"], field="low"),
        close=_parse_decimal(payload["c"], field="close"),
        volume=int(payload["v"]),
    )


def parse_alpaca_bars(symbol: str, payload: dict[str, Any]) -> tuple[Bar, ...]:
    """Parse an Alpaca bars response containing a ``bars`` list."""

    raw_bars = payload.get("bars")
    if not isinstance(raw_bars, list) or not raw_bars:
        raise ValueError("bars response must contain a non-empty list")
    parsed = tuple(parse_alpaca_bar(symbol, item) for item in raw_bars)
    return tuple(sorted(parsed, key=lambda bar: bar.timestamp))


def parse_alpaca_bars_before(
    symbol: str, payload: dict[str, Any], *, before: datetime
) -> tuple[Bar, ...]:
    """Parse bars and exclude the boundary/current still-forming period."""

    if before.tzinfo is None or before.utcoffset() is None:
        raise ValueError("bar cutoff must be timezone-aware")
    bars = tuple(
        bar for bar in parse_alpaca_bars(symbol, payload) if bar.timestamp < before
    )
    if not bars:
        raise ValueError("no completed bars are available before the cutoff")
    return bars
