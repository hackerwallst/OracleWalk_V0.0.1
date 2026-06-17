"""CrossTendency — EMA crossover with ATR + ADX filters, pivot stop, trailing.

Reproduces the MT5 EA "CrossTendency" logic:
  * Entry: EMA fast crosses EMA slow on close price (closed bar).
  * ATR filter: ATR(14) must exceed its own SMA(20) * multiplier AND a minimum
    absolute floor in points.
  * ADX filter: ADX(14) must be >= threshold (trend strength gate).
  * Stop: most recent DAILY pivot high/low (swing point) — multi-timeframe.
    The intraday data is resampled to D1 for pivot detection.
  * Take profit: none (exit by trailing or opposite signal).
  * Trailing stop: percentage-based distance, activates after a profit threshold.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators.trend import add_ema, add_adx
from ..indicators.volatility import add_atr
from .base import StrategyBase
from .registry import register_strategy


def _find_pivot_lows(low: np.ndarray, left: int, right: int) -> np.ndarray:
    n = len(low)
    is_pivot = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window = low[max(0, i - left): i + right + 1]
        if low[i] == np.min(window):
            is_pivot[i] = True
    return is_pivot


def _find_pivot_highs(high: np.ndarray, left: int, right: int) -> np.ndarray:
    n = len(high)
    is_pivot = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window = high[max(0, i - left): i + right + 1]
        if high[i] == np.max(window):
            is_pivot[i] = True
    return is_pivot


def _build_daily_pivots(df: pd.DataFrame, left: int, right: int, search: int):
    """Resample intraday data to D1, detect pivots, return lookup arrays.

    Returns (daily_pivot_low_price, daily_pivot_high_price) — arrays aligned to
    the original intraday index. Each element holds the most recent confirmed
    daily pivot low/high price at that bar, or NaN if none found.
    """
    dt = pd.to_datetime(df["datetime"])
    dates = dt.dt.date
    n = len(df)

    daily = df.assign(_date=dates).groupby("_date").agg(
        high=("high", "max"),
        low=("low", "min"),
    )
    d_high = daily["high"].to_numpy(dtype=float)
    d_low = daily["low"].to_numpy(dtype=float)
    d_dates = daily.index.to_numpy()
    nd = len(daily)

    pv_low_mask = _find_pivot_lows(d_low, left, right)
    pv_high_mask = _find_pivot_highs(d_high, left, right)

    # Pre-compute: for each daily bar, the most recent confirmed pivot price.
    # A pivot at day j is confirmed at day j + right. So at day d, confirmed
    # pivots are those at j <= d - right, within the search window.
    daily_recent_pv_low = np.full(nd, np.nan)
    daily_recent_pv_high = np.full(nd, np.nan)
    for d in range(nd):
        confirmed_end = d - right
        confirmed_start = max(0, d - search)
        for j in range(confirmed_end, confirmed_start - 1, -1):
            if j >= 0 and pv_low_mask[j] and np.isnan(daily_recent_pv_low[d]):
                daily_recent_pv_low[d] = d_low[j]
            if j >= 0 and pv_high_mask[j] and np.isnan(daily_recent_pv_high[d]):
                daily_recent_pv_high[d] = d_high[j]
            if not np.isnan(daily_recent_pv_low[d]) and not np.isnan(daily_recent_pv_high[d]):
                break

    # Map daily values to intraday bars
    date_to_idx = {d: i for i, d in enumerate(d_dates)}
    bar_dates = dates.to_numpy()
    day_indices = np.array([date_to_idx.get(bd, -1) for bd in bar_dates], dtype=int)

    pivot_low_at_bar = np.full(n, np.nan)
    pivot_high_at_bar = np.full(n, np.nan)
    valid = day_indices >= 0
    pivot_low_at_bar[valid] = daily_recent_pv_low[day_indices[valid]]
    pivot_high_at_bar[valid] = daily_recent_pv_high[day_indices[valid]]

    return pivot_low_at_bar, pivot_high_at_bar


@register_strategy("cross_tendency", aliases=("crossTendency", "ema_cross_adx"))
class CrossTendencyStrategy(StrategyBase):
    name = "CrossTendency"

    def __init__(
        self,
        fast_ma_period: int = 20,
        slow_ma_period: int = 50,
        atr_period: int = 14,
        use_dynamic_atr_filter: bool = True,
        atr_filter_ma_period: int = 20,
        atr_high_multiplier: float = 1.1,
        min_atr_points: float = 100.0,
        use_adx_filter: bool = True,
        adx_period: int = 14,
        adx_min_value: float = 25.0,
        pivot_left_bars: int = 20,
        pivot_right_bars: int = 20,
        pivot_search_bars: int = 400,
        pivot_buffer_points: float = 0.0,
        point: float = 0.00001,
        use_trailing: bool = True,
        trailing_stop_percent: float = 0.5,
        trailing_start_profit_percent: float = 1.0,
        trailing_step_points: int = 10,
    ) -> None:
        self.fast_ma_period = fast_ma_period
        self.slow_ma_period = slow_ma_period
        self.atr_period = atr_period
        self.use_dynamic_atr_filter = use_dynamic_atr_filter
        self.atr_filter_ma_period = atr_filter_ma_period
        self.atr_high_multiplier = atr_high_multiplier
        self.min_atr_points = min_atr_points
        self.use_adx_filter = use_adx_filter
        self.adx_period = adx_period
        self.adx_min_value = adx_min_value
        self.pivot_left_bars = pivot_left_bars
        self.pivot_right_bars = pivot_right_bars
        self.pivot_search_bars = pivot_search_bars
        self.pivot_buffer = pivot_buffer_points * point
        self.point = point
        self.use_trailing = use_trailing
        self.trailing_stop_pct = trailing_stop_percent / 100.0
        self.trailing_start_pct = trailing_start_profit_percent / 100.0
        self.trailing_step = trailing_step_points * point

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        out = add_ema(data, self.fast_ma_period, name=f"ema{self.fast_ma_period}")
        out = add_ema(out, self.slow_ma_period, name=f"ema{self.slow_ma_period}")
        out = add_atr(out, self.atr_period, name="atr")
        if self.use_dynamic_atr_filter:
            out["atr_ma"] = out["atr"].rolling(self.atr_filter_ma_period).mean()
        if self.use_adx_filter:
            out = add_adx(out, self.adx_period, name="adx")
        return out

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = self.prepare_indicators(data)
        n = len(df)

        fast = df[f"ema{self.fast_ma_period}"].to_numpy(dtype=float)
        slow = df[f"ema{self.slow_ma_period}"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        atr = df["atr"].to_numpy(dtype=float)

        atr_ma = df["atr_ma"].to_numpy(dtype=float) if "atr_ma" in df.columns else None
        adx = df["adx"].to_numpy(dtype=float) if "adx" in df.columns else None

        # Multi-timeframe: pivots on DAILY resampled data
        daily_pivot_low, daily_pivot_high = _build_daily_pivots(
            df, self.pivot_left_bars, self.pivot_right_bars, self.pivot_search_bars,
        )

        trend = np.where(fast > slow, 1, np.where(fast < slow, -1, 0))
        cross = np.diff(trend, prepend=trend[0])

        signal = np.zeros(n, dtype=int)
        entry_price = np.full(n, np.nan)
        stop_price = np.full(n, np.nan)
        trailing_distance = np.full(n, np.nan)
        comment = np.empty(n, dtype=object)
        comment[:] = ""

        min_atr_price = self.min_atr_points * self.point

        for i in range(1, n):
            if cross[i] == 0:
                continue

            direction = 1 if cross[i] > 0 else -1

            # --- ATR filter ---
            if np.isnan(atr[i]):
                continue
            if atr[i] < min_atr_price:
                continue
            if self.use_dynamic_atr_filter and atr_ma is not None:
                if np.isnan(atr_ma[i]):
                    continue
                if atr[i] < atr_ma[i] * self.atr_high_multiplier:
                    continue

            # --- ADX filter ---
            if self.use_adx_filter and adx is not None:
                if np.isnan(adx[i]) or adx[i] < self.adx_min_value:
                    continue

            # --- Daily pivot stop ---
            if direction == 1:
                pvt = daily_pivot_low[i]
                if np.isnan(pvt):
                    continue
                stop = pvt - self.pivot_buffer
            else:
                pvt = daily_pivot_high[i]
                if np.isnan(pvt):
                    continue
                stop = pvt + self.pivot_buffer

            signal[i] = direction
            entry_price[i] = close[i]
            stop_price[i] = stop
            comment[i] = f"CrossTendency {'BUY' if direction == 1 else 'SELL'}"

            # --- Trailing distance ---
            if self.use_trailing:
                trailing_distance[i] = close[i] * self.trailing_stop_pct

        cols = {
            "datetime": df["datetime"].to_numpy(),
            "signal": signal,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "comment": comment,
        }
        if self.use_trailing:
            cols["trailing_distance"] = trailing_distance

        return pd.DataFrame(cols)
