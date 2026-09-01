"""Strict AI thesis and critic contracts with a deterministic shadow provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from .domain import Direction, Thesis
from .features.engine import FeatureSnapshot, MarketRegime
from .simulation.baselines import conviction_signal


class AgentSchemaError(ValueError):
    """Raised when untrusted model output does not match the exact schema."""


class CriticAction(StrEnum):
    APPROVE = "approve"
    DOWNGRADE = "downgrade"
    REJECT = "reject"


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AgentSchemaError(f"{field} must be a decimal-compatible value") from exc


def _strings(value: object, *, field: str, minimum: int = 1, maximum: int = 8) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AgentSchemaError(f"{field} must be a JSON array")
    if any(not isinstance(item, str) for item in value):
        raise AgentSchemaError(f"{field} items must be JSON strings")
    parsed = tuple(item.strip() for item in value)
    if not minimum <= len(parsed) <= maximum or any(not item for item in parsed):
        raise AgentSchemaError(f"{field} must contain {minimum}–{maximum} non-empty items")
    return parsed


def _require_exact_keys(payload: dict[str, Any], expected: frozenset[str], *, name: str) -> None:
    keys = frozenset(payload)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise AgentSchemaError(f"{name} keys mismatch; missing={missing}, extra={extra}")


@dataclass(frozen=True)
class AgentProposal:
    direction: Direction
    confidence: Decimal
    summary: str
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    invalidation: str
    valid_for_minutes: int

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise AgentSchemaError("proposal confidence must be between 0 and 1")
        if not self.summary.strip() or len(self.summary) > 500:
            raise AgentSchemaError("proposal summary must contain 1–500 characters")
        if not self.evidence or any(not item.strip() for item in self.evidence):
            raise AgentSchemaError("proposal evidence is required")
        if not self.counter_evidence or any(not item.strip() for item in self.counter_evidence):
            raise AgentSchemaError("proposal counter-evidence is required")
        if not self.invalidation.strip() or len(self.invalidation) > 500:
            raise AgentSchemaError("proposal invalidation must contain 1–500 characters")
        if not 1 <= self.valid_for_minutes <= 120:
            raise AgentSchemaError("proposal validity must be between 1 and 120 minutes")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> AgentProposal:
        expected = frozenset(
            {
                "direction",
                "confidence",
                "summary",
                "evidence",
                "counter_evidence",
                "invalidation",
                "valid_for_minutes",
            }
        )
        _require_exact_keys(payload, expected, name="proposal")
        try:
            direction = Direction(str(payload["direction"]).lower())
        except ValueError as exc:
            raise AgentSchemaError("proposal direction must be bullish, bearish, or pass") from exc
        if not isinstance(payload["valid_for_minutes"], int) or isinstance(
            payload["valid_for_minutes"], bool
        ):
            raise AgentSchemaError("valid_for_minutes must be a JSON integer")
        if not isinstance(payload["summary"], str) or not isinstance(
            payload["invalidation"], str
        ):
            raise AgentSchemaError("proposal summary and invalidation must be JSON strings")
        valid_for_minutes = payload["valid_for_minutes"]
        return cls(
            direction=direction,
            confidence=_decimal(payload["confidence"], field="confidence"),
            summary=str(payload["summary"]).strip(),
            evidence=_strings(payload["evidence"], field="evidence"),
            counter_evidence=_strings(
                payload["counter_evidence"], field="counter_evidence"
            ),
            invalidation=str(payload["invalidation"]).strip(),
            valid_for_minutes=valid_for_minutes,
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "confidence": str(self.confidence),
            "summary": self.summary,
            "evidence": list(self.evidence),
            "counter_evidence": list(self.counter_evidence),
            "invalidation": self.invalidation,
            "valid_for_minutes": self.valid_for_minutes,
        }


@dataclass(frozen=True)
class CriticVerdict:
    action: CriticAction
    reasons: tuple[str, ...]
    confidence_cap: Decimal | None

    def __post_init__(self) -> None:
        if not self.reasons or any(not item.strip() for item in self.reasons):
            raise AgentSchemaError("critic reasons are required")
        if self.confidence_cap is not None and not Decimal("0") <= self.confidence_cap <= Decimal("1"):
            raise AgentSchemaError("critic confidence cap must be between 0 and 1")
        if self.action is CriticAction.DOWNGRADE and self.confidence_cap is None:
            raise AgentSchemaError("downgrade requires a confidence cap")
        if self.action is CriticAction.APPROVE and self.confidence_cap is not None:
            raise AgentSchemaError("approve cannot include a confidence cap")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> CriticVerdict:
        _require_exact_keys(
            payload,
            frozenset({"action", "reasons", "confidence_cap"}),
            name="critic",
        )
        try:
            action = CriticAction(str(payload["action"]).lower())
        except ValueError as exc:
            raise AgentSchemaError("critic action must be approve, downgrade, or reject") from exc
        cap = payload["confidence_cap"]
        return cls(
            action=action,
            reasons=_strings(payload["reasons"], field="critic reasons"),
            confidence_cap=None if cap is None else _decimal(cap, field="confidence_cap"),
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "reasons": list(self.reasons),
            "confidence_cap": str(self.confidence_cap) if self.confidence_cap is not None else None,
        }


def finalize_thesis(
    proposal: AgentProposal,
    critic: CriticVerdict,
    *,
    thesis_id: str,
    underlying: str,
    created_at: datetime,
    minimum_confidence: Decimal = Decimal("0.72"),
) -> Thesis:
    """Apply critic authority and deterministic confidence gating."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("thesis creation time must be timezone-aware")
    direction = proposal.direction
    confidence = proposal.confidence
    if critic.action is CriticAction.REJECT:
        direction = Direction.PASS
        confidence = Decimal("0")
    elif critic.action is CriticAction.DOWNGRADE:
        assert critic.confidence_cap is not None
        confidence = min(confidence, critic.confidence_cap)
    if confidence < minimum_confidence:
        direction = Direction.PASS

    return Thesis(
        thesis_id=thesis_id,
        underlying=underlying.strip().upper(),
        direction=direction,
        confidence=confidence,
        summary=proposal.summary,
        evidence=proposal.evidence,
        counter_evidence=proposal.counter_evidence
        + tuple(f"critic: {reason}" for reason in critic.reasons),
        invalidation=proposal.invalidation,
        created_at=created_at,
        valid_until=created_at + timedelta(minutes=proposal.valid_for_minutes),
    )


def deterministic_shadow_proposal(
    features: FeatureSnapshot, *, underlying_price: Decimal
) -> AgentProposal:
    """Transparent Phase 5 test double for a future external AI provider."""

    signal = conviction_signal(features)
    if signal.direction is Direction.BULLISH:
        invalidation_price = underlying_price - features.atr
        invalidation = f"Underlying closes below {invalidation_price:.2f}."
    elif signal.direction is Direction.BEARISH:
        invalidation_price = underlying_price + features.atr
        invalidation = f"Underlying closes above {invalidation_price:.2f}."
    else:
        invalidation = "Do not trade until regime and volume gates align."

    return AgentProposal(
        direction=signal.direction,
        confidence=signal.confidence,
        summary=f"{features.symbol} shadow thesis: {signal.reason}.",
        evidence=(
            f"regime={features.regime.value}",
            f"fast_trend={features.trend_fast}",
            f"slow_trend={features.trend_slow}",
            f"relative_volume={features.relative_volume}",
        ),
        counter_evidence=(
            f"realized_vol={features.realized_vol}",
            f"atr={features.atr}",
            f"relative_strength={features.relative_strength}",
        ),
        invalidation=invalidation,
        valid_for_minutes=30,
    )


def deterministic_shadow_critic(
    proposal: AgentProposal, features: FeatureSnapshot
) -> CriticVerdict:
    """Adversarial deterministic critic used until the model adapter is connected."""

    if proposal.direction is Direction.PASS or features.regime is MarketRegime.NEUTRAL:
        return CriticVerdict(
            action=CriticAction.REJECT,
            reasons=("directional regime is not sufficiently aligned",),
            confidence_cap=Decimal("0"),
        )
    if features.relative_volume < Decimal("0.90"):
        return CriticVerdict(
            action=CriticAction.REJECT,
            reasons=("relative volume is below the declared minimum",),
            confidence_cap=Decimal("0"),
        )
    if features.realized_vol > Decimal("0.03"):
        return CriticVerdict(
            action=CriticAction.DOWNGRADE,
            reasons=("realized volatility is elevated",),
            confidence_cap=Decimal("0.75"),
        )
    return CriticVerdict(
        action=CriticAction.APPROVE,
        reasons=("no deterministic contradiction exceeded its rejection threshold",),
        confidence_cap=None,
    )
