from __future__ import annotations

import numpy as np
import pandas as pd


def add_vwap(df: pd.DataFrame, name: str = "vwap") -> pd.DataFrame:
    out = df.copy()
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    out[name] = (typical * out["volume"]).cumsum() / out["volume"].replace(0, np.nan).cumsum()
    return out


def add_volume_features(
    df: pd.DataFrame,
    period: int = 20,
    spike_multiplier: float = 1.5,
    prefix: str = "volume",
) -> pd.DataFrame:
    out = df.copy()
    ma = out["volume"].rolling(period).mean()
    out[f"{prefix}_ma"] = ma
    out[f"{prefix}_spike"] = out["volume"] > ma * spike_multiplier
    out[f"{prefix}_zscore"] = (out["volume"] - ma) / out["volume"].rolling(period).std().replace(0, np.nan)
    return out
