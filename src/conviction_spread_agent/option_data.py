"""Typed normalization for Alpaca option contract and snapshot payloads."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .domain import OptionLeg, OptionRight, Quote
from .spreads import OptionCandidate


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("quote timestamp must be an ISO string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("quote timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _required_mapping(payload: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = payload.get(name)
        if isinstance(value, dict):
            return value
    raise ValueError(f"response must contain one of: {', '.join(names)}")


def _first_value(payload: dict[str, Any], *names: str) -> object:
    for name in names:
        if name in payload:
            return payload[name]
    raise ValueError(f"response is missing required field: {' or '.join(names)}")


def _optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"{field} cannot be negative")
    return parsed


def parse_alpaca_option_candidate(
    contract: dict[str, Any], snapshot: dict[str, Any]
) -> OptionCandidate:
    """Normalize one explicitly tradable contract and its latest snapshot.

    Alpaca contract metadata is snake_case while market-data containers may be
    camelCase or snake_case depending on whether raw JSON or SDK records are used.
    Both validated shapes are accepted. Missing bid/ask/timestamp fields fail closed.
    """

    if contract.get("tradable") is not True:
        raise ValueError("option contract must be explicitly tradable")
    symbol = str(_first_value(contract, "symbol")).strip().upper()
    underlying = str(
        _first_value(contract, "underlying_symbol", "underlying")
    ).strip().upper()
    if not symbol or not underlying:
        raise ValueError("option symbol and underlying are required")

    try:
        right = OptionRight(str(_first_value(contract, "type", "right")).lower())
    except ValueError as exc:
        raise ValueError("option type must be call or put") from exc
    try:
        expiration = date.fromisoformat(
            str(_first_value(contract, "expiration_date", "expiration"))
        )
    except ValueError as exc:
        raise ValueError("option expiration must be an ISO date") from exc

    quote_payload = _required_mapping(snapshot, "latestQuote", "latest_quote")
    quote = Quote(
        bid=_parse_decimal(
            _first_value(quote_payload, "bp", "bid_price", "bid"), field="bid"
        ),
        ask=_parse_decimal(
            _first_value(quote_payload, "ap", "ask_price", "ask"), field="ask"
        ),
        observed_at=_parse_timestamp(
            _first_value(quote_payload, "t", "timestamp", "observed_at")
        ),
    )

    greeks = snapshot.get("greeks")
    delta: Decimal | None = None
    if isinstance(greeks, dict) and greeks.get("delta") is not None:
        delta = _parse_decimal(greeks["delta"], field="delta")

    daily_bar = snapshot.get("dailyBar", snapshot.get("daily_bar"))
    volume: int | None = None
    if isinstance(daily_bar, dict):
        volume = _optional_int(daily_bar.get("v", daily_bar.get("volume")), field="volume")

    return OptionCandidate(
        leg=OptionLeg(
            symbol=symbol,
            underlying=underlying,
            right=right,
            expiration=expiration,
            strike=_parse_decimal(
                _first_value(contract, "strike_price", "strike"), field="strike"
            ),
            quote=quote,
        ),
        delta=delta,
        open_interest=_optional_int(contract.get("open_interest"), field="open interest"),
        volume=volume,
    )
