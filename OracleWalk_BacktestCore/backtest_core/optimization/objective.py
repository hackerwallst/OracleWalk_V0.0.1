"""Single-run evaluation and objective functions for optimization.

Lives entirely on top of the existing engine contract (it reads the trades
DataFrame). It does not modify the engine — Codex owns that.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from ..analytics.metrics import compute_metrics
from ..core.engine import Backtester
from ..strategies.base import StrategyBase


def evaluate(strategy: StrategyBase, data: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, dict]:
    """Run one backtest and return (trades, metrics). Mirrors core.runner without disk I/O."""
    prepared = strategy.prepare_indicators(data)
    signals = strategy.generate_signals(prepared)
    trades = Backtester(prepared, config).run(signals)
    initial_capital = float(config.get("initial_capital", 1000.0))
    metrics = compute_metrics(trades, initial_capital)
    return trades, metrics


def trade_returns(trades: pd.DataFrame, initial_capital: float) -> np.ndarray:
    """Per-trade returns as a fraction of initial capital (ordered by exit)."""
    if trades is None or trades.empty:
        return np.array([], dtype=float)
    ordered = trades.sort_values("exit_time")
    return (pd.to_numeric(ordered["pnl"], errors="coerce").fillna(0.0) / initial_capital).to_numpy()


def sharpe(returns: np.ndarray, periods_per_year: float | None = None) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    value = r.mean() / sd
    if periods_per_year:
        value *= np.sqrt(periods_per_year)
    return float(value)


def _calmar(metrics: dict) -> float:
    dd = metrics.get("max_drawdown_pct")
    if not dd:
        return 0.0
    return metrics.get("net_return_pct", 0.0) / abs(dd)


# Objective registry: name -> callable(trades, metrics) -> float (higher is better).
OBJECTIVES: dict[str, Callable[[pd.DataFrame, dict], float]] = {
    "net_profit": lambda t, m: float(m.get("net_profit", 0.0)),
    "net_return_pct": lambda t, m: float(m.get("net_return_pct", 0.0)),
    "profit_factor": lambda t, m: float(m.get("profit_factor") or 0.0),
    "sharpe_per_trade": lambda t, m: float(m.get("sharpe_per_trade") or 0.0),
    "expectancy": lambda t, m: float(m.get("expectancy", 0.0)),
    "calmar": lambda t, m: _calmar(m),
}


def get_objective(name: str) -> Callable[[pd.DataFrame, dict], float]:
    if name not in OBJECTIVES:
        raise KeyError(f"unknown objective '{name}'. Available: {sorted(OBJECTIVES)}")
    return OBJECTIVES[name]
