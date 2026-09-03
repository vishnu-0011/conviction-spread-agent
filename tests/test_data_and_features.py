import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from conviction_spread_agent.data.adapters import (
    parse_alpaca_bar,
    parse_alpaca_bars,
    parse_alpaca_bars_before,
)
from conviction_spread_agent.data.bars import Bar, BarSeries
from conviction_spread_agent.features.engine import FeatureConfig, MarketRegime, compute_features


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "spy_daily_bars.json"


def _bar(day: int, close: str, *, volume: int = 50_000_000) -> Bar:
    timestamp = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc) + timedelta(days=day)
    price = Decimal(close)
    return Bar(
        symbol="SPY",
        timestamp=timestamp,
        open=price - Decimal("1"),
        high=price + Decimal("1"),
        low=price - Decimal("2"),
        close=price,
        volume=volume,
    )


def _series(count: int = 30, *, start: str = "500") -> BarSeries:
    start_price = Decimal(start)
    bars = []
    for index in range(count):
        close = start_price + Decimal(index) * Decimal("0.8")
        bars.append(_bar(index, str(close)))
    return BarSeries(symbol="SPY", bars=tuple(bars))


class BarAdapterTests(unittest.TestCase):
    def test_parse_alpaca_bar(self) -> None:
        bar = parse_alpaca_bar(
            "spy",
            {"t": "2026-04-01T20:00:00Z", "o": 520, "h": 522, "l": 519, "c": 521.5, "v": 1000},
        )
        self.assertEqual(bar.symbol, "SPY")
        self.assertEqual(bar.close, Decimal("521.5"))

    def test_parse_fixture_file(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        bars = parse_alpaca_bars("SPY", payload)
        self.assertGreaterEqual(len(bars), 90)
        self.assertLess(bars[0].timestamp, bars[-1].timestamp)

    def test_completed_bar_cutoff_excludes_the_in_progress_boundary_bar(self) -> None:
        cutoff = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
        payload = {
            "bars": [
                {"t": "2026-09-02T04:00:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 1000},
                {"t": "2026-09-03T04:00:00Z", "o": 101, "h": 103, "l": 100, "c": 102, "v": 200},
            ]
        }

        bars = parse_alpaca_bars_before("SPY", payload, before=cutoff)

        self.assertEqual(len(bars), 1)
        self.assertEqual(
            bars[0].timestamp,
            datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc),
        )


class FeatureEngineTests(unittest.TestCase):
    def test_replay_is_deterministic(self) -> None:
        series = _series(35)
        first = compute_features(series)
        second = compute_features(series)
        self.assertEqual(first, second)

    def test_no_look_ahead(self) -> None:
        series = _series(35)
        cutoff = series.bars[20].timestamp
        features = compute_features(series, as_of=cutoff)
        self.assertEqual(features.as_of, cutoff)
        self.assertEqual(features.source_bar_timestamps[-1], cutoff)

    def test_bull_regime_on_uptrend(self) -> None:
        features = compute_features(_series(35))
        self.assertEqual(features.regime, MarketRegime.BULL)
        self.assertGreater(features.trend_fast, 0)
        self.assertGreater(features.trend_slow, 0)

    def test_insufficient_history_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "insufficient history"):
            compute_features(_series(10), config=FeatureConfig())


class BarSeriesTests(unittest.TestCase):
    def test_rejects_unsorted_bars(self) -> None:
        first = _bar(0, "500")
        second = _bar(1, "501")
        with self.assertRaisesRegex(ValueError, "sorted"):
            BarSeries(symbol="SPY", bars=(second, first))


if __name__ == "__main__":
    unittest.main()
