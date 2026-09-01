from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from conviction_spread_agent.domain import (
    Direction,
    OptionLeg,
    OptionRight,
    Quote,
    Thesis,
    VerticalSpread,
)
from conviction_spread_agent.lifecycle import (
    BrokerOrderStatus,
    BrokerOrderView,
    InvalidLifecycleTransition,
    LifecycleEvent,
    LifecycleEventType,
    LifecycleSnapshot,
    LifecycleState,
    apply_event,
    assess_entry_reconciliation,
    start_lifecycle,
)
from conviction_spread_agent.option_data import parse_alpaca_option_candidate
from conviction_spread_agent.orders import OrderPurpose, build_mleg_order_intent
from conviction_spread_agent.phase4_risk import (
    ExecutionRiskContext,
    assess_phase4_trade,
)
from conviction_spread_agent.risk import PortfolioState
from conviction_spread_agent.spreads import (
    OptionCandidate,
    SelectionMethod,
    construct_vertical_spread,
)


NOW = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
MARKET_DATE = date(2026, 9, 1)
EXPIRATION = date(2026, 9, 18)


def quote(bid: str, ask: str, *, observed_at: datetime = NOW) -> Quote:
    return Quote(Decimal(bid), Decimal(ask), observed_at)


def candidate(
    symbol: str,
    strike: str,
    *,
    right: OptionRight = OptionRight.CALL,
    bid: str,
    ask: str,
    delta: str | None,
    observed_at: datetime = NOW,
) -> OptionCandidate:
    return OptionCandidate(
        leg=OptionLeg(
            symbol=symbol,
            underlying="SPY",
            right=right,
            expiration=EXPIRATION,
            strike=Decimal(strike),
            quote=quote(bid, ask, observed_at=observed_at),
        ),
        delta=Decimal(delta) if delta is not None else None,
        open_interest=100,
        volume=25,
    )


def bull_candidates() -> tuple[OptionCandidate, ...]:
    return (
        candidate("SPY260918C00600000", "600", bid="4.90", ask="5.00", delta="0.60"),
        candidate("SPY260918C00605000", "605", bid="2.00", ask="2.10", delta="0.32"),
        candidate("SPY260918C00610000", "610", bid="0.95", ask="1.05", delta=None),
    )


def valid_spread(quantity: int = 1) -> VerticalSpread:
    return VerticalSpread(
        long_leg=bull_candidates()[0].leg,
        short_leg=bull_candidates()[1].leg,
        net_debit=Decimal("3.00"),
        quantity=quantity,
    )


def valid_thesis() -> Thesis:
    return Thesis(
        thesis_id="phase4-thesis",
        underlying="SPY",
        direction=Direction.BULLISH,
        confidence=Decimal("0.80"),
        summary="Orderly bullish continuation.",
        evidence=("trend aligned",),
        counter_evidence=("volatility elevated",),
        invalidation="SPY closes below support.",
        created_at=NOW - timedelta(minutes=5),
        valid_until=NOW + timedelta(minutes=30),
    )


def valid_portfolio() -> PortfolioState:
    return PortfolioState(
        equity=Decimal("100000"),
        start_of_day_equity=Decimal("100000"),
        start_of_week_equity=Decimal("100000"),
        realized_daily_pnl=Decimal("0"),
        realized_weekly_pnl=Decimal("0"),
        current_open_risk=Decimal("0"),
        open_positions=0,
        market_open=True,
        data_healthy=True,
        broker_reconciled=True,
        execution_enabled=True,
        dry_run=False,
        kill_switch=False,
    )


def valid_context(**changes: object) -> ExecutionRiskContext:
    values = {
        "portfolio": valid_portfolio(),
        "options_buying_power": Decimal("100000"),
        "minutes_since_market_open": 60,
        "minutes_until_market_close": 180,
        "decision_id": "decision-001",
    }
    values.update(changes)
    return ExecutionRiskContext(**values)


def entry_intent(quantity: int = 2):
    return build_mleg_order_intent(
        thesis_id="phase4-thesis",
        spread=valid_spread(quantity),
        purpose=OrderPurpose.ENTRY,
        limit_price=Decimal("3.00"),
        created_at=NOW,
    )


def event(
    number: int,
    event_type: LifecycleEventType,
    *,
    broker_order_id: str | None = None,
    filled: int | None = None,
    reason: str | None = None,
) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=f"event-{number}",
        event_type=event_type,
        occurred_at=NOW + timedelta(seconds=number),
        broker_order_id=broker_order_id,
        cumulative_filled_quantity=filled,
        reason=reason,
    )


def acknowledged_lifecycle(quantity: int = 2) -> LifecycleSnapshot:
    snapshot = start_lifecycle(entry_intent(quantity))
    snapshot = apply_event(snapshot, event(1, LifecycleEventType.RISK_APPROVED))
    snapshot = apply_event(snapshot, event(2, LifecycleEventType.ENTRY_SUBMIT_REQUESTED))
    return apply_event(
        snapshot,
        event(3, LifecycleEventType.ENTRY_ACKNOWLEDGED, broker_order_id="broker-entry"),
    )


class OptionDataAdapterTests(unittest.TestCase):
    def test_parses_current_contract_and_snapshot_shapes(self) -> None:
        parsed = parse_alpaca_option_candidate(
            {
                "symbol": "SPY260918C00600000",
                "underlying_symbol": "SPY",
                "type": "call",
                "expiration_date": "2026-09-18",
                "strike_price": "600",
                "tradable": True,
                "open_interest": "125",
            },
            {
                "latestQuote": {"bp": 4.9, "ap": 5.0, "t": "2026-09-01T15:00:00Z"},
                "greeks": {"delta": 0.61},
                "dailyBar": {"v": 42},
            },
        )
        self.assertEqual(parsed.leg.strike, Decimal("600"))
        self.assertEqual(parsed.leg.quote.ask, Decimal("5.0"))
        self.assertEqual(parsed.delta, Decimal("0.61"))
        self.assertEqual(parsed.open_interest, 125)
        self.assertEqual(parsed.volume, 42)

    def test_rejects_contract_not_explicitly_tradable(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicitly tradable"):
            parse_alpaca_option_candidate(
                {
                    "symbol": "SPY260918C00600000",
                    "underlying_symbol": "SPY",
                    "type": "call",
                    "expiration_date": "2026-09-18",
                    "strike_price": "600",
                    "tradable": False,
                },
                {"latestQuote": {"bp": 4.9, "ap": 5.0, "t": "2026-09-01T15:00:00Z"}},
            )


class SpreadConstructionTests(unittest.TestCase):
    def test_rejects_wrong_signed_delta(self) -> None:
        with self.assertRaisesRegex(ValueError, "call delta cannot be negative"):
            candidate("BAD-CALL", "600", bid="4.90", ask="5.00", delta="-0.60")

    def test_prefers_delta_pair_and_uses_conservative_debit(self) -> None:
        result = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=bull_candidates(),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertTrue(result.selected)
        self.assertEqual(result.method, SelectionMethod.DELTA)
        self.assertEqual(result.spread.long_leg.strike, Decimal("600"))
        self.assertEqual(result.spread.short_leg.strike, Decimal("605"))
        self.assertEqual(result.spread.net_debit, Decimal("3.00"))

    def test_moneyness_fallback_is_used_only_when_delta_is_missing(self) -> None:
        missing_greeks = tuple(
            OptionCandidate(item.leg, delta=None) for item in bull_candidates()[:2]
        )
        result = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=missing_greeks,
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertTrue(result.selected)
        self.assertEqual(result.method, SelectionMethod.MONEYNESS)

    def test_available_but_out_of_band_deltas_fail_closed(self) -> None:
        candidates = (
            candidate("LONG", "600", bid="4.90", ask="5.00", delta="0.80"),
            candidate("SHORT", "605", bid="2.00", ask="2.10", delta="0.10"),
        )
        result = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=candidates,
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(result.selected)
        self.assertIn("available deltas are outside the target bands", result.rejection_reasons)

    def test_stale_quotes_and_negative_debit_fail_closed(self) -> None:
        stale = (
            candidate(
                "STALE-LONG",
                "600",
                bid="4.90",
                ask="5.00",
                delta="0.60",
                observed_at=NOW - timedelta(seconds=16),
            ),
            candidate("STALE-SHORT", "605", bid="2.00", ask="2.10", delta="0.32"),
        )
        stale_result = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=stale,
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(stale_result.selected)

        inverted_premium = (
            candidate("CHEAP-LONG", "600", bid="0.90", ask="1.00", delta="0.60"),
            candidate("RICH-SHORT", "605", bid="1.20", ask="1.30", delta="0.32"),
        )
        debit_result = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=inverted_premium,
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(debit_result.selected)
        self.assertIn(
            "candidate pair has a zero or negative executable debit",
            debit_result.rejection_reasons,
        )

    def test_selection_is_deterministic_under_input_reordering(self) -> None:
        first = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=bull_candidates(),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        second = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BULLISH,
            underlying_price=Decimal("602"),
            candidates=tuple(reversed(bull_candidates())),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertEqual(first.spread, second.spread)
        self.assertEqual(first.selection_score, second.selection_score)

    def test_bear_put_uses_higher_long_strike(self) -> None:
        puts = (
            candidate(
                "SPY260918P00605000",
                "605",
                right=OptionRight.PUT,
                bid="4.90",
                ask="5.00",
                delta="-0.60",
            ),
            candidate(
                "SPY260918P00600000",
                "600",
                right=OptionRight.PUT,
                bid="2.00",
                ask="2.10",
                delta="-0.32",
            ),
        )
        result = construct_vertical_spread(
            underlying="SPY",
            direction=Direction.BEARISH,
            underlying_price=Decimal("602"),
            candidates=puts,
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertTrue(result.selected)
        self.assertEqual(result.spread.long_leg.strike, Decimal("605"))
        self.assertEqual(result.spread.short_leg.strike, Decimal("600"))


class Phase4RiskTests(unittest.TestCase):
    def test_buying_power_can_reduce_base_risk_quantity(self) -> None:
        decision = assess_phase4_trade(
            valid_thesis(),
            valid_spread(),
            valid_context(options_buying_power=Decimal("350")),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertTrue(decision.approved)
        self.assertEqual(decision.maximum_allowed_quantity, 1)

    def test_rejects_duplicate_decision(self) -> None:
        decision = assess_phase4_trade(
            valid_thesis(),
            valid_spread(),
            valid_context(processed_decision_ids=frozenset({"decision-001"})),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(decision.approved)
        self.assertIn("decision id has already been processed", decision.reasons)

    def test_missing_session_and_buying_power_inputs_fail_closed(self) -> None:
        decision = assess_phase4_trade(
            valid_thesis(),
            valid_spread(),
            valid_context(
                options_buying_power=None,
                minutes_since_market_open=None,
                minutes_until_market_close=None,
            ),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(decision.approved)
        self.assertEqual(decision.maximum_allowed_quantity, 0)
        self.assertIn("options buying power is unavailable", decision.reasons)
        self.assertIn("minutes until market close are unavailable", decision.reasons)

    def test_opening_and_closing_windows_are_blocked(self) -> None:
        opening = assess_phase4_trade(
            valid_thesis(),
            valid_spread(),
            valid_context(minutes_since_market_open=5),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        closing = assess_phase4_trade(
            valid_thesis(),
            valid_spread(),
            valid_context(minutes_until_market_close=10),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertIn("entry is blocked during the opening window", opening.reasons)
        self.assertIn("entry is blocked near market close", closing.reasons)


class LifecycleTests(unittest.TestCase):
    def test_complete_partial_entry_and_exit_lifecycle(self) -> None:
        snapshot = acknowledged_lifecycle()
        snapshot = apply_event(
            snapshot,
            event(
                4,
                LifecycleEventType.ENTRY_PARTIAL_FILL,
                broker_order_id="broker-entry",
                filled=1,
            ),
        )
        snapshot = apply_event(
            snapshot,
            event(
                5,
                LifecycleEventType.ENTRY_FILLED,
                broker_order_id="broker-entry",
                filled=2,
            ),
        )
        snapshot = apply_event(snapshot, event(6, LifecycleEventType.CLOSE_SUBMIT_REQUESTED))
        snapshot = apply_event(
            snapshot,
            event(7, LifecycleEventType.CLOSE_ACKNOWLEDGED, broker_order_id="broker-exit"),
        )
        snapshot = apply_event(
            snapshot,
            event(
                8,
                LifecycleEventType.EXIT_PARTIAL_FILL,
                broker_order_id="broker-exit",
                filled=1,
            ),
        )
        snapshot = apply_event(
            snapshot,
            event(
                9,
                LifecycleEventType.EXIT_FILLED,
                broker_order_id="broker-exit",
                filled=2,
            ),
        )
        self.assertEqual(snapshot.state, LifecycleState.CLOSED)
        self.assertEqual(snapshot.active_quantity, 0)
        self.assertEqual(snapshot.version, 9)

    def test_duplicate_event_is_idempotent_after_restart(self) -> None:
        snapshot = acknowledged_lifecycle()
        restored = LifecycleSnapshot.from_record(snapshot.to_record())
        duplicate = event(
            3, LifecycleEventType.ENTRY_ACKNOWLEDGED, broker_order_id="broker-entry"
        )
        self.assertEqual(apply_event(restored, duplicate), restored)

    def test_illegal_transition_fails_closed(self) -> None:
        snapshot = start_lifecycle(entry_intent())
        with self.assertRaises(InvalidLifecycleTransition):
            apply_event(
                snapshot,
                event(
                    1,
                    LifecycleEventType.ENTRY_FILLED,
                    broker_order_id="broker-entry",
                    filled=2,
                ),
            )

    def test_cancel_after_partial_entry_preserves_open_exposure(self) -> None:
        snapshot = acknowledged_lifecycle()
        snapshot = apply_event(
            snapshot,
            event(
                4,
                LifecycleEventType.ENTRY_PARTIAL_FILL,
                broker_order_id="broker-entry",
                filled=1,
            ),
        )
        snapshot = apply_event(snapshot, event(5, LifecycleEventType.ENTRY_CANCEL_REQUESTED))
        snapshot = apply_event(snapshot, event(6, LifecycleEventType.ENTRY_CANCELED))
        self.assertEqual(snapshot.state, LifecycleState.OPEN)
        self.assertEqual(snapshot.active_quantity, 1)

    def test_broker_mismatch_requires_reconciliation(self) -> None:
        snapshot = acknowledged_lifecycle()
        snapshot = apply_event(
            snapshot,
            event(4, LifecycleEventType.BROKER_MISMATCH, reason="broker id changed"),
        )
        self.assertEqual(snapshot.state, LifecycleState.RECONCILE_REQUIRED)
        self.assertEqual(snapshot.resume_state, LifecycleState.ENTRY_ACKNOWLEDGED)
        snapshot = apply_event(snapshot, event(5, LifecycleEventType.RECONCILED))
        self.assertEqual(snapshot.state, LifecycleState.ENTRY_ACKNOWLEDGED)

    def test_terminal_failure_cannot_forget_open_quantity(self) -> None:
        snapshot = acknowledged_lifecycle(quantity=1)
        snapshot = apply_event(
            snapshot,
            event(
                4,
                LifecycleEventType.ENTRY_FILLED,
                broker_order_id="broker-entry",
                filled=1,
            ),
        )
        snapshot = apply_event(
            snapshot,
            event(5, LifecycleEventType.TERMINAL_FAILURE, reason="storage unavailable"),
        )
        self.assertEqual(snapshot.state, LifecycleState.RECONCILE_REQUIRED)
        self.assertEqual(snapshot.active_quantity, 1)

    def test_reconciliation_detects_broker_regression(self) -> None:
        snapshot = acknowledged_lifecycle()
        snapshot = apply_event(
            snapshot,
            event(
                4,
                LifecycleEventType.ENTRY_PARTIAL_FILL,
                broker_order_id="broker-entry",
                filled=1,
            ),
        )
        assessment = assess_entry_reconciliation(
            snapshot,
            BrokerOrderView(
                client_order_id=snapshot.client_order_id,
                broker_order_id="broker-entry",
                status=BrokerOrderStatus.NEW,
                filled_quantity=0,
            ),
        )
        self.assertFalse(assessment.consistent)
        self.assertIn("broker filled quantity is behind local state", assessment.reasons)


if __name__ == "__main__":
    unittest.main()
