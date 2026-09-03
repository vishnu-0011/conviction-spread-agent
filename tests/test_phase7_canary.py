from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from urllib.error import URLError

from conviction_spread_agent.canary import prepare_canary
from conviction_spread_agent.reconciliation import (
    AlpacaPaperStateClient,
    reconcile_flat_canary_account,
)


NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


def account() -> dict[str, object]:
    return {
        "id": "paper-account-123",
        "status": "ACTIVE",
        "account_blocked": False,
        "trading_blocked": False,
        "options_trading_level": 3,
        "equity": "100000",
        "last_equity": "100000",
        "options_buying_power": "100000",
    }


def shadow_record(*, selected: bool = True) -> dict[str, object]:
    spread = (
        {
            "structure": "bear_put_debit_spread",
            "long_symbol": "IWM260918P00250000",
            "short_symbol": "IWM260918P00245000",
            "expiration": "2026-09-18",
            "long_strike": "250",
            "short_strike": "245",
            "long_quote": {
                "bid": "4.40",
                "ask": "4.50",
                "observed_at": (NOW - timedelta(seconds=1)).isoformat(),
            },
            "short_quote": {
                "bid": "2.00",
                "ask": "2.10",
                "observed_at": (NOW - timedelta(seconds=1)).isoformat(),
            },
            "quantity": 1,
            "conservative_net_debit": "2.50",
            "width": "5",
            "maximum_loss": "250",
            "maximum_profit": "250",
            "breakeven": "247.50",
        }
        if selected
        else None
    )
    return {
        "generated_at": NOW.isoformat(),
        "decision_id": "shadow-iwm-canary",
        "data": {"market_open": True, "data_healthy": True},
        "features": {"symbol": "IWM"},
        "agent": {
            "final_direction": "bearish" if selected else "pass",
            "final_confidence": "0.95" if selected else "0",
            "valid_until": (NOW + timedelta(minutes=30)).isoformat(),
            "proposal": {
                "summary": "IWM has an aligned bearish regime.",
                "evidence": ["regime=bear", "relative_volume=1.31"],
                "counter_evidence": ["realized_vol=0.02"],
                "invalidation": "IWM closes above the ATR invalidation.",
            },
            "critic": {"reasons": ["no contradiction exceeded the threshold"]},
        },
        "selection": {
            "selected": selected,
            "rejection_reasons": [] if selected else ["a PASS direction cannot construct a spread"],
            "spread": spread,
        },
    }


class FakeStateTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout_seconds):
        self.requests.append(
            (request.get_method(), request.full_url, timeout_seconds)
        )
        return self.responses.pop(0)


class BrokerReconciliationTests(unittest.TestCase):
    def test_state_get_retries_a_transient_transport_failure(self) -> None:
        transport = FakeStateTransport(URLError("temporary"), account())
        original_call = transport.__call__

        def raising_transport(request, timeout_seconds):
            result = original_call(request, timeout_seconds)
            if isinstance(result, BaseException):
                raise result
            return result

        client = AlpacaPaperStateClient(
            "paper-key",
            "paper-secret",
            transport=raising_transport,
            retry_delay_seconds=0,
        )
        self.assertEqual(client.account()["status"], "ACTIVE")
        self.assertEqual(len(transport.requests), 2)

    def test_state_client_is_get_only_and_reads_exact_surfaces(self) -> None:
        transport = FakeStateTransport(account(), [], [])
        client = AlpacaPaperStateClient("paper-key", "paper-secret", transport=transport)

        self.assertEqual(client.account()["status"], "ACTIVE")
        self.assertEqual(client.positions(), ())
        self.assertEqual(client.open_orders(), ())

        self.assertEqual([item[0] for item in transport.requests], ["GET", "GET", "GET"])
        self.assertTrue(transport.requests[0][1].endswith("/v2/account"))
        self.assertTrue(transport.requests[1][1].endswith("/v2/positions"))
        self.assertIn("/v2/orders?", transport.requests[2][1])
        self.assertIn("status=open", transport.requests[2][1])

    def test_flat_account_reconciles_without_emitting_identifier(self) -> None:
        state = reconcile_flat_canary_account(account(), (), ())

        self.assertTrue(state.reconciled)
        self.assertEqual(state.reasons, ())
        public = state.public_record()
        self.assertFalse(public["account_identifier_emitted"])
        self.assertNotIn("paper-account-123", str(public))
        self.assertEqual(len(str(public["account_fingerprint"])), 12)

    def test_position_or_open_order_blocks_first_canary(self) -> None:
        state = reconcile_flat_canary_account(
            account(),
            ({"symbol": "IWM"},),
            ({"client_order_id": "manual-order"},),
        )

        self.assertFalse(state.reconciled)
        self.assertIn("completely flat", " ".join(state.reasons))
        self.assertIn("no open broker orders", " ".join(state.reasons))


class CanaryPreparationTests(unittest.TestCase):
    def test_selected_spread_builds_exact_risk_approved_preview(self) -> None:
        state = reconcile_flat_canary_account(account(), (), ())
        result = prepare_canary(
            shadow_record(),
            state,
            prepared_at=NOW,
            minutes_since_market_open=60,
            minutes_until_market_close=300,
        )

        self.assertTrue(result.ready)
        self.assertTrue(result.risk.approved)
        self.assertEqual(result.spread.max_loss, Decimal("250.00"))
        self.assertEqual(result.intent.as_alpaca_payload()["order_class"], "mleg")
        self.assertEqual(result.record["order"]["quantity"], 1)
        self.assertEqual(result.record["order"]["limit_debit"], "2.50")
        self.assertEqual(
            result.record["order"]["payload_sha256"], result.intent.payload_sha256
        )
        self.assertFalse(result.record["safety"]["broker_write_performed"])

    def test_pass_decision_cannot_produce_an_order(self) -> None:
        state = reconcile_flat_canary_account(account(), (), ())
        result = prepare_canary(
            shadow_record(selected=False),
            state,
            prepared_at=NOW,
            minutes_since_market_open=60,
            minutes_until_market_close=300,
        )

        self.assertFalse(result.ready)
        self.assertIsNone(result.intent)
        self.assertIsNone(result.record["order"])
        self.assertIn("did not select", " ".join(result.record["blocking_reasons"]))

    def test_closed_market_and_stale_quotes_fail_risk(self) -> None:
        state = reconcile_flat_canary_account(account(), (), ())
        record = shadow_record()
        record["data"]["market_open"] = False
        result = prepare_canary(
            record,
            state,
            prepared_at=NOW + timedelta(seconds=20),
            minutes_since_market_open=None,
            minutes_until_market_close=None,
        )

        self.assertFalse(result.ready)
        reasons = " ".join(result.risk.reasons)
        self.assertIn("market is closed", reasons)
        self.assertIn("stale", reasons)


if __name__ == "__main__":
    unittest.main()
