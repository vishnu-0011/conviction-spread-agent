# Phase 7a — paper canary gateway readiness

Phase 7a implements the broker-write boundary without placing an order. The gateway
is intentionally a library component rather than a copy-paste canary command: a live
paper submission still requires a fresh market decision, a reconciled broker state,
and a separate explicit operator approval.

## Verified Alpaca contract

- Alpaca accepts orders at POST https://paper-api.alpaca.markets/v2/orders.
- Multi-leg options orders use order_class mleg, a strategy quantity, a limit price,
  day time in force, and a legs array with side, ratio quantity, and position intent.
- A positive MLeg limit price represents a debit.
- Recovery can retrieve the original order with GET
  /v2/orders:by_client_order_id and its client_order_id query parameter.
- Alpaca documents active, partial, filled, canceled, expired, replaced, rejected,
  and rarer order states, so unknown states fail closed.

Primary references:

- <https://docs.alpaca.markets/us/reference/postorder>
- <https://docs.alpaca.markets/us/reference/getorderbyclientorderid>
- <https://docs.alpaca.markets/us/docs/options-level-3-trading>
- <https://docs.alpaca.markets/us/docs/orders-at-alpaca>

## Safety boundary

The new PaperExecutionGateway requires all of the following at the same time:

1. the gateway was explicitly constructed with submission enabled;
2. the authorization is paper-only, not dry-run, reconciled, and kill-switch clear;
3. the operator explicitly approved a one-contract paper canary;
4. the authorization expires within 120 seconds;
5. the authorization is bound to the exact client order ID and payload SHA-256;
6. the deterministic risk result is approved and no older than 10 seconds;
7. the quantity is exactly one contract;
8. the lifecycle is APPROVED and exactly matches durable local state; and
9. the lifecycle quantity and payload hash match the order intent.

Any missing or contradictory condition blocks before network I/O.

## Restart and uncertainty behavior

- The submit-requested lifecycle state is atomically persisted before POST.
- A timeout, connection loss, server error, or mismatched response is treated as an
  unknown outcome.
- Unknown outcomes enter RECONCILE_REQUIRED.
- The gateway never automatically re-POSTs an uncertain client order ID.
- Recovery performs only the documented GET lookup by client order ID.
- A canceled or rejected parent with a non-zero fill preserves that exposure and
  remains reconciliation-required.
- Local lifecycle versions cannot move backward or change meaning at the same version.

## Verification

Run the complete suite:

~~~powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
~~~

Current result: 80 tests pass, including 10 focused Phase 7 tests. The focused tests
use fake transports and temporary directories, so they perform no Alpaca request and
cannot affect the paper account.

## What remains before an order appears in Alpaca

1. Generate a new eligible spread while the market and data are healthy.
2. Reconcile positions and open orders from the development paper account.
3. Re-run deterministic risk immediately before submission.
4. Present the exact legs, debit, and maximum loss for operator review.
5. Obtain explicit approval for that exact one-contract paper order.
6. Submit once, then monitor and reconcile the broker-confirmed lifecycle.

Until those steps occur, Alpaca should show no order from ConvictionSpread.
