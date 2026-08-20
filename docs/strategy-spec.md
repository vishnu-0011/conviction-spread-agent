# Provisional strategy specification

This specification will change only when platform tests or out-of-sample evidence
justify the change. Thresholds are starting hypotheses, not optimized facts.

## Instrument and thesis

The agent expresses a bullish thesis with a **bull call debit spread** and a bearish
thesis with a **bear put debit spread**. Both have a known maximum loss equal to the
net debit paid (multiplied by the standard contract multiplier and quantity).

For a one-contract vertical with strike width `W` and debit `D`, ignoring exercise,
assignment, and transaction effects:

- maximum loss = `D × 100`;
- maximum profit = `(W − D) × 100`;
- bull-call breakeven = long-call strike + `D`;
- bear-put breakeven = long-put strike − `D`.

The short leg reduces entry cost and some theta/volatility exposure, while also
capping profit. We choose that trade-off deliberately for a short competition and a
defined-risk system.

## Initial universe

`SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA`

This is provisional. A symbol remains eligible only when its underlying and option
quotes pass live liquidity and freshness gates. A smaller reliable universe is
better than a broad universe with poor fills.

## Decision cadence

- Evaluate market regime after sufficient opening data exists.
- Scan periodically during regular US market hours.
- Avoid new entries immediately after the open and near the close.
- Monitor positions and broker state more frequently than entry scans.
- Close or reduce risk before expiration; 0DTE entries are prohibited.

Exact schedules will follow Alpaca clock/calendar validation and observed rate limits.

## Candidate funnel

### 1. Market regime

Classify `BULL`, `BEAR`, or `NEUTRAL` using a small, reproducible feature set such as:

- SPY/QQQ trend alignment over slow and fast horizons;
- realized volatility percentile;
- breadth or universe participation; and
- whether price behavior is orderly enough for directional exposure.

Neutral or contradictory regimes raise the confidence threshold or produce no trade.

### 2. Underlying setup

Starting evidence set:

- trend alignment;
- breakout or pullback continuation;
- relative volume;
- ATR-normalized distance from invalidation; and
- relative strength versus the broad-market reference.

Every feature must use data available at the decision timestamp. The initial model is
a transparent scorecard; complexity is added only if walk-forward evidence supports it.

### 3. Structured AI thesis

The AI receives trusted, normalized features and returns schema-validated fields:

- `direction` (`BULLISH`, `BEARISH`, or `PASS`);
- supporting evidence and counter-evidence;
- a price-based invalidation condition;
- confidence and confidence rationale;
- expected holding horizon; and
- a short human-readable thesis.

The AI cannot supply executable prices, quantities, raw option symbols, or override
risk limits. A critic can reject or downgrade inconsistent theses.

### 4. Contract construction

Starting hypotheses:

- approximately 14–35 calendar days to expiration;
- same underlying, option type, and expiration for both legs;
- long leg around 0.55–0.65 absolute delta when reliable Greeks exist;
- short leg around 0.25–0.40 absolute delta;
- narrow, liquid widths appropriate to the underlying;
- positive net debit below spread width;
- both legs have recent, non-crossed quotes and acceptable relative spreads; and
- use a multi-leg limit order priced from a conservative executable reference.

If Greeks are absent or unreliable, a documented moneyness-based selector replaces
delta selection. The system never invents missing Greeks.

## Risk policy

Initial conservative limits:

- maximum loss per trade: 0.50% of account equity;
- maximum aggregate open risk: 2.00% of account equity;
- maximum open strategies: 3;
- daily loss halt: 1.50% of start-of-day equity;
- weekly loss halt: 4.00% of start-of-week equity;
- minimum thesis confidence: 0.72;
- one active directional thesis per underlying;
- no naked short options, averaging down, 0DTE, or risk-limit overrides;
- no entry when market/data/account/reconciliation health is uncertain.

These values are configuration, but production startup will display and hash the
effective configuration so a quiet parameter change cannot escape the audit trail.

## Position management

Candidate exit reasons, evaluated in deterministic order:

1. emergency or session risk halt;
2. broker/account inconsistency;
3. thesis invalidation;
4. loss threshold;
5. profit capture as the spread realizes a large part of available profit;
6. time stop or declining expected value;
7. expiration-risk cutoff; and
8. end-of-strategy lifecycle.

The exact price thresholds require simulation and paper observation. Multi-leg close
behavior and partial-fill semantics must be platform-tested before activation.

## What counts as autonomous

Once deliberately started, the system can scan, decide, reject, size, submit, monitor,
exit, reconcile, and halt without per-trade human approval. A human may always stop it,
but cannot force a trade around the deterministic gates.

## Falsifiable project claim

> Combining regime-aware directional evidence with structured thesis critique and
> defined-risk spread construction produces better risk-adjusted paper outcomes than
> an ungated momentum trigger over the declared evaluation set.

The baseline and evaluation design in `docs/roadmap.md` exist to test this claim.
