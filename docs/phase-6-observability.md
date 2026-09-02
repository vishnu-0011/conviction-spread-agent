# Phase 6 — observability and demo cockpit

Phase 6 turns the sanitized Phase 5 shadow decision into a judge-facing story.
The dashboard is deliberately an observability surface, not an execution
surface: it contains no broker credentials, account identifiers, order form,
or order-submission route.

## What the cockpit explains

- the captured SPY reference price and market/feed state;
- the versioned bearish thesis, supporting evidence, counter-evidence, and
  invalidation condition;
- the adversarial critic verdict;
- the candidate funnel from contracts to eligible spreads;
- the selected 765/755 bear-put debit spread;
- debit, maximum loss, maximum profit, breakeven, expiry, and DTE;
- every deterministic reason that prevented an order; and
- data, MCP, reconciliation, and order-gateway health.

The headline intentionally distinguishes model approval from execution
authority: **the thesis survived the critic; the order did not**.

## Data provenance

The first version is a replayable presentation of the sanitized live shadow
record in `docs/evidence/phase-5-shadow-live-report.json`. It is not a
continuously refreshing quote terminal. Values came from the development Alpaca
paper account through GET-only API calls using the IEX stock feed and Indicative
options feed.

This choice keeps the public demo stable while the order gateway and broker
reconciliation are still absent. Phase 7 can replace the captured view with
broker-confirmed lifecycle events only after a separately authorized
one-contract paper canary.

## Run locally

```powershell
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

## Verification

- `npm run build` completes successfully with vinext.
- `npm audit --omit=dev --json` reports zero production vulnerabilities.
- The production route returned HTTP 200 during local validation.
- The exact validated source was saved and deployed as Sites version 1.
- The production deployment succeeded at
  <https://conviction-spread-agent.vv11njrfan.chatgpt.site>.

The deployment remains owner-only during active development. It must be made
public, with an explicit access change, before it is submitted as the judge
demo URL.

## Safety and account impact

- No order was placed.
- Execution remains disabled and dry-run remains active.
- Broker reconciliation remains false.
- No order gateway is installed in the dashboard.
- No Alpaca or OpenAI secret is bundled into the client.
- The production view contains no Alpaca account ID or unredacted response.

## Next bounded task

Build Phase 7's paper execution gateway and reconciliation adapter with
submission disabled by default. Before the first one-contract paper MLeg
canary, require an explicit operator authorization and re-run all market,
quote-freshness, loss-budget, duplicate, and account-state gates.
