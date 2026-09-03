# Phase 7d — controlled paper MLeg close

Phase 7d prevents the one-contract canary from becoming an unmanaged position. The
close path is separate from entry, disabled by default, and accepts only the exact
two-leg position created by the saved canary record.

## Close preview

First confirm the entry order is filled with the read-only report. Then run:

```powershell
$env:PYTHONPATH = "src"
python scripts/paper_close.py `
  --entry-record data/private/iwm-canary-submission.json `
  --output data/private/iwm-close-preview.json
```

The command reconstructs the original entry and verifies its client order ID and
payload hash. It then reads the exact entry order from Alpaca, advances the durable
lifecycle only if the broker confirms it, requires exactly one long and one short
option position matching the saved spread, reads fresh quotes for those exact
contracts, and calculates a conservative close credit as long-leg bid minus
short-leg ask.

Proceed only when `ready_for_operator_approval` and
`broker_positions_reconciled` are both `true`, the lifecycle is `open`, and the
payload shows `sell_to_close` plus `buy_to_close` for the expected symbols.

## Submit one close

Set only the separate close gate:

```powershell
$env:ALPACA_CLOSE_SUBMISSION = "true"
$env:CSA_EXECUTION_ENABLED = "true"
$env:CSA_DRY_RUN = "false"

python scripts/paper_close.py `
  --entry-record data/private/iwm-canary-submission.json `
  --submit `
  --output data/private/iwm-close-submission.json
```

The command prints the exact payload and asks for:

```text
APPROVE CLOSE <exact-exit-client-order-id>
```

The gateway rechecks quote age after confirmation, binds the exact exit client ID
and payload hash to durable lifecycle state before POST, sends one MLeg request, and
never retries an uncertain POST. Recovery uses only exact client-order-ID lookup.

If the POST times out or its result is uncertain, do not run `--submit` again. The
first command already saved the exact close preview. Reconcile it with GET only:

```powershell
python scripts/paper_close.py `
  --entry-record data/private/iwm-canary-submission.json `
  --exit-record data/private/iwm-close-submission.json `
  --output data/private/iwm-close-reconciliation.json
```

The same lookup command can be rerun to advance an acknowledged close to `closed`
after Alpaca reports a fill. It cannot submit or resubmit an order.

The kill switch may remain active while closing. It prevents new exposure and must
not trap an existing risk position. Market-open, paper-only, one-contract, broker
position, fresh-quote, short authorization, and exact confirmation checks still
apply.

Restore safe defaults immediately:

```powershell
$env:ALPACA_CLOSE_SUBMISSION = "false"
$env:CSA_EXECUTION_ENABLED = "false"
$env:CSA_DRY_RUN = "true"
$env:CSA_KILL_SWITCH = "true"
```

Finally run `paper_report.py` again. An acknowledged close is not a completed close;
only broker status `filled`, zero matching positions, and lifecycle `closed` prove
that the spread is no longer open.

## Scope

This is an operator-initiated safety close for the first canary, not yet a portfolio
of unattended profit-target, stop, or expiration rules. It completes the exact
entry-to-exit mechanics without weakening the first-write safety boundary.
