# Phase 7b — reconciled paper-canary runbook

## Outcome

Phase 7b connects the live shadow decision to the disabled-by-default Phase 7a
execution gateway. The default command is GET-only. It reads the paper account,
positions, and open orders; requires an entirely flat Level 3 account; reconstructs
the exact selected spread; reruns deterministic risk; and prints the complete MLeg
payload, debit, maximum loss, maximum profit, breakeven, and payload hash.

The first paper POST requires all of the following in the same process:

1. the submit command flag;
2. ALPACA_CANARY_SUBMISSION=true;
3. CSA_EXECUTION_ENABLED=true;
4. CSA_DRY_RUN=false;
5. CSA_KILL_SWITCH=false;
6. a fresh, market-open, data-healthy, risk-approved one-contract spread;
7. no positions and no open orders in the paper account; and
8. an interactive confirmation containing the exact client order ID.

The authorization is bound to the exact payload SHA-256 and expires after 60 seconds.
The gateway still rejects a risk decision older than 10 seconds. A timeout after POST
is never retried because the broker outcome may be unknown.

## Current live evidence

The September 3 overnight preview found a genuine IWM bearish thesis:

- confidence: 0.95;
- completed-bar relative volume: 1.316763;
- paper account: active, flat, and reconciled;
- positions: 0;
- open orders: 0; and
- execution result: blocked because overnight option quotes were stale.

This is expected. Options should not be entered from stale overnight prices. The
sanitized record is docs/evidence/2026-09-03-iwm-canary-preview.json.

## Market-session commands

US regular trading opens at 9:30 a.m. ET (7:00 p.m. IST while New York is on daylight
saving time). The risk policy blocks the first 15 minutes, so run the actionable
preview after 7:15 p.m. IST:

~~~powershell
$env:PYTHONPATH = "src"
python scripts/paper_canary.py --underlying IWM --output data/private/iwm-canary-live-preview.json
~~~

Proceed only when the record says:

~~~text
ready_for_operator_approval: true
broker_reconciliation.reconciled: true
risk.approved: true
order.quantity: 1
~~~

If it remains blocked, preserve the result. Do not weaken confidence, liquidity,
quote-age, market-hours, or risk thresholds to manufacture a trade.

To request the exact one-contract paper canary:

~~~powershell
$env:ALPACA_CANARY_SUBMISSION = "true"
$env:CSA_EXECUTION_ENABLED = "true"
$env:CSA_DRY_RUN = "false"
$env:CSA_KILL_SWITCH = "false"

python scripts/paper_canary.py --underlying IWM --submit --output data/private/iwm-canary-submission.json
~~~

The command prints the exact order first and then asks for:

~~~text
APPROVE <exact-client-order-id>
~~~

Type it promptly. If quotes or the risk decision have become stale, the gateway fails
closed and the command must be rerun from a fresh preview.

Immediately restore the safe shell defaults afterward:

~~~powershell
$env:ALPACA_CANARY_SUBMISSION = "false"
$env:CSA_EXECUTION_ENABLED = "false"
$env:CSA_DRY_RUN = "true"
$env:CSA_KILL_SWITCH = "true"
~~~

Then verify the exact client order ID and MLeg status in Alpaca's paper dashboard.
An accepted order is not a fill; only Alpaca's broker status may be presented as
broker-confirmed.

Keep the complete broker-derived record under ignored `data/private/`. Publish only
the account metadata and paper results you deliberately choose for the submission.

## Model-backed variant

If a valid OpenAI project key and explicit supported model are already configured,
add the ai-provider openai option. This makes the structured thesis and critic calls
while leaving contract selection, order sizing, and risk authority deterministic.

Do not claim a live external-model run unless this command actually succeeds and the
saved provider metadata identifies the model call.

## What this can and cannot prove

A broker-confirmed canary proves autonomous decision flow, exact MLeg construction,
risk gating, and Alpaca paper execution. One trading day cannot establish durable
profitability. Present the walk-forward report as research evidence and the paper
canary as execution evidence; disclose the limited live sample rather than calling a
single winning trade an efficiency measurement.

## Official Alpaca references

- https://docs.alpaca.markets/us/reference/postorder
- https://docs.alpaca.markets/us/docs/options-level-3-trading
- https://docs.alpaca.markets/us/docs/orders-at-alpaca
