"""Fair Value Gap (FVG / price-inefficiency) reversion strategy — classic track.

A three-candle imbalance leaves an untraded "gap" between candle 1 and candle 3,
carved by a strong displacement candle in the middle. Price tends to revisit that
inefficiency; this strategy waits for a retrace to the **50% (midpoint)** of the
gap and enters in the gap's direction.

Rules (as specified by the project owner):
  * Bullish FVG (gap up, inefficiency of *alta*) -> BUY:   high[i-2] < low[i].
    Bearish FVG (gap down, inefficiency of *baixa*) -> SELL: low[i-2]  > high[i].
  * Entry: a limit at the gap's 50% midpoint, taken on the bar that retraces to it.
  * Stop: just behind the WHOLE 3-candle structure (lowest low / highest high of
    the three bars).
  * Take profit: fixed risk:reward (default 1:3) off the entry->stop distance.
  * Volume filter: the displacement candle's volume must exceed the average volume
    of the 5 candles before it.
  * Trend filter (checked at the entry bar): only BUY when close > SMA60, only SELL
    when close < SMA60.
  * Expiry: an unfilled FVG is discarded after `expiry_bars` candles.

The batch engine fills a signal's ``entry_price`` only if that bar touches it
(no carried pending orders), so the signal is emitted on the exact bar the 50%
level is reached — never on the formation bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..indicators.trend import add_sma
from .base import StrategyBase


def detect_fvg_boxes(data: pd.DataFrame, expiry_bars: int = 20) -> list[dict]:
    """Extract every FVG as a drawable box with its lifespan, for chart rendering.

    Returns one dict per gap: ``startIndex`` (detection bar), ``endIndex`` (the bar
    it was filled at the 50% level or expired), ``low``/``high`` (gap bounds),
    ``side`` ('buy'/'sell') and ``outcome`` ('filled'/'expired'/'open'). Mirrors the
    strategy's detection + trend-filtered fill so the boxes match the trades. Needs
    ``sma60`` and ``vol_avg`` columns (added by ``FairValueGapStrategy.prepare_indicators``).
    """
    n = len(data)
    if n < 3 or not {"sma60", "vol_avg"}.issubset(data.columns):
        return []
    high = data["high"].to_numpy(dtype=float)
    low = data["low"].to_numpy(dtype=float)
    close = data["close"].to_numpy(dtype=float)
    volume = data["volume"].to_numpy(dtype=float)
    sma = data["sma60"].to_numpy(dtype=float)
    vol_avg = data["vol_avg"].to_numpy(dtype=float)

    boxes: list[dict] = []
    active: list[dict] = []
    for i in range(n):
        still = []
        for b in active:
            if i > b["expiry"]:
                b["endIndex"], b["outcome"] = b["expiry"], "expired"
                boxes.append(b)
                continue
            touched = low[i] <= b["mid"] <= high[i]
            trend_ok = (b["dir"] > 0 and close[i] > sma[i]) or (b["dir"] < 0 and close[i] < sma[i])
            if touched and not np.isnan(sma[i]) and trend_ok:
                b["endIndex"], b["outcome"] = i, "filled"
                boxes.append(b)
                continue
            still.append(b)
        active = still

        if i >= 2 and not np.isnan(vol_avg[i - 1]) and volume[i - 1] > vol_avg[i - 1]:
            if high[i - 2] < low[i]:
                lo, hi = high[i - 2], low[i]
                active.append({"dir": 1, "low": lo, "high": hi, "mid": (lo + hi) / 2.0,
                               "startIndex": i, "expiry": i + expiry_bars, "side": "buy"})
            elif low[i - 2] > high[i]:
                lo, hi = high[i], low[i - 2]
                active.append({"dir": -1, "low": lo, "high": hi, "mid": (lo + hi) / 2.0,
                               "startIndex": i, "expiry": i + expiry_bars, "side": "sell"})

    for b in active:  # still pending at the end of the data
        b["endIndex"], b["outcome"] = min(b["expiry"], n - 1), "open"
        boxes.append(b)

    return [
        {"startIndex": int(b["startIndex"]), "endIndex": int(b["endIndex"]),
         "low": float(b["low"]), "high": float(b["high"]), "side": b["side"], "outcome": b["outcome"]}
        for b in boxes
    ]


@dataclass
class _FVG:
    direction: int          # +1 bullish (buy), -1 bearish (sell)
    mid: float              # 50% level — the entry price
    stop: float             # behind the 3-candle structure
    created_bar: int
    expiry_bar: int


class FairValueGapStrategy(StrategyBase):
    name = "FVG Imbalance"

    def __init__(
        self,
        sma_period: int = 60,
        vol_lookback: int = 5,
        expiry_bars: int = 20,
        rr: float = 3.0,
        stop_buffer_points: float = 0.0,
        point: float = 0.00001,
    ) -> None:
        self.sma_period = sma_period
        self.vol_lookback = vol_lookback
        self.expiry_bars = expiry_bars
        self.rr = rr
        self.stop_buffer = stop_buffer_points * point

    # ------------------------------------------------------------------ setup
    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        out = add_sma(data, self.sma_period, name="sma60")
        # Average volume of the `vol_lookback` candles BEFORE each bar (the current
        # bar excluded), so a displacement candle is compared against its own past.
        out["vol_avg"] = out["volume"].rolling(self.vol_lookback).mean().shift(1)
        return out

    # ---------------------------------------------------------------- signals
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data if {"sma60", "vol_avg"}.issubset(data.columns) else self.prepare_indicators(data)
        n = len(df)

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        sma = df["sma60"].to_numpy(dtype=float)
        vol_avg = df["vol_avg"].to_numpy(dtype=float)

        signal = np.zeros(n, dtype=int)
        entry_price = np.full(n, np.nan)
        stop_price = np.full(n, np.nan)
        take_price = np.full(n, np.nan)
        comment = np.empty(n, dtype=object)
        comment[:] = ""

        active: list[_FVG] = []

        for i in range(n):
            # 1) Try to fill an active FVG whose 50% is touched on THIS bar.
            still: list[_FVG] = []
            fired = False
            for fvg in active:
                if i > fvg.expiry_bar:
                    continue  # expired, drop it
                touched = low[i] <= fvg.mid <= high[i]
                trend_ok = (
                    (fvg.direction > 0 and close[i] > sma[i])
                    or (fvg.direction < 0 and close[i] < sma[i])
                )
                if not fired and touched and not np.isnan(sma[i]) and trend_ok:
                    risk = abs(fvg.mid - fvg.stop)
                    if risk <= 0:
                        continue
                    signal[i] = fvg.direction
                    entry_price[i] = fvg.mid
                    stop_price[i] = fvg.stop
                    take_price[i] = fvg.mid + fvg.direction * self.rr * risk
                    comment[i] = f"FVG {'BUY' if fvg.direction > 0 else 'SELL'}"
                    fired = True
                    continue  # consumed — don't keep this FVG
                still.append(fvg)
            active = still

            # 2) Detect a new FVG ending on this bar (needs candles i-2, i-1, i).
            if i < 2 or np.isnan(vol_avg[i - 1]):
                continue
            strong_vol = volume[i - 1] > vol_avg[i - 1]
            if not strong_vol:
                continue

            if high[i - 2] < low[i]:  # bullish gap -> buy zone
                gap_lo, gap_hi = high[i - 2], low[i]
                struct = min(low[i - 2], low[i - 1], low[i]) - self.stop_buffer
                active.append(_FVG(+1, (gap_lo + gap_hi) / 2.0, struct, i, i + self.expiry_bars))
            elif low[i - 2] > high[i]:  # bearish gap -> sell zone
                gap_lo, gap_hi = high[i], low[i - 2]
                struct = max(high[i - 2], high[i - 1], high[i]) + self.stop_buffer
                active.append(_FVG(-1, (gap_lo + gap_hi) / 2.0, struct, i, i + self.expiry_bars))

        return pd.DataFrame(
            {
                "datetime": df["datetime"].to_numpy(),
                "signal": signal,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "take_price": take_price,
                "comment": comment,
            }
        )
