# ConvictionSpread

**An explainable autonomous options agent.**

ConvictionSpread is a paper-trading agent for the **Options Alpha Agents**
track of the lablab.ai x Alpaca hackathon.

The agent looks for high-conviction bullish or bearish setups and expresses them
with defined-risk vertical debit spreads. A structured AI thesis may recommend a
trade, but deterministic validation, portfolio limits, and an execution kill
switch have final authority.

> Current milestone: Phase 0 complete; Phase 1 read-only Alpaca preflight ready.
> No Alpaca order execution is implemented or enabled.

## Hackathon progress

| Phase | Status | Evidence |
|---|---|---|
| Product, research, and safety foundation | Complete | 18 passing tests |
| Read-only Alpaca capability preflight | Ready | Waiting for development paper credentials |
| Data and feature pipeline | Planned | Starts after preflight |
| Strategy simulation | Planned | Baselines and walk-forward evaluation |
| Autonomous execution and MCP | Planned | Paper-only, gated rollout |
| Dashboard, burn-in, and submission | Planned | Judge-facing evidence and demo |

See the chronological [build progress](docs/progress.md) and the complete
[implementation roadmap](docs/roadmap.md).

## Design principles

- Paper trading only.
- No naked short options and no single-leg entry for a vertical spread.
- Every order must trace back to a versioned thesis and risk decision.
- The model proposes; deterministic code validates and sizes.
- Reconciliation uses broker state as the source of truth.
- Fail closed on missing, stale, malformed, or contradictory data.

## Repository map

- `docs/roadmap.md` — build-to-submission phases and acceptance gates.
- `docs/strategy-spec.md` — provisional strategy and options mechanics.
- `docs/research/alpaca-platform-research.md` — cited official-platform research.
- `docs/progress.md` — judge-facing build journal and milestone evidence.
- `src/conviction_spread_agent/` — domain and risk-policy foundation.
- `tests/` — dependency-free unit tests for safety-critical calculations.

## Run the current tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Run the read-only paper-account preflight after configuring a local `.env`:

```powershell
python scripts/preflight.py --underlying SPY
```

## Safety notice

This project is for Alpaca's simulated paper environment and educational use.
Options are complex instruments. Paper results do not represent live execution,
liquidity, slippage, assignment behavior, or future performance.
