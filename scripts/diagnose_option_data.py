"""Read-only diagnostic for an empty Alpaca option-snapshot response."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any

from preflight import (
    MARKET_DATA_HOST,
    PAPER_API_HOST,
    ApiError,
    _extract_contracts,
    _extract_snapshots,
    _get_json,
    _spot_price,
    load_local_env,
)


def _mapping_count(payload: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return len(value)
    return 0


def diagnose(api_key: str, secret_key: str, underlying: str) -> dict[str, Any]:
    clock, _ = _get_json(PAPER_API_HOST, "/v2/clock", api_key=api_key, secret_key=secret_key)
    stock_snapshot, _ = _get_json(
        MARKET_DATA_HOST,
        f"/v2/stocks/{underlying}/snapshot",
        api_key=api_key,
        secret_key=secret_key,
        query={"feed": "iex"},
    )
    spot = _spot_price(stock_snapshot)
    if spot is None:
        raise ApiError("Could not derive a positive underlying price from the IEX snapshot")

    broker_date = date.fromisoformat(str(clock["timestamp"])[:10])
    start = broker_date + timedelta(days=14)
    end = broker_date + timedelta(days=35)
    lower = (spot * Decimal("0.95")).quantize(Decimal("0.01"))
    upper = (spot * Decimal("1.05")).quantize(Decimal("0.01"))
    contracts_payload, _ = _get_json(
        PAPER_API_HOST,
        "/v2/options/contracts",
        api_key=api_key,
        secret_key=secret_key,
        query={
            "underlying_symbols": underlying,
            "status": "active",
            "expiration_date_gte": start.isoformat(),
            "expiration_date_lte": end.isoformat(),
            "strike_price_gte": str(lower),
            "strike_price_lte": str(upper),
            "limit": "100",
        },
    )
    contracts = [item for item in _extract_contracts(contracts_payload) if item.get("tradable")]
    contracts.sort(
        key=lambda item: abs(
            (Decimal(str(item.get("strike_price", "0"))) if item.get("strike_price") else Decimal("0"))
            - spot
        )
    )
    symbols = [str(item["symbol"]) for item in contracts[:20] if item.get("symbol")]

    selected_payload: dict[str, Any] = {}
    quotes_payload: dict[str, Any] = {}
    if symbols:
        selected_payload, _ = _get_json(
            MARKET_DATA_HOST,
            "/v1beta1/options/snapshots",
            api_key=api_key,
            secret_key=secret_key,
            query={"symbols": ",".join(symbols), "feed": "indicative"},
        )
        quotes_payload, _ = _get_json(
            MARKET_DATA_HOST,
            "/v1beta1/options/quotes/latest",
            api_key=api_key,
            secret_key=secret_key,
            query={"symbols": ",".join(symbols), "feed": "indicative"},
        )

    chain_payload, _ = _get_json(
        MARKET_DATA_HOST,
        f"/v1beta1/options/snapshots/{underlying}",
        api_key=api_key,
        secret_key=secret_key,
        query={
            "feed": "indicative",
            "strike_price_gte": str(lower),
            "strike_price_lte": str(upper),
            "expiration_date_gte": start.isoformat(),
            "expiration_date_lte": end.isoformat(),
            "limit": "1000",
        },
    )

    selected = _extract_snapshots(selected_payload)
    chain = _extract_snapshots(chain_payload)
    return {
        "mode": "paper-read-only",
        "underlying": underlying,
        "broker_timestamp": clock.get("timestamp"),
        "market_open": clock.get("is_open"),
        "underlying_price": str(spot),
        "strike_window": {"from": str(lower), "to": str(upper)},
        "expiration_window": {"from": start.isoformat(), "to": end.isoformat()},
        "near_money_contracts_found": len(contracts),
        "symbols_requested": len(symbols),
        "selected_snapshots_returned": len(selected),
        "latest_quotes_returned": _mapping_count(quotes_payload, "quotes"),
        "chain_snapshots_returned": len(chain),
        "selected_with_quote": sum(
            bool(item.get("latestQuote", item.get("latest_quote"))) for item in selected.values()
        ),
        "selected_with_greeks": sum(bool(item.get("greeks")) for item in selected.values()),
        "selected_with_iv": sum(
            item.get("impliedVolatility", item.get("implied_volatility")) is not None
            for item in selected.values()
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="SPY")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args(argv or sys.argv[1:])
    load_local_env(args.env_file)
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        print("Refusing to run: ALPACA_PAPER must be explicitly true.", file=sys.stderr)
        return 2
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        print("Missing local paper credentials.", file=sys.stderr)
        return 2
    try:
        result = diagnose(api_key, secret_key, args.underlying.strip().upper())
    except ApiError as exc:
        print(f"Diagnostic failed safely: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
