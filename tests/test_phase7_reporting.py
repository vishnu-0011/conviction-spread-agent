from datetime import datetime, timezone
import unittest

from conviction_spread_agent.performance import build_paper_performance_report
from conviction_spread_agent.reconciliation import AlpacaPaperStateClient


NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout_seconds):
        self.requests.append((request.get_method(), request.full_url))
        return self.responses.pop(0)


class PaperPerformanceReportTests(unittest.TestCase):
    def test_report_is_sanitized_and_filters_strategy_orders(self) -> None:
        report = build_paper_performance_report(
            account={
                "id": "sensitive-account-id",
                "status": "ACTIVE",
                "equity": "100125.50",
                "last_equity": "100000",
            },
            positions=(
                {
                    "symbol": "IWM260918P00250000",
                    "asset_class": "us_option",
                    "qty": "1",
                    "side": "long",
                    "unrealized_pl": "25.50",
                },
            ),
            orders=(
                {
                    "id": "sensitive-broker-order-id",
                    "client_order_id": "csa-entry-123",
                    "status": "filled",
                    "order_class": "mleg",
                    "legs": None,
                },
                {
                    "id": "manual-id",
                    "client_order_id": "manual-order",
                    "status": "filled",
                },
            ),
            history={
                "base_value": 100000,
                "base_value_asof": "2026-09-03",
                "timeframe": "5Min",
                "timestamp": [1, 2],
                "equity": [100000, 100125.5],
                "profit_loss": [0, 125.5],
                "profit_loss_pct": [0, 0.001255],
            },
            generated_at=NOW,
        )

        self.assertEqual(report["account"]["day_pnl"], "125.50")
        self.assertEqual(report["strategy_orders"]["count"], 1)
        self.assertEqual(report["strategy_orders"]["terminal_fill_rate"], "1")
        self.assertEqual(report["positions"]["total_unrealized_pnl"], "25.50")
        self.assertEqual(len(report["portfolio_history"]["points"]), 2)
        self.assertNotIn("sensitive-account-id", str(report))
        self.assertNotIn("sensitive-broker-order-id", str(report))
        self.assertNotIn("manual-order", str(report))
        self.assertEqual(report["strategy_orders"]["items"][0]["legs"], [])
        self.assertFalse(report["safety"]["broker_write_performed"])

    def test_requested_order_filter_is_exact(self) -> None:
        report = build_paper_performance_report(
            account={},
            positions=(),
            orders=(
                {"client_order_id": "csa-one", "status": "filled"},
                {"client_order_id": "csa-two", "status": "canceled"},
            ),
            history={},
            generated_at=NOW,
            requested_client_order_id="csa-two",
        )

        self.assertEqual(report["strategy_orders"]["count"], 1)
        self.assertEqual(
            report["strategy_orders"]["items"][0]["client_order_id"],
            "csa-two",
        )

    def test_state_client_reporting_surfaces_are_get_only(self) -> None:
        transport = FakeTransport([], {"timeframe": "5Min"}, {"status": "filled"})
        client = AlpacaPaperStateClient("key", "secret", transport=transport)

        self.assertEqual(client.orders(status="all", after=NOW), ())
        self.assertEqual(client.portfolio_history()["timeframe"], "5Min")
        self.assertEqual(
            client.order_by_client_order_id("csa-entry")["status"], "filled"
        )

        self.assertEqual([method for method, _ in transport.requests], ["GET"] * 3)
        self.assertIn("status=all", transport.requests[0][1])
        self.assertIn("after=", transport.requests[0][1])
        self.assertIn("portfolio%2Fhistory", transport.requests[1][1].replace("/", "%2F"))
        self.assertIn("/v2/orders:by_client_order_id?", transport.requests[2][1])

    def test_orders_reject_naive_after_timestamp(self) -> None:
        client = AlpacaPaperStateClient(
            "key", "secret", transport=FakeTransport([])
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            client.orders(after=datetime(2026, 9, 3))


if __name__ == "__main__":
    unittest.main()
