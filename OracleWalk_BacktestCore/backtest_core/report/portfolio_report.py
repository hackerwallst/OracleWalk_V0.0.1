"""Portfolio report: multi-asset HTML report with per-symbol breakdown."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..analytics.metrics import compute_metrics, drawdown_curve, equity_curve
from ..analytics.risk import compute_risk_metrics
from ..analytics.correlation import returns_correlation_matrix


def generate_portfolio_report(
    result,
    output_dir: str | Path = "reports/portfolio_report",
    title: str = "Portfolio Report",
) -> dict[str, str]:
    """Generate HTML report from a PortfolioResult.

    result: PortfolioResult (from core.portfolio) with trades, equity, per_symbol, account.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    trades = result.trades
    equity_df = result.equity
    per_symbol = result.per_symbol
    account = result.account
    cap = float(account.get("initial_capital", 1000.0))

    metrics = compute_metrics(trades, cap)
    risk = compute_risk_metrics(trades, cap)

    per_sym_metrics = {}
    for sym, info in per_symbol.items():
        st = info.get("trades", pd.DataFrame())
        if st is not None and not st.empty:
            per_sym_metrics[sym] = compute_metrics(st, cap)
        else:
            per_sym_metrics[sym] = {"total_trades": 0, "net_profit": 0.0}

    trades.to_csv(out / "trades.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    charts = _generate_portfolio_charts(trades, equity_df, per_symbol, per_sym_metrics, cap, out)
    html_path = out / "portfolio_report.html"
    _write_portfolio_html(html_path, title, account, metrics, risk, per_sym_metrics, charts)

    return {
        "output_dir": str(out.resolve()),
        "html": str(html_path.resolve()),
    }


def _generate_portfolio_charts(trades, equity_df, per_symbol, per_sym_metrics, cap, out):
    charts = {}

    path = out / "portfolio_equity.png"
    _plot_portfolio_equity(equity_df, path)
    if path.exists():
        charts["portfolio_equity"] = path

    path = out / "symbol_contribution.png"
    _plot_symbol_contribution(per_sym_metrics, path)
    if path.exists():
        charts["symbol_contribution"] = path

    path = out / "symbol_equity.png"
    _plot_per_symbol_equity(per_symbol, cap, path)
    if path.exists():
        charts["symbol_equity"] = path

    if "symbol" in trades.columns and trades["symbol"].nunique() >= 2:
        path = out / "correlation_heatmap.png"
        _plot_correlation_heatmap(per_symbol, path)
        if path.exists():
            charts["correlation_heatmap"] = path

    path = out / "drawdown.png"
    _plot_portfolio_drawdown(trades, cap, path)
    if path.exists():
        charts["drawdown"] = path

    return charts


def _use_dark():
    plt.style.use("dark_background")


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _plot_portfolio_equity(equity_df, path):
    _use_dark()
    if equity_df is None or equity_df.empty or "equity" not in equity_df.columns:
        return
    fig, ax = plt.subplots(figsize=(16, 5))
    eq = equity_df["equity"].to_numpy(dtype=float)
    ax.plot(eq, color="#00e5ff", linewidth=2)
    ax.fill_between(range(len(eq)), eq, eq[0], color="#00e5ff", alpha=0.1)
    ax.axhline(eq[0], color="#cfd8dc", linestyle="--", linewidth=1)
    ax.set_title("Portfolio Equity")
    ax.set_xlabel("Bar")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _plot_symbol_contribution(per_sym_metrics, path):
    _use_dark()
    syms = list(per_sym_metrics.keys())
    profits = [per_sym_metrics[s].get("net_profit", 0.0) for s in syms]
    colors = ["#00c853" if p >= 0 else "#ff5252" for p in profits]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(syms, profits, color=colors)
    ax.axhline(0, color="#cfd8dc", linewidth=1)
    ax.set_title("Net Profit by Symbol")
    ax.set_ylabel("PnL")
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def _plot_per_symbol_equity(per_symbol, cap, path):
    _use_dark()
    fig, ax = plt.subplots(figsize=(16, 5))
    for sym, info in per_symbol.items():
        st = info.get("trades", pd.DataFrame())
        if st is not None and not st.empty:
            eq = equity_curve(st, cap)
            ax.plot(eq.values, linewidth=1.5, label=sym)
    ax.axhline(cap, color="#cfd8dc", linestyle="--", linewidth=1)
    ax.set_title("Equity by Symbol")
    ax.set_xlabel("Trades")
    ax.set_ylabel("Equity")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _plot_correlation_heatmap(per_symbol, path):
    _use_dark()
    rets = {}
    for sym, info in per_symbol.items():
        st = info.get("trades", pd.DataFrame())
        if st is not None and not st.empty:
            rets[sym] = st["pnl"].reset_index(drop=True)
    if len(rets) < 2:
        return
    max_len = max(len(v) for v in rets.values())
    aligned = {k: v.reindex(range(max_len)).fillna(0) for k, v in rets.items()}
    corr = returns_correlation_matrix(aligned)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index, fontsize=9)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=ax)
    ax.set_title("Return Correlation")
    _save(fig, path)


def _plot_portfolio_drawdown(trades, cap, path):
    _use_dark()
    eq = equity_curve(trades, cap)
    dd = drawdown_curve(eq)
    if dd.empty:
        return
    fig, ax = plt.subplots(figsize=(16, 4))
    ax.plot(dd.index, dd["drawdown_pct"], color="#ff5252", linewidth=1.5)
    ax.fill_between(dd.index, dd["drawdown_pct"], 0, color="#ff5252", alpha=0.15)
    ax.axhline(0, color="#cfd8dc", linewidth=1)
    ax.set_title("Portfolio Drawdown")
    ax.set_xlabel("Trades")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _img_b64(path):
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _write_portfolio_html(html_path, title, account, metrics, risk, per_sym_metrics, charts):
    chart_html = []
    titles_map = {
        "portfolio_equity": "Portfolio Equity",
        "symbol_contribution": "Net Profit by Symbol",
        "symbol_equity": "Equity by Symbol",
        "correlation_heatmap": "Return Correlation",
        "drawdown": "Portfolio Drawdown",
    }
    for key, path in charts.items():
        enc = _img_b64(path)
        if enc:
            chart_html.append(f'<section class="chart"><h2>{titles_map.get(key, key)}</h2>'
                              f'<img src="data:image/png;base64,{enc}"></section>')

    sym_rows = []
    for sym, m in per_sym_metrics.items():
        pnl = m.get("net_profit", 0.0)
        cls = "pos" if pnl > 0 else ("neg" if pnl < 0 else "")
        sym_rows.append(f'<tr><td>{sym}</td><td>{m.get("total_trades", 0)}</td>'
                        f'<td class="{cls}">{pnl:,.2f}</td>'
                        f'<td>{m.get("win_rate", 0):.1f}%</td>'
                        f'<td>{m.get("profit_factor", "-")}</td></tr>')

    def _f(v, fmt=".2f"):
        if v is None:
            return "-"
        return f"{float(v):{fmt}}"

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{title}</title>
<style>
:root{{--bg:#070a12;--panel:#101725;--text:#e9eef7;--muted:#9aa8bd;--cyan:#00e5ff;--green:#00c853;--red:#ff5252}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,sans-serif}}
main{{width:min(1240px,calc(100% - 32px));margin:28px auto 60px}}
h1{{font-size:28px;margin:0 0 8px}}
.sub{{color:var(--muted);font-size:14px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}}
.card{{background:var(--panel);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:14px}}
.card span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}}
.card strong{{font-size:22px}}
.chart{{background:var(--panel);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:14px;margin-bottom:16px}}
.chart h2{{font-size:15px;margin:0 0 10px}}
.chart img{{width:100%;border-radius:8px;background:#050812}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid rgba(255,255,255,.06)}}
th{{background:#0d1422;color:var(--muted);position:sticky;top:0}}
.pos{{color:var(--green);font-weight:700}}.neg{{color:var(--red);font-weight:700}}
</style></head><body><main>
<h1>{title}</h1>
<div class="sub">Account: {account.get("currency","USD")} | Capital: {account.get("initial_capital",0):,.2f} | Leverage: {account.get("leverage",1)}x | Symbols: {len(per_sym_metrics)}</div>

<div class="grid">
<div class="card"><span>Net Profit</span><strong>{metrics["net_profit"]:,.2f}</strong></div>
<div class="card"><span>Return</span><strong>{_f(metrics["net_return_pct"])}%</strong></div>
<div class="card"><span>Win Rate</span><strong>{metrics["win_rate"]:.1f}%</strong></div>
<div class="card"><span>Max DD</span><strong>{_f(metrics["max_drawdown_pct"])}%</strong></div>
<div class="card"><span>Trades</span><strong>{metrics["total_trades"]}</strong></div>
<div class="card"><span>Profit Factor</span><strong>{_f(metrics.get("profit_factor"))}</strong></div>
<div class="card"><span>Sortino</span><strong>{_f(risk.get("sortino"))}</strong></div>
<div class="card"><span>Calmar</span><strong>{_f(risk.get("calmar"))}</strong></div>
<div class="card"><span>VaR 95%</span><strong>{_f(risk.get("var_95"))}%</strong></div>
<div class="card"><span>CVaR 95%</span><strong>{_f(risk.get("cvar_95"))}%</strong></div>
<div class="card"><span>Ulcer Index</span><strong>{_f(risk.get("ulcer_index"))}</strong></div>
<div class="card"><span>Gain/Pain</span><strong>{_f(risk.get("gain_to_pain"))}</strong></div>
</div>

{"".join(chart_html)}

<section class="chart"><h2>Per-Symbol Summary</h2>
<table><thead><tr><th>Symbol</th><th>Trades</th><th>Net PnL</th><th>Win Rate</th><th>PF</th></tr></thead>
<tbody>{"".join(sym_rows)}</tbody></table></section>

</main></body></html>"""
    html_path.write_text(html, encoding="utf-8")
