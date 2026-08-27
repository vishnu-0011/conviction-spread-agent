"""Walk-forward strategy simulation and baseline comparison."""

from .baselines import (
    BaselineKind,
    BaselineSignal,
    buy_and_hold_signal,
    momentum_signal,
    random_direction_signal,
)
from .fills import FillAssumptions, SpreadFillModel, conservative_debit, conservative_credit
from .metrics import PerformanceMetrics, compute_metrics
from .spread_model import SpreadSimulationConfig, simulate_spread_trade
from .walkforward import WalkForwardConfig, WalkForwardResult, run_walk_forward

__all__ = [
    "BaselineKind",
    "BaselineSignal",
    "FillAssumptions",
    "PerformanceMetrics",
    "SpreadFillModel",
    "SpreadSimulationConfig",
    "WalkForwardConfig",
    "WalkForwardResult",
    "buy_and_hold_signal",
    "compute_metrics",
    "conservative_credit",
    "conservative_debit",
    "momentum_signal",
    "random_direction_signal",
    "run_walk_forward",
    "simulate_spread_trade",
]
