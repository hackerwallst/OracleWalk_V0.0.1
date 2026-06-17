"""Robustness battery — the honesty layer of the backtester.

Wires the existing ``optimization/`` machinery (search, walk-forward, overfit) plus
date slicing into one place and aggregates everything into a single scorecard with
a verdict. Pure analysis: reads finished trades, never touches the engine.

Tests provided:
  * date_slice            — restrict to a specific period (filtro de data).
  * in_out_sample         — train/test split; does the edge hold on unseen data?
  * walk_forward_summary  — rolling optimize-then-validate folds (anti-overfit).
  * parameter_sensitivity — 1D sweep; plateau (robust) vs spike (fragile).
  * sensitivity_grid      — 2D sweep for a heatmap.
  * cost_stress           — sweep commission until the edge dies; safety margin.
  * overfit_diagnostics   — PBO (CSCV) + Deflated Sharpe over a parameter grid.
  * multi_market          — same strategy on other symbols/timeframes.
"""
from __future__ import annotations

import inspect
import math
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..optimization.objective import evaluate, get_objective
from ..optimization.overfit import deflated_sharpe_from_matrix, probability_of_backtest_overfitting
from ..optimization.search import ParamSpace, optimize
from ..optimization.walk_forward import walk_forward
from .metrics import compute_metrics

_EXCLUDE_PARAMS = frozenset({
    "point", "fixed_lot", "emit_pending_orders", "entry_mode",
})
_EXCLUDE_SUBSTRINGS = ("buffer", "step_point", "search_bar")


def _is_sweepable(name: str, annotation, default) -> bool:
    if name in _EXCLUDE_PARAMS:
        return False
    if any(sub in name for sub in _EXCLUDE_SUBSTRINGS):
        return False
    if annotation is bool or annotation == "bool" or isinstance(default, bool):
        return False
    if default is None or default is inspect.Parameter.empty:
        return False
    if not isinstance(default, (int, float)):
        return False
    if isinstance(default, float) and default == 0.0:
        return False
    return True


def _param_priority(name: str) -> int:
    if any(k in name for k in ("period", "_ma", "ema_", "sma_", "rsi_base")):
        return 0
    if any(k in name for k in ("_min", "min_", "_max", "max_", "value", "threshold")):
        return 1
    if any(k in name for k in ("multiplier", "factor", "ratio", "percent", "body")):
        return 2
    return 3


def _is_int_param(default, annotation) -> bool:
    if annotation is int or annotation == "int":
        return True
    return isinstance(default, int) and not isinstance(default, bool) and annotation in (inspect.Parameter.empty, int, "int")


def _sweep_values(default, annotation, n: int = 5) -> list:
    as_int = _is_int_param(default, annotation)
    if as_int:
        if default <= 0:
            return [max(1, default + i) for i in range(-2, 3)]
        ratios = [0.5, 0.7, 1.0, 1.5, 2.0]
        vals = sorted({max(1, round(default * r)) for r in ratios})
        return vals[:n]
    if isinstance(default, (int, float)):
        if default <= 0:
            step = 0.1
            return [round(default + step * i, 6) for i in range(-2, 3)]
        ratios = [0.6, 0.8, 1.0, 1.25, 1.5]
        vals = []
        for r in ratios:
            v = round(default * r, 6)
            if v not in vals:
                vals.append(v)
        return vals[:n]
    return [default]


def _auto_sweep_config(strategy_cls) -> dict:
    sig = inspect.signature(strategy_cls.__init__)
    candidates = []
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else type(p.default) if p.default is not inspect.Parameter.empty else None
        if _is_sweepable(name, ann, p.default):
            candidates.append((name, ann, p.default, _param_priority(name)))
    candidates.sort(key=lambda x: x[3])
    if len(candidates) < 2:
        return {}
    p1_name, p1_ann, p1_def, _ = candidates[0]
    p2_name, p2_ann, p2_def, _ = candidates[1]
    p1_vals = _sweep_values(p1_def, p1_ann, 4)
    p2_vals = _sweep_values(p2_def, p2_ann, 4)
    sens_vals = _sweep_values(p1_def, p1_ann, 6)
    return {
        "space": {p1_name: p1_vals, p2_name: p2_vals},
        "sensitivity_param": p1_name,
        "sensitivity_values": sens_vals,
        "grid_x": (p1_name, p1_vals),
        "grid_y": (p2_name, p2_vals),
    }


# --------------------------------------------------------------------------- #
def date_slice(data: pd.DataFrame, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Restrict an OHLC frame to [start, end] (inclusive). Either bound may be None."""
    if "datetime" not in data.columns or (start is None and end is None):
        return data.reset_index(drop=True)
    dt = pd.to_datetime(data["datetime"])
    mask = pd.Series(True, index=data.index)
    if start:
        mask &= dt >= pd.Timestamp(start)
    if end:
        end_ts = pd.Timestamp(end)
        if _is_date_only(end):
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        mask &= dt <= end_ts
    return data.loc[mask].reset_index(drop=True)


def _is_date_only(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text) and " " not in text and "T" not in text and len(text) <= 10


def _slim(metrics: dict, trades: pd.DataFrame | None) -> dict:
    return {
        "trades": int(0 if trades is None else len(trades)),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "net_profit": metrics.get("net_profit"),
        "net_return_pct": metrics.get("net_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "expectancy": metrics.get("expectancy"),
        "payoff_ratio": metrics.get("payoff_ratio"),
        "sharpe_per_trade": metrics.get("sharpe_per_trade"),
    }


# --------------------------------------------------------------------------- #
def in_out_sample(strategy_cls, data, config, base_params=None, split: float = 0.7) -> dict:
    """Split chronologically into IS (first `split`) and OOS (rest); run the SAME
    params on both. PF retention = OOS PF / IS PF (≈1 good, «1 = edge faded)."""
    data = data.sort_values("datetime").reset_index(drop=True)
    cut = int(len(data) * split)
    is_data = data.iloc[:cut].reset_index(drop=True)
    oos_data = data.iloc[cut:].reset_index(drop=True)
    bp = dict(base_params or {})

    full_t, full_m = evaluate(strategy_cls(**bp), data, config)
    is_t, is_m = evaluate(strategy_cls(**bp), is_data, config)
    oos_t, oos_m = evaluate(strategy_cls(**bp), oos_data, config)
    pf_is = is_m.get("profit_factor") or 0.0
    pf_oos = oos_m.get("profit_factor") or 0.0
    return {
        "split": split,
        "is_period": [_d(is_data, 0), _d(is_data, -1)],
        "oos_period": [_d(oos_data, 0), _d(oos_data, -1)],
        "full": _slim(full_m, full_t),
        "is": _slim(is_m, is_t),
        "oos": _slim(oos_m, oos_t),
        "pf_retention": (pf_oos / pf_is) if pf_is else None,
    }


def walk_forward_summary(strategy_cls, data, config, space: ParamSpace, base_params=None,
                         objective: str = "sharpe_per_trade", n_splits: int = 5,
                         scheme: str = "anchored", method: str = "grid", n_iter: int = 40) -> dict:
    """Rolling optimize-in-sample / validate-out-of-sample. Degradation = OOS mean −
    IS mean objective (very negative = the optimizer was fitting noise)."""
    wf = walk_forward(strategy_cls, data, config, space, objective=objective, n_splits=n_splits,
                      scheme=scheme, method=method, n_iter=n_iter, base_params=base_params)
    return {
        "objective": objective,
        "scheme": scheme,
        "windows": wf["windows"],
        "oos_metrics": _slim(wf["oos_metrics"], wf.get("oos_trades")),
        "is_objective_mean": wf["is_objective_mean"],
        "oos_objective_mean": wf["oos_objective_mean"],
        "is_to_oos_degradation": wf["is_to_oos_degradation"],
    }


def parameter_sensitivity(strategy_cls, data, config, param: str, values: Sequence[Any],
                          base_params=None, objective: str = "profit_factor") -> dict:
    """1D sweep of one parameter. A wide plateau = robust; a lone spike = fragile."""
    bp = dict(base_params or {})
    obj = get_objective(objective)
    points = []
    for v in values:
        t, m = evaluate(strategy_cls(**{**bp, param: v}), data, config)
        points.append({
            "value": v, "objective": obj(t, m),
            "profit_factor": m.get("profit_factor"), "net_profit": m.get("net_profit"),
            "max_drawdown_pct": m.get("max_drawdown_pct"), "trades": m.get("total_trades"),
        })
    objs = [p["objective"] for p in points if p["objective"] is not None]
    spread = (max(objs) - min(objs)) if objs else None
    return {"param": param, "objective": objective, "points": points,
            "best": max(points, key=lambda p: p["objective"]) if points else None, "spread": spread}


def sensitivity_grid(strategy_cls, data, config, param_x: str, values_x: Sequence[Any],
                     param_y: str, values_y: Sequence[Any], base_params=None,
                     objective: str = "profit_factor") -> dict:
    """2D sweep (param_x × param_y) → matrix of `objective`, for a heatmap."""
    bp = dict(base_params or {})
    obj = get_objective(objective)
    grid = []
    for vy in values_y:
        row = []
        for vx in values_x:
            t, m = evaluate(strategy_cls(**{**bp, param_x: vx, param_y: vy}), data, config)
            row.append(obj(t, m))
        grid.append(row)
    return {"param_x": param_x, "values_x": list(values_x), "param_y": param_y,
            "values_y": list(values_y), "objective": objective, "matrix": grid}


def cost_stress(strategy_cls, data, config, commissions: Sequence[float], base_params=None) -> dict:
    """Sweep commission/lot; find the breakeven where profit factor crosses 1."""
    bp = dict(base_params or {})
    points = []
    breakeven = None
    for c in commissions:
        t, m = evaluate(strategy_cls(**bp), data, {**config, "commission_per_lot": c})
        pf = m.get("profit_factor")
        points.append({"commission_per_lot": float(c), "profit_factor": pf,
                       "net_profit": m.get("net_profit"), "expectancy": m.get("expectancy")})
        if breakeven is None and pf is not None and pf < 1.0:
            breakeven = float(c)
    return {"points": points, "breakeven_commission": breakeven,
            "current_commission": config.get("commission_per_lot")}


def overfit_diagnostics(strategy_cls, data, config, space: ParamSpace, base_params=None,
                        objective: str = "sharpe_per_trade", bucket: str = "ME", n_splits: int = 10) -> dict:
    """PBO (probability of backtest overfitting, via CSCV) + Deflated Sharpe over the grid."""
    opt = optimize(strategy_cls, data, config, space, objective=objective, base_params=base_params,
                   bucket=bucket, collect_returns=True)
    rm = opt.get("returns_matrix")
    if rm is None or rm.shape[1] < 2:
        return {"pbo": None, "dsr": None, "n_configs": 0 if rm is None else int(rm.shape[1])}
    pbo = probability_of_backtest_overfitting(rm, n_splits=n_splits)
    dsr = deflated_sharpe_from_matrix(rm)
    return {
        "pbo": pbo.get("pbo"), "n_combinations": pbo.get("n_combinations"),
        "n_configs": int(rm.shape[1]),
        "dsr": dsr.get("dsr"), "observed_sr": dsr.get("observed_sr"),
        "expected_max_sr": dsr.get("expected_max_sr"),
        "best_params": {k: opt["best"].get(k) for k in space if k in opt["best"]},
    }


def multi_market(strategy_cls, datasets: list[dict], config, base_params=None) -> dict:
    """Run the SAME strategy on other markets. datasets: [{symbol, timeframe, data}]."""
    bp = dict(base_params or {})
    out = []
    for ds in datasets:
        t, m = evaluate(strategy_cls(**bp), ds["data"], config)
        out.append({"symbol": ds.get("symbol"), "timeframe": ds.get("timeframe"), **_slim(m, t)})
    return {"markets": out}


# --------------------------------------------------------------------------- #
def _resolve_sweep_config(strategy_cls) -> dict:
    """Get sweep config: explicit from strategy, or auto-detected from __init__."""
    if hasattr(strategy_cls, "robustness_space"):
        explicit = strategy_cls.robustness_space()
        if explicit:
            return explicit
    return _auto_sweep_config(strategy_cls)


def run_battery(
    strategy_cls,
    data: pd.DataFrame,
    config: dict,
    base_params: dict | None = None,
    *,
    space: ParamSpace | None = None,
    sensitivity_param: str | None = None,
    sensitivity_values: Sequence[Any] | None = None,
    grid_x: tuple[str, Sequence[Any]] | None = None,
    grid_y: tuple[str, Sequence[Any]] | None = None,
    commissions: Sequence[float] = (0.0, 3.0, 6.0, 10.0, 15.0, 25.0),
    markets: list[dict] | None = None,
    split: float = 0.7,
    wfo_splits: int = 4,
    objective: str = "profit_factor",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Run the whole robustness battery and return a scorecard + verdict.

    Sweep parameters (space, sensitivity, grid) are resolved automatically:
    first from the strategy's ``robustness_space()`` classmethod, then by
    auto-introspecting ``__init__`` parameters. Explicit kwargs override both.
    """
    data = date_slice(data, start, end)
    bp = dict(base_params or {})

    sweep = _resolve_sweep_config(strategy_cls)
    if space is None:
        space = sweep.get("space")
    if sensitivity_param is None:
        sensitivity_param = sweep.get("sensitivity_param")
    if sensitivity_values is None:
        sensitivity_values = sweep.get("sensitivity_values")
    if grid_x is None:
        grid_x = sweep.get("grid_x")
    if grid_y is None:
        grid_y = sweep.get("grid_y")

    can_sweep = bool(space and len(space) >= 2)

    card: dict[str, Any] = {
        "params": bp,
        "period": [_d(data, 0), _d(data, -1)],
        "bars": int(len(data)),
        "objective": objective,
    }
    card["in_out_sample"] = in_out_sample(strategy_cls, data, config, bp, split=split)
    card["cost_stress"] = cost_stress(strategy_cls, data, config, commissions, bp)
    if markets:
        card["multi_market"] = multi_market(strategy_cls, markets, config, bp)
    if can_sweep:
        card["walk_forward"] = walk_forward_summary(strategy_cls, data, config, space, bp,
                                                    objective=objective, n_splits=wfo_splits)
        card["overfit"] = overfit_diagnostics(strategy_cls, data, config, space, bp, objective="sharpe_per_trade")
        if sensitivity_param and sensitivity_values:
            card["sensitivity"] = parameter_sensitivity(strategy_cls, data, config, sensitivity_param,
                                                        sensitivity_values, bp, objective=objective)
        if grid_x and grid_y:
            card["sensitivity_grid"] = sensitivity_grid(strategy_cls, data, config, grid_x[0], grid_x[1],
                                                        grid_y[0], grid_y[1], bp, objective=objective)
    card["verdict"] = verdict(card)
    return card


def verdict(scorecard: dict) -> dict:
    """Boil the scorecard down to a flag per test + an overall robustness rating."""
    flags = {}
    ios = scorecard.get("in_out_sample") or {}
    ret = ios.get("pf_retention")
    flags["oos"] = _flag(ret, good=0.8, warn=0.5) if ret is not None else "n/a"

    of = scorecard.get("overfit") or {}
    pbo = of.get("pbo")
    flags["pbo"] = ("good" if pbo is not None and pbo < 0.3 else
                    "warn" if pbo is not None and pbo < 0.5 else
                    "bad" if pbo is not None else "n/a")

    wf = scorecard.get("walk_forward") or {}
    deg = wf.get("is_to_oos_degradation")
    flags["walk_forward"] = ("good" if deg is not None and deg > -0.2 else
                             "warn" if deg is not None and deg > -0.5 else
                             "bad" if deg is not None else "n/a")

    cs = scorecard.get("cost_stress") or {}
    be = cs.get("breakeven_commission")
    cur = cs.get("current_commission")
    if be is None:
        flags["cost"] = "good"  # never broke within tested range
    elif cur is not None and be >= cur * 2:
        flags["cost"] = "good"
    elif cur is not None and be >= cur * 1.3:
        flags["cost"] = "warn"
    else:
        flags["cost"] = "bad"

    order = {"good": 2, "warn": 1, "bad": 0, "n/a": None}
    scores = [order[f] for f in flags.values() if order[f] is not None]
    rating = "Robusta" if scores and min(scores) >= 2 else \
             "Aceitavel" if scores and min(scores) >= 1 else \
             "Fragil" if scores else "Inconclusiva"
    return {"flags": flags, "rating": rating}


def _flag(value, good, warn):
    if value is None:
        return "n/a"
    return "good" if value >= good else "warn" if value >= warn else "bad"


def _d(df: pd.DataFrame, idx: int) -> str | None:
    if df is None or df.empty or "datetime" not in df.columns:
        return None
    return str(pd.to_datetime(df["datetime"]).iloc[idx])
