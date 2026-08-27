"""Performance metrics for walk-forward simulation results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .spread_model import SimulatedTrade


@dataclass(frozen=True)
class PerformanceMetrics:
    net_pnl: Decimal
    trade_count: int
    filled_count: int
    win_rate: Decimal
    payoff_ratio: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    rejection_rate: Decimal
    average_pnl_per_trade: Decimal
    pnl_per_unit_risk: Decimal

    def as_dict(self) -> dict[str, str | int]:
        return {
            "net_pnl": str(self.net_pnl),
            "trade_count": self.trade_count,
            "filled_count": self.filled_count,
            "win_rate": str(self.win_rate),
            "payoff_ratio": str(self.payoff_ratio),
            "profit_factor": str(self.profit_factor),
            "max_drawdown": str(self.max_drawdown),
            "rejection_rate": str(self.rejection_rate),
            "average_pnl_per_trade": str(self.average_pnl_per_trade),
            "pnl_per_unit_risk": str(self.pnl_per_unit_risk),
        }


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_metrics(trades: tuple[SimulatedTrade, ...]) -> PerformanceMetrics:
    if not trades:
        return PerformanceMetrics(
            net_pnl=Decimal("0"),
            trade_count=0,
            filled_count=0,
            win_rate=Decimal("0"),
            payoff_ratio=Decimal("0"),
            profit_factor=Decimal("0"),
            max_drawdown=Decimal("0"),
            rejection_rate=Decimal("0"),
            average_pnl_per_trade=Decimal("0"),
            pnl_per_unit_risk=Decimal("0"),
        )

    filled = tuple(trade for trade in trades if trade.filled)
    pnls = [trade.pnl for trade in filled]
    net_pnl = sum(pnls, Decimal("0"))
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [abs(pnl) for pnl in pnls if pnl < 0]
    win_rate = Decimal(len(wins)) / Decimal(len(filled)) if filled else Decimal("0")
    average_win = sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else Decimal("0")
    average_loss = sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else Decimal("0")
    payoff_ratio = average_win / average_loss if average_loss > 0 else Decimal("0")
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum(losses, Decimal("0"))
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = Decimal("999.99")
    else:
        profit_factor = Decimal("0")

    equity = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        max_drawdown = max(max_drawdown, drawdown)

    total_risk = sum((trade.max_loss for trade in filled), Decimal("0"))
    rejection_rate = Decimal(len(trades) - len(filled)) / Decimal(len(trades))
    average_pnl = net_pnl / Decimal(len(filled)) if filled else Decimal("0")
    pnl_per_risk = net_pnl / total_risk if total_risk > 0 else Decimal("0")

    return PerformanceMetrics(
        net_pnl=_quantize(net_pnl),
        trade_count=len(trades),
        filled_count=len(filled),
        win_rate=_quantize(win_rate),
        payoff_ratio=_quantize(payoff_ratio),
        profit_factor=_quantize(profit_factor),
        max_drawdown=_quantize(max_drawdown),
        rejection_rate=_quantize(rejection_rate),
        average_pnl_per_trade=_quantize(average_pnl),
        pnl_per_unit_risk=_quantize(pnl_per_risk),
    )
