from __future__ import annotations

import numpy as np
import pandas as pd


def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "close", name: str = "rsi") -> pd.DataFrame:
    out = df.copy()
    delta = out[col].diff()
    gain = pd.Series(np.where(delta > 0, delta, 0.0), index=out.index)
    loss = pd.Series(np.where(delta < 0, -delta, 0.0), index=out.index)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out[name] = (100 - (100 / (1 + rs))).fillna(50.0)
    return out


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    col: str = "close",
    prefix: str = "macd",
) -> pd.DataFrame:
    out = df.copy()
    ema_fast = out[col].ewm(span=fast, adjust=False).mean()
    ema_slow = out[col].ewm(span=slow, adjust=False).mean()
    out[prefix] = ema_fast - ema_slow
    out[f"{prefix}_signal"] = out[prefix].ewm(span=signal, adjust=False).mean()
    out[f"{prefix}_hist"] = out[prefix] - out[f"{prefix}_signal"]
    return out


def add_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    prefix: str = "stoch",
) -> pd.DataFrame:
    out = df.copy()
    low_min = out["low"].rolling(k_period).min()
    high_max = out["high"].rolling(k_period).max()
    out[f"{prefix}_k"] = 100 * (out["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    out[f"{prefix}_d"] = out[f"{prefix}_k"].rolling(d_period).mean()
    return out
