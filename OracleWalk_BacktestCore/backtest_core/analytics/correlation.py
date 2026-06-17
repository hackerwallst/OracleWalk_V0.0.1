"""Return correlation analysis for multi-asset strategies.

Produces correlation matrices from trade returns or OHLC close series.
The portfolio engine can consume max_correlation limits using these outputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def returns_correlation_matrix(
    returns_dict: dict[str, pd.Series],
    method: str = "pearson",
) -> pd.DataFrame:
    """Correlation matrix from a dict of {symbol: returns_series}.

    method: 'pearson', 'spearman', or 'kendall'.
    """
    df = pd.DataFrame(returns_dict)
    return df.corr(method=method)


def close_correlation_matrix(
    closes: dict[str, pd.Series],
    method: str = "pearson",
) -> pd.DataFrame:
    """Correlation matrix from close prices (uses pct_change internally)."""
    rets = {sym: s.pct_change().dropna() for sym, s in closes.items()}
    return returns_correlation_matrix(rets, method)


def rolling_correlation(
    series_a: pd.Series,
    series_b: pd.Series,
    window: int = 60,
) -> pd.Series:
    """Rolling Pearson correlation between two return series."""
    df = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
    return df["a"].rolling(window).corr(df["b"])


def max_correlated_pairs(
    corr_matrix: pd.DataFrame,
    threshold: float = 0.7,
) -> list[tuple[str, str, float]]:
    """Return pairs exceeding the correlation threshold (for exposure limits)."""
    pairs = []
    cols = corr_matrix.columns.tolist()
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            val = corr_matrix.loc[a, b]
            if abs(val) >= threshold:
                pairs.append((a, b, float(val)))
    return sorted(pairs, key=lambda x: abs(x[2]), reverse=True)
