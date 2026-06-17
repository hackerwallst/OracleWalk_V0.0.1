from __future__ import annotations

from importlib import import_module

import pandas as pd


def apply_pandas_ta_indicator(df: pd.DataFrame, name: str, **kwargs) -> pd.DataFrame:
    out = df.copy()
    _import_pandas_ta()

    accessor = getattr(out, "ta", None)
    method = getattr(accessor, name, None) if accessor is not None else None
    if method is None or not callable(method):
        available = ", ".join(list_pandas_ta_indicators()[:80])
        raise KeyError(f"unknown pandas-ta indicator '{name}'. First available: {available}")

    result = method(append=True, **kwargs)
    if isinstance(result, pd.Series):
        out[result.name or name] = result
    elif isinstance(result, pd.DataFrame):
        for col in result.columns:
            out[col] = result[col]
    return out


def list_pandas_ta_indicators() -> list[str]:
    ta_module = _import_pandas_ta()
    indicators = getattr(ta_module, "Category", None)
    if isinstance(indicators, dict):
        names: set[str] = set()
        for values in indicators.values():
            names.update(str(value) for value in values)
        return sorted(names)

    dummy = pd.DataFrame({"open": [], "high": [], "low": [], "close": [], "volume": []})
    accessor = getattr(dummy, "ta", None)
    if accessor is None:
        return []
    return sorted(
        name
        for name in dir(accessor)
        if not name.startswith("_") and callable(getattr(accessor, name, None))
    )


def _import_pandas_ta():
    try:
        return import_module("pandas_ta_classic")
    except ModuleNotFoundError:
        try:
            return import_module("pandas_ta")
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Install the optional indicator pack with: "
                "python -m pip install 'backtest-core[indicators]'"
            ) from exc
