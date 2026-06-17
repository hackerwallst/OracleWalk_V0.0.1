"""Parity probes — deterministic strategies to validate Python↔MT5 engine parity.

The goal here is NOT edge. It is to prove the execution engine matches MT5
trade-for-trade. To do that we deliberately avoid smoothed indicators (EMA, ATR,
ADX) because those diverge between platforms (seeding, Wilder vs simple) and
because sub-pip crossings flip with the tiniest data-feed difference — that noise
would mask real engine bugs.

Every probe below triggers ONLY on exact, feed-robust quantities: the bar's
datetime (weekday/hour), its position index, or exact daily high/low/close. So if
a trade diverges from the MT5 port, it is unambiguously the ENGINE, not the
strategy or the indicators.

Each probe isolates ONE execution mechanism:

  P1 ClockFlip        — market entry, next-bar-open timing, opposite-signal close,
                        swap accrual over multi-day holds (incl. Wed triple swap).
  P2 DailyBreakout    — STOP pending orders + intrabar SL/TP first-touch + expiry.
  P3 DailyLimitFade   — LIMIT pending orders (the carried order book / tick-touch
                        path) + expiry.
  P4 WeeklyTrailing   — trailing stop with a profit-activation threshold.
  P5 NBarAlternator   — dense market reversals; cost (spread/commission) accrual.

Each class docstring states the exact MQL5 logic so the EA port is mechanical.

Recommended engine config for the comparison (clean room — turn cost noise off
first, then re-run with real costs):
    pending_order_book=True         (engine default; limit/stop carried causally)
    close_on_signal="opposite", single_position_mode=True
    leverage=100                    (so 0.1 lot fits the margin; FTMO-like)
    intrabar_mode="mt5_like_ohlc"   (match MT5's O->L->H->C / O->H->L->C walk)
    use_spread=False, slippage=0, commission_*=0, swap_*=0   (phase 1)

entry_timing depends on the order TYPE (this is critical for the EA port):
    MARKET probes  (P1, P4, P5):  entry_timing="next_bar_open"
        signal computed on the closed bar; entry at the NEXT bar's open — exactly
        what an EA does when it acts on a new bar.
    PENDING probes (P2, P3):      entry_timing="signal_close"
        the limit/stop order is placed on the signal bar and rests until touched
        (it cannot fill on its own bar — causal). Matches an EA placing a pending
        order that fills on a later bar/tick. NOTE: "next_bar_open" would shift the
        signal off its trigger price and the order would never arm — use
        "signal_close" for any pending-order probe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import StrategyBase
from .registry import register_strategy


def _dt(data: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(data["datetime"])


def _empty_signal_frame(data: pd.DataFrame) -> dict:
    n = len(data)
    return {
        "datetime": data["datetime"].to_numpy(),
        "signal": np.zeros(n, dtype=int),
    }


def _prev_day_levels(data: pd.DataFrame) -> pd.DataFrame:
    """Exact previous-day high/low/close mapped to each intraday bar.

    Pure max/min/last on the calendar date — no smoothing, fully deterministic and
    identical to iHigh/iLow/iClose(PERIOD_D1, 1) in MT5.
    """
    dt = _dt(data)
    dates = dt.dt.date
    daily = data.assign(_date=dates).groupby("_date").agg(
        d_high=("high", "max"),
        d_low=("low", "min"),
        d_close=("close", "last"),
    )
    daily = daily.shift(1)  # previous day
    out = data.assign(_date=dates).merge(daily, left_on="_date", right_index=True, how="left")
    return out[["d_high", "d_low", "d_close"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
@register_strategy("p1_clock_flip", aliases=("probe1", "clock_flip"))
class P1ClockFlip(StrategyBase):
    """Probe 1 — market flip on a fixed weekly clock.

    Go long on `long_weekday` at `entry_hour`; reverse to short on `short_weekday`
    at the same hour; repeat every week. With close_on_signal="opposite" and
    single_position_mode there is always exactly one position, so this exercises:
    market entry at the next bar's open, opposite-signal close, and swap accrual
    across multi-day holds (the short rides over the weekend; either leg can span
    the Wednesday triple-swap bar).

    MQL5 logic (mechanical port):
        On each NEW bar, read the just-closed bar's time.
        if weekday == long_weekday  and hour == entry_hour:  desired = +1
        elif weekday == short_weekday and hour == entry_hour: desired = -1
        else: desired = 0
        if desired != 0 and current position direction != desired:
            close any open position; open market order in `desired` at bar open.
    """

    name = "P1 ClockFlip"

    def __init__(self, entry_hour: int = 0, long_weekday: int = 0, short_weekday: int = 2) -> None:
        self.entry_hour = entry_hour
        self.long_weekday = long_weekday   # Mon=0 .. Sun=6
        self.short_weekday = short_weekday

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        dt = _dt(data)
        cols = _empty_signal_frame(data)
        sig = cols["signal"]
        hour = dt.dt.hour.to_numpy()
        wday = dt.dt.weekday.to_numpy()
        sig[(wday == self.long_weekday) & (hour == self.entry_hour)] = 1
        sig[(wday == self.short_weekday) & (hour == self.entry_hour)] = -1
        cols["comment"] = np.where(sig == 1, "P1 LONG", np.where(sig == -1, "P1 SHORT", ""))
        return pd.DataFrame(cols)


# --------------------------------------------------------------------------- #
@register_strategy("p2_daily_breakout", aliases=("probe2", "daily_breakout_stop"))
class P2DailyBreakout(StrategyBase):
    """Probe 2 — daily breakout via a STOP pending order.

    Once per day (the bar at `place_hour`) place a buy-stop at the previous day's
    HIGH + buffer, with a fixed SL/TP in points and an intraday expiry. Exercises
    the carried stop-order book, the intrabar SL/TP first-touch resolution, and
    order expiry. One order per day → at most one resting order at a time, so the
    comparison stays unambiguous.

    MQL5 logic (mechanical port):
        On the first new bar with hour == place_hour:
            trigger = iHigh(D1,1) + buffer_points*Point
            place BUY STOP at `trigger`,
                 SL = trigger - sl_points*Point,
                 TP = trigger + tp_points*Point,
                 expiration = end of today.
        (Engine: order_type='stop', entry_price=trigger, expiry_bars carries it.)
    """

    name = "P2 DailyBreakout"

    def __init__(self, place_hour: int = 0, buffer_points: float = 10.0,
                 sl_points: float = 200.0, tp_points: float = 400.0,
                 expiry_bars: int = 23, point: float = 0.00001) -> None:
        self.place_hour = place_hour
        self.buffer_points = buffer_points
        self.sl_points = sl_points
        self.tp_points = tp_points
        self.expiry_bars = expiry_bars
        self.point = point

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        dt = _dt(data)
        hour = dt.dt.hour.to_numpy()
        lv = _prev_day_levels(data)
        d_high = lv["d_high"].to_numpy(dtype=float)
        n = len(data)

        signal = np.zeros(n, dtype=int)
        entry_price = np.full(n, np.nan)
        stop_price = np.full(n, np.nan)
        take_price = np.full(n, np.nan)
        expiry = np.full(n, np.nan)
        order_type = np.empty(n, dtype=object); order_type[:] = ""
        comment = np.empty(n, dtype=object); comment[:] = ""

        place = (hour == self.place_hour) & ~np.isnan(d_high)
        trig = d_high + self.buffer_points * self.point
        signal[place] = 1
        entry_price[place] = trig[place]
        stop_price[place] = trig[place] - self.sl_points * self.point
        take_price[place] = trig[place] + self.tp_points * self.point
        expiry[place] = self.expiry_bars
        order_type[place] = "stop"
        comment[place] = "P2 BUYSTOP"

        return pd.DataFrame({
            "datetime": data["datetime"].to_numpy(),
            "signal": signal,
            "order_type": order_type,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "take_price": take_price,
            "expiry_bars": expiry,
            "comment": comment,
        })


# --------------------------------------------------------------------------- #
@register_strategy("p3_daily_limit_fade", aliases=("probe3", "daily_limit_fade"))
class P3DailyLimitFade(StrategyBase):
    """Probe 3 — daily mean-revert via a LIMIT pending order.

    Once per day (the bar at `place_hour`) place a buy-limit `offset_points` below
    the previous day's CLOSE, fixed SL/TP, intraday expiry. This is the carried
    limit order book — the exact tick-touch path most sensitive to execution
    parity — isolated from any indicator.

    MQL5 logic (mechanical port):
        On the first new bar with hour == place_hour:
            trigger = iClose(D1,1) - offset_points*Point
            place BUY LIMIT at `trigger`,
                 SL = trigger - sl_points*Point,
                 TP = trigger + tp_points*Point,
                 expiration = end of today.
        (Engine: order_type='limit', entry_price=trigger, expiry_bars carries it.)
    """

    name = "P3 DailyLimitFade"

    def __init__(self, place_hour: int = 0, offset_points: float = 150.0,
                 sl_points: float = 200.0, tp_points: float = 300.0,
                 expiry_bars: int = 23, point: float = 0.00001) -> None:
        self.place_hour = place_hour
        self.offset_points = offset_points
        self.sl_points = sl_points
        self.tp_points = tp_points
        self.expiry_bars = expiry_bars
        self.point = point

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        dt = _dt(data)
        hour = dt.dt.hour.to_numpy()
        lv = _prev_day_levels(data)
        d_close = lv["d_close"].to_numpy(dtype=float)
        n = len(data)

        signal = np.zeros(n, dtype=int)
        entry_price = np.full(n, np.nan)
        stop_price = np.full(n, np.nan)
        take_price = np.full(n, np.nan)
        expiry = np.full(n, np.nan)
        order_type = np.empty(n, dtype=object); order_type[:] = ""
        comment = np.empty(n, dtype=object); comment[:] = ""

        place = (hour == self.place_hour) & ~np.isnan(d_close)
        trig = d_close - self.offset_points * self.point
        signal[place] = 1
        entry_price[place] = trig[place]
        stop_price[place] = trig[place] - self.sl_points * self.point
        take_price[place] = trig[place] + self.tp_points * self.point
        expiry[place] = self.expiry_bars
        order_type[place] = "limit"
        comment[place] = "P3 BUYLIMIT"

        return pd.DataFrame({
            "datetime": data["datetime"].to_numpy(),
            "signal": signal,
            "order_type": order_type,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "take_price": take_price,
            "expiry_bars": expiry,
            "comment": comment,
        })


# --------------------------------------------------------------------------- #
@register_strategy("p4_weekly_trailing", aliases=("probe4", "weekly_trailing"))
class P4WeeklyTrailing(StrategyBase):
    """Probe 4 — weekly market long with a trailing stop + activation threshold.

    Enter long once per week (`entry_weekday` at `entry_hour`), no take profit.
    The stop starts `init_stop_points` below entry and only trails once the trade
    is `trailing_start_points` in profit; thereafter it follows price by
    `trailing_distance_points`. Isolates the trailing mechanism (the exact bug we
    fixed: the start threshold must survive entry-timing shift).

    Distances are absolute (points*point). `trailing_start_profit` is emitted as a
    fraction of the signal-bar close so the engine's `entry*(1+f)` activation matches
    the EA's `price-entry >= start_points*Point` to well under 0.001 pip.

    MQL5 logic (mechanical port):
        On a NEW bar with weekday == entry_weekday and hour == entry_hour, if flat:
            open market BUY at bar open; SL = open - init_stop_points*Point.
        On every tick while long:
            if (Bid - entry) >= trailing_start_points*Point:   // activation
                newSL = Bid - trailing_distance_points*Point
                if newSL > currentSL: modify SL = newSL        // ratchet up only
    """

    name = "P4 WeeklyTrailing"

    def __init__(self, entry_weekday: int = 0, entry_hour: int = 0,
                 init_stop_points: float = 300.0, trailing_distance_points: float = 150.0,
                 trailing_start_points: float = 100.0, point: float = 0.00001) -> None:
        self.entry_weekday = entry_weekday
        self.entry_hour = entry_hour
        self.init_stop_points = init_stop_points
        self.trailing_distance_points = trailing_distance_points
        self.trailing_start_points = trailing_start_points
        self.point = point

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        dt = _dt(data)
        hour = dt.dt.hour.to_numpy()
        wday = dt.dt.weekday.to_numpy()
        close = data["close"].to_numpy(dtype=float)
        n = len(data)

        signal = np.zeros(n, dtype=int)
        stop_price = np.full(n, np.nan)
        trailing_distance = np.full(n, np.nan)
        trailing_start_profit = np.full(n, np.nan)
        comment = np.empty(n, dtype=object); comment[:] = ""

        place = (wday == self.entry_weekday) & (hour == self.entry_hour)
        signal[place] = 1
        stop_price[place] = close[place] - self.init_stop_points * self.point
        trailing_distance[place] = self.trailing_distance_points * self.point
        # fraction relative to the signal-bar close (≈ entry); engine uses entry*(1+f)
        trailing_start_profit[place] = (self.trailing_start_points * self.point) / close[place]
        comment[place] = "P4 LONG"

        return pd.DataFrame({
            "datetime": data["datetime"].to_numpy(),
            "signal": signal,
            "stop_price": stop_price,
            "trailing_distance": trailing_distance,
            "trailing_start_profit": trailing_start_profit,
            "comment": comment,
        })


# --------------------------------------------------------------------------- #
@register_strategy("p5_nbar_alternator", aliases=("probe5", "nbar_alternator"))
class P5NBarAlternator(StrategyBase):
    """Probe 5 — dense market reversals on a timestamp-anchored clock.

    The flip schedule is anchored to absolute UNIX time, NOT to a bar counter, so
    Python and MT5 compute the SAME block for the same bar regardless of warmup or
    history offset (a bar counter would drift by the tester's warm-start). Each
    `period_bars`-wide block alternates the desired side; a signal is emitted on the
    first bar of each new block (parity of the block index sets long/short). Stresses
    the executor under many opposite-signal reversals and per-trade cost accrual.

    block(ts) = floor(ts_seconds / (period_bars * bar_seconds)); +1 if even else -1.

    MQL5 logic (mechanical port):
        bar_seconds = PeriodSeconds(PERIOD_CURRENT)
        On each NEW bar, for the just-closed bar t1 (shift 1):
            block1 = (long)t1 / (period_bars * bar_seconds)
            block2 = (long)iTime(shift 2) / (period_bars * bar_seconds)
            if block1 != block2:                       // first bar of a new block
                desired = (block1 % 2 == 0) ? +1 : -1
                if position dir != desired: close & open market `desired`.
    """

    name = "P5 NBarAlternator"

    def __init__(self, period_bars: int = 20) -> None:
        self.period_bars = max(1, int(period_bars))

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        dt = _dt(data)
        ts = dt.astype("int64").to_numpy() // 1_000_000_000  # seconds since epoch
        n = len(data)
        # bar size in seconds = most common consecutive delta (timeframe-agnostic)
        if n > 1:
            diffs = np.diff(ts)
            diffs = diffs[diffs > 0]
            bar_seconds = int(np.bincount(diffs).argmax()) if len(diffs) else 3600
        else:
            bar_seconds = 3600
        block = ts // (self.period_bars * bar_seconds)
        boundary = np.empty(n, dtype=bool)
        boundary[0] = True
        boundary[1:] = block[1:] != block[:-1]

        cols = _empty_signal_frame(data)
        sig = cols["signal"]
        desired = np.where(block % 2 == 0, 1, -1)
        sig[boundary] = desired[boundary]
        cols["comment"] = np.where(sig == 1, "P5 LONG", np.where(sig == -1, "P5 SHORT", ""))
        return pd.DataFrame(cols)
