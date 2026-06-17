"""Walk-forward optimization report: IS vs OOS per window + overfit diagnostics."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..analytics.metrics import compute_metrics, equity_curve


def generate_wfo_report(
    wf_result: dict,
    pbo_result: dict | None = None,
    dsr_result: dict | None = None,
    output_dir: str | Path = "reports/wfo_report",
    title: str = "Walk-Forward Report",
) -> dict[str, str]:
    """Generate HTML report from walk_forward() + overfit diagnostics."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    windows = wf_result["windows"]
    oos_trades = wf_result.get("oos_trades", pd.DataFrame())
    oos_metrics = wf_result.get("oos_metrics", {})
    is_mean = wf_result.get("is_objective_mean", float("nan"))
    oos_mean = wf_result.get("oos_objective_mean", float("nan"))
    degradation = wf_result.get("is_to_oos_degradation", float("nan"))
    objective = wf_result.get("objective", "sharpe_per_trade")
    scheme = wf_result.get("scheme", "anchored")

    (out / "wfo_summary.json").write_text(json.dumps({
        "windows": windows,
        "is_mean": is_mean,
        "oos_mean": oos_mean,
        "degradation": degradation,
        "objective": objective,
        "scheme": scheme,
        "oos_metrics": oos_metrics,
        "pbo": pbo_result,
        "dsr": dsr_result,
    }, indent=2, default=str), encoding="utf-8")

    if oos_trades is not None and not oos_trades.empty:
        oos_trades.to_csv(out / "oos_trades.csv", index=False)

    charts = {}

    path = out / "is_vs_oos.png"
    _plot_is_vs_oos(windows, objective, path)
    if path.exists():
        charts["is_vs_oos"] = path

    if oos_trades is not None and not oos_trades.empty:
        cap = float(oos_metrics.get("initial_capital", 1000.0))
        path = out / "oos_equity.png"
        _plot_oos_equity(oos_trades, cap, path)
        if path.exists():
            charts["oos_equity"] = path

    if pbo_result and pbo_result.get("logits"):
        path = out / "pbo_logits.png"
        _plot_pbo_logits(pbo_result, path)
        if path.exists():
            charts["pbo_logits"] = path

    path = out / "window_params.png"
    _plot_window_params(windows, path)
    if path.exists():
        charts["window_params"] = path

    html_path = out / "wfo_report.html"
    _write_wfo_html(html_path, title, windows, oos_metrics, is_mean, oos_mean,
                    degradation, objective, scheme, pbo_result, dsr_result, charts)

    return {
        "output_dir": str(out.resolve()),
        "html": str(html_path.resolve()),
    }


def _use_dark():
    plt.style.use("dark_background")


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _plot_is_vs_oos(windows, objective, path):
    _use_dark()
    if not windows:
        return
    x = [w["window"] for w in windows]
    is_vals = [w["is_objective"] for w in windows]
    oos_vals = [w["oos_objective"] for w in windows]
    fig, ax = plt.subplots(figsize=(12, 5))
    width = 0.35
    ax.bar([i - width / 2 for i in x], is_vals, width, label="In-Sample", color="#00e5ff", alpha=0.85)
    ax.bar([i + width / 2 for i in x], oos_vals, width, label="Out-of-Sample", color="#ff9100", alpha=0.85)
    ax.axhline(0, color="#cfd8dc", linewidth=1)
    ax.set_title(f"IS vs OOS — {objective}")
    ax.set_xlabel("Window")
    ax.set_ylabel(objective)
    ax.set_xticks(x)
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    _save(fig, path)


def _plot_oos_equity(oos_trades, cap, path):
    _use_dark()
    eq = equity_curve(oos_trades, cap)
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(eq.values, color="#ff9100", linewidth=2)
    ax.axhline(cap, color="#cfd8dc", linestyle="--", linewidth=1)
    ax.set_title("Stitched Out-of-Sample Equity")
    ax.set_xlabel("Trades")
    ax.set_ylabel("Equity")
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _plot_pbo_logits(pbo_result, path):
    _use_dark()
    logits = pbo_result.get("logits", [])
    if not logits:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(logits, bins=30, color="#b388ff", alpha=0.85)
    ax.axvline(0, color="#ff5252", linestyle="--", linewidth=2, label="Overfit threshold")
    pbo = pbo_result.get("pbo", 0)
    ax.set_title(f"PBO Logit Distribution — PBO = {pbo:.3f}")
    ax.set_xlabel("Logit(omega)")
    ax.set_ylabel("Count")
    ax.legend()
    ax.grid(True, alpha=0.25)
    _save(fig, path)


def _plot_window_params(windows, path):
    _use_dark()
    if not windows or "best_params" not in windows[0]:
        return
    params = {}
    for w in windows:
        for k, v in w.get("best_params", {}).items():
            params.setdefault(k, []).append(v)
    n = len(params)
    if n == 0:
        return
    fig, axes = plt.subplots(1, min(n, 4), figsize=(4 * min(n, 4), 4))
    if n == 1:
        axes = [axes]
    for ax, (name, vals) in zip(axes, list(params.items())[:4]):
        x = list(range(1, len(vals) + 1))
        ax.plot(x, vals, "o-", color="#00e5ff", linewidth=1.5)
        ax.set_title(name)
        ax.set_xlabel("Window")
        ax.grid(True, alpha=0.25)
    _save(fig, path)


def _img_b64(path):
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _f(v, fmt=".3f"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    return f"{float(v):{fmt}}"


def _write_wfo_html(html_path, title, windows, oos_metrics, is_mean, oos_mean,
                    degradation, objective, scheme, pbo, dsr, charts):
    chart_html = []
    titles_map = {
        "is_vs_oos": "In-Sample vs Out-of-Sample",
        "oos_equity": "Stitched OOS Equity",
        "pbo_logits": "PBO Logit Distribution",
        "window_params": "Best Params per Window",
    }
    for key, path in charts.items():
        enc = _img_b64(path)
        if enc:
            chart_html.append(f'<section class="chart"><h2>{titles_map.get(key, key)}</h2>'
                              f'<img src="data:image/png;base64,{enc}"></section>')

    win_rows = []
    for w in windows:
        is_v = w.get("is_objective", 0)
        oos_v = w.get("oos_objective", 0)
        cls = "pos" if oos_v > 0 else "neg"
        params_str = ", ".join(f"{k}={v}" for k, v in w.get("best_params", {}).items())
        win_rows.append(
            f'<tr><td>{w["window"]}</td><td>{w.get("test_start","")[:10]}</td>'
            f'<td>{w.get("test_end","")[:10]}</td><td>{is_v:.3f}</td>'
            f'<td class="{cls}">{oos_v:.3f}</td><td>{w.get("oos_trades",0)}</td>'
            f'<td>{w.get("oos_net_profit",0):.2f}</td><td style="font-size:11px">{params_str}</td></tr>'
        )

    pbo_val = _f(pbo.get("pbo")) if pbo else "-"
    pbo_n = pbo.get("n_combinations", 0) if pbo else 0
    dsr_val = _f(dsr.get("dsr")) if dsr else "-"
    dsr_obs = _f(dsr.get("observed_sr")) if dsr else "-"
    dsr_bench = _f(dsr.get("expected_max_sr")) if dsr else "-"

    pbo_color = "#00c853" if pbo and pbo.get("pbo", 1) < 0.5 else "#ff5252"
    dsr_color = "#00c853" if dsr and dsr.get("dsr", 0) > 0.95 else ("#ffab00" if dsr and dsr.get("dsr", 0) > 0.5 else "#ff5252")

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{title}</title>
<style>
:root{{--bg:#070a12;--panel:#101725;--text:#e9eef7;--muted:#9aa8bd}}
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
.pos{{color:#00c853;font-weight:700}}.neg{{color:#ff5252;font-weight:700}}
.verdict{{background:var(--panel);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:20px;margin-bottom:20px}}
.verdict h2{{margin:0 0 12px;font-size:18px}}
</style></head><body><main>
<h1>{title}</h1>
<div class="sub">Objective: {objective} | Scheme: {scheme} | Windows: {len(windows)}</div>

<div class="grid">
<div class="card"><span>IS Mean</span><strong>{_f(is_mean)}</strong></div>
<div class="card"><span>OOS Mean</span><strong>{_f(oos_mean)}</strong></div>
<div class="card"><span>Degradation</span><strong>{_f(degradation)}</strong></div>
<div class="card"><span>OOS Trades</span><strong>{oos_metrics.get("total_trades", 0)}</strong></div>
<div class="card"><span>OOS Net Profit</span><strong>{_f(oos_metrics.get("net_profit", 0), ".2f")}</strong></div>
<div class="card"><span>OOS Profit Factor</span><strong>{_f(oos_metrics.get("profit_factor"))}</strong></div>
<div class="card"><span style="color:{pbo_color}">PBO</span><strong style="color:{pbo_color}">{pbo_val}</strong></div>
<div class="card"><span style="color:{dsr_color}">Deflated Sharpe</span><strong style="color:{dsr_color}">{dsr_val}</strong></div>
</div>

<div class="verdict">
<h2>Overfit Diagnostics</h2>
<p><strong>PBO</strong> = {pbo_val} ({pbo_n} CSCV combinations) — {"< 0.5: optimization likely captures real signal" if pbo and pbo.get("pbo", 1) < 0.5 else "> 0.5: optimization is likely fitting noise"}</p>
<p><strong>DSR</strong> = {dsr_val} (observed SR = {dsr_obs}, benchmark = {dsr_bench}) — {"high confidence the best Sharpe is real" if dsr and dsr.get("dsr", 0) > 0.95 else "the observed Sharpe may be luck given N trials"}</p>
<p><strong>IS→OOS degradation</strong> = {_f(degradation)} — {"strategy generalizes well" if not np.isnan(degradation) and degradation > -0.1 else "significant performance drop out-of-sample"}</p>
</div>

{"".join(chart_html)}

<section class="chart"><h2>Per-Window Results</h2>
<table><thead><tr><th>#</th><th>OOS Start</th><th>OOS End</th><th>IS {objective}</th><th>OOS {objective}</th><th>OOS Trades</th><th>OOS PnL</th><th>Best Params</th></tr></thead>
<tbody>{"".join(win_rows)}</tbody></table></section>

</main></body></html>"""
    html_path.write_text(html, encoding="utf-8")
