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
