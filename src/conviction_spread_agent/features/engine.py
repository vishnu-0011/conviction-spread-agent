"""Deterministic, look-ahead-free feature computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import math

from ..data.bars import BarSeries


FEATURE_SET_VERSION = "2026.08.24.v1"


class MarketRegime(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class FeatureConfig:
    fast_trend_bars: int = 5
    slow_trend_bars: int = 20
    realized_vol_bars: int = 20
    relative_volume_bars: int = 20
    atr_bars: int = 14
    benchmark_symbol: str = "SPY"

    def __post_init__(self) -> None:
        for name in (
            "fast_trend_bars",
            "slow_trend_bars",
            "realized_vol_bars",
            "relative_volume_bars",
            "atr_bars",
        ):
            value = getattr(self, name)
            if value <= 1:
                raise ValueError(f"{name} must be greater than 1")
        if not self.benchmark_symbol.strip():
            raise ValueError("benchmark_symbol is required")


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    as_of: datetime
    feature_set_version: str
    trend_fast: Decimal
    trend_slow: Decimal
    realized_vol: Decimal
    relative_volume: Decimal
    atr: Decimal
    relative_strength: Decimal
    regime: MarketRegime
    source_bar_timestamps: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not self.source_bar_timestamps:
            raise ValueError("source bar timestamps are required")
        if self.realized_vol < 0 or self.relative_volume < 0 or self.atr < 0:
            raise ValueError("non-negative features required for vol, volume, and ATR")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _returns(closes: list[Decimal]) -> list[Decimal]:
    return [(closes[index] / closes[index - 1]) - Decimal("1") for index in range(1, len(closes))]


def _trend_return(closes: list[Decimal], window: int) -> Decimal:
    start = closes[-window - 1]
    end = closes[-1]
    return _quantize((end / start) - Decimal("1"))


def _realized_vol(returns: list[Decimal], window: int) -> Decimal:
    sample = returns[-window:]
    if len(sample) < window:
        raise ValueError("insufficient returns for realized volatility")
    mean = sum(sample) / Decimal(len(sample))
    variance = sum((value - mean) ** 2 for value in sample) / Decimal(len(sample))
    return _quantize(Decimal(str(math.sqrt(float(variance)))))


def _average_true_range(bars: tuple, window: int) -> Decimal:
    if len(bars) < window + 1:
        raise ValueError("insufficient bars for ATR")
    true_ranges: list[Decimal] = []
    for index in range(-window, 0):
        current = bars[index]
        previous_close = bars[index - 1].close
        tr = max(
            current.high - current.low,
            abs(current.high - previous_close),
            abs(current.low - previous_close),
        )
        true_ranges.append(tr)
    return _quantize(sum(true_ranges) / Decimal(len(true_ranges)))


def _classify_regime(trend_fast: Decimal, trend_slow: Decimal) -> MarketRegime:
    if trend_fast > 0 and trend_slow > 0:
        return MarketRegime.BULL
    if trend_fast < 0 and trend_slow < 0:
        return MarketRegime.BEAR
    return MarketRegime.NEUTRAL


def compute_features(
    symbol_series: BarSeries,
    *,
    benchmark_series: BarSeries | None = None,
    as_of: datetime | None = None,
    config: FeatureConfig = FeatureConfig(),
) -> FeatureSnapshot:
    """Compute features using only bars available at ``as_of``."""

    as_of_time = as_of or symbol_series.bars[-1].timestamp
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    visible = symbol_series.through(as_of_time)
    minimum_bars = max(
        config.slow_trend_bars,
        config.realized_vol_bars,
        config.relative_volume_bars,
        config.atr_bars,
    ) + 1
    if len(visible.bars) < minimum_bars:
        raise ValueError("insufficient history for feature computation")

    closes = [bar.close for bar in visible.bars]
    returns = _returns(closes)
    trend_fast = _trend_return(closes, config.fast_trend_bars)
    trend_slow = _trend_return(closes, config.slow_trend_bars)
    realized_vol = _realized_vol(returns, config.realized_vol_bars)
    recent_volume = visible.bars[-1].volume
    average_volume = sum(bar.volume for bar in visible.bars[-config.relative_volume_bars :]) / (
        config.relative_volume_bars
    )
    relative_volume = _quantize(Decimal(recent_volume) / Decimal(average_volume))
    atr = _average_true_range(visible.bars, config.atr_bars)

    relative_strength = Decimal("0")
    if benchmark_series is not None:
        benchmark_visible = benchmark_series.through(as_of_time)
        benchmark_closes = [bar.close for bar in benchmark_visible.bars]
        if len(benchmark_closes) >= config.fast_trend_bars + 1:
            symbol_return = _trend_return(closes, config.fast_trend_bars)
            benchmark_return = _trend_return(benchmark_closes, config.fast_trend_bars)
            relative_strength = _quantize(symbol_return - benchmark_return)

    regime = _classify_regime(trend_fast, trend_slow)
    return FeatureSnapshot(
        symbol=visible.symbol,
        as_of=as_of_time,
        feature_set_version=FEATURE_SET_VERSION,
        trend_fast=trend_fast,
        trend_slow=trend_slow,
        realized_vol=realized_vol,
        relative_volume=relative_volume,
        atr=atr,
        relative_strength=relative_strength,
        regime=regime,
        source_bar_timestamps=tuple(bar.timestamp for bar in visible.bars),
    )
