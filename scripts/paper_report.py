"""Create a sanitized, GET-only Alpaca paper performance report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from conviction_spread_agent.performance import build_paper_performance_report
from conviction_spread_agent.reconciliation import (
    AlpacaPaperStateClient,
    AlpacaReconciliationError,
)
from shadow_scan import load_local_env


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AFTER = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _aware_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must use ISO 8601, for example 2026-08-28T00:00:00+00:00"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def _emit(record: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(record, indent=2, sort_keys=True)
    print(rendered)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read Alpaca paper account state and create a sanitized performance "
            "report. This command issues GET requests only."
        )
    )
    parser.add_argument("--after", type=_aware_timestamp, default=DEFAULT_AFTER)
    parser.add_argument("--period", default="1D")
    parser.add_argument("--timeframe", default="5Min")
    parser.add_argument("--client-order-id", default=None)
    parser.add_argument("--output", type=Path, default=None)
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
        client = AlpacaPaperStateClient(api_key, secret_key)
        orders = client.orders(status="all", after=args.after)
        requested_client_order_id = (
            args.client_order_id.strip() if args.client_order_id else None
        )
        if requested_client_order_id:
            exact = client.order_by_client_order_id(requested_client_order_id)
            if exact is not None and not any(
                item.get("id") == exact.get("id") for item in orders
            ):
                orders = (*orders, exact)
        record = build_paper_performance_report(
            account=client.account(),
            positions=client.positions(),
            orders=orders,
            history=client.portfolio_history(
                period=args.period.strip(), timeframe=args.timeframe.strip()
            ),
            generated_at=datetime.now(timezone.utc),
            requested_client_order_id=requested_client_order_id,
        )
        _emit(record, args.output)
        return 0
    except (AlpacaReconciliationError, ValueError) as exc:
        print(f"paper report failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
