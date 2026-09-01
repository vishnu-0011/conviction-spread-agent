# Phase 5a — live read-only shadow mode

## Outcome

ConvictionSpread can now make one end-to-end decision from authenticated Alpaca
paper data without possessing a broker-write path. It reads completed daily bars,
the latest underlying snapshot, account capability fields, the broker clock, and a
filtered option chain. It then computes features, produces a structured thesis,
runs an adversarial critic, constructs a defined-risk spread, and sends that
candidate through the Phase 4 risk boundary.

This is live market output, but it is not an order. The Alpaca paper dashboard is
expected to show no new order or position until the controlled execution phase.

## Run it

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python scripts/shadow_scan.py --underlying SPY
```

To save a public-safe evidence file:

```powershell
$env:PYTHONPATH = "src"
python scripts/shadow_scan.py --underlying SPY `
  --output docs/evidence/phase-5-shadow-live-report.json
```

The command requires the ignored `.env` file with development paper credentials
and `ALPACA_PAPER=true`. It exits before authentication if paper mode is absent or
false.

## What the output proves

- `data` identifies the live feeds, reference price, market state, and number of
  normalized option candidates.
- `features` records the feature version, completed source-bar window, regime, trend,
  volatility, relative volume, ATR, and relative strength.
- `agent` records the proposal, counter-evidence, critic verdict, final direction,
  confidence, and thesis expiry.
- `selection` explains how the two legs were chosen and reports conservative debit,
  maximum loss, maximum profit, and breakeven.
- `risk` shows why the candidate is blocked and the maximum quantity the observed
  budget could support.
- `safety` explicitly states that broker writes are impossible and that no order
  payload, account identifier, or equity value was emitted.

## First live result

The first run used broker time `2026-09-01T19:39:18Z` and produced:

- 98 completed SPY daily bars;
- a bearish thesis with 0.95 deterministic confidence;
- 323 normalized Indicative option candidates;
- a 765/755 bear-put debit-spread candidate expiring 2026-09-15;
- a conservative $3.86 debit and $386 defined maximum loss; and
- a blocked risk decision because execution was disabled, dry-run was active,
  broker state was deliberately unreconciled, and the closing-window gate was active.

The sanitized full record is in
`docs/evidence/phase-5-shadow-live-report.json`.

## Trust boundary

The deterministic shadow provider is a transparent test double for the future
external AI adapter. It already uses the exact proposal and critic schemas that the
model adapter must satisfy. Unknown keys, missing keys, non-string reasoning items,
invalid confidence, and invalid validity windows fail closed. The critic may approve,
downgrade, or reject, while deterministic confidence and risk gates retain final
authority.

The GET-only Alpaca client contains no public operation for submit, cancel, replace,
close, or exercise. The shadow orchestrator never builds an order intent. The MCP
profile further restricts the server to asset and market-data toolsets by omitting
`trading`.

## MCP verification and compatibility finding

The official Alpaca MCP 2.2.0 package initially resolved FastMCP 4.0.0 and failed
because it imports a module removed in that major version. Pinning FastMCP 3.1.0 fixed
the launch. The restricted server then exposed 32 tools, with no order-, position-,
account-, watchlist-, exercise-, close-, cancel-, or replace-named tool. A live
`get_stock_snapshot` call for SPY on IEX succeeded through MCP.

The proof at `docs/evidence/phase-5-mcp-readonly-proof.json` records the exact tool
names and a hash of the successful result while excluding raw market output and all
credentials.

## Next gate

Phase 5b connects a real structured AI provider behind the same strict schemas.
Phase 6 may then add a separately guarded Alpaca paper MLeg gateway. The first visible
entry in Alpaca's Orders page will only be allowed after reconciliation, idempotency,
stale-data, market-window, kill-switch, and tiny-size canary tests pass.
