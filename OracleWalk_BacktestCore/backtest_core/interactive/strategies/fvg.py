"""Fair Value Gap (FVG / imbalance) strategy for the INTERACTIVE replay track.

Same trading logic as the classic ``FairValueGapStrategy``, re-shaped as an
event-driven ``on_bar`` strategy so you can WATCH it on the candle chart: the
SMA60 trend filter renders as a price overlay, and every detected gap is exposed
as a rectangle (a "box") that is born on the detection bar and lives until it is
either filled (price retraces to the 50% midpoint) or expires after ``expiry_bars``
candles — so you literally watch each inefficiency's useful life on the chart.

The boxes are surfaced through ``boxes_at(cursor)`` and merged into the snapshot's
``zones`` array, so the existing zone-rectangle rendering draws them with no
frontend change. Bullish gaps are tagged ``support`` (buy / green), bearish gaps
``resistance`` (sell / red).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ...indicators.trend import add_sma
from ...strategies.fvg_imbalance import _body_ok
from ..strategy_base import BarContext, Intent, InteractiveStrategyBase


class FVGStrategy(InteractiveStrategyBase):
    name = "FVG Imbalance"
    indicator_columns = ["sma60"]  # rendered as a price overlay on the chart

    def __init__(
        self,
        sma_period: int = 60,
        vol_lookback: int = 5,
        expiry_bars: int = 20,
        rr: float = 3.0,
        stop_buffer_points: float = 0.0,
        point: float = 0.00001,
        min_body_ratio: float = 0.0,
    ) -> None:
        self.sma_period = sma_period
        self.vol_lookback = vol_lookback
        self.expiry_bars = expiry_bars
        self.rr = rr
        self.stop_buffer = stop_buffer_points * point
        self.min_body_ratio = float(min_body_ratio)
        self.warmup_bars = sma_period + vol_lookback + 2
        self.reset_state()

    # ----------------------------------------------------------------- setup
    def engine_overrides(self) -> dict:
        return {"risk_per_trade_pct": 1.0, "single_position_mode": True}

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        out = add_sma(data, self.sma_period, name="sma60")
        out["vol_avg"] = out["volume"].rolling(self.vol_lookback).mean().shift(1)
        return out

    def reset_state(self) -> None:
        self._boxes: list[dict] = []
        self._counter = 0

    # ------------------------------------------------------------- main hook
    def on_bar(self, ctx: BarContext) -> Optional[Intent]:
        i = ctx.bar_index
        w = ctx.window
        close = float(ctx.bar.close)
        high_i = float(ctx.bar.high)
        low_i = float(ctx.bar.low)
        sma = getattr(ctx.bar, "sma60", None)

        # 1) drop boxes that have outlived their expiry.
        self._boxes = [b for b in self._boxes if b["state"] == "active" and i <= b["expiry"]]

        # 2) a box whose 50% is touched on this bar fires an entry (trend-filtered).
        intent: Optional[Intent] = None
        if sma is not None and not pd.isna(sma):
            for b in self._boxes:
                if b["created"] >= i:  # never on the formation bar
                    continue
                if not (low_i <= b["mid"] <= high_i):
                    continue
                trend_ok = (b["dir"] > 0 and close > sma) or (b["dir"] < 0 and close < sma)
                if not trend_ok:
                    continue
                risk = abs(b["mid"] - b["stop"])
                if risk <= 0:
                    continue
                b["state"] = "filled"
                tag = "BUY" if b["dir"] > 0 else "SELL"
                intent = Intent(
                    signal=b["dir"],
                    entry_price=b["mid"],
                    stop_price=b["stop"],
                    take_price=b["mid"] + b["dir"] * self.rr * risk,
                    comment=f"FVG {tag}",
                )
                break
        # filled boxes leave the live set (their life ended at the entry).
        self._boxes = [b for b in self._boxes if b["state"] == "active"]

        # 3) detect a new FVG ending on this bar (candles i-2, i-1, i).
        if len(w) >= 3:
            vavg = w["vol_avg"].iloc[-2]
            v_disp = float(w["volume"].iloc[-2])
            o1 = float(w["open"].iloc[-2])
            h1d, l1d, c1d = float(w["high"].iloc[-2]), float(w["low"].iloc[-2]), float(w["close"].iloc[-2])
            if pd.notna(vavg) and v_disp > float(vavg) and _body_ok(o1, h1d, l1d, c1d, self.min_body_ratio):
                h2, l2 = float(w["high"].iloc[-3]), float(w["low"].iloc[-3])
                h1, l1 = float(w["high"].iloc[-2]), float(w["low"].iloc[-2])
                h0, l0 = float(w["high"].iloc[-1]), float(w["low"].iloc[-1])
                if h2 < l0:  # bullish gap -> buy
                    self._add_box(+1, h2, l0, min(l2, l1, l0) - self.stop_buffer, i)
                elif l2 > h0:  # bearish gap -> sell
                    self._add_box(-1, h0, l2, max(h2, h1, h0) + self.stop_buffer, i)

        return intent

    def _add_box(self, direction: int, gap_lo: float, gap_hi: float, stop: float, bar: int) -> None:
        self._counter += 1
        self._boxes.append(
            {
                "id": f"fvg{self._counter}",
                "dir": direction,
                "price_low": float(gap_lo),
                "price_high": float(gap_hi),
                "mid": (float(gap_lo) + float(gap_hi)) / 2.0,
                "stop": float(stop),
                "created": int(bar),
                "expiry": int(bar) + self.expiry_bars,
                "state": "active",
            }
        )

    # ----------------------------------------------------- boxes for the UI
    def boxes_at(self, cursor: int) -> list[dict]:
        """Active FVG rectangles visible at `cursor` (zone-shaped for the overlay)."""
        out: list[dict] = []
        for b in self._boxes:
            if b["state"] != "active" or not (b["created"] <= cursor <= b["expiry"]):
                continue
            out.append(
                {
                    "id": b["id"],
                    "price_low": b["price_low"],
                    "price_high": b["price_high"],
                    "side": "support" if b["dir"] > 0 else "resistance",
                    "timeframe": "",
                    "created_at_bar": b["created"],
                    "expires_at_bar": b["expiry"],
                    "state": "active",
                    "auto": True,
                    "label": "FVG",
                }
            )
        return out
