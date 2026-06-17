from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from .external import apply_pandas_ta_indicator, list_pandas_ta_indicators
from .momentum import add_macd, add_rsi, add_stochastic
from .trend import add_adx, add_ema, add_sma, add_supertrend
from .volatility import add_atr, add_bbands
from .volume import add_vwap, add_volume_features


INDICATORS: dict[str, Callable[..., pd.DataFrame]] = {
    "adx": add_adx,
    "atr": add_atr,
    "bbands": add_bbands,
    "ema": add_ema,
    "macd": add_macd,
    "rsi": add_rsi,
    "sma": add_sma,
    "stochastic": add_stochastic,
    "supertrend": add_supertrend,
    "volume_features": add_volume_features,
    "vwap": add_vwap,
}


def apply_indicator(df: pd.DataFrame, name: str, **kwargs) -> pd.DataFrame:
    if name.startswith(("ta:", "pandas_ta:")):
        _, external_name = name.split(":", 1)
        return apply_pandas_ta_indicator(df, external_name, **kwargs)
    if name not in INDICATORS:
        available = ", ".join(sorted(INDICATORS))
        raise KeyError(f"unknown indicator '{name}'. Available built-ins: {available}")
    return INDICATORS[name](df, **kwargs)


def apply_pipeline(df: pd.DataFrame, pipeline: list[dict]) -> pd.DataFrame:
    out = df.copy()
    for item in pipeline:
        name = item["name"]
        kwargs = {k: v for k, v in item.items() if k != "name"}
        out = apply_indicator(out, name, **kwargs)
    return out


def available_indicators(include_external: bool = False) -> list[str]:
    names = sorted(INDICATORS)
    if include_external:
        names.extend(f"ta:{name}" for name in list_pandas_ta_indicators())
    return names
