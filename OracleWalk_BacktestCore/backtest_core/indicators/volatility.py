from __future__ import annotations

import pandas as pd


def add_atr(df: pd.DataFrame, period: int = 14, name: str | None = None) -> pd.DataFrame:
    out = df.copy()
    col_name = name or f"atr{period}"
    high = out["high"]
    low = out["low"]
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out[col_name] = tr.rolling(period).mean()
    return out


def add_bbands(
    df: pd.DataFrame,
    period: int = 20,
    std_mult: float = 2.0,
    col: str = "close",
    prefix: str = "bb",
) -> pd.DataFrame:
    out = df.copy()
    mid = out[col].rolling(period).mean()
    std = out[col].rolling(period).std()
    out[f"{prefix}_mid"] = mid
    out[f"{prefix}_upper"] = mid + std_mult * std
    out[f"{prefix}_lower"] = mid - std_mult * std
    out[f"{prefix}_width"] = out[f"{prefix}_upper"] - out[f"{prefix}_lower"]
    return out
