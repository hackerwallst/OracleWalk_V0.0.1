from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ...data import load_mt5_csv, load_mt5_ticks_csv


def load_mt5_broker_package(
    package_path: str | Path,
    engine_overrides: dict | None = None,
    load_ticks: bool = True,
    tick_start: str | pd.Timestamp | None = None,
    tick_end: str | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """
    Load a BacktestCore MT5 broker package.

    Expected files:
      candles.csv
      symbol_spec.json
      account_spec.json
      export_manifest.json

    Returns:
      {
        "data": DataFrame,
        "ticks": DataFrame | None,
        "engine_config": dict,
        "symbol_spec": dict,
        "account_spec": dict,
        "manifest": dict,
      }
    """
    root = Path(package_path)
    if not root.exists():
        raise FileNotFoundError(f"MT5 package folder not found: {root}")

    manifest = _read_json(root / "export_manifest.json", default={})
    files = manifest.get("files", {})
    candles_path = root / files.get("candles", "candles.csv")
    ticks_name = files.get("ticks")
    ticks_path = root / ticks_name if ticks_name else None
    symbol_path = root / files.get("symbol_spec", "symbol_spec.json")
    account_path = root / files.get("account_spec", "account_spec.json")

    data = load_mt5_csv(candles_path)
    ticks = (
        load_mt5_ticks_csv(ticks_path, start=tick_start, end=tick_end)
        if load_ticks and ticks_path and ticks_path.exists()
        else None
    )
    symbol_spec = _read_json(symbol_path)
    account_spec = _read_json(account_path, default={})

    engine_config = engine_config_from_symbol_spec(symbol_spec, account_spec)
    if engine_overrides:
        engine_config.update({k: v for k, v in engine_overrides.items() if v is not None})

    return {
        "data": data,
        "ticks": ticks,
        "engine_config": engine_config,
        "symbol_spec": symbol_spec,
        "account_spec": account_spec,
        "manifest": manifest,
        "package_path": str(root),
    }


def engine_config_from_symbol_spec(
    symbol_spec: dict[str, Any],
    account_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account_spec = account_spec or {}
    point = float(symbol_spec.get("point") or 0.00001)
    contract_size = float(symbol_spec.get("contract_size") or 1.0)
    swap_mode = symbol_spec.get("swap_mode")

    swap_long = _swap_to_deposit_currency(
        float(symbol_spec.get("swap_long_per_lot") or 0.0),
        swap_mode,
        point,
        contract_size,
    )
    swap_short = _swap_to_deposit_currency(
        float(symbol_spec.get("swap_short_per_lot") or 0.0),
        swap_mode,
        point,
        contract_size,
    )

    commission = symbol_spec.get("commission_per_lot")
    if commission is None:
        commission = 0.0

    return {
        "contract_size": contract_size,
        "point": point,
        "leverage": float(account_spec.get("leverage") or 1.0),
        "margin_rate": symbol_spec.get("margin_rate"),
        "use_spread": True,
        "spread_column": "spread",
        "fixed_spread_points": None,
        "commission_per_lot": float(commission),
        "commission_perc": 0.0,
        "swap_long_per_lot": swap_long,
        "swap_short_per_lot": swap_short,
        "triple_swap_weekday": _mt5_weekday_to_python(symbol_spec.get("triple_swap_weekday", 3)),
    }


def _swap_to_deposit_currency(raw_swap: float, swap_mode, point: float, contract_size: float) -> float:
    """
    BacktestCore expects swap as deposit-currency money per lot per day.

    MT5 mode 1 means points in the common ENUM_SYMBOL_SWAP_MODE. In that case,
    convert points -> price -> money per lot. Other modes are passed through
    because brokers often already expose a currency amount.
    """
    try:
        mode = int(swap_mode)
    except Exception:
        mode = None
    if mode == 1:
        return raw_swap * point * contract_size
    return raw_swap


def _mt5_weekday_to_python(raw_day) -> int | None:
    """
    MT5/MQL5 uses ENUM_DAY_OF_WEEK: 0=Sunday, 1=Monday, ..., 6=Saturday.
    BacktestCore uses Python/pandas weekday semantics: 0=Monday, ..., 6=Sunday.
    """
    if raw_day is None or raw_day == "":
        return None
    try:
        day = int(raw_day)
    except Exception:
        return None
    if day < 0 or day > 6:
        return None
    return (day + 6) % 7


def _read_json(path: Path, default=None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"Required JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
