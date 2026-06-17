"""Throwaway stub strategy to exercise the interactive engine end to end.

NOT the user's real strategy. It just enters when price touches a hand-drawn
zone, so we can prove the replay loop, the causal zone store, and the report all
work together. Replace by plugging the real strategy into ``InteractiveStrategyBase``.
"""

from __future__ import annotations

from typing import Optional

from .strategy_base import BarContext, Intent, InteractiveStrategyBase


class ZoneTouchStub(InteractiveStrategyBase):
    name = "Zone Touch Stub"
    warmup_bars = 1

    def __init__(self, stop_frac: float = 0.5, take_mult: float = 2.0) -> None:
        # SL placed stop_frac of the zone height beyond the touched edge;
        # TP at take_mult times the risk distance.
        self.stop_frac = stop_frac
        self.take_mult = take_mult

    def on_bar(self, ctx: BarContext) -> Optional[Intent]:
        if ctx.open_trades:
            return None
        close = float(ctx.bar.close)
        for zone in ctx.zones:
            lo = zone["price_low"]
            hi = zone["price_high"]
            if not (lo <= close <= hi):
                continue
            height = max(hi - lo, 1e-9)
            if zone["side"] == "support":
                stop = lo - self.stop_frac * height
                risk = close - stop
                take = close + self.take_mult * risk
                return Intent(signal=1, stop_price=stop, take_price=take, comment=self.name)
            stop = hi + self.stop_frac * height
            risk = stop - close
            take = close - self.take_mult * risk
            return Intent(signal=-1, stop_price=stop, take_price=take, comment=self.name)
        return None
