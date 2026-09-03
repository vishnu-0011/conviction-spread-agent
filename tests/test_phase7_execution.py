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


def exit_intent(quantity: int = 1, *, observed_at: datetime | None = None):
    current = spread(quantity)
    observed = observed_at or (NOW - timedelta(seconds=1))
    repriced = VerticalSpread(
        long_leg=OptionLeg(
            symbol=current.long_leg.symbol,
            underlying=current.long_leg.underlying,
            right=current.long_leg.right,
            expiration=current.long_leg.expiration,
            strike=current.long_leg.strike,
            quote=Quote(Decimal("3.90"), Decimal("4.00"), observed),
        ),
        short_leg=OptionLeg(
            symbol=current.short_leg.symbol,
            underlying=current.short_leg.underlying,
            right=current.short_leg.right,
            expiration=current.short_leg.expiration,
            strike=current.short_leg.strike,
            quote=Quote(Decimal("2.30"), Decimal("2.40"), observed),
        ),
        net_debit=current.net_debit,
        quantity=quantity,
    )
    return build_mleg_order_intent(
        thesis_id="phase7-canary",
        spread=repriced,
        purpose=OrderPurpose.EXIT,
        limit_price=Decimal("1.50"),
        created_at=NOW - timedelta(seconds=1),
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


def open_lifecycle(order_intent):
    snapshot = approved_lifecycle(order_intent)
    snapshot = apply_event(
        snapshot,
        LifecycleEvent(
            event_id="entry-submit",
            event_type=LifecycleEventType.ENTRY_SUBMIT_REQUESTED,
            occurred_at=NOW - timedelta(seconds=3),
        ),
    )
    return apply_event(
        snapshot,
        LifecycleEvent(
            event_id="entry-filled",
            event_type=LifecycleEventType.ENTRY_FILLED,
            occurred_at=NOW - timedelta(seconds=2),
            broker_order_id="broker-entry",
            cumulative_filled_quantity=order_intent.spread.quantity,
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


def exit_authorization(order_intent, **changes: object) -> ExecutionAuthorization:
    values = {
        "paper_trading": True,
        "submission_enabled": True,
        "dry_run": False,
        "broker_reconciled": True,
        "kill_switch": True,
        "operator_canary_approved": True,
        "market_open": True,
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

    def test_exit_defaults_block_before_network_io(self) -> None:
        entry = intent()
        close = exit_intent()
        transport = FakeTransport(broker_receipt(close))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = open_lifecycle(entry)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store, enabled=False)

            with self.assertRaises(ExecutionBlocked) as raised:
                gateway.submit_exit(close, ExecutionAuthorization(), lifecycle)

        self.assertIn("paper submission gateway is disabled", raised.exception.reasons)
        self.assertIn(
            "operator has not approved the exact paper close",
            raised.exception.reasons,
        )
        self.assertEqual(transport.requests, [])

    def test_authorized_exit_persists_binding_and_acknowledges(self) -> None:
        entry = intent()
        close = exit_intent()
        transport = FakeTransport(broker_receipt(close))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = open_lifecycle(entry)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            result = gateway.submit_exit(
                close, exit_authorization(close), lifecycle
            )
            persisted = store.load(entry.client_order_id)

        self.assertEqual(result.lifecycle.state, LifecycleState.CLOSE_ACKNOWLEDGED)
        self.assertEqual(persisted.exit_client_order_id, close.client_order_id)
        self.assertEqual(persisted.exit_payload_sha256, close.payload_sha256)
        self.assertEqual(transport.requests[0]["method"], "POST")
        self.assertEqual(transport.requests[0]["body"], close.as_alpaca_payload())
        self.assertEqual(transport.requests[0]["body"]["limit_price"], "-1.5")

    def test_filled_exit_closes_lifecycle(self) -> None:
        entry = intent()
        close = exit_intent()
        transport = FakeTransport(broker_receipt(close, status="filled", filled="1"))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = open_lifecycle(entry)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            result = gateway.submit_exit(close, exit_authorization(close), lifecycle)

        self.assertEqual(result.lifecycle.state, LifecycleState.CLOSED)
        self.assertEqual(result.lifecycle.active_quantity, 0)

    def test_stale_exit_quote_and_closed_market_block_without_io(self) -> None:
        entry = intent()
        close = exit_intent(observed_at=NOW - timedelta(seconds=16))
        transport = FakeTransport(broker_receipt(close))
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = open_lifecycle(entry)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            with self.assertRaises(ExecutionBlocked) as raised:
                gateway.submit_exit(
                    close,
                    exit_authorization(close, market_open=False),
                    lifecycle,
                )

        self.assertIn("paper close requires an open market session", raised.exception.reasons)
        self.assertTrue(any("stale" in reason for reason in raised.exception.reasons))
        self.assertEqual(transport.requests, [])

    def test_unknown_exit_outcome_uses_lookup_and_never_resubmits(self) -> None:
        entry = intent()
        close = exit_intent()
        transport = FakeTransport(
            URLError("connection reset"),
            broker_receipt(close, status="filled", filled="1"),
        )
        with TemporaryDirectory() as directory:
            store = JsonLifecycleStore(directory)
            lifecycle = open_lifecycle(entry)
            store.save(lifecycle)
            gateway = self.make_gateway(transport, store)
            with self.assertRaises(AlpacaExecutionError):
                gateway.submit_exit(close, exit_authorization(close), lifecycle)
            uncertain = store.load(entry.client_order_id)
            self.assertEqual(uncertain.state, LifecycleState.RECONCILE_REQUIRED)
            self.assertEqual(uncertain.resume_state, LifecycleState.CLOSE_SUBMITTING)
            result = gateway.reconcile_exit(close, uncertain)

        self.assertTrue(result.consistent)
        self.assertEqual(result.lifecycle.state, LifecycleState.CLOSED)
        self.assertEqual(
            [request["method"] for request in transport.requests], ["POST", "GET"]
        )


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
