# Complete build roadmap

This roadmap treats the hackathon submission as a small trading system, not a
prompt that happens to place orders. Each phase has an explicit exit gate so we
do not hide uncertainty behind a polished dashboard.

## Target outcome

Submit an autonomous **Options Alpha Agent** that:

1. observes a liquid US equity/ETF universe;
2. classifies market regime and finds directional setups;
3. writes a falsifiable, structured thesis;
4. constructs a defined-risk bull-call or bear-put vertical spread;
5. passes deterministic account, market, liquidity, sizing, and loss gates;
6. submits and manages the multi-leg paper order through Alpaca;
7. explains entries, rejections, exits, and P&L in a demo dashboard; and
8. leaves a complete evidence trail tied to the fresh judging account.

## Phase 0 — rules, product definition, and safety foundation

**Questions to close**

- Is pre-event implementation allowed, or only research/design before August 28?
- What exact interval and account state will judges use for P&L?
- Must MCP/CLI directly place orders, or is demonstrable project usage sufficient?
- Which US jurisdictions and options levels are available to each teammate?

**Work**

- Preserve an official rules snapshot and submission checklist.
- Select Track 1 and define the project claim.
- Establish paper-only credentials and secret handling.
- Define strategy invariants, risk budgets, decision records, and kill switch.
- Create a development paper account; reserve a brand-new account for final judging.

**Exit gate**

- Every non-negotiable rule has a source or is explicitly marked unresolved.
- Safety calculations have unit tests.
- Execution defaults to disabled and dry-run.

## Phase 1 — Alpaca platform validation spike

**Work**

- Authenticate against the paper Trading API.
- Read account, options approval level, clock, calendar, assets, and positions.
- Retrieve the configured universe, option contracts, chains, quotes, and Greeks
  that the subscribed data plan actually exposes.
- Verify timestamps, freshness, pagination, empty responses, and rate-limit errors.
- Submit, observe, replace/cancel, and close the smallest acceptable test order.
- Verify an atomic two-leg vertical order, its nested response, fill behavior, and
  closing `position_intent` values.
- Inventory Alpaca MCP tools and CLI JSON output against the same development account.

**Exit gate**

- A redacted capability report records observed responses and limitations.
- No strategy assumption depends on unverified API behavior.
- The executor can remain in dry-run while producing a valid order preview.

## Phase 2 — data and feature pipeline

**Work**

- Build typed adapters for clocks, calendars, bars, snapshots, contracts, and chains.
- Normalize all timestamps to UTC internally and US/Eastern at the strategy boundary.
- Cache slowly changing contract metadata; never treat quotes as cacheable metadata.
- Reject stale or crossed quotes and contracts without usable bid/ask information.
- Compute trend, breakout, realized volatility, relative volume, ATR, and relative
  strength features without look-ahead bias.
- Record every input snapshot used by a decision.

**Exit gate**

- Replaying an identical snapshot yields an identical feature set.
- Missing/stale data produces `NO_TRADE`, never guessed values.

## Phase 3 — strategy research and simulation

**Work**

- Establish simple baselines: buy-and-hold, random-direction, and underlying-only
  momentum. These prevent us from mistaking market beta for agent skill.
- Walk forward through available historical underlying and options data.
- Test regime and entry thresholds on earlier periods; reserve a final untouched
  period for evaluation.
- Model bid/ask fills, rejected orders, fees if applicable, and conservative slippage.
- Compare single-signal and ablated variants to learn which features contribute.
- Freeze a small parameter set; do not optimize on the hackathon week.

**Metrics**

- Net and realized P&L, maximum drawdown, win rate, payoff ratio, profit factor.
- Exposure, turnover, rejection rate, fill rate, average slippage, and time in trade.
- P&L per unit of maximum capital at risk.

**Exit gate**

- The strategy beats its declared baselines in walk-forward testing or is honestly
  labeled experimental.
- Results include losing periods and sensitivity analysis, not one best run.

## Phase 4 — spread construction and deterministic risk engine

**Work**

- Choose same-expiration bull-call or bear-put legs from liquid chains.
- Enforce DTE, strike ordering, spread width, net-debit, quote-quality, and buying-
  power constraints.
- Size from maximum loss, never from desired profit.
- Apply per-trade, total-open-risk, concentration, position-count, daily-loss, and
  weekly-loss limits.
- Prohibit averaging down, naked legs, 0DTE, trading on stale data, and entries near
  market close.
- Define a fail-closed state machine for intent, submit, acknowledge, partial/fill,
  cancel, close, reconcile, and terminal failure.

**Exit gate**

- Property and scenario tests cover invalid strikes, zero/negative debits, duplicate
  decisions, stale quotes, partial fills, restarts, and broker/local disagreement.
- Every allowable order has bounded loss known before submission.

## Phase 5 — autonomous agent and MCP/CLI integration

**Work**

- Schedule scan, decision, position-monitor, reconciliation, and end-of-day jobs.
- Give the AI a strict JSON schema: direction, evidence, counter-evidence,
  invalidation, confidence, and expiry of the thesis.
- Prevent the AI from choosing arbitrary symbols, quantities, account settings, or
  bypass flags; those come from trusted code and broker data.
- Add an adversarial critic pass that can downgrade or reject a thesis.
- Use Alpaca MCP for visible, structured agent interaction in the demo. Add CLI only
  where it improves operations or reproducibility.
- Add idempotency keys, leases, timeouts, bounded retries, and a manual kill switch.

**Exit gate**

- The service can run unattended for a full paper session and restart safely.
- Re-running the same decision cannot create a duplicate position.
- Invalid model output becomes `NO_TRADE`.

## Phase 6 — observability and demo application

**Views**

- Account equity, buying power, realized/unrealized P&L, and current risk.
- Market regime, candidate funnel, active theses, confidence, and invalidations.
- Spread legs, debit, maximum loss/profit, breakeven, DTE, and live marks.
- Decision timeline covering `TRADE`, `NO_TRADE`, risk rejection, order updates,
  and exits.
- Strategy health: API status, data freshness, scheduler heartbeat, and kill switch.

**Exit gate**

- A judge can understand one complete trade in under two minutes.
- The UI never implies a fill before Alpaca confirms it.

## Phase 7 — paper burn-in and controlled iteration

**Work**

- Shadow mode first: generate decisions without orders.
- Canary mode second: one contract, one position, tight session loss cap.
- Compare expected and observed quotes/fills; investigate every discrepancy.
- Run disconnect, stale-data, rejected-order, restart, and forced-kill-switch drills.
- Freeze strategy logic before moving to the final account; fix only correctness and
  reliability defects after the freeze.

**Exit gate**

- At least one complete autonomous entry-to-exit lifecycle is evidenced.
- No unresolved critical reconciliation or risk-control defects.

## Phase 8 — fresh judging account and competition operation

**Work**

- Create a new dedicated paper account only when the strategy is stable.
- Record the account ID and verify options level, buying power, market-data access,
  and credentials without placing unrelated manual trades.
- Start with canary limits, monitor health, and preserve all logs and screenshots.
- Keep an operator runbook for start, pause, reconcile, emergency stop, and recovery.

**Exit gate**

- Every account trade maps to a decision, order payload hash, and lifecycle log.
- The account ID in the app, evidence, and final submission is identical.

## Phase 9 — presentation and submission

**Deliverables**

- Public GitHub repository with one-command setup and an architecture diagram.
- Hosted demo and stable application URL.
- Cover image, concise slide deck, and recorded demo.
- Project title, short/long descriptions, technology/category tags, and account ID.
- Up to five substantive X/LinkedIn build-in-public posts tagging both organizers.

**Recommended demo narrative**

1. State the problem: directional conviction is easy; disciplined expression is hard.
2. Show the live market regime and candidate funnel.
3. Open one thesis with supporting and contradicting evidence.
4. Show deterministic spread construction and maximum loss before execution.
5. Show the Alpaca MCP/API action and broker-confirmed lifecycle.
6. Show risk rejection and kill switch—not only a winning trade.
7. Close with paper-account performance and honest limitations.

## Current critical path

`rules → API capability spike → reliable data → risk engine → execution state machine
→ shadow session → canary session → dashboard/demo → fresh account → submission`

P&L matters, but a high-variance last-minute strategy can erase both P&L and technical
credibility. Reliability and bounded risk remain release requirements.
