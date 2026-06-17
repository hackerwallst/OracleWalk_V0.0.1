"""Buy & hold benchmark: compare strategy equity against passive holding.

Works with single-asset OHLC data. For multi-asset, call per symbol and
aggregate — the portfolio-level benchmark comes when PortfolioResult lands.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def buy_and_hold_equity(
    data: pd.DataFrame,
    initial_capital: float,
    contract_size: float = 100_000.0,
    point: float = 0.00001,
) -> pd.Series:
    """Equity curve for a buy-and-hold position sized to initial capital.

    Buys at the first close, holds until the last close.
    Returns a Series indexed like `data`.
    """
    close = data["close"].to_numpy(dtype=float)
    lots = initial_capital / (close[0] * contract_size) if close[0] != 0 else 0.0
    pnl_per_bar = np.diff(close, prepend=close[0]) * lots * contract_size
    return pd.Series(initial_capital + np.cumsum(pnl_per_bar), index=data.index)


def buy_and_hold_metrics(
    data: pd.DataFrame,
    initial_capital: float,
    contract_size: float = 100_000.0,
    point: float = 0.00001,
) -> dict:
    """Summary stats for buy & hold on the given data."""
    eq = buy_and_hold_equity(data, initial_capital, contract_size, point)
    final = float(eq.iloc[-1])
    net = final - initial_capital
    peak = eq.cummax()
    dd = eq - peak
    dd_pct = dd / peak.replace(0, np.nan) * 100.0
    return {
        "initial_capital": initial_capital,
        "final_balance": final,
        "net_profit": net,
        "net_return_pct": (final / initial_capital - 1.0) * 100.0,
        "max_drawdown_pct": float(dd_pct.min()) if not dd_pct.isna().all() else None,
        "bars": len(data),
    }


def strategy_vs_benchmark(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
    initial_capital: float,
) -> dict:
    """Compare strategy equity curve against a benchmark.

    Both series should share the same time axis (or at least same length).
    Returns alpha, beta, correlation, and information ratio.
    """
    s_ret = strategy_equity.pct_change().dropna().to_numpy(dtype=float)
    b_ret = benchmark_equity.pct_change().dropna().to_numpy(dtype=float)
    n = min(len(s_ret), len(b_ret))
    if n < 2:
        return {"alpha": None, "beta": None, "correlation": None, "information_ratio": None}
    s_ret, b_ret = s_ret[:n], b_ret[:n]

    cov = np.cov(s_ret, b_ret)
    beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else None
    alpha = float(s_ret.mean() - (beta or 0) * b_ret.mean())
    corr = float(np.corrcoef(s_ret, b_ret)[0, 1])

    excess = s_ret - b_ret
    ir = float(excess.mean() / excess.std(ddof=1)) if excess.std(ddof=1) > 0 else None

    return {
        "alpha": alpha,
        "beta": beta,
        "correlation": corr,
        "information_ratio": ir,
    }
