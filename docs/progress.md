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

## Milestone 5a — live read-only shadow autonomy

**Date:** 2026-09-02
**Status:** Complete

### Shipped

- Added exact structured contracts for the thesis proposal and adversarial critic.
  Missing, additional, mistyped, or invalid fields fail closed.
- Added a minimal Alpaca client whose complete network boundary is fixed to GET and
  whose public surface contains no broker-write operation.
- Added an authenticated shadow runner that reads completed daily bars, the underlying
  snapshot, paper account capabilities, broker clock, option contracts, and option
  snapshots before producing one sanitized decision record.
- Reused the Phase 2 feature engine, Phase 4 option normalization and spread selector,
  and Phase 4 risk boundary instead of creating a parallel demo path.
- Added an Alpaca MCP v2.2.0 profile that requests `assets`, `stock-data`, and
  `options-data` while deliberately omitting the `trading` toolset.
- Diagnosed an upstream FastMCP 4.0.0 incompatibility, pinned FastMCP 3.1.0, and added
  a reproducible stdio verifier that keeps the server open through each response.

### Live evidence

- The first live scan processed 98 completed SPY bars and 323 normalized Indicative
  option candidates.
- It formed a bearish 765/755 put debit spread expiring 2026-09-15 with a conservative
  $3.86 debit, $386 maximum loss, and $614 maximum profit.
- The final risk boundary rejected submission because execution was disabled, dry-run
  was active, broker state was intentionally unreconciled, and only 21 minutes remained
  before market close.
- The public-safe record is `docs/evidence/phase-5-shadow-live-report.json`.
- The restricted MCP registry exposed 32 read-shaped tools and no account- or
  trading-named tools; a live IEX SPY snapshot call succeeded through MCP. Sanitized
  proof is stored in
  `docs/evidence/phase-5-mcp-readonly-proof.json`.
- 64 tests pass and Python compilation succeeds across source, scripts, and tests.

### Safety, decisions, and limitations

- The shadow orchestrator never constructs an order intent, and the live run made no
  broker mutation. No order or position should appear in Alpaca for this milestone.
- The output excludes keys, account identifiers, request identifiers, and equity values.
- Candidate identity is hashed into a deterministic decision ID, independent of input
  ordering, so the same observation cannot silently become a new logical decision.
- The deterministic agent was the only provider at this milestone. The MCP proof
  intentionally stores only a response hash, not the raw live snapshot.
- Portfolio exposure is deliberately marked unreconciled in shadow mode; it must not be
  treated as execution-ready sizing.

### Next task

Build Phase 5b: connect a real structured AI provider behind the exact schemas and
archive deterministic-versus-model comparison cases. Only then begin Phase 6 with a
separately guarded, one-contract paper MLeg canary and broker reconciliation.

## Milestone 5b — structured external AI adapter

**Date:** 2026-09-02
**Status:** Integration-ready; live provider validation pending

### Shipped

- Added an opt-in OpenAI Responses API adapter with separate structured proposal and
  critic calls; deterministic mode remains the zero-cost default.
- Defined closed JSON schemas with all fields required and repeated local validation
  through the existing `AgentProposal` and `CriticVerdict` contracts.
- Limited model input to the versioned feature snapshot and underlying reference price.
  The adapter exposes no tools and sends no Alpaca credential, account, portfolio,
  contract, quantity, or order data.
- Added bounded timeouts and retries, explicit model selection, refusal/incomplete
  handling, response hashing, token-count evidence, and `store: false`.
- Added deterministic-versus-model comparison metadata without allowing either model
  call to control contract selection, sizing, execution, or risk overrides.

### Verification

- Six focused tests use an in-memory transport and incur no model cost.
- Tests cover exact request shape, closed schemas, hostile extra fields, incomplete
  responses, explicit model selection, data minimization, and final execution blocking.
- 70 project tests pass and Python compilation succeeds across source, scripts, and
  tests.
- Evidence: `docs/evidence/phase-5b-structured-model-report.json`.

### Safety and limitation

- No paid external-model call was made because no OpenAI project key, explicit model,
  or API budget was authorized for this run.
- The external path is opt-in with `--ai-provider openai`; the default path performs
  no OpenAI request.
- A successful external thesis remains shadow-only with execution disabled, dry-run
  active, and broker state unreconciled.

### Next task

Configure a local OpenAI project key, explicit supported model, and budget, then save
one sanitized external-provider shadow result. Phase 6 builds the judge-facing
observability surface; Phase 7 adds an execution gateway with submission disabled by
default and prepares a separately approved one-contract Alpaca paper canary.

## Milestone 6 — judge-facing decision cockpit

**Date:** 2026-09-02
**Status:** Complete; production access remains owner-only

### Shipped

- Added a dark, responsive decision cockpit that narrates one complete captured live
  shadow decision from market observation through thesis, critic, spread construction,
  and final deterministic risk rejection.
- Visualized the 323 → 316 → 11,534 → 1 → 0 decision funnel, the selected 765/755
  bear-put spread, debit, bounded payoff, breakeven, feature snapshot, counter-evidence,
  timeline, and system health.
- Added an explicit safety proof showing that execution is disabled, dry-run is active,
  broker state is unreconciled, and no order gateway is installed.
- Generated and wired a project social-preview card containing no account or credential
  data.
- Deployed Sites version 1 at
  <https://conviction-spread-agent.vv11njrfan.chatgpt.site>.

### Verification

- The final vinext production build completes successfully.
- The production dependency audit reports zero vulnerabilities.
- The local production route returned HTTP 200.
- Sites reports the production deployment succeeded.
- Evidence: `docs/evidence/phase-6-dashboard-report.json`.

### Safety and limitations

- The dashboard replays a sanitized captured decision; it does not continuously refresh.
- No paper order was placed and no broker-write surface exists in the dashboard.
- The production deployment is owner-only and must be explicitly made public before
  it is submitted as the judge demo URL.

### Next task

Build Phase 7's disabled-by-default paper execution gateway and broker reconciliation,
then request explicit authorization before a one-contract paper MLeg canary.

## Milestone 7a — disabled-by-default paper MLeg gateway

**Date:** 2026-09-02
**Status:** Gateway-ready; live canary not authorized

### Shipped

- Added a narrow Alpaca client fixed to the paper host and only two endpoints: POST
  `/v2/orders` for a typed MLeg intent and GET `/v2/orders:by_client_order_id` for
  recovery.
- Added a one-contract execution boundary that requires paper mode, execution enabled,
  dry-run off, broker reconciliation, kill switch clear, explicit operator approval,
  a fresh deterministic risk decision, and a lifecycle matching durable state.
- Bound the short-lived authorization to the exact client order ID and payload SHA-256.
- Added atomic monotonic lifecycle persistence and wrote `ENTRY_SUBMIT_REQUESTED` before
  network I/O.
- Prohibited automatic POST retries after uncertain outcomes; recovery can only look up
  the original client order ID.
- Preserved non-zero exposure when a canceled or rejected parent reports a partial fill.

### Verification

- 10 focused tests cover default blocking, exact POST shape, stale risk, the one-contract
  cap, exact-order authorization, uncertain outcomes, missing orders, mismatched broker
  responses, terminal partial fills, status mapping, and persistence regression.
- All 80 project tests pass and Python compilation succeeds.
- The Phase 7 tests use fake transports and temporary lifecycle stores.
- Evidence: `docs/evidence/phase-7a-gateway-readiness-report.json`.

### Safety and account impact

- No Phase 7 test made an Alpaca request.
- No order was submitted, canceled, replaced, or filled.
- There is no live canary command; operator approval must be obtained for one exact
  fresh paper order before the gateway is enabled.
- Current Alpaca request and lifecycle behavior was checked against official order,
  MLeg, client-order-ID lookup, and order-status documentation.

### Next task

Build the pre-canary portfolio/open-order reconciliation and exact-order preview, then
request explicit approval for a one-contract development-paper MLeg submission during
a healthy market window.

## Maintenance — Windows timezone portability

**Date:** 2026-09-03
**Status:** Complete

### Issue and fix

- The shadow runner failed on Windows before contacting Alpaca because Python's
  standard library could not resolve `America/New_York` without an installed IANA
  timezone database.
- Added and pinned `tzdata==2026.3` as a project dependency.
- Installed the dependency in the repository virtual environment and confirmed
  `ZoneInfo("America/New_York")` loads successfully.
- Added the missing environment-install step to the main runbook.

### Live verification

- The authenticated GET-only shadow scan completed with exit code 0.
- It processed 97 completed SPY bars and observed an IEX reference price of $765.20.
- The deterministic agent returned PASS because relative volume was below its entry
  threshold; the market was also closed.
- No option spread, risk approval, order payload, or broker write was produced.
- Sanitized evidence: `docs/evidence/2026-09-03-shadow-pass.json`.
- All 80 tests pass in the corrected virtual environment.

### Next task

Run another shadow scan during a healthy US market window, then complete the Phase 7b
pre-canary position/open-order reconciliation and exact one-contract order preview.

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
