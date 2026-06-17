"""Walk-forward optimization: optimize in-sample, evaluate out-of-sample.

Stitches the out-of-sample segments into one continuous OOS track so you can
judge the strategy on data it was never tuned on — the core anti-overfit test.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..analytics.metrics import compute_metrics
from .objective import evaluate, get_objective
from .search import ParamSpace, optimize


def _fold_bounds(n_rows: int, n_splits: int) -> list[tuple[int, int]]:
    edges = np.linspace(0, n_rows, n_splits + 2, dtype=int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n_splits + 1)]


def walk_forward(
    strategy_cls,
    data: pd.DataFrame,
    config: dict[str, Any],
    space: ParamSpace,
    objective: str = "sharpe_per_trade",
    n_splits: int = 5,
    scheme: str = "anchored",       # "anchored" (expanding) or "rolling"
    method: str = "grid",
    n_iter: int = 50,
    base_params: dict[str, Any] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Run walk-forward optimization.

    For each of n_splits steps: optimize on the in-sample window, take the best
    params, and evaluate them on the next (out-of-sample) fold. Returns the
    stitched OOS trades, OOS metrics, and the per-window record (IS vs OOS).
    """
    data = data.sort_values("datetime").reset_index(drop=True)
    folds = _fold_bounds(len(data), n_splits)
    obj_fn = get_objective(objective)
    param_names = list(space.keys())

    windows: list[dict[str, Any]] = []
    oos_trades_all: list[pd.DataFrame] = []

    for i in range(n_splits):
        train_start = 0 if scheme == "anchored" else folds[i][0]
        train_end = folds[i][1]
        test_start, test_end = folds[i + 1]

        train = data.iloc[train_start:train_end].reset_index(drop=True)
        test = data.iloc[test_start:test_end].reset_index(drop=True)
        if len(train) < 50 or len(test) < 20:
            continue

        opt = optimize(strategy_cls, train, config, space, objective=objective,
                       method=method, n_iter=n_iter, base_params=base_params,
                       seed=seed, collect_returns=False)
        bp = {k: opt["best"][k] for k in param_names if k in opt["best"]}

        strategy = strategy_cls(**{**(base_params or {}), **bp})
        oos_trades, oos_metrics = evaluate(strategy, test, config)
        is_score = float(opt["best"].get("objective", float("nan")))
        oos_score = obj_fn(oos_trades, oos_metrics)

        if oos_trades is not None and not oos_trades.empty:
            oos_trades_all.append(oos_trades)

        windows.append({
            "window": i + 1,
            "train_rows": len(train),
            "test_rows": len(test),
            "test_start": str(test["datetime"].iloc[0]),
            "test_end": str(test["datetime"].iloc[-1]),
            "best_params": bp,
            "is_objective": is_score,
            "oos_objective": oos_score,
            "oos_trades": int(0 if oos_trades is None else len(oos_trades)),
            "oos_net_profit": float(oos_metrics.get("net_profit", 0.0)),
        })

    stitched = pd.concat(oos_trades_all, ignore_index=True) if oos_trades_all else pd.DataFrame()
    initial_capital = float(config.get("initial_capital", 1000.0))
    oos_combined = compute_metrics(stitched, initial_capital)

    is_scores = [w["is_objective"] for w in windows if not np.isnan(w["is_objective"])]
    oos_scores = [w["oos_objective"] for w in windows]
    degradation = (float(np.mean(oos_scores)) - float(np.mean(is_scores))) if is_scores else float("nan")

    return {
        "windows": windows,
        "oos_trades": stitched,
        "oos_metrics": oos_combined,
        "is_objective_mean": float(np.mean(is_scores)) if is_scores else float("nan"),
        "oos_objective_mean": float(np.mean(oos_scores)) if oos_scores else float("nan"),
        "is_to_oos_degradation": degradation,
        "objective": objective,
        "scheme": scheme,
    }
