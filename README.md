# ConvictionSpread

**An explainable autonomous options agent.**

ConvictionSpread is a paper-trading agent for the **Options Alpha Agents**
track of the lablab.ai x Alpaca hackathon.

The agent looks for high-conviction bullish or bearish setups and expresses them
with defined-risk vertical debit spreads. A structured AI thesis may recommend a
trade, but deterministic validation, portfolio limits, and an execution kill
switch have final authority.

> Current milestone: the Phase 6 decision cockpit is deployed and the Phase 7a paper
> MLeg gateway is code-complete. Submission remains disabled by default, the one-contract
> live canary is not authorized, and deterministic risk code retains final authority.

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
| Paper execution gateway and order reconciliation | Gateway-ready | 10 focused tests; live canary not authorized |
| Paper burn-in and controlled canary | Next | One exact one-contract MLeg after approval |
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

The first version replays a sanitized live shadow decision. It does not claim a
fill or continuously refresh because the paper execution gateway and broker
reconciliation are Phase 7 work.

## Safety notice

This project is for Alpaca's simulated paper environment and educational use.
Options are complex instruments. Paper results do not represent live execution,
liquidity, slippage, assignment behavior, or future performance.
