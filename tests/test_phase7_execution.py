from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError, URLError

from conviction_spread_agent.domain import (
    OptionLeg,
    OptionRight,
    Quote,
    VerticalSpread,
)
from conviction_spread_agent.execution import (
    AlpacaExecutionError,
    AlpacaPaperOrderClient,
    ExecutionAuthorization,
    ExecutionBlocked,
    JsonLifecycleStore,
    PaperExecutionGateway,
    parse_broker_order,
)
from conviction_spread_agent.lifecycle import (
    BrokerOrderStatus,
    LifecycleEvent,
    LifecycleEventType,
    LifecycleState,
    apply_event,
    start_lifecycle,
)
from conviction_spread_agent.orders import OrderPurpose, build_mleg_order_intent
from conviction_spread_agent.risk import RiskDecision


NOW = datetime(2026, 9, 2, 14, 30, tzinfo=timezone.utc)
EXPIRATION = date(2026, 9, 18)


def spread(quantity: int = 1) -> VerticalSpread:
    observed = NOW - timedelta(seconds=1)
    return VerticalSpread(
        long_leg=OptionLeg(
            symbol="SPY260918C00600000",
            underlying="SPY",
            right=OptionRight.CALL,
            expiration=EXPIRATION,
            strike=Decimal("600"),
            quote=Quote(Decimal("4.90"), Decimal("5.00"), observed),
        ),
        short_leg=OptionLeg(
            symbol="SPY260918C00605000",
            underlying="SPY",
            right=OptionRight.CALL,
            expiration=EXPIRATION,
            strike=Decimal("605"),
            quote=Quote(Decimal("2.00"), Decimal("2.10"), observed),
        ),
        net_debit=Decimal("3.00"),
        quantity=quantity,
    )


def intent(quantity: int = 1):
    return build_mleg_order_intent(
        thesis_id="phase7-canary",
        spread=spread(quantity),
        purpose=OrderPurpose.ENTRY,
        limit_price=Decimal("3.00"),
        created_at=NOW - timedelta(seconds=5),
    )


def approved_lifecycle(order_intent):
    initial = start_lifecycle(order_intent)
    return apply_event(
        initial,
        LifecycleEvent(
            event_id="risk-approved",
            event_type=LifecycleEventType.RISK_APPROVED,
            occurred_at=NOW - timedelta(seconds=4),
        ),
    )


def approved_risk(*, assessed_at: datetime = NOW, quantity: int = 1) -> RiskDecision:
    return RiskDecision(
        approved=True,
        reasons=(),
        maximum_allowed_quantity=quantity,
        assessed_at=assessed_at,
    )


def authorization(order_intent, **changes: object) -> ExecutionAuthorization:
    values = {
        "paper_trading": True,
        "submission_enabled": True,
        "dry_run": False,
        "broker_reconciled": True,
        "kill_switch": False,
        "operator_canary_approved": True,
        "maximum_contracts": 1,
        "valid_until": NOW + timedelta(minutes=1),
        "client_order_id": order_intent.client_order_id,
        "payload_sha256": order_intent.payload_sha256,
    }
    values.update(changes)
    return ExecutionAuthorization(**values)


def broker_receipt(order_intent, *, status: str = "new", filled: str = "0"):
    return {
        "id": "broker-order-001",
        "client_order_id": order_intent.client_order_id,
        "order_class": "mleg",
        "qty": str(order_intent.spread.quantity),
        "filled_qty": filled,
        "status": status,
        "legs": [
            {"symbol": order_intent.spread.long_leg.symbol},
            {"symbol": order_intent.spread.short_leg.symbol},
        ],
    }


class FakeTransport:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout_seconds):
        self.requests.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "body": json.loads(request.data) if request.data else None,
                "timeout": timeout_seconds,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class PaperGatewayTests(unittest.TestCase):
    def make_gateway(self, transport, store, *, enabled: bool = True):
        client = AlpacaPaperOrderClient(
            "paper-key",
            "paper-secret",
            transport=transport,
        )
        return PaperExecutionGateway(
            client,
            store,
            submission_enabled=enabled,
            clock=lambda: NOW,
        )

    def test_defaults_block_before_network_io(self) -> None:
        order_intent = intent()
        transport = FakeTransport(broker_receipt(order_intent))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store, enabled=False)

            with self.assertRaises(ExecutionBlocked) as raised:
                gateway.submit_entry(
                    order_intent,
                    approved_risk(),
                    ExecutionAuthorization(),
                    lifecycle,
                )

        self.assertIn("paper submission gateway is disabled", raised.exception.reasons)
        self.assertIn(
            "operator has not approved the paper canary", raised.exception.reasons
        )
        self.assertEqual(transport.requests, [])

    def test_authorized_canary_persists_before_post_and_acknowledges(self) -> None:
        order_intent = intent()
        transport = FakeTransport(broker_receipt(order_intent))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            result = gateway.submit_entry(
                order_intent, approved_risk(), authorization(order_intent), lifecycle
            )

            self.assertEqual(result.lifecycle.state, LifecycleState.ENTRY_ACKNOWLEDGED)
            self.assertEqual(store.load(order_intent.client_order_id), result.lifecycle)

        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://paper-api.alpaca.markets/v2/orders")
        self.assertEqual(request["body"], order_intent.as_alpaca_payload())
        self.assertEqual(len(result.response_sha256), 64)

    def test_stale_risk_and_multi_contract_intent_fail_closed(self) -> None:
        order_intent = intent(quantity=2)
        transport = FakeTransport(broker_receipt(order_intent))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)

            with self.assertRaises(ExecutionBlocked) as raised:
                gateway.submit_entry(
                    order_intent,
                    approved_risk(
                        assessed_at=NOW - timedelta(seconds=11), quantity=2
                    ),
                    authorization(order_intent),
                    lifecycle,
                )

        self.assertIn("paper canary is limited to one contract", raised.exception.reasons)
        self.assertIn(
            "deterministic risk decision is stale or future-dated",
            raised.exception.reasons,
        )
        self.assertEqual(transport.requests, [])

    def test_unknown_post_outcome_requires_lookup_and_never_resubmits(self) -> None:
        order_intent = intent()
        transport = FakeTransport(
            URLError("connection reset"),
            broker_receipt(order_intent, status="filled", filled="1"),
        )
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)

            with self.assertRaises(AlpacaExecutionError) as raised:
                gateway.submit_entry(
                    order_intent, approved_risk(), authorization(order_intent), lifecycle
                )
            self.assertTrue(raised.exception.outcome_unknown)
            uncertain = store.load(order_intent.client_order_id)
            self.assertEqual(uncertain.state, LifecycleState.RECONCILE_REQUIRED)
            self.assertEqual(uncertain.resume_state, LifecycleState.ENTRY_SUBMITTING)

            with self.assertRaises(ExecutionBlocked):
                gateway.submit_entry(
                    order_intent, approved_risk(), authorization(order_intent), uncertain
                )
            reconciled = gateway.reconcile_entry(order_intent, uncertain)
            self.assertTrue(reconciled.consistent)
            self.assertEqual(reconciled.lifecycle.state, LifecycleState.OPEN)

        self.assertEqual(
            [request["method"] for request in transport.requests], ["POST", "GET"]
        )
        self.assertIn(
            "/v2/orders:by_client_order_id?",
            transport.requests[1]["url"],
        )

    def test_not_found_reconciliation_prohibits_automatic_resubmit(self) -> None:
        order_intent = intent()
        not_found = HTTPError("paper", 404, "not found", {}, None)
        transport = FakeTransport(not_found)
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            lifecycle = apply_event(
                lifecycle,
                LifecycleEvent(
                    event_id="submit-requested",
                    event_type=LifecycleEventType.ENTRY_SUBMIT_REQUESTED,
                    occurred_at=NOW - timedelta(seconds=2),
                ),
            )
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            result = gateway.reconcile_entry(order_intent, lifecycle)

        self.assertFalse(result.consistent)
        self.assertEqual(result.broker_status, BrokerOrderStatus.NOT_FOUND)
        self.assertIn("automatic resubmission is prohibited", result.reasons[0])
        self.assertEqual(transport.requests[0]["method"], "GET")

    def test_mismatched_broker_response_requires_reconciliation(self) -> None:
        order_intent = intent()
        response = broker_receipt(order_intent)
        response["client_order_id"] = "different-order"
        transport = FakeTransport(response)
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)

            with self.assertRaises(AlpacaExecutionError) as raised:
                gateway.submit_entry(
                    order_intent, approved_risk(), authorization(order_intent), lifecycle
                )
            persisted = store.load(order_intent.client_order_id)

        self.assertTrue(raised.exception.outcome_unknown)
        self.assertEqual(persisted.state, LifecycleState.RECONCILE_REQUIRED)


    def test_authorization_is_bound_to_exact_order_and_short_expiry(self) -> None:
        order_intent = intent()
        transport = FakeTransport(broker_receipt(order_intent))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)

            with self.assertRaises(ExecutionBlocked) as raised:
                gateway.submit_entry(
                    order_intent,
                    approved_risk(),
                    authorization(
                        order_intent,
                        client_order_id="different-order",
                        valid_until=NOW + timedelta(minutes=3),
                    ),
                    lifecycle,
                )

        self.assertIn(
            "authorization client order id does not match the intent",
            raised.exception.reasons,
        )
        self.assertIn(
            "paper canary authorization is not short-lived",
            raised.exception.reasons,
        )
        self.assertEqual(transport.requests, [])

    def test_terminal_broker_status_cannot_hide_partial_exposure(self) -> None:
        order_intent = intent(quantity=2)
        transport = FakeTransport(
            broker_receipt(order_intent, status="canceled", filled="1")
        )
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = approved_lifecycle(order_intent)
            lifecycle = apply_event(
                lifecycle,
                LifecycleEvent(
                    event_id="submit-requested",
                    event_type=LifecycleEventType.ENTRY_SUBMIT_REQUESTED,
                    occurred_at=NOW - timedelta(seconds=2),
                ),
            )
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            result = gateway.reconcile_entry(order_intent, lifecycle)

        self.assertFalse(result.consistent)
        self.assertEqual(result.lifecycle.state, LifecycleState.RECONCILE_REQUIRED)
        self.assertEqual(result.lifecycle.active_quantity, 1)


class ParserAndStoreTests(unittest.TestCase):
    def test_current_and_rare_active_statuses_are_supported(self) -> None:
        order_intent = intent()
        receipt = parse_broker_order(
            broker_receipt(order_intent, status="accepted"), order_intent
        )
        self.assertEqual(receipt.view.status, BrokerOrderStatus.NEW)

    def test_store_rejects_version_regression(self) -> None:
        order_intent = intent()
        lifecycle = approved_lifecycle(order_intent)
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            store.save(lifecycle)
            with self.assertRaisesRegex(ValueError, "cannot move backward"):
                store.save(start_lifecycle(order_intent))


if __name__ == "__main__":
    unittest.main()
