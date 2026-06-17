"""Institutional-grade metric suite for the interactive report (Pillar 1).

Aggregates the building blocks already in this package (``metrics``, ``risk``,
``monte_carlo``, ``benchmark``) plus the overfit guards (``optimization.overfit``)
into a single **sectioned** dict the UI can render as grouped panels:

    summary · returns · ratios · risk · streaks · robustness · costs

Everything reads *finished* results only (a trades DataFrame). No engine
dependency, no lookahead. Missing/undefined numbers come back as ``None`` so the
frontend can show a dash instead of crashing.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ..optimization.overfit import probabilistic_sharpe_ratio
from .benchmark import buy_and_hold_metrics, strategy_vs_benchmark
from .metrics import compute_metrics, drawdown_curve, equity_curve
from .monte_carlo import monte_carlo_equity, monte_carlo_suite_summary
from .risk import compute_risk_metrics

_TRADES_PER_YEAR_FALLBACK = 252.0
_RUIN_DRAWDOWN = 0.50  # equity dropping 50% from start counts as "ruin"


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def build_full_metrics(
    trades: pd.DataFrame,
    initial_capital: float,
    *,
    n_bars: int | None = None,
    mc_sims: int = 1000,
    seed: int | None = 42,
) -> dict[str, Any]:
    """The sectioned ``metrics_full`` payload (see CODEX_HANDOFF contract v2)."""
    initial = float(initial_capital or 0.0) or 1.0
    base = compute_metrics(trades, initial)
    risk = compute_risk_metrics(trades, initial)

    if trades is None or trades.empty:
        return _empty_sections(initial, base)

    df = trades.copy()
    pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    eq = equity_curve(df, initial)
    dd = drawdown_curve(eq)
    max_dd_abs = float(dd["drawdown"].min()) if not dd.empty else 0.0

    years = _calendar_years(df)
    final_balance = float(base["final_balance"])
    cagr = _cagr(initial, final_balance, years)

    r_mult = _r_multiples(df)
    streak = _streaks(df)
    mc = _monte_carlo_risk(df, initial, n_sims=mc_sims, seed=seed)

    sharpe_pt = base.get("sharpe_per_trade")
    sharpe_ann = _annualize_sharpe(sharpe_pt, len(df), years)
    sortino = risk.get("sortino")
    calmar = risk.get("calmar")
    mar = _safe_div(cagr, abs(base["max_drawdown_pct"] / 100.0)) if base.get("max_drawdown_pct") else None

    sections: dict[str, Any] = {
        "summary": {
            "net_profit": base["net_profit"],
            "net_return_pct": base["net_return_pct"],
            "final_balance": final_balance,
            "initial_capital": initial,
            "total_trades": base["total_trades"],
            "cagr_pct": _pct(cagr),
            "best_trade": float(np.max(pnl)) if pnl.size else None,
            "worst_trade": float(np.min(pnl)) if pnl.size else None,
        },
        "returns": {
            "expectancy": base["expectancy"],
            "expectancy_r": _mean_or_none(r_mult),
            "avg_win": base["avg_win"],
            "avg_loss": base["avg_loss"],
            "payoff_ratio": base["payoff_ratio"],
            "avg_trade_duration_h": _avg_duration_hours(df),
            "exposure_pct": _exposure_pct(df, n_bars),
        },
        "ratios": {
            "profit_factor": base["profit_factor"],
            "sharpe_per_trade": sharpe_pt,
            "sharpe_annual": sharpe_ann,
            "sortino": sortino,
            "calmar": calmar,
            "mar": mar,
            "omega": _omega_ratio(pnl),
            "k_ratio": _k_ratio(eq),
            "sqn": _sqn(pnl),
            "recovery_factor": _safe_div(base["net_profit"], abs(max_dd_abs)),
            "gain_to_pain": risk.get("gain_to_pain"),
            "tail_ratio": risk.get("tail_ratio"),
            "kelly_pct": _kelly_pct(base),
        },
        "risk": {
            "max_drawdown_pct": base["max_drawdown_pct"],
            "max_drawdown_abs": max_dd_abs,
            "ulcer_index": risk.get("ulcer_index"),
            "var_95": risk.get("var_95"),
            "cvar_95": risk.get("cvar_95"),
            "tuw_max": risk.get("tuw_max_tuw"),
            "tuw_mean": risk.get("tuw_mean_tuw"),
            "tuw_median": risk.get("tuw_median_tuw"),
            "n_drawdowns": risk.get("tuw_n_drawdowns"),
        },
        "streaks": {
            "win_rate": base["win_rate"],
            "wins": base["wins"],
            "losses": base["losses"],
            "breakeven": base["breakeven"],
            "max_consec_wins": streak["max_consec_wins"],
            "max_consec_losses": streak["max_consec_losses"],
            "largest_win": float(np.max(pnl)) if pnl.size else None,
            "largest_loss": float(np.min(pnl)) if pnl.size else None,
        },
        "robustness": {
            "psr": _psr(pnl, initial),
            "risk_of_ruin_pct": mc["risk_of_ruin_pct"],
            "prob_profit_pct": mc["prob_profit_pct"],
            "mc_final_p05": mc["mc_final_p05"],
            "mc_final_p50": mc["mc_final_p50"],
            "mc_final_p95": mc["mc_final_p95"],
            "mc_maxdd_p95": mc["mc_maxdd_p95"],
        },
        "costs": {
            "total_commissions": base["total_commissions"],
            "total_swap": base["total_swap"],
            "gross_profit": base["gross_profit"],
            "gross_loss": base["gross_loss"],
        },
    }
    return sections


def monte_carlo_block(
    trades: pd.DataFrame,
    initial_capital: float,
    *,
    n_sims: int = 1000,
    seed: int | None = 42,
) -> dict[str, dict]:
    """The 4-mode Monte Carlo numeric summary (shuffle/bootstrap/block/exec-stress)."""
    return monte_carlo_suite_summary(trades, float(initial_capital or 1.0), n_sims=n_sims, seed=seed)


def benchmark_block(
    trades: pd.DataFrame,
    data: pd.DataFrame | None,
    initial_capital: float,
    *,
    contract_size: float = 100_000.0,
    point: float = 0.00001,
) -> dict[str, Any]:
    """Strategy vs buy-and-hold on the same window."""
    if data is None or "close" not in getattr(data, "columns", []) or len(data) < 2:
        return {"buy_hold": None, "vs": None}
    initial = float(initial_capital or 1.0)
    bh_full = buy_and_hold_metrics(data, initial, contract_size, point)
    buy_hold = {
        "net_return_pct": bh_full["net_return_pct"],
        "max_drawdown_pct": bh_full["max_drawdown_pct"],
        "final_balance": bh_full["final_balance"],
    }
    vs: dict[str, Any] | None = None
    if trades is not None and not trades.empty:
        strat_eq = _bar_indexed_equity(trades, data, initial)
        from .benchmark import buy_and_hold_equity

        bh_eq = buy_and_hold_equity(data, initial, contract_size, point)
        comp = strategy_vs_benchmark(strat_eq, bh_eq, initial)
        comp["excess_return_pct"] = float(compute_metrics(trades, initial)["net_return_pct"] - bh_full["net_return_pct"])
        vs = comp
    return {"buy_hold": buy_hold, "vs": vs}


# --------------------------------------------------------------------------- #
# Internals                                                                    #
# --------------------------------------------------------------------------- #
def _empty_sections(initial: float, base: dict) -> dict[str, Any]:
    z = lambda *keys: {k: None for k in keys}  # noqa: E731
    return {
        "summary": {"net_profit": 0.0, "net_return_pct": 0.0, "final_balance": initial,
                    "initial_capital": initial, "total_trades": 0, "cagr_pct": None,
                    "best_trade": None, "worst_trade": None},
        "returns": z("expectancy", "expectancy_r", "avg_win", "avg_loss", "payoff_ratio",
                     "avg_trade_duration_h", "exposure_pct"),
        "ratios": z("profit_factor", "sharpe_per_trade", "sharpe_annual", "sortino", "calmar",
                    "mar", "omega", "k_ratio", "sqn", "recovery_factor", "gain_to_pain",
                    "tail_ratio", "kelly_pct"),
        "risk": z("max_drawdown_pct", "max_drawdown_abs", "ulcer_index", "var_95", "cvar_95",
                  "tuw_max", "tuw_mean", "tuw_median", "n_drawdowns"),
        "streaks": {"win_rate": 0.0, "wins": 0, "losses": 0, "breakeven": 0,
                    "max_consec_wins": 0, "max_consec_losses": 0, "largest_win": None,
                    "largest_loss": None},
        "robustness": z("psr", "risk_of_ruin_pct", "prob_profit_pct", "mc_final_p05",
                        "mc_final_p50", "mc_final_p95", "mc_maxdd_p95"),
        "costs": {"total_commissions": 0.0, "total_swap": 0.0, "gross_profit": 0.0, "gross_loss": 0.0},
    }


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return float(a) / float(b)


def _pct(x):
    return None if x is None else float(x) * 100.0


def _mean_or_none(arr: np.ndarray):
    return float(np.mean(arr)) if arr is not None and arr.size else None


def _calendar_years(df: pd.DataFrame) -> float:
    try:
        start = pd.to_datetime(df["entry_time"]).min()
        end = pd.to_datetime(df["exit_time"]).max()
        days = (end - start).total_seconds() / 86400.0
        return max(days / 365.25, 1e-6)
    except Exception:
        return max(len(df) / _TRADES_PER_YEAR_FALLBACK, 1e-6)


def _cagr(initial: float, final: float, years: float):
    if initial <= 0 or final <= 0 or years <= 0:
        return None
    return (final / initial) ** (1.0 / years) - 1.0


def _annualize_sharpe(sharpe_per_trade, n_trades, years):
    """The per-trade Sharpe already carries sqrt(N); rescale to a yearly figure."""
    if sharpe_per_trade is None or n_trades < 2 or years <= 0:
        return None
    per_obs = sharpe_per_trade / math.sqrt(n_trades)
    trades_per_year = n_trades / years
    return float(per_obs * math.sqrt(trades_per_year))


def _r_multiples(df: pd.DataFrame) -> np.ndarray:
    if "risk_reward" in df.columns:
        r = pd.to_numeric(df["risk_reward"], errors="coerce").dropna().to_numpy(dtype=float)
        if r.size:
            return r
    return np.empty(0, dtype=float)


def _avg_duration_hours(df: pd.DataFrame):
    if "duration" not in df.columns:
        return None
    dur = pd.to_timedelta(df["duration"], errors="coerce").dropna()
    if dur.empty:
        return None
    return float(dur.dt.total_seconds().mean() / 3600.0)


def _exposure_pct(df: pd.DataFrame, n_bars: int | None):
    if not n_bars or n_bars <= 0 or "bars_in_trade" not in df.columns:
        return None
    bars = pd.to_numeric(df["bars_in_trade"], errors="coerce").fillna(0.0).sum()
    return float(min(bars / n_bars, 1.0) * 100.0)


def _omega_ratio(pnl: np.ndarray, threshold: float = 0.0):
    gains = pnl[pnl > threshold] - threshold
    losses = threshold - pnl[pnl < threshold]
    denom = float(losses.sum())
    if denom <= 0:
        return None
    return float(gains.sum() / denom)


def _k_ratio(equity: pd.Series):
    """Zephyr K-ratio: trend slope of the equity curve / its standard error."""
    eq = equity.to_numpy(dtype=float)
    n = eq.size
    if n < 3 or np.any(eq <= 0):
        # fall back to raw equity if logs are invalid
        y = eq.astype(float)
    else:
        y = np.log(eq)
    if n < 3:
        return None
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    dof = n - 2
    if dof <= 0:
        return None
    s_err = math.sqrt(float(np.sum(resid ** 2)) / dof)
    sxx = float(np.sum((x - x.mean()) ** 2))
    if sxx <= 0 or s_err <= 0:
        return None
    slope_se = s_err / math.sqrt(sxx)
    return float(slope / slope_se / math.sqrt(n))


def _sqn(pnl: np.ndarray):
    """Van Tharp System Quality Number: sqrt(N) * mean(pnl) / std(pnl)."""
    n = pnl.size
    if n < 2:
        return None
    sd = float(np.std(pnl, ddof=1))
    if sd == 0:
        return None
    return float(math.sqrt(n) * float(np.mean(pnl)) / sd)


def _kelly_pct(base: dict):
    payoff = base.get("payoff_ratio")
    wr = base.get("win_rate")
    if payoff is None or wr is None or payoff == 0:
        return None
    p = wr / 100.0
    kelly = p - (1.0 - p) / payoff
    return float(kelly * 100.0)


def _streaks(df: pd.DataFrame) -> dict[str, int]:
    if "result" in df.columns:
        results = df.sort_values("exit_time")["result"].tolist() if "exit_time" in df.columns else df["result"].tolist()
    else:
        pnl = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
        results = ["win" if v > 0 else "loss" if v < 0 else "be" for v in pnl]
    max_w = max_l = cur_w = cur_l = 0
    for r in results:
        if r == "win":
            cur_w += 1
            cur_l = 0
        elif r == "loss":
            cur_l += 1
            cur_w = 0
        else:
            cur_w = cur_l = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)
    return {"max_consec_wins": max_w, "max_consec_losses": max_l}


def _psr(pnl: np.ndarray, initial: float):
    """Probabilistic Sharpe Ratio vs a zero benchmark, accounting for non-normality."""
    if pnl.size < 2:
        return None
    r = pnl / initial
    sd = float(np.std(r, ddof=1))
    if sd == 0:
        return None
    sr = float(np.mean(r)) / sd
    s = pd.Series(r)
    skew = float(s.skew()) if s.size > 2 else 0.0
    kurt = float(s.kurtosis()) + 3.0 if s.size > 3 else 3.0  # pandas gives excess kurtosis
    psr = probabilistic_sharpe_ratio(sr, pnl.size, skew=skew, kurtosis=kurt, benchmark_sr=0.0)
    return None if (psr != psr) else float(psr)  # NaN guard


def _monte_carlo_risk(df: pd.DataFrame, initial: float, *, n_sims: int, seed: int | None) -> dict[str, Any]:
    sims = monte_carlo_equity(df, initial, n_sims=n_sims, mode="bootstrap", seed=seed)
    if sims.size == 0:
        return {k: None for k in ("risk_of_ruin_pct", "prob_profit_pct", "mc_final_p05",
                                  "mc_final_p50", "mc_final_p95", "mc_maxdd_p95")}
    final = sims[:, -1]
    troughs = sims.min(axis=1)
    ruin_level = initial * (1.0 - _RUIN_DRAWDOWN)
    max_dds = np.array([_path_max_dd(p, initial) for p in sims], dtype=float)
    return {
        "risk_of_ruin_pct": float(np.mean(troughs <= ruin_level) * 100.0),
        "prob_profit_pct": float(np.mean(final > initial) * 100.0),
        "mc_final_p05": float(np.percentile(final, 5)),
        "mc_final_p50": float(np.percentile(final, 50)),
        "mc_final_p95": float(np.percentile(final, 95)),
        "mc_maxdd_p95": float(np.percentile(max_dds, 95)),
    }


def _path_max_dd(equity: np.ndarray, initial: float) -> float:
    peak = np.maximum.accumulate(np.concatenate(([initial], equity)))
    dd = (np.concatenate(([initial], equity)) - peak) / peak * 100.0
    return float(dd.min())


def _bar_indexed_equity(trades: pd.DataFrame, data: pd.DataFrame, initial: float) -> pd.Series:
    """Strategy equity sampled on the data's bar timeline (step at each trade exit)."""
    times = pd.to_datetime(data["datetime"]) if "datetime" in data.columns else pd.Series(data.index)
    eq = pd.Series(initial, index=range(len(data)), dtype=float)
    ordered = trades.sort_values("exit_time")
    running = initial
    exit_times = pd.to_datetime(ordered["exit_time"]).to_numpy()
    pnls = pd.to_numeric(ordered["pnl"], errors="coerce").fillna(0.0).to_numpy()
    bar_times = times.to_numpy()
    for t, p in zip(exit_times, pnls):
        running += float(p)
        idx = int(np.searchsorted(bar_times, t, side="right")) - 1
        if 0 <= idx < len(eq):
            eq.iloc[idx:] = running
    return eq
