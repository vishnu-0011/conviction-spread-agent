# ConvictionSpread

**An explainable autonomous options agent.**

ConvictionSpread is a paper-trading agent for the **Options Alpha Agents**
track of the lablab.ai x Alpaca hackathon.

The agent looks for high-conviction bullish or bearish setups and expresses them
with defined-risk vertical debit spreads. A structured AI thesis may recommend a
trade, but deterministic validation, portfolio limits, and an execution kill
switch have final authority.

> Current milestone: the Phase 6 decision cockpit is deployed, the Phase 7b
> reconciled canary preview is code-complete, and Phase 7c can produce a sanitized
> broker-confirmed performance report. Phase 7d adds an exact, position-reconciled
> close path. Entry and close submission remain disabled by default and require
> separate exact operator approvals.

## Hackathon progress

| Phase | Status | Evidence |
|---|---|---|
| Product, research, and safety foundation | Complete | 18 passing tests |
| Read-only Alpaca capability preflight | Complete | Level 3 and near-money data validated |
| Data and feature pipeline | Complete | Typed bar adapters and deterministic features |
| Strategy simulation | Complete | Baselines, walk-forward, and fixture report |
| Spread construction and risk lifecycle | Complete | 55 tests; no broker writes |
| Live shadow autonomy and read-only MCP profile | Complete | Live SPY + MCP calls; 64 tests |
| Structured external AI adapter | Integration-ready | Closed schemas; 70 total tests |
| Observability and demo cockpit | Complete | Production build, zero audit findings, deployed v1 |
| Paper execution, reconciliation, reporting, and close | Preview-ready | Exact entry/exit lifecycle plus broker report; 103 tests |
| Paper burn-in and controlled canary | Market-window pending | One exact one-contract MLeg after approval |
| Fresh judging account and submission | Planned | Broker-confirmed evidence and demo |

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
- `docs/phase-7-paper-canary-readiness.md` — paper gateway safety contract and canary gate.
- `docs/phase-7b-paper-canary-runbook.md` — exact preview, approval, and session runbook.
- `docs/phase-7c-paper-reporting.md` — broker-confirmed status and performance evidence.
- `docs/phase-7d-paper-close-runbook.md` — exact-leg, position-reconciled close path.
- `lessons/` — short, project-linked lessons for understanding and defending the build.
- `mcp/` — pinned read-only Alpaca MCP v2 profile with trading tools omitted.
- `dashboard/` — judge-facing decision cockpit with no broker-write surface.
- `src/conviction_spread_agent/` — domain, agent, shadow, and risk-policy code.
- `tests/` — dependency-free unit tests for safety-critical calculations.

## Install the Python environment

On Windows, install the project into its virtual environment before running a scan.
This also installs the pinned IANA timezone database required for New York market time:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Run the current tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Run the read-only paper-account preflight after configuring a local `.env`:

```powershell
python scripts/preflight.py --underlying SPY
```

Run the fixture-backed walk-forward simulation (no API keys required):

```powershell
python scripts/run_simulation.py
```

Run one authenticated GET-only live shadow decision:

```powershell
$env:PYTHONPATH = "src"
python scripts/shadow_scan.py --underlying SPY
```

Build a GET-only, broker-reconciled one-contract preview:

```powershell
$env:PYTHONPATH = "src"
python scripts/paper_canary.py --underlying IWM
```

Create a sanitized, GET-only report from the paper broker after a preview or canary:

```powershell
$env:PYTHONPATH = "src"
python scripts/paper_report.py --output data/private/paper-performance.json
```

After a broker-confirmed fill, preview the exact risk-reducing close:

```powershell
$env:PYTHONPATH = "src"
python scripts/paper_close.py --entry-record data/private/paper-canary-submission.json
```

The command cannot submit unless the submit flag, four explicit runtime gates, every
market/data/risk check, and an interactive exact-order confirmation all agree. See
the [Phase 7b runbook](docs/phase-7b-paper-canary-runbook.md).

See the [Phase 5a runbook](docs/phase-5-shadow-mode.md) for the output guide and
read-only Alpaca MCP setup.

After locally configuring `OPENAI_API_KEY` and an explicit `OPENAI_MODEL`, opt into
the structured provider with:

```powershell
$env:PYTHONPATH = "src"
python scripts/shadow_scan.py --underlying SPY --ai-provider openai
```

This path makes two model calls. The deterministic mode remains the default and makes
none. See the [Phase 5b adapter guide](docs/phase-5b-structured-ai.md).

## Demo cockpit

The current production preview is owner-only while the project is still being
developed: <https://conviction-spread-agent.vv11njrfan.chatgpt.site>.

Run the same dashboard locally:

```powershell
cd dashboard
npm install
npm run dev
```

The current deployed version replays a sanitized live shadow decision. Broker status
and performance are produced by the Phase 7c CLI and are not yet streamed into this
owner-only dashboard.

## Safety notice

This project is for Alpaca's simulated paper environment and educational use.
Options are complex instruments. Paper results do not represent live execution,
liquidity, slippage, assignment behavior, or future performance.
