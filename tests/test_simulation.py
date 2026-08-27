import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from conviction_spread_agent.data.adapters import parse_alpaca_bars
from conviction_spread_agent.data.bars import Bar, BarSeries
from conviction_spread_agent.domain import Direction
from conviction_spread_agent.features.engine import compute_features
from conviction_spread_agent.simulation.baselines import (
    buy_and_hold_signal,
    conviction_signal,
    momentum_signal,
    random_direction_signal,
)
from conviction_spread_agent.simulation.fills import FillAssumptions, SpreadFillModel, conservative_debit
from conviction_spread_agent.domain import Quote
from conviction_spread_agent.simulation.metrics import compute_metrics
from conviction_spread_agent.simulation.spread_model import SpreadSimulationConfig, simulate_spread_trade
from conviction_spread_agent.simulation.walkforward import WalkForwardConfig, run_walk_forward


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "spy_daily_bars.json"


def _load_fixture_series() -> BarSeries:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return BarSeries(symbol="SPY", bars=parse_alpaca_bars("SPY", payload))


class FillModelTests(unittest.TestCase):
    def test_conservative_debit_is_worse_than_midpoint(self) -> None:
        now = datetime(2026, 8, 20, tzinfo=timezone.utc)
        debit = SpreadFillModel().entry_debit(
            Quote(Decimal("4.90"), Decimal("5.10"), now),
            Quote(Decimal("2.40"), Decimal("2.60"), now),
        )
        midpoint_debit = Decimal("2.60") - Decimal("2.50")
        self.assertGreater(debit, midpoint_debit)

    def test_standalone_helper_matches_model(self) -> None:
        self.assertEqual(
            conservative_debit(
                Decimal("4.90"),
                Decimal("5.10"),
                Decimal("2.40"),
                Decimal("2.60"),
            ),
            SpreadFillModel().entry_debit(
                Quote(Decimal("4.90"), Decimal("5.10"), datetime(2026, 8, 20, tzinfo=timezone.utc)),
                Quote(Decimal("2.40"), Decimal("2.60"), datetime(2026, 8, 20, tzinfo=timezone.utc)),
            ),
        )


class BaselineTests(unittest.TestCase):
    def test_random_signal_is_deterministic(self) -> None:
        as_of = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
        first = random_direction_signal(as_of=as_of)
        second = random_direction_signal(as_of=as_of)
        self.assertEqual(first, second)

    def test_buy_and_hold_is_always_bullish(self) -> None:
        signal = buy_and_hold_signal(as_of=datetime(2026, 8, 20, tzinfo=timezone.utc))
        self.assertEqual(signal.direction, Direction.BULLISH)


class SimulationTests(unittest.TestCase):
    def test_simulated_spread_trade_has_bounded_loss(self) -> None:
        series = _load_fixture_series()
        features = compute_features(series)
        future = [(bar.timestamp, bar.close) for bar in series.bars[25:36]]
        trade = simulate_spread_trade(
            features,
            direction=Direction.BULLISH,
            future_closes=future,
            assumptions=FillAssumptions(rejection_probability=Decimal("0")),
        )
        self.assertTrue(trade.filled)
        self.assertLessEqual(abs(trade.pnl), trade.max_loss + Decimal("500"))

    def test_metrics_cover_empty_and_filled_trades(self) -> None:
        empty = compute_metrics(())
        self.assertEqual(empty.trade_count, 0)
        series = _load_fixture_series()
        features = compute_features(series)
        future = [(bar.timestamp, bar.close) for bar in series.bars[25:36]]
        trade = simulate_spread_trade(
            features,
            direction=Direction.BULLISH,
            future_closes=future,
            assumptions=FillAssumptions(rejection_probability=Decimal("0")),
        )
        metrics = compute_metrics((trade,))
        self.assertEqual(metrics.filled_count, 1)
        self.assertGreaterEqual(metrics.win_rate, Decimal("0"))

    def test_walk_forward_runs_on_fixture(self) -> None:
        result = run_walk_forward(
            _load_fixture_series(),
            walk_config=WalkForwardConfig(step_bars=3),
        )
        self.assertEqual(result.symbol, "SPY")
        self.assertEqual(len(result.strategies), 4)
        self.assertIn(result.label, {"validated", "experimental"})
        agent = next(item for item in result.strategies if item.name == "conviction_spread")
        self.assertGreater(agent.test_metrics.trade_count, 0)

    def test_conviction_signal_passes_in_neutral_regime(self) -> None:
        bars = []
        price = Decimal("500")
        for index in range(30):
            timestamp = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc) + timedelta(days=index)
            close = price + (Decimal("1") if index % 2 == 0 else Decimal("-1"))
            bars.append(
                Bar(
                    symbol="SPY",
                    timestamp=timestamp,
                    open=close - Decimal("0.5"),
                    high=close + Decimal("0.5"),
                    low=close - Decimal("1"),
                    close=close,
                    volume=50_000_000,
                )
            )
        series = BarSeries(symbol="SPY", bars=tuple(bars))
        features = compute_features(series)
        signal = conviction_signal(features)
        self.assertEqual(signal.direction, Direction.PASS)


if __name__ == "__main__":
    unittest.main()
