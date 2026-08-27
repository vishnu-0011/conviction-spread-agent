"""Conservative bid/ask fill assumptions for paper simulation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from ..domain import Quote


@dataclass(frozen=True)
class FillAssumptions:
    slippage_fraction: Decimal = Decimal("0.02")
    rejection_probability: Decimal = Decimal("0.05")
    fee_per_contract: Decimal = Decimal("0.65")

    def __post_init__(self) -> None:
        for name in ("slippage_fraction", "rejection_probability"):
            value = getattr(self, name)
            if value < 0 or value >= 1:
                raise ValueError(f"{name} must be in [0, 1)")
        if self.fee_per_contract < 0:
            raise ValueError("fee_per_contract cannot be negative")


class SpreadFillModel:
    """Apply conservative executable prices to a two-leg debit spread."""

    def __init__(self, assumptions: FillAssumptions = FillAssumptions()) -> None:
        self.assumptions = assumptions

    def _apply_slippage(self, price: Decimal, *, worse: bool) -> Decimal:
        bump = price * self.assumptions.slippage_fraction
        adjusted = price + bump if worse else price - bump
        return adjusted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def entry_debit(self, long_quote: Quote, short_quote: Quote) -> Decimal:
        long_pay = self._apply_slippage(long_quote.ask, worse=True)
        short_receive = self._apply_slippage(short_quote.bid, worse=False)
        debit = long_pay - short_receive
        if debit <= 0:
            raise ValueError("conservative entry debit must be positive")
        return debit

    def exit_credit(self, long_quote: Quote, short_quote: Quote) -> Decimal:
        long_receive = self._apply_slippage(long_quote.bid, worse=False)
        short_pay = self._apply_slippage(short_quote.ask, worse=True)
        credit = long_receive - short_pay
        return credit


def conservative_debit(long_bid: Decimal, long_ask: Decimal, short_bid: Decimal, short_ask: Decimal) -> Decimal:
    """Standalone helper for tests and scripts."""

    model = SpreadFillModel()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return model.entry_debit(
        Quote(long_bid, long_ask, now),
        Quote(short_bid, short_ask, now),
    )


def conservative_credit(long_bid: Decimal, long_ask: Decimal, short_bid: Decimal, short_ask: Decimal) -> Decimal:
    model = SpreadFillModel()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return model.exit_credit(
        Quote(long_bid, long_ask, now),
        Quote(short_bid, short_ask, now),
    )
