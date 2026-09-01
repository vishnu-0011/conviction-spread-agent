# Phase 4 — spread construction and deterministic lifecycle

Phase 4 converts normalized option-chain records into one bounded-risk vertical
spread, applies the final order-admission gates, and records the legal broker
lifecycle transitions. It still performs no broker writes.

## Delivered boundary

1. `option_data.py` normalizes explicitly tradable Alpaca contract metadata plus
   camelCase or snake_case quote snapshots. Missing bid, ask, timestamp, or contract
   identity fails closed.
2. `spreads.py` filters by underlying, right, DTE, quote freshness, relative width,
   positive bid, strike width, and debit-to-width ratio.
3. The selector prefers the declared long/short delta bands. Moneyness is used only
   when at least one leg is missing delta; observed but out-of-band deltas are not
   silently ignored.
4. Entry debit uses the conservative executable reference `long ask − short bid`.
5. `phase4_risk.py` adds options buying power, opening/closing windows, and duplicate
   decision IDs without allowing those checks to override an existing risk rejection.
6. `lifecycle.py` provides an immutable, event-driven state machine for approval,
   entry acknowledgement, partial/final fills, cancellation, open exposure, close,
   restart replay, reconciliation, and terminal failure.

## Safety properties

- No naked or single-leg order path was added.
- A partial entry followed by cancellation remains an open position; it is never
  mistaken for a fully canceled strategy.
- A terminal software failure cannot erase open quantity. It moves to
  `reconcile_required`.
- Duplicate broker events are idempotent across serialized restart recovery.
- A broker filled quantity behind local state is classified as disagreement.
- Every selected spread has a positive debit below its strike width and a known
  maximum loss before an order intent is created.

## Verification

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q scripts src tests
```

The current suite has 55 passing tests, including 20 Phase 4 adapter, selector, risk,
partial-fill, restart, cancellation, and reconciliation scenarios.

## Honest limitations

- The option normalizer and selector are tested against validated response shapes and
  deterministic fixtures; the scheduled live shadow scanner is Phase 5 work.
- No POST, cancel, replace, exercise, or close request exists in this phase.
- Broker MLeg partial-fill and replacement behavior still requires a controlled paper
  validation before execution can be enabled.

## Official contract

Alpaca's [Options Level 3 documentation](https://docs.alpaca.markets/us/docs/options-level-3-trading)
defines MLeg order structure and covered-leg restrictions. Its
[order lifecycle documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
defines statuses such as `new`, `partially_filled`, `filled`, and `canceled` that the
state model must reconcile.
