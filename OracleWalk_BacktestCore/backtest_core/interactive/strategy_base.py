"""Event-driven strategy interface for the interactive replay track.

This is intentionally separate from the classic batch ``StrategyBase``. The two
coexist. A batch strategy returns *all* signals from the whole DataFrame at once
(no good for human-in-the-loop). An interactive strategy reacts **one bar at a
time** via ``on_bar(ctx)``, seeing only the past and the zones that exist at that
bar — never the future.

The user's real strategy is NOT implemented here. This base is the plug point so
it can be brought in later. Only a stub is provided (see ``stub.py``) to exercise
the engine end to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass
class Intent:
    """What the strategy wants to do on the current bar.

    ``signal``: 1 = go long, -1 = go short, 0 = do nothing.
    The optional fields mirror the engine's signal payload. Leave them None to
    let the engine default (market entry at close, no SL/TP, size by risk).
    """

    signal: int
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_price: Optional[float] = None
    size: Optional[float] = None
    risk: Optional[float] = None
    trailing_distance: Optional[float] = None
    comment: str = ""
    # Which causal zone triggered this entry (for per-zone edge analytics). The
    # engine carries these onto the trade record so the report can answer "which
    # of my hand-drawn zones actually had edge?".
    zone_id: Optional[str] = None
    zone_tf: Optional[str] = None
    zone_side: Optional[str] = None


@dataclass
class BarContext:
    """Everything the strategy may look at on the current bar — past only."""

    bar_index: int
    bar: Any  # current row as a namedtuple (open/high/low/close/volume/datetime + indicators)
    window: pd.DataFrame  # data[0 .. bar_index] inclusive — no future rows
    zones: list[dict[str, Any]]  # active S/R zones at this bar (causal)
    open_trades: list[dict[str, Any]]  # currently open trades (read-only view)
    indicators: dict[str, float]  # indicator values at this bar (base timeframe)
    recent_closed: list[dict[str, Any]]  # trades closed on the previous bar (with exit_reason)
    # Per-timeframe indicators, e.g. {"H1": {...}, "H4": {...}}. The H4 values are
    # the *last closed* H4 bar at this moment (causal — never the forming candle).
    # A zone is evaluated on its own timeframe via this map.
    tf_indicators: dict[str, dict[str, float]] = field(default_factory=dict)
    # Last 2 closed bars (close + sma60) per timeframe — for the SMA-cross trigger,
    # which is read on the timeframe one step BELOW the zone's. Causal.
    tf_series_tail: dict[str, dict[str, list]] = field(default_factory=dict)


class InteractiveStrategyBase:
    name = "Unnamed Interactive Strategy"

    # Bars to skip at the start before signals may fire (indicator warmup).
    warmup_bars = 1

    # Indicator columns to surface in the snapshot (frontend reads these).
    indicator_columns: list[str] = []

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Precompute causal indicators once over the whole series.

        Safe against lookahead as long as every indicator only depends on past
        and current bars (RSI, Stochastic, Ultimate Oscillator, ATR all do).
        The engine then just reads the value at the current bar.
        """
        return data.copy()

    def indicator_thresholds(self) -> dict[str, dict[str, float]]:
        """Per-indicator visual thresholds surfaced to the replay UI."""
        return {}

    def reset_state(self) -> None:
        """Clear event-driven state before replaying from the warmup cursor."""
        return None

    def on_bar(self, ctx: BarContext) -> Optional[Intent]:
        raise NotImplementedError
