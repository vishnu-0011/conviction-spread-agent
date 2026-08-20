# System architecture and trust boundaries

The system separates **reasoning**, **risk authority**, and **broker execution**.
This is the central architectural decision: natural-language intelligence is useful
for synthesizing evidence, but it is not a safe source of executable order facts.

```text
Alpaca market data ──► data adapters ──► feature engine ──► candidate funnel
       │                                                        │
       │                                                        ▼
       │                                              thesis + critic agent
       │                                                (strict schema)
       │                                                        │
       ▼                                                        ▼
broker clock/account ─► reconciler ───────────────► deterministic planner
       │                                                        │
       │                                                        ▼
       └──────────────────────────────────────────────► risk authority
                                                                │
                                                    approve / reject + reasons
                                                                │
                                                                ▼
                                                     execution state machine
                                                     (Alpaca paper API/MCP)
                                                                │
                                   broker updates ◄──────────────┘
                                         │
                                         ▼
                              append-only audit log + dashboard
```

## Trust levels

### Trusted, deterministic inputs

- Broker account, position, order, clock, and calendar responses after validation.
- Market data with valid types, timestamps, and freshness.
- Versioned configuration loaded at startup.
- Locally calculated features and spread payoff values.

### Untrusted inputs

- Model output, including apparently valid JSON.
- News text and other external natural language.
- Missing or delayed quote fields.
- Locally remembered order state after a disconnect.
- Dashboard actions other than an authenticated pause/kill operation.

Untrusted data may inform a candidate, but cannot relax a gate or create executable
symbols, quantities, prices, account identifiers, or position intent.

## Core components

### Data adapters

Convert Alpaca responses into internal immutable records. They validate enumeration
values, timezones, timestamps, quote sanity, and required identifiers at the boundary.
Provider-specific objects do not leak into strategy or risk code.

### Feature engine

Calculates reproducible features from timestamped bars and snapshots. Feature records
include source timestamps and a feature-set version so historical decisions can be
replayed.

### Candidate funnel

Applies inexpensive deterministic filters before any model call: universe membership,
market health, broad regime, tradability, liquidity, cooldowns, and existing exposure.
This saves latency and makes `NO_TRADE` an ordinary successful outcome.

### Thesis and critic

The thesis agent synthesizes normalized evidence into a falsifiable claim. A separate
critic looks for regime contradictions, stretched entries, weak evidence, or unclear
invalidation. Both return schema-constrained data. Parse or validation failure means
`PASS`.

### Deterministic planner

Selects contracts from an allowlisted chain and constructs a vertical. It owns DTE,
strike ordering, width, debit, quote quality, and order price. The thesis never supplies
an OCC symbol or quantity.

### Risk authority

The single decision point for execution. It evaluates account state, reconciliation,
data health, confidence, time window, DTE, liquidity, maximum loss, concentration,
portfolio risk, loss halts, and kill-switch state. Its decision is immutable and logged.

### Execution state machine

Submits only previously approved plans and uses a deterministic client order ID. It
treats timeouts as unknown—not failed—until broker reconciliation proves the state.
Retries may repeat a query but cannot manufacture a second logical intent.

Because Alpaca currently lists only `simple` and `mleg` order classes for options, the
position monitor owns profit, loss, invalidation, time, and expiration exits. It closes
the vertical with an opposing atomic MLeg order; it does not assume bracket/OCO/OTO
attachments are available.

### Reconciler

Periodically and at startup compares local intents with broker orders and positions.
Broker state wins for facts about accepted orders and held positions. Any unexplained
position or leg imbalance halts new entries and raises an operator alert.

### Audit store and dashboard

The write path records inputs, features, thesis, risk decision, order payload hash,
broker lifecycle, and exit reason. The dashboard reads those records; it does not infer
fills or P&L that Alpaca has not confirmed.

## Logical order lifecycle

```text
DRAFT
  ├─► REJECTED
  └─► APPROVED
         └─► SUBMITTING
                ├─► BROKER_UNKNOWN ─► RECONCILING ─┬─► ACKNOWLEDGED
                │                                  ├─► REJECTED
                │                                  └─► HALTED
                └─► ACKNOWLEDGED
                       ├─► WORKING
                       ├─► PARTIALLY_FILLED
                       ├─► FILLED ─► MANAGING ─► CLOSING ─► CLOSED
                       ├─► CANCELED
                       └─► REJECTED
```

Actual Alpaca multi-leg lifecycle behavior must be observed in Phase 1 before these
states are mapped to provider statuses.

## Scheduler jobs

- **heartbeat:** frequent process and dependency health.
- **reconcile:** frequent broker/local comparison and always at startup.
- **position monitor:** quote, thesis invalidation, risk, and expiration management.
- **candidate scan:** slower and only inside the permitted entry window.
- **end of day:** cancel unwanted working entries, snapshot evidence, and summarize.

Only one active scheduler lease may create new intents. Position safety and emergency
halts continue even when entry scanning is disabled.

## Failure policy

| Failure | Required behavior |
|---|---|
| Stale or missing market data | No new trade; keep reconciling existing positions |
| Model timeout or invalid schema | Record `PASS`; no retry storm |
| Order submission timeout | Mark broker state unknown and query by client order ID |
| Broker/local mismatch | Halt entries; reconcile and alert |
| Partial or asymmetric exposure | Follow tested broker recovery policy; never improvise |
| Daily/weekly loss threshold | Halt entries; manage or flatten per configured policy |
| Process restart | Rebuild state from broker and audit store before scheduling |
| Kill switch | Stop new entries immediately; cancellation/flatten behavior is explicit |

## Deployment shape for the hackathon

One Python service is sufficient initially:

- typed domain/application modules;
- Alpaca adapters;
- scheduler and execution worker;
- SQLite with append-oriented decision/order tables;
- a small FastAPI health/read API; and
- Streamlit or a lightweight web UI for the judge-facing dashboard.

Splitting this into distributed services would add more failure modes than value in a
seven-day project. Module boundaries preserve a later migration path without requiring
network boundaries now.

## Alpaca integration decision

- Use the official `alpaca-py` SDK for typed production REST/streaming and broker
  reconciliation.
- Use Alpaca MCP v2 as the visible required agent integration with restricted toolsets.
- Test MLeg arrays in the exact MCP client because Alpaca issue #97 reports a
  client-specific serialization failure.
- Keep the official CLI's raw JSON API command as an operational/debugging fallback,
  not as an excuse to maintain multiple execution authorities.
- Pin all three tool versions used during judging and save their discovered schemas.
