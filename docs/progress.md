# Build progress

This is the public engineering journal for **ConvictionSpread**. Each entry records
what changed, how it was verified, what remains uncertain, and the next bounded task.
It intentionally excludes credentials, full development-account identifiers, and
unredacted broker responses.

## Milestone 0 — research and safety foundation

**Date:** 2026-08-20
**Status:** Complete

### Shipped

- Selected the Options Alpha Agents track and narrowed the product to regime-aware
  bull-call and bear-put debit spreads.
- Researched current Alpaca paper, options data, Level 3 MLeg, MCP v2, CLI, streaming,
  and paper-simulation behavior using official sources.
- Defined the complete build-to-submission roadmap and component trust boundaries.
- Implemented immutable option quote, contract, thesis, and vertical-spread records.
- Implemented maximum loss/profit and breakeven calculations.
- Added deterministic pre-trade gates for confidence, data health, quote freshness,
  quote width, DTE, duplicate exposure, buying-risk budget, and daily/weekly loss halts.
- Added atomic Alpaca MLeg entry and exit payload construction with explicit position
  intents, deterministic client order IDs, and payload hashes.
- Added a GET-only Alpaca paper-account preflight. It refuses non-paper mode and masks
  account identifiers in its output.

### Evidence

- 18 unit tests pass on Python 3.13.
- The preflight exits safely with code 2 when credentials are absent.
- Execution is disabled and dry-run is enabled by default.
- No order submission, cancel, replace, exercise, or close operation exists yet.

### What research changed

- Options exits will be agent-managed opposing MLeg orders because bracket/OCO/OTO
  classes are not officially documented for options.
- The data layer treats Greeks and IV as nullable.
- Feed identity is part of every decision because Basic uses Alpaca Indicative rather
  than OPRA.
- Production execution will use typed `alpaca-py`; MCP v2 remains the required visible
  agent integration and must pass a client-specific MLeg-array test.

### Open questions

- Does the development paper account expose Level 3 and positive options buying power?
- Is its feed Indicative only, or is OPRA entitlement available through the event?
- Which field will the event form call the Alpaca account ID: UUID `id` or
  `account_number`?
- Do event rules permit implementation before the official start, or only preparation?

### Next task

Run the read-only development-account preflight, archive a masked capability report,
and implement typed Alpaca adapters from the observed response shapes.

## Task 1.1 — Phase 1 validation plan

**Date:** 2026-08-20
**Status:** Complete

### Shipped

- Established a learning mission tied directly to building and defending the agent.
- Curated first-party Alpaca learning resources and an official community channel.
- Added a short, printable lesson explaining the read-only account preflight.
- Defined the exact Phase 1 pass criteria and the boundary before order validation.

### Verification and safety impact

- The lesson points to the existing GET-only preflight and keeps credentials local.
- No broker request was run and no execution setting changed.
- Project tests remain the release gate; this documentation task changes no runtime code.

### Next task

Configure development paper credentials locally and run the GET-only capability report.

## Task 1.2 — Paper-key setup guide

**Date:** 2026-08-20
**Status:** Complete

### Shipped

- Verified the current paper-account key workflow against Alpaca's March 2026 guide.
- Added a click-by-click lesson covering signup, MFA, paper-account selection, key
  generation, one-time secret handling, local `.env` storage, and Git verification.
- Added a printable paper-key security checklist.

### Verification and safety impact

- The guide uses a development paper account and reserves the fresh judging account.
- It requires `git check-ignore .env` before authenticated testing.
- No credentials were created, read, stored, or committed by the project.
- No broker request or runtime behavior changed.

### Next task

The user creates the development keys locally, confirms `.env` is ignored, and runs
the GET-only preflight.

## Milestone 1 — Paper platform capability validated

**Date:** 2026-08-20
**Status:** Complete

### Shipped

- Authenticated a development paper account and verified active/unblocked status,
  Level 3 options permission, and $100,000 options buying power.
- Diagnosed an empty selected-snapshot result by comparing near-money selected
  snapshots, latest quotes, and the underlying-wide option chain.
- Changed preflight selection from the first metadata records to tradable contracts
  ranked near the IEX underlying price within a ±5% strike window.
- Added a reusable read-only option-data diagnostic and regression tests.
- Published a sanitized capability artifact with no account or request identifiers.

### Evidence

- The corrected preflight has zero critical failures and reports
  `ready_for_order_validation: true`.
- 100/100 discovered near-money contracts were explicitly tradable.
- 14/20 selected contracts returned snapshots; all 14 included Greeks and IV.
- The chain comparison returned 462 snapshots while the market was closed, ruling out
  session timing as the root cause.
- 20 local tests pass.

### Safety and account impact

- Every authenticated request was GET-only.
- No order, position, account configuration, exercise, or other mutation occurred.
- Credentials and account identifiers remain outside Git.

### Next task

Implement typed Alpaca account, clock, underlying-snapshot, contract, and option-snapshot
adapters using sanitized fixtures derived from the validated response shapes.

## Milestone 2 — Data and feature pipeline

**Date:** 2026-08-24
**Status:** Complete

### Shipped

- Added typed Alpaca bar adapters and immutable `Bar` / `BarSeries` records.
- Added a deterministic feature engine with trend, realized volatility, relative
  volume, ATR, relative strength, and regime classification.
- Enforced look-ahead-free feature computation with versioned `FeatureSnapshot`
  records that include source bar timestamps for replay.

### Evidence

- Feature replay tests confirm identical snapshots produce identical features.
- Missing history raises explicit errors instead of producing guessed values.
- 35 total unit tests pass.

### Safety impact

- No broker requests were added.
- Feature code is read-only and deterministic.

### Next task

Run walk-forward simulation against baselines and archive the report artifact.

## Milestone 3 — Strategy research and simulation

**Date:** 2026-08-24
**Status:** Complete

### Shipped

- Added conservative bid/ask fill modeling with slippage, fees, and deterministic
  entry rejection handling.
- Implemented three baselines: buy-and-hold, random-direction, and underlying
  momentum, plus the conviction spread strategy signal.
- Built walk-forward evaluation with train / validation / test fold boundaries.
- Added performance metrics: net P&L, drawdown, win rate, payoff ratio, profit
  factor, rejection rate, and P&L per unit of risk.
- Added a fixture-backed simulation script and archived walk-forward evidence.

### Evidence

- `python scripts/run_simulation.py` runs without API credentials.
- Walk-forward report saved to `docs/evidence/phase-3-walkforward-report.json`.
- 35 unit tests pass including simulation and walk-forward integration tests.

### Honest limitations

- Spread outcomes use a simplified intrinsic-value model with synthetic quotes;
  live Alpaca option chains will replace this when credentials are available.
- The fixture is a monotonic SPY uptrend; real mixed-regime data is required
  before treating results as out-of-sample proof.

### Next task

Implement deterministic spread construction and the final risk/lifecycle boundary.

## Milestone 4 — spread construction and deterministic lifecycle

**Date:** 2026-09-02
**Status:** Complete

### Shipped

- Added typed normalization for tradable Alpaca option contracts and quote snapshots.
- Added deterministic bull-call and bear-put selection with DTE, quote, width, debit,
  delta-band, and missing-Greeks fallback rules.
- Added buying-power, duplicate-decision, and market-session admission gates.
- Added replayable partial-fill, cancellation, restart, close, and reconciliation states.

### Evidence

- 55 tests pass; 20 cover Phase 4.
- Python compilation passes for scripts, source, and tests.
- Sanitized evidence: `docs/evidence/phase-4-risk-lifecycle-report.json`.

### Safety and limitations

- No broker mutation or order-submission path was added.
- Partial exposure cannot be forgotten after cancellation or software failure.
- Selection uses normalized fixtures; live shadow scanning and controlled Alpaca MLeg
  lifecycle validation remain Phase 5 work.

### Next task

Build the Phase 5 shadow agent and Alpaca MCP/CLI integration with submission disabled.

## Update format for future tasks

Every completed task should add an entry containing:

1. objective and date;
2. shipped behavior;
3. verification evidence;
4. decisions or surprises;
5. safety/account impact; and
6. the next bounded task.

The corresponding Git commit should be narrow and use a descriptive conventional
prefix such as `feat:`, `fix:`, `test:`, `docs:`, or `chore:`.
