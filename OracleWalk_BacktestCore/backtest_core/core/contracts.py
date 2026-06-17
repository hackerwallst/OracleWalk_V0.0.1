from __future__ import annotations

from dataclasses import dataclass


DATA_COLUMNS = ("datetime", "open", "high", "low", "close", "volume")
SIGNAL_COLUMNS = ("datetime", "signal")
OPTIONAL_SIGNAL_COLUMNS = (
    "order_type",
    "entry_price",
    "stop_price",
    "take_price",
    "size",
    "risk",
    "trailing_distance",
    "comment",
)


@dataclass(frozen=True)
class DatasetSpec:
    symbol: str
    timeframe: str
    source: str = "csv"


@dataclass(frozen=True)
class BacktestRunSpec:
    strategy_name: str
    symbol: str
    timeframe: str
    initial_capital: float = 1000.0
    risk_per_trade_pct: float = 1.0
    commission_perc: float = 0.0
    slippage: float = 0.0
