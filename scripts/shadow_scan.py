"""Run one authenticated Alpaca paper shadow scan using GET requests only."""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from conviction_spread_agent.agent import (
    CriticAction,
    deterministic_shadow_critic,
    deterministic_shadow_proposal,
)
from conviction_spread_agent.alpaca_readonly import (
    AlpacaReadError,
    AlpacaReadOnlyClient,
)
from conviction_spread_agent.data.adapters import parse_alpaca_bars
from conviction_spread_agent.data.bars import BarSeries
from conviction_spread_agent.domain import Direction
from conviction_spread_agent.features.engine import compute_features
from conviction_spread_agent.option_data import parse_alpaca_option_candidate
from conviction_spread_agent.shadow import ShadowBrokerContext, build_shadow_decision


ROOT = Path(__file__).resolve().parents[1]
NEW_YORK = ZoneInfo("America/New_York")


def load_local_env(path: Path) -> None:
    """Load simple local KEY=VALUE entries without overriding the environment."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("broker clock timestamp is unavailable")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("broker clock timestamp is missing a timezone")
    return parsed.astimezone(timezone.utc)


def _spot_price(snapshot: dict[str, object]) -> Decimal:
    for container_name in (
        "latestTrade",
        "latest_trade",
        "minuteBar",
        "minute_bar",
        "dailyBar",
        "daily_bar",
        "prevDailyBar",
        "prev_daily_bar",
    ):
        container = snapshot.get(container_name)
        if not isinstance(container, dict):
            continue
        for field in ("p", "c", "price", "close"):
            parsed = _decimal(container.get(field))
            if parsed is not None and parsed > 0:
                return parsed
    raise ValueError("stock snapshot did not contain a positive reference price")


def _session_minutes(
    now: datetime, *, market_open: bool
) -> tuple[int | None, int | None]:
    if not market_open:
        return None, None
    local_now = now.astimezone(NEW_YORK)
    session_open = datetime.combine(local_now.date(), time(9, 30), tzinfo=NEW_YORK)
    session_close = datetime.combine(local_now.date(), time(16, 0), tzinfo=NEW_YORK)
    since_open = int((local_now - session_open).total_seconds() // 60)
    until_close = int((session_close - local_now).total_seconds() // 60)
    if since_open < 0 or until_close < 0:
        return None, None
    return since_open, until_close


def _completed_daily_window(now: datetime) -> tuple[datetime, datetime]:
    local_date = now.astimezone(NEW_YORK).date()
    end = datetime.combine(local_date, time.min, tzinfo=NEW_YORK).astimezone(timezone.utc)
    return end - timedelta(days=140), end


def _effective_direction(features, *, spot: Decimal) -> Direction:
    proposal = deterministic_shadow_proposal(features, underlying_price=spot)
    critic = deterministic_shadow_critic(proposal, features)
    if critic.action is CriticAction.REJECT:
        return Direction.PASS
    confidence = proposal.confidence
    if critic.action is CriticAction.DOWNGRADE:
        assert critic.confidence_cap is not None
        confidence = min(confidence, critic.confidence_cap)
    if confidence < Decimal("0.72"):
        return Direction.PASS
    return proposal.direction


def _load_series(
    client: AlpacaReadOnlyClient,
    symbol: str,
    *,
    start: datetime,
    end: datetime,
    feed: str,
) -> BarSeries:
    payload = client.stock_bars(symbol, start=start, end=end, feed=feed)
    bars = parse_alpaca_bars(symbol, payload)
    return BarSeries(symbol=symbol, bars=bars)


def run_live_shadow(
    client: AlpacaReadOnlyClient,
    *,
    underlying: str,
    stock_feed: str,
    option_feed: str,
) -> dict[str, object]:
    account = client.account()
    if str(account.get("status", "")).upper() != "ACTIVE":
        raise ValueError("paper account is not active")
    if bool(account.get("account_blocked")) or bool(account.get("trading_blocked")):
        raise ValueError("paper account is blocked")

    clock = client.clock()
    generated_at = _timestamp(clock.get("timestamp"))
    market_open = bool(clock.get("is_open"))
    minutes_since_open, minutes_until_close = _session_minutes(
        generated_at, market_open=market_open
    )

    start, end = _completed_daily_window(generated_at)
    symbol_series = _load_series(
        client, underlying, start=start, end=end, feed=stock_feed
    )
    benchmark_series = None
    if underlying != "SPY":
        benchmark_series = _load_series(
            client, "SPY", start=start, end=end, feed=stock_feed
        )
    features = compute_features(
        symbol_series,
        benchmark_series=benchmark_series,
        as_of=symbol_series.bars[-1].timestamp,
    )
    spot = _spot_price(client.stock_snapshot(underlying, feed=stock_feed))
    direction = _effective_direction(features, spot=spot)

    candidates = []
    parse_failures = 0
    if direction is not Direction.PASS:
        expiration_from = generated_at.date() + timedelta(days=14)
        expiration_to = generated_at.date() + timedelta(days=35)
        strike_from = spot * Decimal("0.95")
        strike_to = spot * Decimal("1.05")
        right = "call" if direction is Direction.BULLISH else "put"
        contracts = client.option_contracts(
            underlying,
            right=right,
            expiration_from=expiration_from,
            expiration_to=expiration_to,
            strike_from=str(strike_from),
            strike_to=str(strike_to),
        )
        snapshots = client.option_chain(
            underlying,
            right=right,
            expiration_from=expiration_from,
            expiration_to=expiration_to,
            strike_from=str(strike_from),
            strike_to=str(strike_to),
            feed=option_feed,
        )
        for contract in contracts:
            symbol = str(contract.get("symbol", "")).upper()
            snapshot = snapshots.get(symbol)
            if snapshot is None:
                continue
            try:
                candidates.append(parse_alpaca_option_candidate(contract, snapshot))
            except ValueError:
                parse_failures += 1

    data_healthy = bool(symbol_series.bars) and (
        direction is Direction.PASS or bool(candidates)
    )
    result = build_shadow_decision(
        features,
        underlying_price=spot,
        candidates=tuple(candidates),
        broker=ShadowBrokerContext(
            equity=_decimal(account.get("equity")),
            options_buying_power=_decimal(account.get("options_buying_power")),
            market_open=market_open,
            minutes_since_market_open=minutes_since_open,
            minutes_until_market_close=minutes_until_close,
            data_healthy=data_healthy,
        ),
        generated_at=generated_at,
        market_date=generated_at.astimezone(NEW_YORK).date(),
        stock_feed=stock_feed,
        option_feed=option_feed,
    )
    result["data"]["candidate_parse_failures"] = parse_failures
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one GET-only Alpaca paper shadow decision."
    )
    parser.add_argument("--underlying", default="SPY")
    parser.add_argument("--stock-feed", default="iex")
    parser.add_argument("--option-feed", default="indicative")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the sanitized JSON record.",
    )
    args = parser.parse_args(argv)

    load_local_env(ROOT / ".env")
    if os.environ.get("ALPACA_PAPER", "").strip().lower() != "true":
        print("refusing to run: ALPACA_PAPER=true is required", file=sys.stderr)
        return 2
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        print("missing ALPACA_API_KEY or ALPACA_SECRET_KEY", file=sys.stderr)
        return 2

    try:
        result = run_live_shadow(
            AlpacaReadOnlyClient(api_key, secret_key),
            underlying=args.underlying.strip().upper(),
            stock_feed=args.stock_feed.strip().lower(),
            option_feed=args.option_feed.strip().lower(),
        )
    except (AlpacaReadError, ValueError) as exc:
        print(f"shadow scan failed safely: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
