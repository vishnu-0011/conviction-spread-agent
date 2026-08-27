"""Run walk-forward simulation on fixture or Alpaca historical bars."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from conviction_spread_agent.data.adapters import parse_alpaca_bars
from conviction_spread_agent.data.bars import BarSeries
from conviction_spread_agent.simulation.walkforward import WalkForwardConfig, run_walk_forward


DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "spy_daily_bars.json"


def load_fixture(path: Path) -> BarSeries:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bars = parse_alpaca_bars("SPY", payload)
    return BarSeries(symbol="SPY", bars=bars)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ConvictionSpread walk-forward simulation.")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to an Alpaca-shaped daily bars JSON fixture.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the JSON result summary.",
    )
    args = parser.parse_args(argv)

    if not args.fixture.exists():
        print(f"fixture not found: {args.fixture}", file=sys.stderr)
        return 2

    series = load_fixture(args.fixture)
    result = run_walk_forward(series, walk_config=WalkForwardConfig())
    rendered = json.dumps(result.as_dict(), indent=2)

    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
