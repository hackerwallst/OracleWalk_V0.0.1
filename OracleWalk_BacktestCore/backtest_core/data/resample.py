from __future__ import annotations

import pandas as pd


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    data = df.copy()
    if "datetime" not in data.columns and isinstance(data.index, pd.DatetimeIndex):
        data = data.reset_index().rename(columns={"index": "datetime"})
    data["datetime"] = pd.to_datetime(data["datetime"])
    data = data.set_index("datetime").sort_index()
    out = data.resample(timeframe).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    return out.dropna().reset_index()
