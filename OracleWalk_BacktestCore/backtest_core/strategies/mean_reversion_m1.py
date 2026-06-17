from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.momentum import add_rsi
from ..indicators.trend import add_ema
from ..indicators.volatility import add_atr
from ..strategies.base import StrategyBase


class M1MeanReversionScalper(StrategyBase):
    """
    Mechanical implementation of the documented M1 Countertrend Scalping idea.

    This is intentionally conservative and auditable:
      - countertrend entries after extension away from EMA20/EMA50
      - Heiken Ashi color turn as momentum reversal
      - RSI crossing its own MA
      - optional volume exhaustion/confirmation filter
      - target at a selected EMA
      - controlled cost averaging, same fixed lot, max positions
    """

    name = "M1 Countertrend Mean Reversion"

    def __init__(
        self,
        entry_mode: str = "confirmed",
        fixed_lot: float = 0.01,
        ema_fast: int = 9,
        ema_target: int = 20,
        ema_filter: int = 50,
        ema_slow: int = 200,
        atr_period: int = 14,
        min_extension_atr: float = 0.35,
        min_wick_ratio: float = 0.35,
        rsi_period: int = 14,
        rsi_ma_period: int = 7,
        rsi_buy_max: float = 48.0,
        rsi_sell_min: float = 52.0,
        volume_period: int = 20,
        volume_mode: str = "exhaustion",  # "off", "exhaustion", "confirmation"
        volume_multiplier: float = 1.10,
        require_ha_ema9_cross: bool = True,
        max_positions: int = 10,
        add_step_atr: float = 0.45,
        use_ema9_add_filter: bool = True,
        emergency_stop_atr: float | None = None,
        trade_start_hour: int | None = None,
        trade_end_hour: int | None = None,
    ):
        if entry_mode not in {"confirmed", "raw"}:
            raise ValueError("entry_mode must be 'confirmed' or 'raw'")
        self.entry_mode = entry_mode
        self.fixed_lot = fixed_lot
        self.ema_fast = ema_fast
        self.ema_target = ema_target
        self.ema_filter = ema_filter
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.min_extension_atr = min_extension_atr
        self.min_wick_ratio = min_wick_ratio
        self.rsi_period = rsi_period
        self.rsi_ma_period = rsi_ma_period
        self.rsi_buy_max = rsi_buy_max
        self.rsi_sell_min = rsi_sell_min
        self.volume_period = volume_period
        self.volume_mode = volume_mode
        self.volume_multiplier = volume_multiplier
        self.require_ha_ema9_cross = require_ha_ema9_cross
        self.max_positions = max_positions
        self.add_step_atr = add_step_atr
        self.use_ema9_add_filter = use_ema9_add_filter
        self.emergency_stop_atr = emergency_stop_atr
        self.trade_start_hour = trade_start_hour
        self.trade_end_hour = trade_end_hour

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        out = data.copy()
        out = add_ema(out, self.ema_fast, name=f"ema{self.ema_fast}")
        out = add_ema(out, self.ema_target, name=f"ema{self.ema_target}")
        out = add_ema(out, self.ema_filter, name=f"ema{self.ema_filter}")
        out = add_ema(out, self.ema_slow, name=f"ema{self.ema_slow}")
        out = add_atr(out, self.atr_period, name=f"atr{self.atr_period}")
        out = add_rsi(out, self.rsi_period, name="rsi")
        out["rsi_ma"] = out["rsi"].rolling(self.rsi_ma_period).mean()
        out["volume_ma"] = out["volume"].rolling(self.volume_period).mean()
        return self._add_heiken_ashi(out)

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = self.prepare_indicators(data)
        signals = pd.DataFrame(
            {
                "datetime": df["datetime"],
                "signal": 0,
                "entry_price": np.nan,
                "stop_price": np.nan,
                "take_price": np.nan,
                "size": np.nan,
                "comment": "",
            }
        )

        basket_side = 0
        basket_entries: list[float] = []
        last_entry = np.nan

        for i in range(2, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            if self._has_missing(row):
                continue

            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            atr = float(row[f"atr{self.atr_period}"])
            target = float(row[f"ema{self.ema_target}"])

            if basket_side != 0:
                if self._target_touched(basket_side, high, low, target):
                    basket_side = 0
                    basket_entries = []
                    last_entry = np.nan
                elif len(basket_entries) < self.max_positions and self._should_add(row, basket_side, last_entry, atr):
                    self._set_signal(signals, i, basket_side, close, target, atr, "cost_average")
                    basket_entries.append(close)
                    last_entry = close
                continue

            if not self._time_allowed(row["datetime"]):
                continue

            buy = self._buy_setup(row, prev, atr)
            sell = self._sell_setup(row, prev, atr)

            if buy and target > close:
                self._set_signal(signals, i, 1, close, target, atr, "initial_buy")
                basket_side = 1
                basket_entries = [close]
                last_entry = close
            elif sell and target < close:
                self._set_signal(signals, i, -1, close, target, atr, "initial_sell")
                basket_side = -1
                basket_entries = [close]
                last_entry = close

        return signals

    def _buy_setup(self, row: pd.Series, prev: pd.Series, atr: float) -> bool:
        close = float(row["close"])
        ema20 = float(row[f"ema{self.ema_target}"])
        ema50 = float(row[f"ema{self.ema_filter}"])
        extension = min(ema20 - close, ema50 - close)
        base = (
            close < ema20
            and close < ema50
            and extension >= self.min_extension_atr * atr
        )
        if self.entry_mode == "raw":
            return base
        return (
            base
            and self._ha_turns_green(row, prev)
            and self._ha_crosses_ema9_up(row, prev)
            and self._rsi_turns_up(row, prev)
            and self._support_rejection(row)
            and self._volume_ok(row)
        )

    def _sell_setup(self, row: pd.Series, prev: pd.Series, atr: float) -> bool:
        close = float(row["close"])
        ema20 = float(row[f"ema{self.ema_target}"])
        ema50 = float(row[f"ema{self.ema_filter}"])
        extension = min(close - ema20, close - ema50)
        base = (
            close > ema20
            and close > ema50
            and extension >= self.min_extension_atr * atr
        )
        if self.entry_mode == "raw":
            return base
        return (
            base
            and self._ha_turns_red(row, prev)
            and self._ha_crosses_ema9_down(row, prev)
            and self._rsi_turns_down(row, prev)
            and self._resistance_rejection(row)
            and self._volume_ok(row)
        )

    def _should_add(self, row: pd.Series, side: int, last_entry: float, atr: float) -> bool:
        close = float(row["close"])
        ema9 = float(row[f"ema{self.ema_fast}"])
        if side == 1:
            adverse = close <= last_entry - self.add_step_atr * atr
            ema_filter = ema9 <= last_entry if self.use_ema9_add_filter else True
            return adverse and ema_filter
        adverse = close >= last_entry + self.add_step_atr * atr
        ema_filter = ema9 >= last_entry if self.use_ema9_add_filter else True
        return adverse and ema_filter

    def _set_signal(
        self,
        signals: pd.DataFrame,
        i: int,
        side: int,
        entry: float,
        target: float,
        atr: float,
        comment: str,
    ) -> None:
        stop = np.nan
        if self.emergency_stop_atr is not None and self.emergency_stop_atr > 0:
            stop = entry - self.emergency_stop_atr * atr if side == 1 else entry + self.emergency_stop_atr * atr
        signals.loc[i, "signal"] = side
        signals.loc[i, "entry_price"] = entry
        signals.loc[i, "stop_price"] = stop
        signals.loc[i, "take_price"] = target
        signals.loc[i, "size"] = self.fixed_lot
        signals.loc[i, "comment"] = comment

    def _target_touched(self, side: int, high: float, low: float, target: float) -> bool:
        return high >= target if side == 1 else low <= target

    def _ha_turns_green(self, row: pd.Series, prev: pd.Series) -> bool:
        return row["ha_close"] > row["ha_open"] and prev["ha_close"] <= prev["ha_open"]

    def _ha_turns_red(self, row: pd.Series, prev: pd.Series) -> bool:
        return row["ha_close"] < row["ha_open"] and prev["ha_close"] >= prev["ha_open"]

    def _ha_crosses_ema9_up(self, row: pd.Series, prev: pd.Series) -> bool:
        if not self.require_ha_ema9_cross:
            return True
        ema_col = f"ema{self.ema_fast}"
        return prev["ha_close"] <= prev[ema_col] and row["ha_close"] > row[ema_col]

    def _ha_crosses_ema9_down(self, row: pd.Series, prev: pd.Series) -> bool:
        if not self.require_ha_ema9_cross:
            return True
        ema_col = f"ema{self.ema_fast}"
        return prev["ha_close"] >= prev[ema_col] and row["ha_close"] < row[ema_col]

    def _rsi_turns_up(self, row: pd.Series, prev: pd.Series) -> bool:
        return row["rsi"] <= self.rsi_buy_max and prev["rsi"] <= prev["rsi_ma"] and row["rsi"] > row["rsi_ma"]

    def _rsi_turns_down(self, row: pd.Series, prev: pd.Series) -> bool:
        return row["rsi"] >= self.rsi_sell_min and prev["rsi"] >= prev["rsi_ma"] and row["rsi"] < row["rsi_ma"]

    def _support_rejection(self, row: pd.Series) -> bool:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        open_ = float(row["open"])
        candle_range = max(high - low, 1e-12)
        lower_wick = min(open_, close) - low
        return lower_wick / candle_range >= self.min_wick_ratio

    def _resistance_rejection(self, row: pd.Series) -> bool:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        open_ = float(row["open"])
        candle_range = max(high - low, 1e-12)
        upper_wick = high - max(open_, close)
        return upper_wick / candle_range >= self.min_wick_ratio

    def _volume_ok(self, row: pd.Series) -> bool:
        if self.volume_mode == "off":
            return True
        volume = float(row["volume"])
        volume_ma = float(row["volume_ma"])
        if self.volume_mode == "confirmation":
            return volume >= volume_ma * self.volume_multiplier
        return volume <= volume_ma * self.volume_multiplier

    def _time_allowed(self, dt) -> bool:
        if self.trade_start_hour is None or self.trade_end_hour is None:
            return True
        hour = pd.to_datetime(dt).hour
        if self.trade_start_hour <= self.trade_end_hour:
            return self.trade_start_hour <= hour < self.trade_end_hour
        return hour >= self.trade_start_hour or hour < self.trade_end_hour

    def _has_missing(self, row: pd.Series) -> bool:
        cols = [
            f"ema{self.ema_fast}",
            f"ema{self.ema_target}",
            f"ema{self.ema_filter}",
            f"atr{self.atr_period}",
            "rsi",
            "rsi_ma",
            "volume_ma",
            "ha_open",
            "ha_close",
        ]
        return any(pd.isna(row[col]) for col in cols)

    @staticmethod
    def _add_heiken_ashi(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ha_close = (out["open"] + out["high"] + out["low"] + out["close"]) / 4.0
        ha_open = ha_close.copy()
        if len(out) > 0:
            ha_open.iloc[0] = (out["open"].iloc[0] + out["close"].iloc[0]) / 2.0
            for i in range(1, len(out)):
                ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0
        out["ha_open"] = ha_open
        out["ha_close"] = ha_close
        out["ha_high"] = pd.concat([out["high"], ha_open, ha_close], axis=1).max(axis=1)
        out["ha_low"] = pd.concat([out["low"], ha_open, ha_close], axis=1).min(axis=1)
        return out
