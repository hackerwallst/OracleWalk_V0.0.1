"""Cyberpunk matplotlib charts for the robustness battery (PNGs for the dashboard).

Neon palette + glow (multi-pass low-alpha strokes) + gradient fills, all pure
matplotlib (no extra deps). Same function names/signatures as before.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

# --- cyberpunk palette ---
_BG = "#0a0a16"
_PANEL = "#0d0d1f"
_GRID = "#23234a"
_TEXT = "#cfd6ff"
_CYAN = "#00f0ff"
_MAGENTA = "#ff2bd6"
_PURPLE = "#a64dff"
_GREEN = "#2bff9e"
_AMBER = "#ffcf2b"
_RED = "#ff3b6b"
# neon heatmap colormap (deep purple -> blue -> cyan -> magenta -> hot pink)
_CYBER_CMAP = LinearSegmentedColormap.from_list(
    "cyberpunk", ["#1a0b2e", "#3a0ca3", "#4361ee", "#00f0ff", "#ff2bd6", "#ff7ce5"]
)


def _fig(w=12, h=5):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_PANEL)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
        spine.set_linewidth(1.0)
    ax.tick_params(colors=_TEXT, labelsize=9)
    ax.grid(True, color=_GRID, alpha=0.45, linewidth=0.7)
    ax.xaxis.label.set_color(_TEXT)
    ax.yaxis.label.set_color(_TEXT)
    return fig, ax


def _title(ax, text, color=_CYAN):
    ax.set_title(text, color=color, fontsize=13, fontweight="bold", pad=12)


def _save(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor=_BG)
    plt.close(fig)


def _glow_line(ax, x, y, color, lw=2.4, marker="o", label=None, n=7):
    """A bright line with a soft neon glow (multiple wide low-alpha strokes)."""
    for i in range(n, 0, -1):
        ax.plot(x, y, color=color, lw=lw + i * 1.8, alpha=0.035, solid_capstyle="round", zorder=3)
    ax.plot(x, y, color=color, lw=lw, marker=marker, markersize=6,
            markerfacecolor=color, markeredgecolor=_BG, markeredgewidth=1.2, label=label, zorder=6)


def _glow_bars(ax, positions, values, colors, width=0.8):
    bars = ax.bar(positions, values, width, color=colors, zorder=5,
                  edgecolor=[_lighten(c) for c in colors], linewidth=1.4)
    # glow: redraw a slightly larger translucent bar behind
    for pos, val, c in zip(positions, values, colors):
        ax.bar(pos, val, width * 1.04, color=c, alpha=0.12, zorder=2)
    return bars


def _lighten(hex_color, amt=0.4):
    c = hex_color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * amt); g = int(g + (255 - g) * amt); b = int(b + (255 - b) * amt)
    return f"#{r:02x}{g:02x}{b:02x}"


def _legend(ax):
    leg = ax.legend(facecolor=_PANEL, edgecolor=_GRID, labelcolor=_TEXT, fontsize=9)
    if leg:
        leg.get_frame().set_alpha(0.85)


# --------------------------------------------------------------------------- #
def plot_is_oos(io: dict, path: Path):
    fig, ax = _fig(11, 5)
    metrics = [("profit_factor", "Profit Factor"), ("win_rate", "Win %"), ("payoff_ratio", "Payoff")]
    x = np.arange(len(metrics))
    width = 0.36
    for gi, (g, c, lbl) in enumerate([("is", _CYAN, "In-Sample"), ("oos", _MAGENTA, "Out-of-Sample")]):
        vals = [float(io.get(g, {}).get(k) or 0.0) for k, _ in metrics]
        _glow_bars(ax, x + (gi - 0.5) * width, vals, [c] * len(vals), width)
        ax.bar([], [], color=c, label=lbl)
    ax.set_xticks(x); ax.set_xticklabels([n for _, n in metrics])
    ret = io.get("pf_retention")
    _title(ax, f"In-Sample vs Out-of-Sample · PF retention = {ret:.2f}" if ret else "In-Sample vs Out-of-Sample")
    _legend(ax)
    _save(fig, path)


def plot_walk_forward(wf: dict, path: Path):
    windows = wf.get("windows", [])
    if not windows:
        return
    fig, ax = _fig(12, 5)
    x = [w["window"] for w in windows]
    _glow_line(ax, x, [w.get("is_objective") for w in windows], _CYAN, label="In-Sample (otimizado)")
    _glow_line(ax, x, [w.get("oos_objective") for w in windows], _MAGENTA, label="Out-of-Sample (validacao)")
    ax.axhline(0, color=_GRID, linewidth=1)
    ax.set_xticks(x); ax.set_xlabel("Janela (fold)"); ax.set_ylabel(wf.get("objective", "objetivo"))
    deg = wf.get("is_to_oos_degradation")
    _title(ax, f"Walk-Forward · degradacao IS->OOS = {deg:+.3f}" if deg is not None else "Walk-Forward")
    _legend(ax)
    _save(fig, path)


def plot_sensitivity(sens: dict, path: Path):
    pts = sens.get("points", [])
    if not pts:
        return
    fig, ax = _fig(11, 5)
    xs = [str(p["value"]) for p in pts]
    ys = [p["objective"] for p in pts]
    _glow_line(ax, xs, ys, _GREEN)
    ax.fill_between(range(len(xs)), ys, min(ys), color=_GREEN, alpha=0.08, zorder=1)
    best = sens.get("best")
    if best is not None:
        ax.axvline(str(best["value"]), color=_AMBER, linestyle="--", linewidth=1.3, label=f"melhor = {best['value']}")
        _legend(ax)
    ax.set_xlabel(sens.get("param")); ax.set_ylabel(sens.get("objective", "objetivo"))
    _title(ax, f"Sensibilidade · {sens.get('param')} (plato = robusto)", color=_GREEN)
    _save(fig, path)


def plot_sensitivity_heatmap(grid: dict, path: Path):
    matrix = grid.get("matrix")
    if not matrix:
        return
    arr = np.array(matrix, dtype=float)
    fig, ax = _fig(10, 6)
    im = ax.imshow(arr, cmap=_CYBER_CMAP, aspect="auto", origin="lower")
    ax.set_xticks(range(len(grid["values_x"]))); ax.set_xticklabels([str(v) for v in grid["values_x"]])
    ax.set_yticks(range(len(grid["values_y"]))); ax.set_yticklabels([str(v) for v in grid["values_y"]])
    ax.set_xlabel(grid.get("param_x")); ax.set_ylabel(grid.get("param_y"))
    ax.grid(False)
    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            if np.isfinite(arr[i, j]):
                ax.text(j, i, f"{arr[i, j]:.2f}", ha="center", va="center", fontsize=8,
                        color="#ffffff", fontweight="bold")
    _title(ax, f"Heatmap de sensibilidade ({grid.get('objective')})", color=_MAGENTA)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    cb.ax.yaxis.set_tick_params(color=_TEXT); cb.outline.set_edgecolor(_GRID)
    plt.setp(plt.getp(cb.ax.axes, "yticklabels"), color=_TEXT)
    _save(fig, path)


def plot_cost_stress(cs: dict, path: Path):
    pts = cs.get("points", [])
    if not pts:
        return
    fig, ax = _fig(11, 5)
    xs = [p["commission_per_lot"] for p in pts]
    ys = [p.get("profit_factor") or 0.0 for p in pts]
    _glow_line(ax, xs, ys, _CYAN)
    ax.fill_between(xs, ys, 1.0, where=[v >= 1.0 for v in ys], color=_GREEN, alpha=0.08, zorder=1)
    ax.fill_between(xs, ys, 1.0, where=[v < 1.0 for v in ys], color=_RED, alpha=0.10, zorder=1)
    ax.axhline(1.0, color=_RED, linestyle="--", linewidth=1.3, label="breakeven (PF=1)")
    cur = cs.get("current_commission")
    if cur is not None:
        ax.axvline(cur, color=_GREEN, linestyle="--", linewidth=1.3, label=f"custo atual = ${cur}")
    be = cs.get("breakeven_commission")
    if be is not None:
        ax.axvline(be, color=_AMBER, linestyle=":", linewidth=1.5, label=f"quebra em ${be}")
    ax.set_xlabel("Comissao por lote ($)"); ax.set_ylabel("Profit Factor")
    _title(ax, "Stress de custo · margem ate o edge morrer")
    _legend(ax)
    _save(fig, path)


def plot_multi_market(mm: dict, path: Path):
    markets = mm.get("markets", [])
    if not markets:
        return
    fig, ax = _fig(11, 5)
    labels = [f"{m['symbol']} {m['timeframe']}" for m in markets]
    pfs = [float(m.get("profit_factor") or 0.0) for m in markets]
    colors = [_GREEN if v >= 1.0 else _RED for v in pfs]
    _glow_bars(ax, np.arange(len(labels)), pfs, colors)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
    ax.axhline(1.0, color=_TEXT, linestyle="--", linewidth=1, alpha=0.6)
    ax.set_ylabel("Profit Factor")
    _title(ax, "Multi-mercado · o edge generaliza?", color=_GREEN)
    _save(fig, path)


# friendly titles (also used by the HTML export)
ROBUSTNESS_CHART_TITLES = {
    "robust_is_oos": "Robustez · In-Sample vs Out-of-Sample",
    "robust_walk_forward": "Robustez · Walk-Forward (IS x OOS)",
    "robust_sensitivity": "Robustez · Sensibilidade de parametro",
    "robust_heatmap": "Robustez · Heatmap de sensibilidade",
    "robust_cost_stress": "Robustez · Stress de custo",
    "robust_multi_market": "Robustez · Multi-mercado",
}


def generate_robustness_charts(scorecard: dict, out_dir: str | Path) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    made: dict[str, str] = {}
    jobs = [
        ("robust_is_oos", lambda p: plot_is_oos(scorecard["in_out_sample"], p), "in_out_sample"),
        ("robust_walk_forward", lambda p: plot_walk_forward(scorecard["walk_forward"], p), "walk_forward"),
        ("robust_sensitivity", lambda p: plot_sensitivity(scorecard["sensitivity"], p), "sensitivity"),
        ("robust_heatmap", lambda p: plot_sensitivity_heatmap(scorecard["sensitivity_grid"], p), "sensitivity_grid"),
        ("robust_cost_stress", lambda p: plot_cost_stress(scorecard["cost_stress"], p), "cost_stress"),
        ("robust_multi_market", lambda p: plot_multi_market(scorecard["multi_market"], p), "multi_market"),
    ]
    for name, fn, key in jobs:
        if not scorecard.get(key):
            continue
        path = out / f"{name}.png"
        try:
            fn(path)
            if path.exists():
                made[name] = path.name
        except Exception as exc:  # noqa: BLE001
            print(f"[robustness chart] skipped {name}: {exc}")
    return made
