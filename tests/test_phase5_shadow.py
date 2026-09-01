from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
import unittest
from unittest.mock import patch

from conviction_spread_agent.agent import (
    AgentProposal,
    AgentSchemaError,
    CriticAction,
    CriticVerdict,
    finalize_thesis,
)
from conviction_spread_agent.alpaca_readonly import AlpacaReadOnlyClient
from conviction_spread_agent.domain import Direction, OptionLeg, OptionRight, Quote
from conviction_spread_agent.features.engine import FeatureSnapshot, MarketRegime
from conviction_spread_agent.shadow import ShadowBrokerContext, build_shadow_decision
from conviction_spread_agent.spreads import OptionCandidate


NOW = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)
EXPIRATION = date(2026, 9, 18)


def feature_snapshot(*, regime: MarketRegime = MarketRegime.BULL) -> FeatureSnapshot:
    trend_fast = Decimal("0.02") if regime is MarketRegime.BULL else Decimal("0")
    trend_slow = Decimal("0.01") if regime is MarketRegime.BULL else Decimal("0")
    return FeatureSnapshot(
        symbol="SPY",
        as_of=NOW,
        feature_set_version="test-v1",
        trend_fast=trend_fast,
        trend_slow=trend_slow,
        realized_vol=Decimal("0.02"),
        relative_volume=Decimal("1.10"),
        atr=Decimal("5"),
        relative_strength=Decimal("0"),
        regime=regime,
        source_bar_timestamps=(NOW,),
    )


def candidate(
    symbol: str,
    strike: str,
    *,
    bid: str,
    ask: str,
    delta: str,
) -> OptionCandidate:
    return OptionCandidate(
        leg=OptionLeg(
            symbol=symbol,
            underlying="SPY",
            right=OptionRight.CALL,
            expiration=EXPIRATION,
            strike=Decimal(strike),
            quote=Quote(Decimal(bid), Decimal(ask), NOW),
        ),
        delta=Decimal(delta),
        open_interest=100,
        volume=25,
    )


def candidates() -> tuple[OptionCandidate, ...]:
    return (
        candidate("SPY260918C00600000", "600", bid="4.90", ask="5.00", delta="0.60"),
        candidate("SPY260918C00605000", "605", bid="2.00", ask="2.10", delta="0.32"),
    )


def broker_context() -> ShadowBrokerContext:
    return ShadowBrokerContext(
        equity=Decimal("100000"),
        options_buying_power=Decimal("100000"),
        market_open=True,
        minutes_since_market_open=60,
        minutes_until_market_close=180,
        data_healthy=True,
    )


def valid_proposal_payload() -> dict[str, object]:
    return {
        "direction": "bullish",
        "confidence": "0.82",
        "summary": "Trend and volume are aligned.",
        "evidence": ["fast and slow trends are positive"],
        "counter_evidence": ["realized volatility remains material"],
        "invalidation": "SPY closes below 595.",
        "valid_for_minutes": 30,
    }


class AgentContractTests(unittest.TestCase):
    def test_proposal_requires_exact_keys(self) -> None:
        payload = valid_proposal_payload()
        payload["free_form_order"] = "buy anything"
        with self.assertRaisesRegex(AgentSchemaError, "extra"):
            AgentProposal.from_mapping(payload)

    def test_proposal_rejects_coerced_types(self) -> None:
        payload = valid_proposal_payload()
        payload["evidence"] = [123]
        with self.assertRaisesRegex(AgentSchemaError, "JSON strings"):
            AgentProposal.from_mapping(payload)

        payload = valid_proposal_payload()
        payload["valid_for_minutes"] = 30.5
        with self.assertRaisesRegex(AgentSchemaError, "JSON integer"):
            AgentProposal.from_mapping(payload)

    def test_critic_rejection_has_final_authority(self) -> None:
        proposal = AgentProposal.from_mapping(valid_proposal_payload())
        critic = CriticVerdict.from_mapping(
            {
                "action": "reject",
                "reasons": ["contradictory regime evidence"],
                "confidence_cap": 0,
            }
        )
        thesis = finalize_thesis(
            proposal,
            critic,
            thesis_id="strict-contract-test",
            underlying="SPY",
            created_at=NOW,
        )
        self.assertEqual(thesis.direction, Direction.PASS)
        self.assertEqual(thesis.confidence, Decimal("0"))

    def test_approve_cannot_smuggle_a_confidence_override(self) -> None:
        with self.assertRaisesRegex(AgentSchemaError, "approve cannot"):
            CriticVerdict(
                action=CriticAction.APPROVE,
                reasons=("looks acceptable",),
                confidence_cap=Decimal("1"),
            )


class ReadOnlyClientTests(unittest.TestCase):
    def test_network_method_is_fixed_to_get(self) -> None:
        response = BytesIO(b'{"status":"ACTIVE"}')
        with patch(
            "conviction_spread_agent.alpaca_readonly.urlopen", return_value=response
        ) as mocked:
            result = AlpacaReadOnlyClient("key", "secret").account()
        request = mocked.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(result["status"], "ACTIVE")

    def test_public_surface_has_no_broker_write_operations(self) -> None:
        public_methods = {
            name for name in dir(AlpacaReadOnlyClient) if not name.startswith("_")
        }
        write_terms = ("order", "submit", "cancel", "replace", "exercise", "close")
        self.assertFalse(
            any(term in method for method in public_methods for term in write_terms)
        )


class ShadowDecisionTests(unittest.TestCase):
    def test_live_candidate_is_always_blocked_and_emits_no_order(self) -> None:
        result = build_shadow_decision(
            feature_snapshot(),
            underlying_price=Decimal("602"),
            candidates=candidates(),
            broker=broker_context(),
            generated_at=NOW,
            stock_feed="iex",
            option_feed="indicative",
        )
        self.assertEqual(result["outcome"], "candidate_blocked")
        self.assertTrue(result["selection"]["selected"])
        self.assertFalse(result["risk"]["approved"])
        self.assertIn("execution is disabled", result["risk"]["reasons"])
        self.assertIn("dry-run mode cannot submit orders", result["risk"]["reasons"])
        self.assertFalse(result["safety"]["broker_writes_possible"])
        self.assertFalse(result["safety"]["order_payload_emitted"])
        self.assertNotIn("account", result)
        self.assertNotIn("equity", str(result["data"]))

    def test_decision_id_is_stable_under_candidate_reordering(self) -> None:
        common = {
            "underlying_price": Decimal("602"),
            "broker": broker_context(),
            "generated_at": NOW,
            "stock_feed": "iex",
            "option_feed": "indicative",
        }
        first = build_shadow_decision(
            feature_snapshot(), candidates=candidates(), **common
        )
        second = build_shadow_decision(
            feature_snapshot(), candidates=tuple(reversed(candidates())), **common
        )
        self.assertEqual(first["decision_id"], second["decision_id"])
        self.assertEqual(first["selection"]["spread"], second["selection"]["spread"])

    def test_neutral_regime_passes_without_a_spread(self) -> None:
        result = build_shadow_decision(
            feature_snapshot(regime=MarketRegime.NEUTRAL),
            underlying_price=Decimal("602"),
            candidates=(),
            broker=broker_context(),
            generated_at=NOW,
            stock_feed="iex",
            option_feed="indicative",
        )
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["agent"]["final_direction"], "pass")
        self.assertFalse(result["selection"]["selected"])
        self.assertIsNone(result["risk"])


if __name__ == "__main__":
    unittest.main()
