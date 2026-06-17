"""Multi-symbol data alignment and quality checks.

Prepares the unified time axis that core/portfolio.py will consume.
Reads raw per-symbol DataFrames, aligns them to a common datetime index,
and reports gaps / mismatches across symbols.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .loaders import load_market_csv, load_mt5_csv, load_ohlcv_csv


def align_symbols(
    datasets: dict[str, pd.DataFrame],
    join: str = "inner",
    fill_method: str | None = "ffill",
) -> dict[str, pd.DataFrame]:
    """Align multiple symbol DataFrames to a common datetime index.

    datasets: {symbol: DataFrame with 'datetime' column}
    join: 'inner' (only common timestamps) or 'outer' (union, with fill).
    fill_method: 'ffill', 'bfill', or None (leave NaN).

    Returns dict of aligned DataFrames, all sharing the same datetime index.
    """
    indexed = {}
    for sym, df in datasets.items():
        d = df.copy()
        d["datetime"] = pd.to_datetime(d["datetime"])
        d = d.set_index("datetime").sort_index()
        d = d[~d.index.duplicated(keep="first")]
        indexed[sym] = d

    if join == "inner":
        common = sorted(set.intersection(*(set(d.index) for d in indexed.values())))
        return {sym: d.loc[common].reset_index() for sym, d in indexed.items()}

    all_times = sorted(set.union(*(set(d.index) for d in indexed.values())))
    result = {}
    for sym, d in indexed.items():
        aligned = d.reindex(all_times)
        if fill_method == "ffill":
            aligned = aligned.ffill()
        elif fill_method == "bfill":
            aligned = aligned.bfill()
        aligned.index.name = "datetime"
        result[sym] = aligned.reset_index()
    return result


def load_portfolio_data(
    symbols: list[dict[str, Any]],
    join: str = "inner",
    fill_method: str | None = "ffill",
) -> dict[str, pd.DataFrame]:
    """Load and align multiple symbols from disk.

    symbols: list of dicts, each with at least:
      - symbol: str (e.g. "EURUSD")
      - path: str or Path to CSV
      - source: "mt5" or "generic" (default "generic")

    Returns aligned dict {symbol: DataFrame}.
    """
    datasets = {}
    for spec in symbols:
        sym = spec["symbol"]
        path = Path(spec["path"])
        source = spec.get("source", "generic")
        if source == "mt5":
            datasets[sym] = load_mt5_csv(path)
        else:
            datasets[sym] = load_ohlcv_csv(path)
    return align_symbols(datasets, join=join, fill_method=fill_method)


def portfolio_data_quality(
    datasets: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Cross-symbol data quality report.

    Checks for: bar count mismatches, datetime gaps, missing values.
    """
    report: dict[str, Any] = {"symbols": {}, "summary": {}}
    bar_counts = {}
    date_ranges = {}

    for sym, df in datasets.items():
        dt = pd.to_datetime(df["datetime"])
        n_bars = len(df)
        n_gaps = int((dt.diff().dropna() > dt.diff().dropna().median() * 2).sum())
        n_nulls = int(df[["open", "high", "low", "close"]].isna().sum().sum())
        bar_counts[sym] = n_bars
        date_ranges[sym] = (str(dt.min()), str(dt.max()))
        report["symbols"][sym] = {
            "bars": n_bars,
            "start": str(dt.min()),
            "end": str(dt.max()),
            "gaps": n_gaps,
            "null_ohlc": n_nulls,
        }

    counts = list(bar_counts.values())
    report["summary"] = {
        "n_symbols": len(datasets),
        "bar_count_match": len(set(counts)) == 1,
        "min_bars": min(counts) if counts else 0,
        "max_bars": max(counts) if counts else 0,
        "all_clean": all(s["gaps"] == 0 and s["null_ohlc"] == 0 for s in report["symbols"].values()),
    }
    return report
