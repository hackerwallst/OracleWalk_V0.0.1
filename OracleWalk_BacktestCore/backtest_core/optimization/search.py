"""Parameter search: grid and random, with a per-config returns matrix for CSCV.

Returns, alongside the ranked results, a time-bucketed returns matrix
(buckets x config) that the overfit tests (PBO/CSCV) consume.
"""
from __future__ import annotations

import itertools
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..strategies.base import StrategyBase
from .objective import evaluate, get_objective

ParamSpace = dict[str, Sequence[Any]]


def grid_points(space: ParamSpace) -> list[dict[str, Any]]:
    if not space:
        return [{}]
    keys = list(space.keys())
    return [dict(zip(keys, combo)) for combo in itertools.product(*(space[k] for k in keys))]


def random_points(space: ParamSpace, n_iter: int, seed: int = 0) -> list[dict[str, Any]]:
    if not space:
        return [{}]
    rng = np.random.default_rng(seed)
    keys = list(space.keys())
    points, seen = [], set()
    attempts = 0
    max_attempts = n_iter * 50
    while len(points) < n_iter and attempts < max_attempts:
        attempts += 1
        combo = tuple(space[k][rng.integers(len(space[k]))] for k in keys)
        if combo in seen:
            continue
        seen.add(combo)
        points.append(dict(zip(keys, combo)))
    return points


def _bucket_index(data: pd.DataFrame, bucket: str) -> pd.DatetimeIndex:
    dt = pd.to_datetime(data["datetime"])
    s = pd.Series(0.0, index=pd.DatetimeIndex(dt))
    return s.resample(bucket).sum().index


def _config_return_series(trades: pd.DataFrame, full_index: pd.DatetimeIndex, bucket: str) -> pd.Series:
    if trades is None or trades.empty:
        return pd.Series(0.0, index=full_index)
    s = pd.Series(
        pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0).to_numpy(),
        index=pd.DatetimeIndex(pd.to_datetime(trades["exit_time"])),
    )
    bucketed = s.resample(bucket).sum()
    return bucketed.reindex(full_index, fill_value=0.0)


def optimize(
    strategy_cls,
    data: pd.DataFrame,
    config: dict[str, Any],
    space: ParamSpace,
    objective: str = "sharpe_per_trade",
    method: str = "grid",
    n_iter: int = 50,
    base_params: dict[str, Any] | None = None,
    seed: int = 0,
    bucket: str = "W",
    collect_returns: bool = True,
) -> dict[str, Any]:
    """Run a parameter search.

    Returns a dict with:
      - results: DataFrame (one row per config: params + objective + key metrics)
      - best: the top row as a dict
      - returns_matrix: DataFrame (bucket index x config_id) of bucketed PnL, or None
    """
    base_params = dict(base_params or {})
    obj_fn = get_objective(objective)
    points = grid_points(space) if method == "grid" else random_points(space, n_iter, seed)

    full_index = _bucket_index(data, bucket) if collect_returns else None
    rows: list[dict[str, Any]] = []
    return_cols: dict[str, pd.Series] = {}

    for i, params in enumerate(points):
        strategy = strategy_cls(**{**base_params, **params})
        trades, metrics = evaluate(strategy, data, config)
        score = obj_fn(trades, metrics)
        cfg_id = f"cfg_{i}"
        row = {"config_id": cfg_id, **params, "objective": score,
               "total_trades": metrics.get("total_trades", 0),
               "net_profit": metrics.get("net_profit", 0.0),
               "profit_factor": metrics.get("profit_factor"),
               "max_drawdown_pct": metrics.get("max_drawdown_pct"),
               "sharpe_per_trade": metrics.get("sharpe_per_trade")}
        rows.append(row)
        if collect_returns:
            return_cols[cfg_id] = _config_return_series(trades, full_index, bucket)

    results = pd.DataFrame(rows).sort_values("objective", ascending=False).reset_index(drop=True)
    returns_matrix = pd.DataFrame(return_cols) if collect_returns and return_cols else None
    best = results.iloc[0].to_dict() if not results.empty else {}
    return {"results": results, "best": best, "returns_matrix": returns_matrix,
            "objective": objective, "param_names": list(space.keys())}


def best_params(results_or_opt, param_names: list[str]) -> dict[str, Any]:
    """Extract the best parameter dict from an optimize() result or its results DataFrame."""
    if isinstance(results_or_opt, dict):
        row = results_or_opt["best"]
    else:
        row = results_or_opt.iloc[0].to_dict()
    return {k: row[k] for k in param_names if k in row}
