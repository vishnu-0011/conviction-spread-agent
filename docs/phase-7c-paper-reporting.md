# Phase 7c — broker-confirmed paper reporting

Phase 7c adds a narrow, read-only evidence path for the paper account. It does not
estimate fills from local state. Account equity, positions, order status, nested MLeg
legs, and intraday portfolio history are read back from Alpaca and sanitized before
being displayed or saved.

## Run it

From the repository root with the existing paper-only `.env`:

```powershell
$env:PYTHONPATH = "src"
python scripts/paper_report.py --output data/private/paper-performance.json
```

To isolate one strategy order after submission:

```powershell
python scripts/paper_report.py --client-order-id csa-ent-YYYYMMDD-EXACT_ID
```

The optional ID must be copied from the exact canary preview or submission receipt.
Do not invent it and do not submit a second order merely because a status request is
delayed.

## What the report proves

- the paper account responded and its current equity is broker-confirmed;
- `csa-` strategy orders are separated from unrelated/manual paper orders;
- current positions and unrealized P&L come from broker state;
- nested MLeg order and leg statuses are retained;
- broker IDs and the account ID are replaced by short SHA-256 fingerprints; and
- every request made by this command is GET-only.

The report deliberately includes a sample-size warning. A single paper trade proves
the execution and reconciliation path, not durable profitability.

## Verified pre-trade baseline

On 2026-09-03 the live command completed successfully against the dedicated paper
account. The detailed broker response is retained only under ignored `data/private/`
and is intentionally not committed to the public repository.

The implementation follows Alpaca's documented [list orders](https://docs.alpaca.markets/us/reference/getallorders-1),
[client-order-ID lookup](https://docs.alpaca.markets/us/reference/getorderbyclientorderid),
and [portfolio history](https://docs.alpaca.markets/us/reference/getaccountportfoliohistory-1)
surfaces.

## Safety boundary

`paper_report.py` requires `ALPACA_PAPER=true`, exposes no write operation, and never
prints API credentials or full broker/account identifiers. It does not authorize,
submit, replace, cancel, or close an order.
