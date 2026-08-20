# Phase 1: read-only Alpaca preflight

The first authenticated step is intentionally incapable of placing, replacing,
canceling, exercising, or closing an order. It sends GET requests only.

## Before running it

1. Create or use a **development** Alpaca paper account. Do not create the fresh final
   judging account yet.
2. Copy `.env.example` to `.env` locally.
3. Add the paper account's API key and secret to `.env`. Never paste them into chat,
   source code, screenshots, or commits.
4. Leave these values unchanged:

   ```text
   ALPACA_PAPER=true
   CSA_EXECUTION_ENABLED=false
   CSA_DRY_RUN=true
   ```

## Run

```powershell
python scripts/preflight.py --underlying SPY
```

Optionally store the masked report in the gitignored private-data directory:

```powershell
python scripts/preflight.py --underlying SPY --output data/private/preflight.json
```

## What it proves

- Credentials authenticate specifically against `paper-api.alpaca.markets`.
- The account is active/unblocked with positive options buying power.
- `options_trading_level` is at least 3.
- Alpaca's clock is reachable.
- Tradable SPY contracts exist in the explicit 14–35 DTE window.
- The account can retrieve Indicative option snapshots.
- It reports, but does not require, observed Greeks and IV because Alpaca documents
  those values as nullable.

The output masks both account identifiers. Record the full `id` and `account_number`
privately later; the event wording does not yet disambiguate which one its submission
form will call the account ID.

## What it does not prove

- OPRA entitlement or realistic live fill quality.
- MLeg order acceptance, cancel/replace, closing, or stream recovery.
- MCP MLeg-array serialization in the exact client.
- Paper exercise or assignment behavior.

Those are separate controlled tests. We will not add the first POST request until the
read-only report passes and the order harness has a second explicit enablement gate.
