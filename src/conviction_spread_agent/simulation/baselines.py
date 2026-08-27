"""Simple baseline signal generators for walk-forward comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import random

from ..domain import Direction
from ..features.engine import FeatureSnapshot, MarketRegime


class BaselineKind(StrEnum):
    BUY_AND_HOLD = "buy_and_hold"
    RANDOM_DIRECTION = "random_direction"
    MOMENTUM = "momentum"


@dataclass(frozen=True)
class BaselineSignal:
    kind: BaselineKind
    direction: Direction
    confidence: Decimal
    reason: str


def buy_and_hold_signal(*, as_of: datetime) -> BaselineSignal:
    return BaselineSignal(
        kind=BaselineKind.BUY_AND_HOLD,
        direction=Direction.BULLISH,
        confidence=Decimal("1.0"),
        reason=f"always long from {as_of.date().isoformat()}",
    )


def momentum_signal(
    features: FeatureSnapshot,
    *,
    threshold: Decimal = Decimal("0.01"),
) -> BaselineSignal:
    if features.trend_fast >= threshold and features.trend_slow >= 0:
        direction = Direction.BULLISH
        reason = "fast and slow momentum aligned bullish"
    elif features.trend_fast <= -threshold and features.trend_slow <= 0:
        direction = Direction.BEARISH
        reason = "fast and slow momentum aligned bearish"
    else:
        direction = Direction.PASS
        reason = "momentum below entry threshold"
    confidence = min(Decimal("1"), abs(features.trend_fast) * Decimal("10"))
    return BaselineSignal(
        kind=BaselineKind.MOMENTUM,
        direction=direction,
        confidence=confidence,
        reason=reason,
    )


def random_direction_signal(*, as_of: datetime, seed: str = "conviction-spread") -> BaselineSignal:
    digest = hashlib.sha256(f"{seed}|{as_of.isoformat()}".encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    roll = rng.random()
    if roll < 0.45:
        direction = Direction.BULLISH
        reason = "deterministic pseudo-random bullish draw"
    elif roll < 0.90:
        direction = Direction.BEARISH
        reason = "deterministic pseudo-random bearish draw"
    else:
        direction = Direction.PASS
        reason = "deterministic pseudo-random pass draw"
    return BaselineSignal(
        kind=BaselineKind.RANDOM_DIRECTION,
        direction=direction,
        confidence=Decimal("0.50"),
        reason=reason,
    )


def conviction_signal(
    features: FeatureSnapshot,
    *,
    minimum_confidence: Decimal = Decimal("0.72"),
    minimum_relative_volume: Decimal = Decimal("0.90"),
) -> BaselineSignal:
    """Deterministic agent-style signal derived from trusted features only."""

    if features.regime is MarketRegime.NEUTRAL:
        return BaselineSignal(
            kind=BaselineKind.MOMENTUM,
            direction=Direction.PASS,
            confidence=Decimal("0"),
            reason="neutral regime",
        )
    if features.relative_volume < minimum_relative_volume:
        return BaselineSignal(
            kind=BaselineKind.MOMENTUM,
            direction=Direction.PASS,
            confidence=Decimal("0"),
            reason="relative volume below minimum",
        )

    direction = Direction.BULLISH if features.regime is MarketRegime.BULL else Direction.BEARISH
    alignment = abs(features.trend_fast) + abs(features.trend_slow) + abs(features.relative_strength)
    confidence = min(Decimal("0.95"), Decimal("0.60") + alignment * Decimal("25"))
    if confidence < minimum_confidence:
        return BaselineSignal(
            kind=BaselineKind.MOMENTUM,
            direction=Direction.PASS,
            confidence=confidence,
            reason="confidence below minimum threshold",
        )
    return BaselineSignal(
        kind=BaselineKind.MOMENTUM,
        direction=direction,
        confidence=confidence,
        reason=f"{features.regime.value} regime with aligned features",
    )
