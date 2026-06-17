from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..analytics.monte_carlo import monte_carlo_equity
from ..analytics.metrics import compute_metrics, drawdown_curve, equity_curve
from ..analytics.benchmark import buy_and_hold_equity
from ..optimization.overfit import _norm_ppf


def generate_report_bundle(
    data: pd.DataFrame,
    trades: pd.DataFrame,
    config: dict | None = None,
    output_dir: str | Path = "reports/backtest_report",
    initial_capital: float | None = None,
    title: str = "Backtest Report",
    zone_analytics: dict | None = None,
    extra_charts: list | None = None,
) -> dict[str, str]:
    """
    Export a complete report bundle:
      - trades.csv
      - metrics.json
      - PNG charts
      - embedded HTML report
    """
    if trades is None or trades.empty:
        raise ValueError("trades is empty; cannot generate a report")

    cfg = config or {}
    initial = float(initial_capital or cfg.get("initial_capital", 1000.0))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    data_clean = _prepare_data(data)
    trades_clean = _prepare_trades(trades)
    metrics = compute_metrics(trades_clean, initial)

    trades_path = out / "trades.csv"
    metrics_path = out / "metrics.json"
    html_path = out / "backtest_report.html"

    trades_clean.to_csv(trades_path, index=False)
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=True), encoding="utf-8")

    chart_paths = _generate_all_charts(data_clean, trades_clean, initial, out, cfg, zone_analytics)
    _write_html_report(html_path, title, cfg, metrics, trades_clean, chart_paths, extra_charts=extra_charts)

    return {
        "output_dir": str(out.resolve()),
        "trades_csv": str(trades_path.resolve()),
        "metrics_json": str(metrics_path.resolve()),
        "html": str(html_path.resolve()),
    }


def _prepare_data(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    if "datetime" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index().rename(columns={"index": "datetime"})
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    df = trades.copy()
    for col in ("entry_time", "exit_time"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    for col in (
        "entry_price",
        "exit_price",
        "size",
        "stop_price",
        "take_price",
        "risk",
        "risk_reward",
        "max_favor",
        "max_adverse",
        "gross_pnl",
        "swap",
        "commission_open",
        "commission_close",
        "entry_spread_points",
        "exit_spread_points",
        "contract_size",
        "notional_value",
        "leverage",
        "margin_required",
        "free_margin_at_entry",
        "pnl",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("exit_time").reset_index(drop=True)


def _generate_all_charts(
    data: pd.DataFrame,
    trades: pd.DataFrame,
    initial_capital: float,
    out: Path,
    config: dict | None = None,
    zone_analytics: dict | None = None,
) -> dict[str, Path]:
    cfg = config or {}
    contract_size = float(cfg.get("contract_size", 100_000.0) or 100_000.0)
    point = float(cfg.get("point", 0.00001) or 0.00001)
    charts: dict[str, Path] = {}
    chart_specs = [
        ("equity_total", lambda p: plot_equity_curve(trades, initial_capital, p)),
        ("drawdown_curve", lambda p: plot_drawdown_curve(trades, initial_capital, p)),
        ("underwater", lambda p: plot_underwater(trades, initial_capital, p)),
        ("rolling_sharpe", lambda p: plot_rolling_sharpe(trades, p)),
        ("strategy_vs_buyhold", lambda p: plot_strategy_vs_buyhold(data, trades, initial_capital, contract_size, point, p)),
        ("zsharp", lambda p: plot_zsharp(data, p)),
        ("drawdown_monthly", lambda p: plot_monthly_drawdown(trades, initial_capital, p)),
        ("histograms", lambda p: plot_histograms(trades, p)),
        ("returns_qq", lambda p: plot_returns_qq(trades, p)),
        ("heatmap", lambda p: plot_heatmap_trades(trades, p)),
        ("scatter", lambda p: plot_scatter_relations(trades, p)),
        ("monthly_profit", lambda p: plot_monthly_profit(trades, p)),
        ("monthly_returns_table", lambda p: plot_monthly_returns_table(trades, initial_capital, p)),
        ("profit_factor_month", lambda p: plot_profit_factor_by_month(trades, p)),
        ("yearly_profit", lambda p: plot_yearly_profit(trades, p)),
        ("best_worst", lambda p: plot_best_and_worst_trades(trades, p)),
        ("boxplot_weekday", lambda p: plot_boxplot_weekday(trades, p)),
        ("boxplot_hour", lambda p: plot_boxplot_hour(trades, p)),
        ("monte_carlo_shuffle", lambda p: plot_monte_carlo_equity_variant(trades, initial_capital, p, mode="shuffle")),
        ("monte_carlo_bootstrap", lambda p: plot_monte_carlo_equity_variant(trades, initial_capital, p, mode="bootstrap")),
        ("monte_carlo_block_bootstrap", lambda p: plot_monte_carlo_equity_variant(trades, initial_capital, p, mode="block_bootstrap")),
        ("monte_carlo_fan", lambda p: plot_monte_carlo_fan(trades, initial_capital, p)),
        ("monte_carlo_distribution", lambda p: plot_monte_carlo_distribution(trades, initial_capital, p)),
        ("r_multiples", lambda p: plot_r_multiples(trades, p)),
    ]

    if zone_analytics and zone_analytics.get("by_zone"):
        chart_specs.append(("zone_edge", lambda p: plot_zone_edge(zone_analytics, p)))
        chart_specs.append(("zone_respect", lambda p: plot_zone_respect(zone_analytics, p)))
    if {"high", "low"}.issubset(data.columns):
        chart_specs.append(("volatility_vs_pnl", lambda p: plot_volatility_vs_pnl(data, trades, p)))
    if _find_atr_column(data) is not None:
        chart_specs.append(("atr_volume_price", lambda p: plot_3d_atr_volume_price(data, p)))

    for name, fn in chart_specs:
        path = out / f"{name}.png"
        try:
            fn(path)
            if path.exists():
                charts[name] = path
        except Exception as exc:
            print(f"[report] skipped chart {name}: {exc}")

    return charts


def _use_dark_style():
    plt.style.use("dark_background")


def _save(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_equity_curve(trades: pd.DataFrame, initial_capital: float, path: Path):
    _use_dark_style()
    eq = equity_curve(trades, initial_capital)
    x = np.arange(len(eq))
    fig, ax = plt.subplots(figsize=(16, 5))
    ax.plot(x, eq.values, color="#00e5ff", linewidth=2.3)
    ax.fill_between(x, eq.values, initial_capital, color="#00e5ff", alpha=0.12)
    ax.axhline(initial_capital, color="#cfd8dc", linestyle="--", linewidth=1)
    ax.set_title("Equity Curve")
    ax.set_xlabel("Trades")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_drawdown_curve(trades: pd.DataFrame, initial_capital: float, path: Path):
    _use_dark_style()
    eq = equity_curve(trades, initial_capital)
    dd = drawdown_curve(eq)
    fig, ax = plt.subplots(figsize=(16, 4))
    ax.plot(dd.index, dd["drawdown_pct"], color="#ff5252", linewidth=1.8)
    ax.fill_between(dd.index, dd["drawdown_pct"], 0, color="#ff5252", alpha=0.18)
    ax.axhline(0, color="#cfd8dc", linewidth=1)
    ax.set_title("Drawdown Curve")
    ax.set_xlabel("Trades")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _compute_zsharp(close: pd.Series, period: int = 20) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    mean = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0).replace(0, np.nan)
    return (close - mean) / std


def _smooth_series(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=max(int(span), 2), adjust=False, min_periods=1).mean()


def plot_zsharp(data: pd.DataFrame, path: Path, period: int = 20):
    _use_dark_style()
    df = data.copy()
    if "close" not in df.columns:
        return
    if "datetime" in df.columns:
        x = pd.to_datetime(df["datetime"])
    else:
        x = pd.RangeIndex(len(df))
    z = _compute_zsharp(df["close"], period=period)
    z = z.clip(-3.5, 3.5)
    smooth_span = max(20, len(df) // 60)
    z_smooth = _smooth_series(z.ffill().fillna(0.0), smooth_span).clip(-3.5, 3.5)

    fig, ax = plt.subplots(figsize=(16, 5))
    ax.plot(x, z_smooth, color="#4ad6e6", linewidth=4.8, alpha=0.18, label="_nolegend_", solid_capstyle="round")
    ax.plot(x, z_smooth, color="#4ad6e6", linewidth=2.4, label="Z-Sharp suave", solid_capstyle="round")
    ax.axhline(2, color="#2bd47f", linestyle=(0, (4, 4)), linewidth=0.9, alpha=0.55)
    ax.axhline(1, color="#4ad6e6", linestyle=(0, (2, 4)), linewidth=0.8, alpha=0.3)
    ax.axhline(0, color="#b5c0cf", linewidth=0.9, alpha=0.45)
    ax.axhline(-1, color="#4ad6e6", linestyle=(0, (2, 4)), linewidth=0.8, alpha=0.3)
    ax.axhline(-2, color="#ff5867", linestyle=(0, (4, 4)), linewidth=0.9, alpha=0.55)
    ax.fill_between(x, 0, z_smooth, color="#4ad6e6", alpha=0.22)
    ax.set_title("Z-Sharp (Close Z-Score)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Z-Score")
    ax.set_ylim(-3.5, 3.5)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    _save(fig, path)


def plot_monthly_drawdown(trades: pd.DataFrame, initial_capital: float, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["equity"] = initial_capital + df["pnl"].cumsum()
    df["peak"] = df["equity"].cummax()
    df["dd_pct"] = (df["equity"] - df["peak"]) / df["peak"] * 100.0
    df["month"] = df["exit_time"].dt.to_period("M")
    monthly = df.groupby("month")["dd_pct"].min()

    fig, ax = plt.subplots(figsize=(18, 5))
    labels = [str(x) for x in monthly.index]
    ax.bar(labels, monthly.values, color="#ff5252", alpha=0.85)
    ax.axhline(0, color="#cfd8dc", linewidth=1)
    ax.set_title("Monthly Max Drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.tick_params(axis="x", rotation=75)
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_histograms(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    fig, axes = plt.subplots(1, 3, figsize=(20, 5))
    axes[0].hist(trades["pnl"], bins=40, color="#00e5ff", alpha=0.85)
    axes[0].axvline(0, color="white", linestyle="--", linewidth=1)
    axes[0].set_title("PnL Distribution")

    rr = trades["risk_reward"].replace([np.inf, -np.inf], np.nan).dropna()
    if rr.empty:
        rr = pd.Series([0.0])
    axes[1].hist(rr, bins=40, color="#ff40ff", alpha=0.85)
    axes[1].axvline(0, color="white", linestyle="--", linewidth=1)
    axes[1].set_title("R Multiple Distribution")

    dur = pd.to_timedelta(trades["duration"]).dt.total_seconds() / 3600.0
    axes[2].hist(dur, bins=40, color="#ffc400", alpha=0.85)
    axes[2].set_title("Trade Duration (hours)")

    for ax in axes:
        ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_heatmap_trades(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["weekday"] = df["exit_time"].dt.weekday
    df["hour"] = df["exit_time"].dt.hour
    pivot = (
        df.pivot_table(values="pnl", index="weekday", columns="hour", aggfunc="mean")
        .reindex(index=range(7), columns=range(24))
    )
    fig, ax = plt.subplots(figsize=(14, 6))
    values = pivot.to_numpy(dtype=float)
    vmax = np.nanmax(np.abs(values)) if np.isfinite(values).any() else 1.0
    im = ax.imshow(values, aspect="auto", cmap="viridis", vmin=-vmax, vmax=vmax)
    fig.colorbar(im, ax=ax, label="Avg PnL")
    ax.set_title("Average PnL by Weekday and Hour")
    ax.set_xlabel("Hour")
    ax.set_ylabel("Weekday (0=Mon)")
    ax.set_xticks(range(0, 24, 2))
    ax.set_yticks(range(7))
    _save(fig, path)


def plot_scatter_relations(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["duration_minutes"] = pd.to_timedelta(df["duration"]).dt.total_seconds() / 60.0
    fig, axes = plt.subplots(1, 3, figsize=(20, 5))
    axes[0].scatter(df["max_favor"], df["pnl"], alpha=0.65, color="#00e5ff")
    axes[0].set_title("MFE vs PnL")
    axes[1].scatter(df["max_adverse"], df["pnl"], alpha=0.65, color="#ff5252")
    axes[1].set_title("MAE vs PnL")
    axes[2].scatter(df["duration_minutes"], df["pnl"], alpha=0.65, color="#69f0ae")
    axes[2].set_title("Duration vs PnL")
    for ax in axes:
        ax.axhline(0, color="white", linewidth=0.7, alpha=0.5)
        ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_monthly_profit(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["month"] = pd.to_datetime(df["exit_time"]).dt.to_period("M")
    pnl = df.groupby("month")["pnl"].sum()
    colors = ["#00c853" if v >= 0 else "#ff5252" for v in pnl.values]
    fig, ax = plt.subplots(figsize=(18, 5))
    ax.bar([str(x) for x in pnl.index], pnl.values, color=colors)
    ax.set_title("Monthly Net Profit")
    ax.set_ylabel("PnL")
    ax.tick_params(axis="x", rotation=75)
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_profit_factor_by_month(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["month"] = pd.to_datetime(df["exit_time"]).dt.to_period("M")

    def _pf(group):
        wins = group.loc[group["pnl"] > 0, "pnl"].sum()
        losses = group.loc[group["pnl"] < 0, "pnl"].sum()
        return wins / abs(losses) if losses < 0 else np.nan

    pf = df.groupby("month", group_keys=False)[["pnl"]].apply(_pf)
    fig, ax = plt.subplots(figsize=(18, 5))
    ax.bar([str(x) for x in pf.index], pf.values, color="#ffab00")
    ax.set_title("Profit Factor by Month")
    ax.set_ylabel("Profit Factor")
    ax.tick_params(axis="x", rotation=75)
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_yearly_profit(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["year"] = pd.to_datetime(df["exit_time"]).dt.year
    pnl = df.groupby("year")["pnl"].sum()
    colors = ["#00c853" if v >= 0 else "#ff5252" for v in pnl.values]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(pnl.index.astype(str), pnl.values, color=colors)
    ax.set_title("Yearly Net Profit")
    ax.set_ylabel("PnL")
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_best_and_worst_trades(trades: pd.DataFrame, path: Path, top: int = 15):
    _use_dark_style()
    best = trades.nlargest(top, "pnl")
    worst = trades.nsmallest(top, "pnl")
    fig, axes = plt.subplots(1, 2, figsize=(18, 5))
    axes[0].bar(range(len(best)), best["pnl"], color="#00c853")
    axes[0].set_title(f"Top {top} Best Trades")
    axes[1].bar(range(len(worst)), worst["pnl"], color="#ff5252")
    axes[1].set_title(f"Top {top} Worst Trades")
    for ax in axes:
        ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_volatility_vs_pnl(data: pd.DataFrame, trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    source = data.copy()
    source["datetime"] = pd.to_datetime(source["datetime"])
    volatility = source.set_index("datetime").eval("high - low")
    entry_times = pd.to_datetime(df["entry_time"])
    vol_at_entry = volatility.reindex(entry_times, method="nearest").to_numpy()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.scatter(vol_at_entry, df["pnl"], alpha=0.6, color="#7c4dff")
    ax.axhline(0, color="white", linewidth=0.7, alpha=0.5)
    ax.set_title("Volatility at Entry vs PnL")
    ax.set_xlabel("High - Low")
    ax.set_ylabel("PnL")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_boxplot_weekday(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["weekday"] = pd.to_datetime(df["exit_time"]).dt.weekday
    fig, ax = plt.subplots(figsize=(12, 5))
    groups = [df.loc[df["weekday"] == i, "pnl"].dropna().to_numpy() for i in range(7)]
    ax.boxplot(groups, labels=[str(i) for i in range(7)], patch_artist=True)
    ax.set_title("PnL Distribution by Weekday")
    ax.set_xlabel("Weekday (0=Mon)")
    ax.set_ylabel("PnL")
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_boxplot_hour(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    df = trades.copy()
    df["hour"] = pd.to_datetime(df["exit_time"]).dt.hour
    fig, ax = plt.subplots(figsize=(14, 5))
    groups = [df.loc[df["hour"] == i, "pnl"].dropna().to_numpy() for i in range(24)]
    ax.boxplot(groups, labels=[str(i) for i in range(24)], patch_artist=True)
    ax.set_title("PnL Distribution by Hour")
    ax.set_xlabel("Hour")
    ax.set_ylabel("PnL")
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def plot_monte_carlo_equity_variant(
    trades: pd.DataFrame,
    initial_capital: float,
    path: Path,
    *,
    mode: str,
):
    _use_dark_style()
    sims = monte_carlo_equity(trades, initial_capital, n_sims=500, mode=mode, seed=42)
    real = initial_capital + trades.sort_values("exit_time")["pnl"].cumsum().to_numpy()
    fig, ax = plt.subplots(figsize=(16, 6))
    for curve in sims[:150]:
        ax.plot(curve, color="gray", alpha=0.07)
    ax.plot(real, color="#00e5ff", linewidth=2.4, label="Real equity")
    ax.set_title(f"Monte Carlo Equity · {mode.replace('_', ' ').title()}")
    ax.set_xlabel("Trade")
    ax.set_ylabel("Equity")
    ax.legend()
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_monte_carlo_distribution(trades: pd.DataFrame, initial_capital: float, path: Path):
    _use_dark_style()
    sims = monte_carlo_equity(trades, initial_capital, n_sims=1000, mode="bootstrap", seed=42)
    final_eq = sims[:, -1]
    max_dd = [(eq - np.maximum.accumulate(eq)).min() for eq in sims]
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    axes[0].hist(final_eq, bins=45, color="#00e5ff", alpha=0.85)
    axes[0].set_title("Bootstrap · Final Balance Distribution")
    axes[1].hist(max_dd, bins=45, color="#ff5252", alpha=0.85)
    axes[1].set_title("Bootstrap · Max Drawdown Distribution")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_r_multiples(trades: pd.DataFrame, path: Path):
    _use_dark_style()
    if "risk_reward" in trades.columns:
        r = trades["risk_reward"].replace([np.inf, -np.inf], np.nan).dropna()
    else:
        base = trades["max_adverse"].abs().replace(0, np.nan)
        r = (trades["pnl"] / base).replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        r = pd.Series([0.0])
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.hist(r, bins=50, color="#b388ff", alpha=0.85)
    ax.axvline(0, color="white", linestyle="--", linewidth=1)
    ax.set_title("R Multiples")
    ax.set_xlabel("R")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_underwater(trades: pd.DataFrame, initial_capital: float, path: Path):
    """Underwater plot: % drawdown below the running peak over trades."""
    _use_dark_style()
    eq = equity_curve(trades, initial_capital)
    dd = drawdown_curve(eq)["drawdown_pct"].to_numpy(dtype=float)
    x = np.arange(len(dd))
    fig, ax = plt.subplots(figsize=(16, 4))
    ax.fill_between(x, dd, 0, color="#ff5252", alpha=0.35)
    ax.plot(x, dd, color="#ff5252", linewidth=1.4)
    ax.axhline(0, color="#cfd8dc", linewidth=1)
    ax.set_title("Underwater (Drawdown %)")
    ax.set_xlabel("Trades")
    ax.set_ylabel("Drawdown %")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_rolling_sharpe(trades: pd.DataFrame, path: Path, window: int = 30):
    """Rolling per-trade Sharpe — shows when the edge was strong vs fading."""
    _use_dark_style()
    pnl = pd.to_numeric(trades.sort_values("exit_time")["pnl"], errors="coerce").fillna(0.0)
    w = max(5, min(window, len(pnl)))
    roll = pnl.rolling(w)
    sharpe = (roll.mean() / roll.std(ddof=1)).replace([np.inf, -np.inf], np.nan)
    x = np.arange(len(sharpe))
    fig, ax = plt.subplots(figsize=(16, 4))
    ax.plot(x, sharpe.to_numpy(), color="#ffd54f", linewidth=1.8)
    ax.axhline(0, color="#cfd8dc", linestyle="--", linewidth=1)
    ax.set_title(f"Rolling Sharpe (window={w} trades)")
    ax.set_xlabel("Trades")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_strategy_vs_buyhold(data, trades, initial_capital, contract_size, point, path: Path):
    """Strategy equity (sampled on bars) vs passive buy & hold on the same window."""
    _use_dark_style()
    if "close" not in data.columns or len(data) < 2:
        return
    bh = buy_and_hold_equity(data, initial_capital, contract_size, point).to_numpy(dtype=float)
    times = pd.to_datetime(data["datetime"]).to_numpy() if "datetime" in data.columns else np.arange(len(data))
    strat = np.full(len(data), float(initial_capital))
    ordered = trades.sort_values("exit_time")
    running = float(initial_capital)
    ex = pd.to_datetime(ordered["exit_time"]).to_numpy()
    pnls = pd.to_numeric(ordered["pnl"], errors="coerce").fillna(0.0).to_numpy()
    for t, p in zip(ex, pnls):
        running += float(p)
        idx = int(np.searchsorted(times, t, side="right")) - 1
        if 0 <= idx < len(strat):
            strat[idx:] = running
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(16, 5))
    ax.plot(x, strat, color="#00e5ff", linewidth=2.2, label="Strategy")
    ax.plot(x, bh, color="#9e9e9e", linewidth=1.8, label="Buy & Hold")
    ax.axhline(initial_capital, color="#cfd8dc", linestyle="--", linewidth=1)
    ax.set_title("Strategy vs Buy & Hold")
    ax.set_xlabel("Bars")
    ax.set_ylabel("Equity")
    ax.legend()
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_returns_qq(trades: pd.DataFrame, path: Path):
    """QQ plot of per-trade PnL vs a normal distribution (fat-tail check)."""
    _use_dark_style()
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").dropna().to_numpy(dtype=float)
    if pnl.size < 3:
        return
    sample = np.sort(pnl)
    n = sample.size
    probs = (np.arange(1, n + 1) - 0.5) / n
    theo = np.array([_norm_ppf(p) for p in probs])
    mu, sigma = float(np.mean(sample)), float(np.std(sample, ddof=1)) or 1.0
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(theo, sample, s=12, color="#80d8ff", alpha=0.8)
    line = mu + sigma * theo
    ax.plot(theo, line, color="#ff5252", linewidth=1.6, label="Normal")
    ax.set_title("QQ Plot · Trade PnL vs Normal")
    ax.set_xlabel("Theoretical quantiles")
    ax.set_ylabel("Observed PnL")
    ax.legend()
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_monthly_returns_table(trades: pd.DataFrame, initial_capital: float, path: Path):
    """Calendar heatmap of monthly returns (year rows × month cols)."""
    _use_dark_style()
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["year"] = df["exit_time"].dt.year
    df["month"] = df["exit_time"].dt.month
    monthly = df.groupby(["year", "month"])["pnl"].sum().reset_index()
    if monthly.empty:
        return
    pivot = monthly.pivot(index="year", columns="month", values="pnl").reindex(columns=range(1, 13))
    grid = (pivot / initial_capital * 100.0).to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(14, max(2.4, 0.6 * pivot.shape[0] + 1.5)))
    vmax = np.nanmax(np.abs(grid)) if np.isfinite(grid).any() else 1.0
    im = ax.imshow(grid, cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels([str(y) for y in pivot.index])
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8, color="#212121")
    ax.set_title("Monthly Returns (% of initial)")
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    _save(fig, path)


def plot_monte_carlo_fan(trades: pd.DataFrame, initial_capital: float, path: Path):
    """Monte Carlo fan: P05/P25/median/P75/P95 equity bands + ruin line."""
    _use_dark_style()
    sims = monte_carlo_equity(trades, initial_capital, n_sims=1000, mode="bootstrap", seed=42)
    if sims.size == 0:
        return
    x = np.arange(sims.shape[1])
    p05, p25, p50, p75, p95 = (np.percentile(sims, q, axis=0) for q in (5, 25, 50, 75, 95))
    real = initial_capital + trades.sort_values("exit_time")["pnl"].cumsum().to_numpy()
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.fill_between(x, p05, p95, color="#00e5ff", alpha=0.12, label="P05–P95")
    ax.fill_between(x, p25, p75, color="#00e5ff", alpha=0.22, label="P25–P75")
    ax.plot(x, p50, color="#00e5ff", linewidth=1.8, label="Median")
    ax.plot(np.arange(len(real)), real, color="#ffd54f", linewidth=2.2, label="Real")
    ax.axhline(initial_capital * 0.5, color="#ff5252", linestyle="--", linewidth=1.2, label="Ruin (-50%)")
    ax.set_title("Monte Carlo Fan · Bootstrap")
    ax.set_xlabel("Trade")
    ax.set_ylabel("Equity")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def plot_zone_edge(zone_analytics: dict, path: Path):
    """Net PnL per zone, colored by win rate — which drawn zones had edge."""
    _use_dark_style()
    rows = [z for z in zone_analytics.get("by_zone", []) if z.get("trades", 0) > 0]
    if not rows:
        return
    rows.sort(key=lambda z: z.get("net_pnl", 0.0))
    labels = [f"{z['zone_id']} {z.get('side','')[:3]} {z.get('timeframe','')}" for z in rows]
    pnls = [z.get("net_pnl", 0.0) for z in rows]
    wr = [z.get("win_rate") or 0.0 for z in rows]
    colors = plt.cm.RdYlGn(np.array(wr) / 100.0)
    fig, ax = plt.subplots(figsize=(12, max(3, 0.45 * len(rows) + 1)))
    ax.barh(range(len(rows)), pnls, color=colors)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.axvline(0, color="white", linewidth=1)
    ax.set_title("Edge por Zona (PnL líquido · cor = win rate)")
    ax.set_xlabel("Net PnL")
    ax.grid(True, axis="x", alpha=0.25)
    _save(fig, path)


def plot_zone_respect(zone_analytics: dict, path: Path):
    """Respect rate per zone: bounces vs breaks on touches after the draw."""
    _use_dark_style()
    rows = [z for z in zone_analytics.get("by_zone", []) if (z.get("touches") or 0) > 0]
    if not rows:
        return
    rows.sort(key=lambda z: (z.get("respect_rate") or 0.0))
    labels = [f"{z['zone_id']} {z.get('side','')[:3]} {z.get('timeframe','')}" for z in rows]
    bounces = [z.get("bounces", 0) for z in rows]
    breaks = [z.get("breaks", 0) for z in rows]
    y = range(len(rows))
    fig, ax = plt.subplots(figsize=(12, max(3, 0.45 * len(rows) + 1)))
    ax.barh(y, bounces, color="#66bb6a", label="Bounces")
    ax.barh(y, breaks, left=bounces, color="#ff5252", label="Breaks")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title("Respeito por Zona (toques: respeitou × rompeu)")
    ax.set_xlabel("Touches")
    ax.legend()
    ax.grid(True, axis="x", alpha=0.25)
    _save(fig, path)


def plot_3d_atr_volume_price(data: pd.DataFrame, path: Path):
    _use_dark_style()
    atr_col = _find_atr_column(data)
    if atr_col is None:
        return
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")
    clean = data[["close", "volume", atr_col]].dropna()
    ax.scatter(clean["close"], clean["volume"], clean[atr_col], s=7, c=clean[atr_col], cmap="viridis")
    ax.set_title("Close x Volume x ATR")
    ax.set_xlabel("Close")
    ax.set_ylabel("Volume")
    ax.set_zlabel(atr_col)
    _save(fig, path)


def _find_atr_column(data: pd.DataFrame) -> str | None:
    return next((col for col in data.columns if "atr" in col.lower()), None)


def _img_to_base64(path: Path) -> str | None:
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _fmt_money(value) -> str:
    return f"${float(value):,.2f}"


def _fmt_pct(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):+.2f}%"


def _fmt_ratio(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    num = float(value)
    if np.isinf(num):
        return "∞"
    return f"{num:.2f}"


def _fmt_num(value, digits: int = 2, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _spread_label(config: dict) -> str:
    if config.get("use_spread") and config.get("spread_column"):
        return f"Real (coluna '{config['spread_column']}')"
    fixed = config.get("fixed_spread_points")
    if fixed not in (None, "", 0):
        return f"{_fmt_num(fixed, 0)} pts (fixo)"
    return "0 (sem spread)"


def _broker_cost_section(config: dict, metrics: dict) -> str:
    """Costs + asset/broker specs panel — shown by default in the report."""
    sym = config.get("symbol") or "—"
    tf = config.get("timeframe") or ""
    broker = config.get("broker") or "—"
    weekday_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    try:
        triple = weekday_names[int(config.get("triple_swap_weekday", 2))]
    except (TypeError, ValueError, IndexError):
        triple = "—"

    gross = float(metrics.get("gross_pnl", metrics.get("net_profit", 0.0)) or 0.0)
    comm = float(metrics.get("total_commissions", 0.0) or 0.0)
    swap = float(metrics.get("total_swap", 0.0) or 0.0)
    net = float(metrics.get("net_profit", 0.0) or 0.0)
    cost_total = comm - swap  # net = gross - commissions + swap
    drag = (cost_total / abs(gross) * 100.0) if gross else 0.0

    def kv(label, value):
        return f'<div class="kv"><span>{label}</span><strong>{value}</strong></div>'

    asset = "".join([
        kv("Ativo", f"{sym} {tf}".strip()),
        kv("Corretora", broker),
        kv("Contract size", _fmt_num(config.get("contract_size"), 0)),
        kv("Point", _fmt_num(config.get("point"), 5)),
        kv("Alavancagem", f"1:{_fmt_num(config.get('leverage'), 0)}"),
    ])
    params = "".join([
        kv("Comissao / lote", _fmt_money(config["commission_per_lot"]) if config.get("commission_per_lot") is not None else "—"),
        kv("Comissao %", _fmt_num(config.get("commission_perc"), 3, "%")),
        kv("Swap long / lote-dia", _fmt_money(config["swap_long_per_lot"]) if config.get("swap_long_per_lot") is not None else "—"),
        kv("Swap short / lote-dia", _fmt_money(config["swap_short_per_lot"]) if config.get("swap_short_per_lot") is not None else "—"),
        kv("Triple swap", triple),
        kv("Spread", _spread_label(config)),
    ])
    realized = "".join([
        kv("PnL bruto", _fmt_money(gross)),
        kv("(-) Comissoes", _fmt_money(-comm)),
        kv("(+/-) Swap", _fmt_money(swap)),
        kv("(=) Lucro liquido", _fmt_money(net)),
        kv("Custo total", _fmt_money(cost_total)),
        kv("% do bruto consumido", _fmt_num(drag, 1, "%")),
    ])
    return f"""
    <section class="broker-costs">
      <div class="bc-col"><h3>Ativo / Corretora</h3>{asset}</div>
      <div class="bc-col"><h3>Parametros de custo</h3>{params}</div>
      <div class="bc-col"><h3>Custos realizados</h3>{realized}</div>
    </section>
    """


def _write_html_report(
    html_path: Path,
    title: str,
    config: dict,
    metrics: dict,
    trades: pd.DataFrame,
    chart_paths: dict[str, Path],
    extra_charts: list | None = None,
) -> None:
    chart_cards = []
    chart_titles = {
        "equity_total": "Equity Curve",
        "drawdown_curve": "Drawdown Curve",
        "zsharp": "Z-Sharp (Close Z-Score)",
        "drawdown_monthly": "Monthly Drawdown",
        "histograms": "PnL, R and Duration",
        "heatmap": "Weekday and Hour Heatmap",
        "scatter": "MFE, MAE and Duration vs PnL",
        "monthly_profit": "Monthly Net Profit",
        "profit_factor_month": "Monthly Profit Factor",
        "yearly_profit": "Yearly Net Profit",
        "best_worst": "Best and Worst Trades",
        "boxplot_weekday": "Weekday PnL Boxplot",
        "boxplot_hour": "Hourly PnL Boxplot",
        "monte_carlo_shuffle": "Monte Carlo Shuffle Equity",
        "monte_carlo_bootstrap": "Monte Carlo Bootstrap Equity",
        "monte_carlo_block_bootstrap": "Monte Carlo Block Bootstrap Equity",
        "monte_carlo_distribution": "Monte Carlo Distribution",
        "r_multiples": "R Multiples",
        "volatility_vs_pnl": "Volatility vs PnL",
        "atr_volume_price": "Close x Volume x ATR",
    }

    for key, path in chart_paths.items():
        encoded = _img_to_base64(path)
        if not encoded:
            continue
        chart_cards.append(
            f"""
            <section class="chart-card">
              <h2>{chart_titles.get(key, key)}</h2>
              <img src="data:image/png;base64,{encoded}" alt="{key}">
            </section>
            """
        )

    rows = []
    table = trades.tail(300).copy()
    for _, row in table.iterrows():
        direction = str(row.get("direction", "")).upper()
        pnl = float(row.get("pnl", 0.0))
        costs = float(row.get("commission_open", 0.0)) + float(row.get("commission_close", 0.0))
        swap = float(row.get("swap", 0.0))
        margin = float(row.get("margin_required", 0.0))
        pnl_class = "pos" if pnl > 0 else ("neg" if pnl < 0 else "flat")
        rows.append(
            f"""
            <tr>
              <td>#{int(row.get("id", 0))}</td>
              <td>{pd.to_datetime(row.get("entry_time")).strftime("%Y-%m-%d %H:%M")}</td>
              <td>{direction}</td>
              <td>{float(row.get("entry_price", 0.0)):.4f}</td>
              <td>{float(row.get("exit_price", 0.0)):.4f}</td>
              <td>{margin:,.2f}</td>
              <td>{costs:,.2f}</td>
              <td>{swap:,.2f}</td>
              <td class="{pnl_class}">{pnl:,.2f}</td>
              <td>{str(row.get("exit_reason", ""))}</td>
            </tr>
            """
        )

    # Pre-rendered extra charts (e.g. the robustness battery), embedded base64.
    extra_cards = []
    for title_label, img_path in (extra_charts or []):
        encoded = _img_to_base64(Path(img_path))
        if not encoded:
            continue
        extra_cards.append(
            f"""
            <section class="chart-card">
              <h2>{title_label}</h2>
              <img src="data:image/png;base64,{encoded}" alt="{title_label}">
            </section>
            """
        )
    extra_section = (
        '<h2 style="color:var(--cyan);border-top:1px solid rgba(255,255,255,.08);'
        'padding-top:22px;margin-top:26px;letter-spacing:.04em;">⚡ Robustez</h2>'
        f'<section class="charts">{"".join(extra_cards)}</section>'
        if extra_cards else ""
    )

    strategy_name = config.get("strategy_name", "N/A")
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #070a12;
      --panel: #101725;
      --panel2: #121f32;
      --text: #e9eef7;
      --muted: #9aa8bd;
      --cyan: #00e5ff;
      --green: #00c853;
      --red: #ff5252;
      --amber: #ffab00;
      --violet: #b388ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(1240px, calc(100% - 32px));
      margin: 28px auto 60px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: end;
      margin-bottom: 24px;
    }}
    h1 {{ margin: 0; font-size: 28px; }}
    .subtitle {{ color: var(--muted); margin-top: 8px; font-size: 14px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin: 22px 0 26px;
    }}
    .metric {{
      background: linear-gradient(145deg, var(--panel), var(--panel2));
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 10px;
      padding: 16px;
      min-height: 104px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: .08em;
      margin-bottom: 8px;
    }}
    .metric strong {{ font-size: 24px; }}
    .metric small {{ display: block; color: var(--muted); margin-top: 8px; }}
    .charts {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
    }}
    .chart-card {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 10px;
      padding: 16px;
    }}
    .chart-card h2 {{
      font-size: 16px;
      margin: 0 0 12px;
      color: #f6f8fb;
    }}
    .chart-card img {{
      display: block;
      width: 100%;
      max-height: 520px;
      object-fit: contain;
      background: #050812;
      border-radius: 8px;
    }}
    .table-card {{
      margin-top: 22px;
      background: var(--panel);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 10px;
      overflow: hidden;
    }}
    .table-head {{
      padding: 14px 16px;
      color: var(--muted);
      border-bottom: 1px solid rgba(255,255,255,.08);
    }}
    .table-scroll {{ overflow: auto; max-height: 520px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255,255,255,.05);
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #0d1422;
      color: var(--muted);
      font-weight: 600;
    }}
    tr:nth-child(even) td {{ background: rgba(255,255,255,.015); }}
    .pos {{ color: var(--green); font-weight: 700; }}
    .neg {{ color: var(--red); font-weight: 700; }}
    .flat {{ color: var(--muted); font-weight: 700; }}
    .broker-costs {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin: 22px 0;
    }}
    .bc-col {{
      background: var(--panel);
      border: 1px solid rgba(255,255,255,.06);
      border-radius: 12px;
      padding: 16px 18px;
    }}
    .bc-col h3 {{
      margin: 0 0 12px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--cyan);
    }}
    .kv {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 6px 0;
      border-bottom: 1px solid rgba(255,255,255,.04);
      font-size: 13px;
    }}
    .kv:last-child {{ border-bottom: none; }}
    .kv span {{ color: var(--muted); }}
    .kv strong {{ font-variant-numeric: tabular-nums; }}
    @media (max-width: 860px) {{
      header {{ display: block; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .broker-costs {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>{title}</h1>
        <div class="subtitle">Strategy: {strategy_name}</div>
      </div>
      <div class="subtitle">Trades: {metrics["total_trades"]}</div>
    </header>

    <section class="metrics">
      <div class="metric"><span>Net Return</span><strong>{_fmt_pct(metrics["net_return_pct"])}</strong><small>Net profit: {_fmt_money(metrics["net_profit"])}</small></div>
      <div class="metric"><span>Final Balance</span><strong>{_fmt_money(metrics["final_balance"])}</strong><small>Initial: {_fmt_money(metrics["initial_capital"])}</small></div>
      <div class="metric"><span>Gross PnL</span><strong>{_fmt_money(metrics.get("gross_pnl", metrics["net_profit"]))}</strong><small>Before commissions and swap</small></div>
      <div class="metric"><span>Broker Costs</span><strong>{_fmt_money(metrics.get("total_commissions", 0.0))}</strong><small>Total commissions paid</small></div>
      <div class="metric"><span>Swap</span><strong>{_fmt_money(metrics.get("total_swap", 0.0))}</strong><small>Rollover financing impact</small></div>
      <div class="metric"><span>Win Rate</span><strong>{metrics["win_rate"]:.2f}%</strong><small>{metrics["wins"]} wins / {metrics["losses"]} losses</small></div>
      <div class="metric"><span>Max Drawdown</span><strong>{_fmt_pct(metrics["max_drawdown_pct"])}</strong><small>Profit factor: {_fmt_ratio(metrics.get("profit_factor"))}</small></div>
      <div class="metric"><span>Expectancy</span><strong>{_fmt_money(metrics["expectancy"])}</strong><small>Average PnL per trade</small></div>
      <div class="metric"><span>Average Win</span><strong>{_fmt_money(metrics["avg_win"])}</strong><small>Average Loss: {_fmt_money(metrics["avg_loss"])}</small></div>
      <div class="metric"><span>Payoff Ratio</span><strong>{_fmt_ratio(metrics.get("payoff_ratio"))}</strong><small>Avg win / abs(avg loss)</small></div>
      <div class="metric"><span>Sharpe per Trade</span><strong>{_fmt_ratio(metrics.get("sharpe_per_trade"))}</strong><small>Simple trade-return Sharpe</small></div>
    </section>

    {_broker_cost_section(config, metrics)}

    <section class="charts">
      {"".join(chart_cards)}
    </section>

    {extra_section}

    <section class="table-card">
      <div class="table-head">Last {len(table)} trades</div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Entry Time</th>
              <th>Direction</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Margin</th>
              <th>Commissions</th>
              <th>Swap</th>
              <th>PnL</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
