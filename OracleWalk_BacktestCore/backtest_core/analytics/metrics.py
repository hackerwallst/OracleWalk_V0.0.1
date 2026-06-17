from __future__ import annotations

import numpy as np
import pandas as pd


def equity_curve(trades: pd.DataFrame, initial_capital: float) -> pd.Series:
    if trades is None or trades.empty:
        return pd.Series(dtype=float)
    ordered = trades.sort_values("exit_time").reset_index(drop=True)
    return initial_capital + ordered["pnl"].cumsum()


def drawdown_curve(equity: pd.Series) -> pd.DataFrame:
    if equity is None or equity.empty:
        return pd.DataFrame(columns=["equity", "peak", "drawdown", "drawdown_pct"])
    peak = equity.cummax()
    drawdown = equity - peak
    drawdown_pct = drawdown / peak.replace(0, np.nan) * 100.0
    return pd.DataFrame(
        {
            "equity": equity,
            "peak": peak,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
        }
    )


def compute_metrics(trades: pd.DataFrame, initial_capital: float) -> dict:
    if trades is None or trades.empty:
        return {
            "initial_capital": float(initial_capital),
            "final_balance": float(initial_capital),
            "net_profit": 0.0,
            "net_return_pct": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": None,
            "max_drawdown_pct": None,
            "expectancy": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "payoff_ratio": None,
            "sharpe_per_trade": None,
            "gross_pnl": 0.0,
            "total_commissions": 0.0,
            "total_swap": 0.0,
        }

    df = trades.copy()
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    gross_pnl = _num_col(df, "gross_pnl", pnl)
    commission_open = _num_col(df, "commission_open", 0.0)
    commission_close = _num_col(df, "commission_close", 0.0)
    swap = _num_col(df, "swap", 0.0)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    breakeven = pnl[pnl == 0]
    total = len(pnl)

    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(losses.sum()) if len(losses) else 0.0
    net_profit = float(pnl.sum())
    final_balance = float(initial_capital + net_profit)
    eq = equity_curve(df.assign(pnl=pnl), initial_capital)
    dd = drawdown_curve(eq)

    returns = pnl / float(initial_capital)
    sharpe = None
    if len(returns) > 1 and returns.std(ddof=1) != 0:
        sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(total))

    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = (avg_win / abs(avg_loss)) if avg_loss < 0 else None

    return {
        "initial_capital": float(initial_capital),
        "final_balance": final_balance,
        "net_profit": net_profit,
        "net_return_pct": (final_balance / initial_capital - 1.0) * 100.0,
        "total_trades": int(total),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "breakeven": int(len(breakeven)),
        "win_rate": (len(wins) / total * 100.0) if total else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
        "max_drawdown_pct": float(dd["drawdown_pct"].min()) if not dd.empty else None,
        "expectancy": net_profit / total if total else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "sharpe_per_trade": sharpe,
        "gross_pnl": float(gross_pnl.sum()),
        "total_commissions": float(commission_open.sum() + commission_close.sum()),
        "total_swap": float(swap.sum()),
    }


def _num_col(df: pd.DataFrame, column: str, default) -> pd.Series:
    if column in df.columns:
        return pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    if isinstance(default, pd.Series):
        return default
    return pd.Series([float(default)] * len(df), index=df.index)
