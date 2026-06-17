from __future__ import annotations

import numpy as np
import pandas as pd

from ...indicators.trend import add_ema
from ...indicators.volatility import add_atr
from ..base import StrategyBase
from ..registry import register_strategy


@register_strategy("ema_cross", aliases=("ema_crossover",))
class EmaCrossStrategy(StrategyBase):
    name = "EMA Crossover"

    def __init__(
        self,
        fast: int = 12,
        slow: int = 36,
        atr_period: int = 14,
        stop_atr: float = 1.5,
        take_atr: float = 3.0,
    ):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.stop_atr = stop_atr
        self.take_atr = take_atr

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        out = add_ema(data, self.fast, name=f"ema{self.fast}")
        out = add_ema(out, self.slow, name=f"ema{self.slow}")
        out = add_atr(out, self.atr_period, name=f"atr{self.atr_period}")
        return out

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        prepared = self.prepare_indicators(data)
        fast = prepared[f"ema{self.fast}"]
        slow = prepared[f"ema{self.slow}"]
        trend = np.where(fast > slow, 1, -1)
        cross = pd.Series(trend, index=prepared.index).diff().fillna(0)
        entries = np.where(cross > 0, 1, np.where(cross < 0, -1, 0))

        atr = prepared[f"atr{self.atr_period}"].fillna(prepared["close"] * 0.02)
        entry = prepared["close"]
        stop = np.where(entries > 0, entry - self.stop_atr * atr, entry + self.stop_atr * atr)
        take = np.where(entries > 0, entry + self.take_atr * atr, entry - self.take_atr * atr)

        return pd.DataFrame(
            {
                "datetime": prepared["datetime"],
                "signal": entries,
                "entry_price": entry,
                "stop_price": np.where(entries != 0, stop, np.nan),
                "take_price": np.where(entries != 0, take, np.nan),
                "comment": np.where(entries != 0, self.name, ""),
            }
        )
