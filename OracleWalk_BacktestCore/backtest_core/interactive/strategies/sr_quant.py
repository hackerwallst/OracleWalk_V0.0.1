"""S&R Quant 0.2.0 — Python port (single-timeframe v1).

Faithful re-implementation of the *trading logic* of the MQL5 EA "S&R 0.2.0",
written from scratch for the interactive replay engine. None of the MT5
infrastructure (chart objects, panels, JSON/CSV zone I/O, buttons, alerts) is
ported — zones come live from the replay's ZoneStore and execution/risk/costs
come from the engine.

What IS ported (the strategy itself):
  * Entry = exhaustion of 3 oscillators while price sits inside an S/R zone:
      BUY  (support):     RSI<27  AND Stoch%K<20 AND UltimateOsc<30
      SELL (resistance):  RSI>72  AND Stoch%K>80 AND UltimateOsc>70
  * "Window" state machine: once exhaustion triggers at a touched zone, a wait
    window opens for up to 3 bars; it cancels if price leaves the zone or the
    window expires.
  * Three operating modes:
      SEM   — enter immediately on exhaustion + price-in-zone.
      COM   — wait for an SMA60 confirmation (two closed bars on the trade side
              of the SMA).
      AMBOS — both can fire (each once per window); up to 2 positions/side.
  * Risk: SL at the far zone edge minus 50% of the zone height; TP at risk*3
    (1:3). Position sizing by the engine's risk_per_trade_pct (2%).
  * Cooldown: after a stop-loss, block new entries for 4 hours.

Single-TF simplification (v1): oscillators AND the SMA60 trigger are read on the
loaded timeframe. The EA's multi-timeframe nuance (oscillators on the zone TF,
SMA on a lower TF) is intentionally deferred to v2.

Parameters are fixed to the EA's values (the user asked to mirror them).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ...indicators.momentum import add_rsi
from ...indicators.trend import add_sma
from ..strategy_base import BarContext, Intent, InteractiveStrategyBase


# ---------------------------------------------------------------- indicators
def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-smoothed ATR (matches MT5 iATR closely)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def ultimate_oscillator_atr(
    df: pd.DataFrame,
    fast: int = 7,
    middle: int = 14,
    slow: int = 28,
    k_fast: int = 4,
    k_middle: int = 2,
    k_slow: int = 1,
) -> pd.Series:
    """Ultimate Oscillator, MT5 "Ultimate_Oscillator.mq5" variant (ATR-based).

    BP = close - min(low, prev_close); raw = Σ k_n · SMA(BP,n)/ATR(n); UO = raw/Σk · 100.
    """
    close, low = df["close"], df["low"]
    true_low = pd.concat([low, close.shift(1)], axis=1).min(axis=1)
    bp = close - true_low
    raw = (
        k_fast * (bp.rolling(fast).mean() / _atr(df, fast))
        + k_middle * (bp.rolling(middle).mean() / _atr(df, middle))
        + k_slow * (bp.rolling(slow).mean() / _atr(df, slow))
    )
    return raw / (k_fast + k_middle + k_slow) * 100.0


def stochastic_slowed_k(df: pd.DataFrame, k_period: int = 50, slowing: int = 3) -> pd.Series:
    """MT5 iStochastic main line (%K with slowing) over LOW/HIGH."""
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    raw_k = 100.0 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    return raw_k.rolling(slowing).mean()


def _nearest_zone(zones: list[dict], side: str, price: float) -> Optional[dict]:
    """Zone of `side` that contains `price`, closest by center distance."""
    best = None
    best_dist = float("inf")
    for z in zones:
        if z.get("side") != side:
            continue
        lo, hi = z["price_low"], z["price_high"]
        if lo <= price <= hi:
            dist = abs(price - (lo + hi) / 2.0)
            if dist < best_dist:
                best_dist = dist
                best = z
    return best


# ----------------------------------------------------------------- strategy
class SRQuantStrategy(InteractiveStrategyBase):
    name = "S&R Quant 0.2.0"
    indicator_columns = ["rsi", "stoch_k", "uo", "sma60"]

    # --- fixed parameters (mirroring S&R 0.2.0) ---
    RSI_PERIOD = 14
    RSI_BUY = 27.0
    RSI_SELL = 72.0
    STOCH_K = 50
    STOCH_SLOWING = 3
    STOCH_BUY = 20.0
    STOCH_SELL = 80.0
    UO_BUY = 30.0
    UO_SELL = 70.0
    SMA_PERIOD = 60
    SL_RECUO_PCT = 50.0
    TP_FACTOR = 3.0
    MAX_TOTAL = 2          # MaxOrdensPorAtivo
    MAX_PER_SIDE_AMBOS = 2  # MaxPorLado_Ambos
    WINDOW_BARS = 3         # segundosJanela = 3 bars of the (single) TF
    COOLDOWN_HOURS = 4

    # Zone timeframe -> the timeframe one step below, where the SMA60 cross
    # (média / confirmation) is read. Mirrors the EA's GatilhoTF().
    GATILHO_TF = {"M15": "M1", "H1": "M5", "H4": "M15", "D1": "H1", "W1": "D1"}

    VALID_MODES = ("SEM", "COM", "AMBOS")

    def __init__(self, mode: str = "COM") -> None:
        mode = str(mode).upper()
        if mode not in self.VALID_MODES:
            raise ValueError(f"mode must be one of {self.VALID_MODES}")
        self.mode = mode
        self.warmup_bars = max(self.SMA_PERIOD, 28 + self.STOCH_SLOWING) + 2
        self.reset_state()

    def reset_state(self) -> None:
        self._buy_win: Optional[dict] = None
        self._sell_win: Optional[dict] = None
        self._cooldown_until: Optional[pd.Timestamp] = None

    # ----- the engine config this strategy expects (helper for callers) -----
    def engine_overrides(self) -> dict:
        return {
            "risk_per_trade_pct": 2.0,
            "single_position_mode": self.mode != "AMBOS",
        }

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        out = add_rsi(data, self.RSI_PERIOD, name="rsi")
        out["stoch_k"] = stochastic_slowed_k(out, self.STOCH_K, self.STOCH_SLOWING)
        out["uo"] = ultimate_oscillator_atr(out)
        out = add_sma(out, self.SMA_PERIOD, name="sma60")
        return out

    def indicator_thresholds(self) -> dict[str, dict[str, float]]:
        return {
            "rsi": {"oversold": self.RSI_BUY, "overbought": self.RSI_SELL},
            "stoch_k": {"oversold": self.STOCH_BUY, "overbought": self.STOCH_SELL},
            "uo": {"oversold": self.UO_BUY, "overbought": self.UO_SELL},
        }

    # ------------------------------------------------------------- main hook
    def on_bar(self, ctx: BarContext) -> Optional[Intent]:
        now = pd.Timestamp(ctx.bar.datetime)
        self._update_cooldown(ctx)
        if self._cooldown_until is not None and now < self._cooldown_until:
            return None

        ambos = self.mode == "AMBOS"
        # Non-AMBOS modes are single-position: skip entirely while a trade is open.
        if not ambos and ctx.open_trades:
            return None

        permit_sem = self.mode in ("SEM", "AMBOS")
        permit_com = self.mode in ("COM", "AMBOS")

        close = float(ctx.bar.close)
        # MTF rule: exhaustion is read on EACH zone's own timeframe. A trade in an
        # H4 zone only triggers if H4 is exhausted; an H1 zone, only if H1 is.
        support = self._find_setup(ctx, "support", close)
        resistance = self._find_setup(ctx, "resistance", close)

        intent = self._manage_side(ctx, "long", close, support, support is not None, permit_sem, permit_com, ambos)
        if intent is not None:
            return intent
        return self._manage_side(ctx, "short", close, resistance, resistance is not None, permit_sem, permit_com, ambos)

    def _find_setup(self, ctx, side, close) -> Optional[dict]:
        """Nearest zone of `side` containing price, IF its own timeframe is exhausted."""
        zone = _nearest_zone(ctx.zones, side, close)
        if zone is None:
            return None
        ind = self._tf_indicators_for(ctx, zone)
        rsi, stoch, uo = ind.get("rsi"), ind.get("stoch_k"), ind.get("uo")
        if rsi is None or stoch is None or uo is None:
            return None
        if side == "support":
            ok = rsi < self.RSI_BUY and stoch < self.STOCH_BUY and uo < self.UO_BUY
        else:
            ok = rsi > self.RSI_SELL and stoch > self.STOCH_SELL and uo > self.UO_SELL
        return zone if ok else None

    @staticmethod
    def _tf_indicators_for(ctx, zone) -> dict:
        """Indicators on the zone's timeframe; fall back to the base TF."""
        tf = str(zone.get("timeframe") or "").upper()
        tf_map = getattr(ctx, "tf_indicators", None) or {}
        if tf and tf in tf_map and tf_map[tf]:
            return tf_map[tf]
        return ctx.indicators

    # ----------------------------------------------------------- state logic
    def _manage_side(self, ctx, direction, close, zone, exhaustion, permit_sem, permit_com, ambos):
        win = self._buy_win if direction == "long" else self._sell_win

        intent = None
        if win is not None:
            intent, win = self._process_window(ctx, direction, close, win, permit_sem, permit_com, ambos)

        # Open a new window only if we didn't just act and none is pending.
        if intent is None and win is None and exhaustion and zone is not None:
            if self._has_capacity(ctx, direction, ambos):
                win = {
                    "start": ctx.bar_index,
                    "zmin": zone["price_low"],
                    "zmax": zone["price_high"],
                    "sem": False,
                    "com": False,
                    # Trigger TF = one step below the zone's TF (None if untagged).
                    "gatilho_tf": self.GATILHO_TF.get(str(zone.get("timeframe") or "").upper()),
                    # Identity of the zone that opened this window (per-zone edge).
                    "zid": zone.get("id"),
                    "ztf": str(zone.get("timeframe") or "").upper(),
                    "zside": zone.get("side"),
                }
                intent, win = self._process_window(ctx, direction, close, win, permit_sem, permit_com, ambos)

        self._set_window(direction, win)
        return intent

    def _process_window(self, ctx, direction, close, win, permit_sem, permit_com, ambos):
        # Expired or price left the zone -> cancel.
        if ctx.bar_index - win["start"] > self.WINDOW_BARS:
            return None, None
        if not (win["zmin"] <= close <= win["zmax"]):
            return None, None
        if not self._has_capacity(ctx, direction, ambos):
            return None, None

        # COM (confirmation) takes priority, mirroring the EA.
        if permit_com and not win["com"] and self._sma_confirms(ctx, direction, win.get("gatilho_tf")):
            if self._can_open(ctx, direction, sem=False):
                win["com"] = True
                intent = self._build_intent(direction, close, win, "COM")
                return intent, (None if (not ambos or win["sem"]) else win)

        if permit_sem and not win["sem"]:
            if self._can_open(ctx, direction, sem=True):
                win["sem"] = True
                intent = self._build_intent(direction, close, win, "SEM")
                return intent, (None if (not ambos or win["com"]) else win)

        return None, win

    def _build_intent(self, direction, close, win, tag) -> Intent:
        height = max(win["zmax"] - win["zmin"], 1e-12)
        recuo = height * (self.SL_RECUO_PCT / 100.0)
        z = {"zone_id": win.get("zid"), "zone_tf": win.get("ztf"), "zone_side": win.get("zside")}
        if direction == "long":
            sl = win["zmin"] - recuo
            risk = close - sl
            tp = close + risk * self.TP_FACTOR
            return Intent(signal=1, stop_price=sl, take_price=tp, comment=f"BUY|{tag}", **z)
        sl = win["zmax"] + recuo
        risk = sl - close
        tp = close - risk * self.TP_FACTOR
        return Intent(signal=-1, stop_price=sl, take_price=tp, comment=f"SELL|{tag}", **z)

    # ------------------------------------------------------------- helpers
    def _sma_confirms(self, ctx, direction, gatilho_tf) -> bool:
        """SMA60 cross on the trigger timeframe (one below the zone's).

        - Untagged zone (no TF) -> base-TF window (legacy single-TF behaviour).
        - Tagged zone -> read the trigger TF from tf_series_tail. If that TF isn't
          available (finer than the loaded data), we CANNOT confirm -> no COM entry
          until finer data (e.g. M1) is loaded.
        """
        if gatilho_tf is None:
            return self._base_sma_confirms(ctx, direction)
        tail = (getattr(ctx, "tf_series_tail", None) or {}).get(gatilho_tf)
        if not tail or not tail.get("close") or not tail.get("sma60"):
            return False
        return self._cross(tail["close"], tail["sma60"], direction)

    def _base_sma_confirms(self, ctx, direction) -> bool:
        w = ctx.window
        if len(w) < 2 or "sma60" not in w.columns:
            return False
        return self._cross(
            [w["close"].iloc[-2], w["close"].iloc[-1]],
            [w["sma60"].iloc[-2], w["sma60"].iloc[-1]],
            direction,
        )

    @staticmethod
    def _cross(closes, smas, direction) -> bool:
        if len(closes) < 2 or len(smas) < 2:
            return False
        c0, c1 = closes[-2], closes[-1]
        s0, s1 = smas[-2], smas[-1]
        if any(v is None or pd.isna(v) for v in (c0, c1, s0, s1)):
            return False
        if direction == "long":
            return c1 > s1 and c0 > s0
        return c1 < s1 and c0 < s0

    def _count(self, trades, direction, sem=None) -> int:
        n = 0
        for t in trades:
            if t["direction"] != direction:
                continue
            if sem is True and "SEM" not in t.get("comment", ""):
                continue
            if sem is False and "COM" not in t.get("comment", ""):
                continue
            n += 1
        return n

    def _has_capacity(self, ctx, direction, ambos) -> bool:
        if len(ctx.open_trades) >= self.MAX_TOTAL:
            return False
        if ambos and self._count(ctx.open_trades, direction) >= self.MAX_PER_SIDE_AMBOS:
            return False
        return True

    def _can_open(self, ctx, direction, sem) -> bool:
        if not self._has_capacity(ctx, direction, ambos=(self.mode == "AMBOS")):
            return False
        # No duplicate "SEM" position on the same side.
        if sem and self._count(ctx.open_trades, direction, sem=True) > 0:
            return False
        return True

    def _set_window(self, direction, win) -> None:
        if direction == "long":
            self._buy_win = win
        else:
            self._sell_win = win

    def _update_cooldown(self, ctx) -> None:
        for t in ctx.recent_closed:
            if t.get("exit_reason") == "sl":
                exit_time = pd.Timestamp(t["exit_time"])
                until = exit_time + pd.Timedelta(hours=self.COOLDOWN_HOURS)
                if self._cooldown_until is None or until > self._cooldown_until:
                    self._cooldown_until = until
                # Kill the window on the side that was stopped out.
                if t["direction"] == "long":
                    self._buy_win = None
                else:
                    self._sell_win = None
