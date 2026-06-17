from __future__ import annotations

import numpy as np
import pandas as pd

from .volatility import add_atr


def add_sma(df: pd.DataFrame, period: int = 20, col: str = "close", name: str | None = None) -> pd.DataFrame:
    out = df.copy()
    out[name or f"sma{period}"] = out[col].rolling(period).mean()
    return out


def add_ema(df: pd.DataFrame, period: int = 20, col: str = "close", name: str | None = None) -> pd.DataFrame:
    out = df.copy()
    out[name or f"ema{period}"] = out[col].ewm(span=period, adjust=False).mean()
    return out


def add_adx(df: pd.DataFrame, period: int = 14, name: str = "adx") -> pd.DataFrame:
    out = df.copy()
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

    plus_dm = (high - high.shift(1)).where((high - high.shift(1)) > (low.shift(1) - low), 0.0)
    plus_dm = plus_dm.where(plus_dm > 0, 0.0)
    minus_dm = (low.shift(1) - low).where((low.shift(1) - low) > (high - high.shift(1)), 0.0)
    minus_dm = minus_dm.where(minus_dm > 0, 0.0)

    tr_n = tr.rolling(period).sum()
    out["plus_di"] = 100 * (plus_dm.rolling(period).sum() / tr_n)
    out["minus_di"] = 100 * (minus_dm.rolling(period).sum() / tr_n)
    dx = ((out["plus_di"] - out["minus_di"]).abs() / (out["plus_di"] + out["minus_di"]).replace(0, np.nan)) * 100
    out[name] = dx.rolling(period).mean()
    return out


def add_supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
    name: str = "supertrend",
) -> pd.DataFrame:
    out = add_atr(df, period, name=f"atr{period}")
    atr = out[f"atr{period}"]
    hl2 = (out["high"] + out["low"]) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    trend = np.ones(len(out))
    line = pd.Series(index=out.index, dtype=float)
    for i in range(1, len(out)):
        if out["close"].iloc[i] > upper.iloc[i - 1]:
            trend[i] = 1
        elif out["close"].iloc[i] < lower.iloc[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
            if trend[i] > 0 and lower.iloc[i] < lower.iloc[i - 1]:
                lower.iloc[i] = lower.iloc[i - 1]
            if trend[i] < 0 and upper.iloc[i] > upper.iloc[i - 1]:
                upper.iloc[i] = upper.iloc[i - 1]
        line.iloc[i] = lower.iloc[i] if trend[i] > 0 else upper.iloc[i]

    out[f"{name}_direction"] = trend
    out[name] = line
    return out
