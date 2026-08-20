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
from conviction_spread_agent.risk import PortfolioState, RiskLimits, assess_trade
from conviction_spread_agent.orders import OrderPurpose, build_mleg_order_intent


NOW = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
MARKET_DATE = date(2026, 8, 31)


def quote(
    bid: str = "4.90", ask: str = "5.10", *, observed_at: datetime = NOW
) -> Quote:
    return Quote(Decimal(bid), Decimal(ask), observed_at)


def call_leg(symbol: str, strike: str, *, q: Quote | None = None) -> OptionLeg:
    return OptionLeg(
        symbol=symbol,
        underlying="SPY",
        right=OptionRight.CALL,
        expiration=date(2026, 9, 18),
        strike=Decimal(strike),
        quote=q or quote(),
    )


def valid_spread(quantity: int = 1) -> VerticalSpread:
    return VerticalSpread(
        long_leg=call_leg("SPY260918C00600000", "600"),
        short_leg=call_leg("SPY260918C00605000", "605"),
        net_debit=Decimal("2.00"),
        quantity=quantity,
    )


def valid_thesis(**changes: object) -> Thesis:
    values = {
        "thesis_id": "thesis-001",
        "underlying": "SPY",
        "direction": Direction.BULLISH,
        "confidence": Decimal("0.80"),
        "summary": "Orderly uptrend with a confirmed continuation setup.",
        "evidence": ("trend aligned", "relative volume confirmed"),
        "counter_evidence": ("broad-market volatility is rising",),
        "invalidation": "SPY closes below the defined support level.",
        "created_at": NOW - timedelta(minutes=5),
        "valid_until": NOW + timedelta(minutes=25),
    }
    values.update(changes)
    return Thesis(**values)


def valid_portfolio(**changes: object) -> PortfolioState:
    values = {
        "equity": Decimal("100000"),
        "start_of_day_equity": Decimal("100000"),
        "start_of_week_equity": Decimal("100000"),
        "realized_daily_pnl": Decimal("0"),
        "realized_weekly_pnl": Decimal("0"),
        "current_open_risk": Decimal("0"),
        "open_positions": 0,
        "market_open": True,
        "data_healthy": True,
        "broker_reconciled": True,
        "execution_enabled": True,
        "dry_run": False,
        "kill_switch": False,
    }
    values.update(changes)
    return PortfolioState(**values)


class VerticalSpreadTests(unittest.TestCase):
    def test_bull_call_math(self) -> None:
        spread = valid_spread()
        self.assertEqual(spread.max_loss, Decimal("200.00"))
        self.assertEqual(spread.max_profit, Decimal("300.00"))
        self.assertEqual(spread.breakeven, Decimal("602.00"))
        self.assertEqual(spread.direction, Direction.BULLISH)

    def test_rejects_inverted_call_strikes(self) -> None:
        with self.assertRaisesRegex(ValueError, "buys the lower strike"):
            VerticalSpread(
                long_leg=call_leg("HIGH", "605"),
                short_leg=call_leg("LOW", "600"),
                net_debit=Decimal("2"),
                quantity=1,
            )

    def test_rejects_debit_at_or_above_width(self) -> None:
        with self.assertRaisesRegex(ValueError, "less than the strike width"):
            VerticalSpread(
                long_leg=call_leg("LOW", "600"),
                short_leg=call_leg("HIGH", "605"),
                net_debit=Decimal("5"),
                quantity=1,
            )


class RiskTests(unittest.TestCase):
    def test_approves_valid_one_contract_spread(self) -> None:
        decision = assess_trade(
            valid_thesis(), valid_spread(), valid_portfolio(), market_date=MARKET_DATE, as_of=NOW
        )
        self.assertTrue(decision.approved)
        self.assertEqual(decision.reasons, ())
        self.assertEqual(decision.maximum_allowed_quantity, 2)

    def test_rejects_trade_over_risk_budget(self) -> None:
        decision = assess_trade(
            valid_thesis(),
            valid_spread(quantity=3),
            valid_portfolio(),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(decision.approved)
        self.assertIn("proposed quantity exceeds the risk budget", decision.reasons)
        self.assertEqual(decision.maximum_allowed_quantity, 2)

    def test_fails_closed_when_execution_is_not_deliberately_enabled(self) -> None:
        decision = assess_trade(
            valid_thesis(),
            valid_spread(),
            valid_portfolio(execution_enabled=False, dry_run=True),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(decision.approved)
        self.assertIn("execution is disabled", decision.reasons)
        self.assertIn("dry-run mode cannot submit orders", decision.reasons)

    def test_daily_loss_limit_is_inclusive(self) -> None:
        decision = assess_trade(
            valid_thesis(),
            valid_spread(),
            valid_portfolio(realized_daily_pnl=Decimal("-1500")),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(decision.approved)
        self.assertIn("daily loss halt is active", decision.reasons)

    def test_rejects_wide_option_quote(self) -> None:
        spread = VerticalSpread(
            long_leg=call_leg("LOW", "600", q=quote("4.00", "6.00")),
            short_leg=call_leg("HIGH", "605"),
            net_debit=Decimal("2"),
            quantity=1,
        )
        decision = assess_trade(
            valid_thesis(), spread, valid_portfolio(), market_date=MARKET_DATE, as_of=NOW
        )
        self.assertFalse(decision.approved)
        self.assertIn("an option leg exceeds the quote-width limit", decision.reasons)

    def test_rejects_direction_mismatch(self) -> None:
        decision = assess_trade(
            valid_thesis(direction=Direction.BEARISH),
            valid_spread(),
            valid_portfolio(),
            market_date=MARKET_DATE,
            as_of=NOW,
        )
        self.assertFalse(decision.approved)
        self.assertIn("thesis direction does not match spread direction", decision.reasons)

    def test_rejects_stale_quotes(self) -> None:
        stale = quote(observed_at=NOW - timedelta(seconds=16))
        spread = VerticalSpread(
            long_leg=call_leg("LOW", "600", q=stale),
            short_leg=call_leg("HIGH", "605", q=stale),
            net_debit=Decimal("2"),
            quantity=1,
        )
        decision = assess_trade(
            valid_thesis(), spread, valid_portfolio(), market_date=MARKET_DATE, as_of=NOW
        )
        self.assertFalse(decision.approved)
        self.assertTrue(any("stale or future-dated" in reason for reason in decision.reasons))

    def test_rejects_naive_assessment_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            assess_trade(
                valid_thesis(),
                valid_spread(),
                valid_portfolio(),
                market_date=MARKET_DATE,
                as_of=datetime(2026, 8, 31),
            )


class OrderIntentTests(unittest.TestCase):
    def test_entry_payload_is_atomic_debit_with_opening_intents(self) -> None:
        intent = build_mleg_order_intent(
            thesis_id="thesis-001",
            spread=valid_spread(),
            purpose=OrderPurpose.ENTRY,
            limit_price=Decimal("2.00"),
            created_at=NOW,
        )
        payload = intent.as_alpaca_payload()
        self.assertEqual(payload["order_class"], "mleg")
        self.assertEqual(payload["limit_price"], "2")
        self.assertEqual(payload["time_in_force"], "day")
        self.assertEqual(
            payload["legs"],
            [
                {
                    "symbol": "SPY260918C00600000",
                    "ratio_qty": "1",
                    "side": "buy",
                    "position_intent": "buy_to_open",
                },
                {
                    "symbol": "SPY260918C00605000",
                    "ratio_qty": "1",
                    "side": "sell",
                    "position_intent": "sell_to_open",
                },
            ],
        )

    def test_exit_payload_is_credit_with_closing_intents(self) -> None:
        intent = build_mleg_order_intent(
            thesis_id="thesis-001",
            spread=valid_spread(),
            purpose=OrderPurpose.EXIT,
            limit_price=Decimal("3.25"),
            created_at=NOW,
        )
        payload = intent.as_alpaca_payload()
        self.assertEqual(payload["limit_price"], "-3.25")
        self.assertEqual(payload["legs"][0]["position_intent"], "sell_to_close")
        self.assertEqual(payload["legs"][1]["position_intent"], "buy_to_close")

    def test_same_logical_order_has_same_client_id_and_payload_hash(self) -> None:
        inputs = {
            "thesis_id": "thesis-001",
            "spread": valid_spread(),
            "purpose": OrderPurpose.ENTRY,
            "limit_price": Decimal("2.00"),
            "created_at": NOW,
        }
        first = build_mleg_order_intent(**inputs)
        second = build_mleg_order_intent(**inputs)
        self.assertEqual(first.client_order_id, second.client_order_id)
        self.assertEqual(first.payload_sha256, second.payload_sha256)

    def test_price_change_creates_a_distinct_client_id(self) -> None:
        first = build_mleg_order_intent(
            thesis_id="thesis-001",
            spread=valid_spread(),
            purpose=OrderPurpose.ENTRY,
            limit_price=Decimal("2.00"),
            created_at=NOW,
        )
        second = build_mleg_order_intent(
            thesis_id="thesis-001",
            spread=valid_spread(),
            purpose=OrderPurpose.ENTRY,
            limit_price=Decimal("2.05"),
            created_at=NOW,
        )
        self.assertNotEqual(first.client_order_id, second.client_order_id)


if __name__ == "__main__":
    unittest.main()
