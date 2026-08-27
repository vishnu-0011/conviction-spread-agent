"""Immutable daily bar records used by the feature and simulation layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("bar symbol is required")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must be timezone-aware")
        for label, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            if value <= 0:
                raise ValueError(f"{label} must be positive")
        if self.high < self.low:
            raise ValueError("high cannot be below low")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("open/close must lie within the bar range")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")


@dataclass(frozen=True)
class BarSeries:
    """Chronologically sorted bars for one symbol."""

    symbol: str
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("series symbol is required")
        if not self.bars:
            raise ValueError("bar series cannot be empty")
        if any(bar.symbol != self.symbol for bar in self.bars):
            raise ValueError("all bars must match the series symbol")
        timestamps = [bar.timestamp for bar in self.bars]
        if timestamps != sorted(timestamps):
            raise ValueError("bars must be sorted by timestamp")

    def through(self, as_of: datetime) -> BarSeries:
        """Return bars whose timestamp is less than or equal to as_of."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        filtered = tuple(bar for bar in self.bars if bar.timestamp <= as_of)
        if not filtered:
            raise ValueError("no bars available at or before as_of")
        return BarSeries(symbol=self.symbol, bars=filtered)
