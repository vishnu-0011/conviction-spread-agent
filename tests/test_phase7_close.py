from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from conviction_spread_agent.close import (
    entry_intent_from_record,
    exit_intent_from_record,
    prepare_close,
)
from conviction_spread_agent.domain import OptionLeg, OptionRight, Quote, VerticalSpread
from conviction_spread_agent.orders import OrderPurpose, build_mleg_order_intent


NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


def entry_intent():
    observed = NOW - timedelta(seconds=5)
    spread = VerticalSpread(
        long_leg=OptionLeg(
            symbol="IWM260918P00250000",
            underlying="IWM",
            right=OptionRight.PUT,
            expiration=date(2026, 9, 18),
            strike=Decimal("250"),
            quote=Quote(Decimal("4.40"), Decimal("4.50"), observed),
        ),
        short_leg=OptionLeg(
            symbol="IWM260918P00245000",
            underlying="IWM",
            right=OptionRight.PUT,
            expiration=date(2026, 9, 18),
            strike=Decimal("245"),
            quote=Quote(Decimal("2.00"), Decimal("2.10"), observed),
        ),
        net_debit=Decimal("2.50"),
        quantity=1,
    )
    return build_mleg_order_intent(
        thesis_id="shadow-iwm-canary",
        spread=spread,
        purpose=OrderPurpose.ENTRY,
        limit_price=spread.net_debit,
        created_at=NOW - timedelta(seconds=4),
    )


def entry_record() -> dict[str, object]:
    entry = entry_intent()
    spread = entry.spread
    return {
        "prepared_at": entry.created_at.isoformat(),
        "decision_id": "shadow-iwm-canary",
        "order": {
            "client_order_id": entry.client_order_id,
            "payload_sha256": entry.payload_sha256,
            "quantity": 1,
            "structure": "bear_put_debit_spread",
            "underlying": "IWM",
            "right": "put",
            "expiration": "2026-09-18",
            "limit_debit": "2.50",
            "legs": [
                {
                    "action": "buy_to_open",
                    "symbol": spread.long_leg.symbol,
                    "strike": "250",
                    "bid": "4.40",
                    "ask": "4.50",
                    "observed_at": spread.long_leg.quote.observed_at.isoformat(),
                },
                {
                    "action": "sell_to_open",
                    "symbol": spread.short_leg.symbol,
                    "strike": "245",
                    "bid": "2.00",
                    "ask": "2.10",
                    "observed_at": spread.short_leg.quote.observed_at.isoformat(),
                },
            ],
        },
    }


def snapshots(*, observed_at: datetime = NOW) -> dict[str, dict[str, object]]:
    return {
        "IWM260918P00250000": {
            "latestQuote": {"bp": "4.00", "ap": "4.10", "t": observed_at.isoformat()}
        },
        "IWM260918P00245000": {
            "latestQuote": {"bp": "2.00", "ap": "2.10", "t": observed_at.isoformat()}
        },
    }


def positions() -> tuple[dict[str, object], ...]:
    return (
        {"symbol": "IWM260918P00250000", "qty": "1", "side": "long"},
        {"symbol": "IWM260918P00245000", "qty": "-1", "side": "short"},
    )


class PaperClosePreparationTests(unittest.TestCase):
    def test_entry_record_reproduces_exact_intent(self) -> None:
        parsed = entry_intent_from_record(entry_record())
        expected = entry_intent()

        self.assertEqual(parsed.client_order_id, expected.client_order_id)
        self.assertEqual(parsed.payload_sha256, expected.payload_sha256)

    def test_exact_positions_and_fresh_quotes_build_close_preview(self) -> None:
        result = prepare_close(
            entry_intent=entry_intent_from_record(entry_record()),
            snapshots=snapshots(),
            positions=positions(),
            market_open=True,
            prepared_at=NOW,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.exit_intent.purpose, OrderPurpose.EXIT)
        self.assertEqual(result.exit_intent.limit_price, Decimal("1.90"))
        payload = result.exit_intent.as_alpaca_payload()
        self.assertEqual(payload["limit_price"], "-1.9")
        self.assertEqual(payload["legs"][0]["position_intent"], "sell_to_close")
        self.assertEqual(payload["legs"][1]["position_intent"], "buy_to_close")

        restored = exit_intent_from_record(
            result.record, entry_intent=entry_intent_from_record(entry_record())
        )
        self.assertEqual(restored.client_order_id, result.exit_intent.client_order_id)
        self.assertEqual(restored.payload_sha256, result.exit_intent.payload_sha256)

    def test_position_mismatch_and_closed_market_block(self) -> None:
        result = prepare_close(
            entry_intent=entry_intent_from_record(entry_record()),
            snapshots=snapshots(),
            positions=positions()[:1],
            market_open=False,
            prepared_at=NOW,
        )

        self.assertFalse(result.ready)
        reasons = " ".join(result.record["blocking_reasons"])
        self.assertIn("exactly two", reasons)
        self.assertIn("open market", reasons)

    def test_stale_quotes_block_even_with_matching_positions(self) -> None:
        result = prepare_close(
            entry_intent=entry_intent_from_record(entry_record()),
            snapshots=snapshots(observed_at=NOW - timedelta(seconds=16)),
            positions=positions(),
            market_open=True,
            prepared_at=NOW,
        )

        self.assertFalse(result.ready)
        self.assertTrue(
            any("stale" in reason for reason in result.record["blocking_reasons"])
        )


if __name__ == "__main__":
    unittest.main()
