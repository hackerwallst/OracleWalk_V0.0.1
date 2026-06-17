"""Advanced risk metrics: Sortino, Calmar, Ulcer, VaR/CVaR, time-under-water.

All functions accept either a trades DataFrame or a returns/equity Series.
No engine dependency — reads finished results only.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .metrics import drawdown_curve, equity_curve


def sortino_ratio(
    trades: pd.DataFrame,
    initial_capital: float,
    annualize: int = 252,
    mar: float = 0.0,
) -> float | None:
    """Sortino ratio: excess return / downside deviation.

    mar = minimum acceptable return (per-trade, default 0).
    annualize = scale factor (252 for daily trades, 1 to skip).
    """
    if trades is None or trades.empty or len(trades) < 2:
        return None
    pnl = trades["pnl"].to_numpy(dtype=float)
    returns = pnl / float(initial_capital)
    excess = returns - mar
    downside = returns[returns < mar] - mar
    if len(downside) == 0 or downside.std(ddof=1) == 0:
        return None
    return float(excess.mean() / downside.std(ddof=1) * math.sqrt(annualize))


def calmar_ratio(
    trades: pd.DataFrame,
    initial_capital: float,
    annualize: int = 252,
) -> float | None:
    """Calmar ratio: annualised return / max drawdown (absolute)."""
    if trades is None or trades.empty:
        return None
    eq = equity_curve(trades, initial_capital)
    dd = drawdown_curve(eq)
    max_dd = dd["drawdown"].min()
    if max_dd == 0:
        return None
    total_return = float(eq.iloc[-1] / initial_capital - 1.0)
    n_trades = len(trades)
    ann_return = total_return * (annualize / n_trades) if n_trades > 0 else 0.0
    return float(ann_return / abs(max_dd / initial_capital))


def ulcer_index(trades: pd.DataFrame, initial_capital: float) -> float | None:
    """Ulcer index: RMS of percentage drawdowns (pain measure)."""
    if trades is None or trades.empty:
        return None
    eq = equity_curve(trades, initial_capital)
    dd = drawdown_curve(eq)
    dd_pct = dd["drawdown_pct"].to_numpy(dtype=float)
    if len(dd_pct) == 0:
        return None
    return float(math.sqrt(np.mean(dd_pct ** 2)))


def value_at_risk(
    trades: pd.DataFrame,
    initial_capital: float,
    confidence: float = 0.95,
) -> dict:
    """Historical VaR and CVaR (Expected Shortfall) at given confidence.

    Returns per-trade values as fractions of initial capital.
    """
    if trades is None or trades.empty:
        return {"var": None, "cvar": None, "confidence": confidence}
    returns = trades["pnl"].to_numpy(dtype=float) / float(initial_capital)
    alpha = 1.0 - confidence
    var = float(np.percentile(returns, alpha * 100))
    tail = returns[returns <= var]
    cvar = float(tail.mean()) if len(tail) > 0 else var
    return {"var": var, "cvar": cvar, "confidence": confidence}


def time_under_water(
    trades: pd.DataFrame,
    initial_capital: float,
) -> dict:
    """Time-under-water analysis from the equity curve.

    Returns max, mean, and median drawdown durations measured in trade count.
    """
    if trades is None or trades.empty:
        return {"max_tuw": 0, "mean_tuw": 0.0, "median_tuw": 0.0, "n_drawdowns": 0}
    eq = equity_curve(trades, initial_capital).to_numpy(dtype=float)
    peak = np.maximum.accumulate(eq)
    in_dd = eq < peak

    durations: list[int] = []
    current = 0
    for underwater in in_dd:
        if underwater:
            current += 1
        elif current > 0:
            durations.append(current)
            current = 0
    if current > 0:
        durations.append(current)

    if not durations:
        return {"max_tuw": 0, "mean_tuw": 0.0, "median_tuw": 0.0, "n_drawdowns": 0}
    return {
        "max_tuw": int(max(durations)),
        "mean_tuw": float(np.mean(durations)),
        "median_tuw": float(np.median(durations)),
        "n_drawdowns": len(durations),
    }


def tail_ratio(trades: pd.DataFrame, percentile: float = 95.0) -> float | None:
    """Tail ratio: right tail / |left tail| at given percentile.

    >1 means the distribution has fatter right tails (good).
    """
    if trades is None or trades.empty or len(trades) < 10:
        return None
    pnl = trades["pnl"].to_numpy(dtype=float)
    right = np.percentile(pnl, percentile)
    left = np.percentile(pnl, 100 - percentile)
    if left == 0:
        return None
    return float(abs(right / left))


def gain_to_pain_ratio(trades: pd.DataFrame) -> float | None:
    """Gain-to-pain: net profit / sum of absolute losses."""
    if trades is None or trades.empty:
        return None
    pnl = trades["pnl"].to_numpy(dtype=float)
    pain = np.abs(pnl[pnl < 0]).sum()
    if pain == 0:
        return None
    return float(pnl.sum() / pain)


def compute_risk_metrics(trades: pd.DataFrame, initial_capital: float) -> dict:
    """Convenience: compute all advanced risk metrics in one call."""
    var = value_at_risk(trades, initial_capital)
    tuw = time_under_water(trades, initial_capital)
    return {
        "sortino": sortino_ratio(trades, initial_capital),
        "calmar": calmar_ratio(trades, initial_capital),
        "ulcer_index": ulcer_index(trades, initial_capital),
        "var_95": var["var"],
        "cvar_95": var["cvar"],
        "tail_ratio": tail_ratio(trades),
        "gain_to_pain": gain_to_pain_ratio(trades),
        **{f"tuw_{k}": v for k, v in tuw.items()},
    }
