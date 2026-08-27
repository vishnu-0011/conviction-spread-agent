"""Walk-forward evaluation with held-out test windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from ..data.bars import BarSeries
from ..domain import Direction
from ..features.engine import FeatureConfig, FeatureSnapshot, compute_features
from .baselines import (
    BaselineKind,
    BaselineSignal,
    buy_and_hold_signal,
    conviction_signal,
    momentum_signal,
    random_direction_signal,
)
from .fills import FillAssumptions
from .metrics import PerformanceMetrics, compute_metrics
from .spread_model import (
    SimulatedTrade,
    SpreadSimulationConfig,
    simulate_spread_trade,
    simulate_underlying_trade,
)


SignalFn = Callable[[FeatureSnapshot], BaselineSignal]


@dataclass(frozen=True)
class WalkForwardConfig:
    warmup_bars: int = 25
    step_bars: int = 5
    horizon_bars: int = 10
    train_fraction: Decimal = Decimal("0.60")
    validation_fraction: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        if self.warmup_bars <= 1 or self.step_bars <= 0 or self.horizon_bars <= 0:
            raise ValueError("warmup, step, and horizon must be positive")
        total = self.train_fraction + self.validation_fraction
        if total <= 0 or total >= 1:
            raise ValueError("train and validation fractions must sum to less than 1")


@dataclass(frozen=True)
class StrategyResult:
    name: str
    kind: BaselineKind | str
    train_metrics: PerformanceMetrics
    validation_metrics: PerformanceMetrics
    test_metrics: PerformanceMetrics
    trades: tuple[SimulatedTrade, ...]


@dataclass(frozen=True)
class WalkForwardResult:
    symbol: str
    fold_boundaries: tuple[tuple[str, str], ...]
    strategies: tuple[StrategyResult, ...]
    beats_baselines: bool
    label: str

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "fold_boundaries": self.fold_boundaries,
            "beats_baselines": self.beats_baselines,
            "label": self.label,
            "strategies": [
                {
                    "name": strategy.name,
                    "kind": str(strategy.kind),
                    "train": strategy.train_metrics.as_dict(),
                    "validation": strategy.validation_metrics.as_dict(),
                    "test": strategy.test_metrics.as_dict(),
                }
                for strategy in self.strategies
            ],
        }


def _future_closes(series: BarSeries, start_index: int, horizon: int) -> list[tuple[datetime, Decimal]]:
    window = series.bars[start_index : start_index + horizon + 1]
    if len(window) < 2:
        return []
    return [(bar.timestamp, bar.close) for bar in window]


def _evaluate_signal_fn(
    *,
    name: str,
    kind: BaselineKind | str,
    signal_fn: SignalFn,
    series: BarSeries,
    benchmark: BarSeries | None,
    indices: range,
    config: WalkForwardConfig,
    feature_config: FeatureConfig,
    spread_config: SpreadSimulationConfig,
    assumptions: FillAssumptions,
    use_spreads: bool,
) -> StrategyResult:
    trades: list[SimulatedTrade] = []
    for index in indices:
        as_of = series.bars[index].timestamp
        try:
            features = compute_features(
                series.through(as_of),
                benchmark_series=benchmark,
                as_of=as_of,
                config=feature_config,
            )
        except ValueError:
            continue
        signal = signal_fn(features)
        future = _future_closes(series, index, config.horizon_bars)
        if not future or signal.direction is Direction.PASS:
            continue
        if use_spreads:
            trades.append(
                simulate_spread_trade(
                    features,
                    direction=signal.direction,
                    future_closes=future,
                    assumptions=assumptions,
                    config=spread_config,
                )
            )
        else:
            trades.append(
                simulate_underlying_trade(
                    features,
                    direction=signal.direction,
                    future_closes=future,
                    assumptions=assumptions,
                )
            )

    trade_tuple = tuple(trades)
    train_end = int(len(series.bars) * float(config.train_fraction))
    validation_end = train_end + int(len(series.bars) * float(config.validation_fraction))

    # Split by entry index for reproducibility.
    indexed_trades: list[tuple[int, SimulatedTrade]] = []
    timestamp_to_index = {bar.timestamp: index for index, bar in enumerate(series.bars)}
    for trade in trade_tuple:
        indexed_trades.append((timestamp_to_index[trade.entry_time], trade))

    def metrics_for_range(start: int, end: int) -> PerformanceMetrics:
        subset = tuple(trade for index, trade in indexed_trades if start <= index < end)
        return compute_metrics(subset)

    return StrategyResult(
        name=name,
        kind=kind,
        train_metrics=metrics_for_range(0, train_end),
        validation_metrics=metrics_for_range(train_end, validation_end),
        test_metrics=metrics_for_range(validation_end, len(series.bars)),
        trades=trade_tuple,
    )


def run_walk_forward(
    series: BarSeries,
    *,
    benchmark: BarSeries | None = None,
    walk_config: WalkForwardConfig = WalkForwardConfig(),
    feature_config: FeatureConfig = FeatureConfig(),
    spread_config: SpreadSimulationConfig = SpreadSimulationConfig(),
    assumptions: FillAssumptions = FillAssumptions(),
) -> WalkForwardResult:
    if len(series.bars) < walk_config.warmup_bars + walk_config.horizon_bars + 5:
        raise ValueError("insufficient bars for walk-forward simulation")

    start_index = walk_config.warmup_bars
    end_index = len(series.bars) - walk_config.horizon_bars
    indices = range(start_index, end_index, walk_config.step_bars)

    train_end = int(len(series.bars) * float(walk_config.train_fraction))
    validation_end = train_end + int(len(series.bars) * float(walk_config.validation_fraction))
    fold_boundaries = (
        ("train", f"0-{train_end}"),
        ("validation", f"{train_end}-{validation_end}"),
        ("test", f"{validation_end}-{len(series.bars)}"),
    )

    strategies = (
        _evaluate_signal_fn(
            name="buy_and_hold",
            kind=BaselineKind.BUY_AND_HOLD,
            signal_fn=lambda features: buy_and_hold_signal(as_of=features.as_of),
            series=series,
            benchmark=benchmark,
            indices=indices,
            config=walk_config,
            feature_config=feature_config,
            spread_config=spread_config,
            assumptions=assumptions,
            use_spreads=False,
        ),
        _evaluate_signal_fn(
            name="random_direction",
            kind=BaselineKind.RANDOM_DIRECTION,
            signal_fn=lambda features: random_direction_signal(as_of=features.as_of),
            series=series,
            benchmark=benchmark,
            indices=indices,
            config=walk_config,
            feature_config=feature_config,
            spread_config=spread_config,
            assumptions=assumptions,
            use_spreads=False,
        ),
        _evaluate_signal_fn(
            name="momentum_underlying",
            kind=BaselineKind.MOMENTUM,
            signal_fn=momentum_signal,
            series=series,
            benchmark=benchmark,
            indices=indices,
            config=walk_config,
            feature_config=feature_config,
            spread_config=spread_config,
            assumptions=assumptions,
            use_spreads=False,
        ),
        _evaluate_signal_fn(
            name="conviction_spread",
            kind="agent_spread",
            signal_fn=conviction_signal,
            series=series,
            benchmark=benchmark,
            indices=indices,
            config=walk_config,
            feature_config=feature_config,
            spread_config=spread_config,
            assumptions=assumptions,
            use_spreads=True,
        ),
    )

    agent = next(strategy for strategy in strategies if strategy.name == "conviction_spread")
    baselines = tuple(strategy for strategy in strategies if strategy.name != "conviction_spread")
    beats = all(
        agent.test_metrics.pnl_per_unit_risk >= baseline.test_metrics.pnl_per_unit_risk
        for baseline in baselines
    )
    label = "validated" if beats else "experimental"
    return WalkForwardResult(
        symbol=series.symbol,
        fold_boundaries=fold_boundaries,
        strategies=strategies,
        beats_baselines=beats,
        label=label,
    )
