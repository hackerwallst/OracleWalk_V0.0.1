"""Optimization & overfit diagnostics (Claude-owned, reads engine output only).

- search.optimize: grid/random parameter search + per-config returns matrix
- walk_forward.walk_forward: in-sample optimize -> out-of-sample evaluation
- overfit: PBO (CSCV), Deflated & Probabilistic Sharpe
"""
from .objective import OBJECTIVES, evaluate, get_objective
from .overfit import (
    deflated_sharpe_from_matrix,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from .search import grid_points, optimize, random_points
from .walk_forward import walk_forward

__all__ = [
    "evaluate",
    "get_objective",
    "OBJECTIVES",
    "optimize",
    "grid_points",
    "random_points",
    "walk_forward",
    "probability_of_backtest_overfitting",
    "deflated_sharpe_ratio",
    "deflated_sharpe_from_matrix",
    "probabilistic_sharpe_ratio",
]
