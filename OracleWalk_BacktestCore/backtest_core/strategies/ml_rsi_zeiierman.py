from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import StrategyBase


@dataclass
class _Neighbor:
    gap: float
    cls: int


class MachineLearningRsiZeiiermanStrategy(StrategyBase):
    """
    Raw strategy port of Zeiierman's "Machine Learning RSI | AI Classification & Ranking".

    The TradingView script is an indicator, not a strategy. This port keeps the original
    long/short trigger logic and lets OracleWalk close on opposite signals by default.
    Optional ATR stop/take parameters are available, but disabled by default.
    """

    name = "Machine Learning RSI Zeiierman"

    def __init__(
        self,
        fixed_lot: float = 0.01,
        rsi_base: int = 14,
        memory_depth: int = 500,
        k_neighbors: int = 8,
        gate_rank: int = 60,
        gate_conf: int = 50,
        use_trend_gate: bool = True,
        use_vol_band: bool = True,
        vol_band_lo: int = 20,
        use_chop: bool = True,
        atr_factor: float = 0.5,
        auto_weights_on: bool = True,
        auto_speed: float = 1.0,
        st_mult_base: float = 1.5,
        st_ml_resp: float = 1.0,
        stop_atr: float | None = None,
        take_atr: float | None = None,
    ):
        self.fixed_lot = fixed_lot
        self.rsi_base = rsi_base
        self.memory_depth = memory_depth
        self.k_neighbors = k_neighbors
        self.gate_rank = gate_rank
        self.gate_conf = gate_conf
        self.use_trend_gate = use_trend_gate
        self.use_vol_band = use_vol_band
        self.vol_band_lo = vol_band_lo
        self.use_chop = use_chop
        self.atr_factor = atr_factor
        self.auto_weights_on = auto_weights_on
        self.auto_speed = auto_speed
        self.st_mult_base = st_mult_base
        self.st_ml_resp = st_ml_resp
        self.stop_atr = stop_atr
        self.take_atr = take_atr

        self.win_len = 100
        self.spacing_bars = 4
        self.horizon_bars = 4
        self.trend_len = 50
        self.chop_cut = 0.5
        self.vol_band_hi = 85
        self.auto_floor = 0.5
        self.auto_min_rows = 60
        self.st_atr_len = 10
        self.smooth_len = 10
        self.cool_bars = 5
        self.step_len = 3

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy().reset_index(drop=True)
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        hl2 = (high + low) / 2.0

        r_osc = _rsi(close, self.rsi_base)
        r_osc_fast = _rsi(close, max(2, round(self.rsi_base / 2)))
        r_osc_slow = _rsi(close, self.rsi_base * 2)
        atr_14 = _atr(high, low, close, 14)

        features = pd.DataFrame(
            {
                "value": r_osc / 100.0,
                "slope": _scale01(r_osc - r_osc.shift(self.step_len), self.win_len),
                "accel": _scale01(
                    (r_osc - r_osc.shift(self.step_len))
                    - (r_osc.shift(self.step_len) - r_osc.shift(2 * self.step_len)),
                    self.win_len,
                ),
                "mid": (r_osc - 50.0).abs() / 50.0,
                "pct": _percent_rank(r_osc, self.win_len) / 100.0,
                "churn": _scale01(r_osc.rolling(14).std(), self.win_len),
                "spread": _scale01(r_osc_fast - r_osc_slow, self.win_len),
                "regime": _scale01(_ema(r_osc, 20) - 50.0, self.win_len),
            }
        )

        ema_trend = _ema(close, self.trend_len)
        ema_quick = _ema(close, 5)
        atr_pct = _percent_rank(atr_14, 100)
        st_atr_series = _atr(high, low, close, self.st_atr_len)
        trend_force = (ema_quick - ema_trend).abs() / atr_14.replace(0, np.nan)
        chop_raw = trend_force < self.chop_cut
        chop_now = chop_raw if self.use_chop else pd.Series(False, index=df.index)
        slope_up = r_osc > r_osc.shift(self.step_len)
        osc_reg = _ema(r_osc, 20)
        osc_smooth = _ema(r_osc, 5)

        n = len(df)
        out_cols = {
            "ml_rsi": np.full(n, np.nan),
            "ml_rank": np.full(n, np.nan),
            "ml_conf": np.full(n, np.nan),
            "ml_bias": np.zeros(n, dtype=float),
            "ml_st_dir": np.ones(n, dtype=float),
            "ml_st_line": np.full(n, np.nan),
            "ml_trigger_long": np.zeros(n, dtype=bool),
            "ml_trigger_short": np.zeros(n, dtype=bool),
            "atr14": atr_14.to_numpy(dtype=float),
        }

        bank: list[list[float]] = []
        w_auto = np.ones(8, dtype=float)
        stance_state = 0
        stance_age = 0
        last_stance_changed = False
        last_entry_bar: int | None = None
        st_long = np.nan
        st_short = np.nan
        st_dir = 1
        conv_smoothed = np.nan
        rank_smoothed = np.nan

        feature_values = features.to_numpy(dtype=float)
        price = close.to_numpy(dtype=float)
        atr_vals = atr_14.to_numpy(dtype=float)
        hl2_vals = hl2.to_numpy(dtype=float)

        for i in range(n):
            if i > self.horizon_bars:
                past_i = i - self.horizon_bars
                past = feature_values[past_i]
                band_fwd = self.atr_factor * atr_vals[past_i]
                move_fwd = price[i] - price[past_i]
                outcome = _classify_outcome(move_fwd, band_fwd)
                if np.isfinite(past).all() and np.isfinite(outcome):
                    bank.insert(0, [*past.tolist(), float(outcome)])
                    if len(bank) > self.memory_depth:
                        bank.pop()

            if self.auto_weights_on:
                raw_weights = _auto_feature_weights(bank, self.auto_min_rows, self.auto_floor)
                w_auto = w_auto + self.auto_speed * (raw_weights - w_auto)
                weights = w_auto
            else:
                weights = np.ones(8, dtype=float)

            cur = feature_values[i]
            neighbors = _nearest_neighbors(cur, bank, weights, self.k_neighbors, self.spacing_bars, self.memory_depth)
            analog_score, agree_frac, gap_tight, k_count = _vote(neighbors, weights)
            bias_dir = 1 if analog_score > 0.15 else -1 if analog_score < -0.15 else 0

            conv_inst = float(np.clip(analog_score / 1.5, -1.0, 1.0))
            conv_smoothed = _ema_next(conv_smoothed, conv_inst, self.smooth_len)
            ml_drive = max(0.0, min(1.0, abs(conv_smoothed) * 0.5 + gap_tight * 0.3 + agree_frac * 0.2))
            if bool(chop_now.iloc[i]):
                ml_drive *= 0.35

            st_atr = _rolling_value(st_atr_series, i)
            adapt_mult = self.st_mult_base * (1.0 + self.st_ml_resp * (1.0 - ml_drive))
            up_band = hl2_vals[i] - adapt_mult * st_atr if np.isfinite(st_atr) else np.nan
            dn_band = hl2_vals[i] + adapt_mult * st_atr if np.isfinite(st_atr) else np.nan

            prev_close = price[i - 1] if i > 0 else np.nan
            prev_st_long = st_long
            prev_st_short = st_short
            prev_st_dir = st_dir
            st_long = up_band if not np.isfinite(prev_st_long) else max(up_band, prev_st_long) if prev_close > prev_st_long else up_band
            st_short = dn_band if not np.isfinite(prev_st_short) else min(dn_band, prev_st_short) if prev_close < prev_st_short else dn_band
            if i == 0:
                st_dir = 1
            elif prev_st_dir == -1 and price[i] > prev_st_short:
                st_dir = 1
            elif prev_st_dir == 1 and price[i] < prev_st_long:
                st_dir = -1
            else:
                st_dir = prev_st_dir

            up_trend = st_dir == 1
            down_trend = st_dir == -1
            vol_healthy = self.vol_band_lo <= float(atr_pct.iloc[i]) <= self.vol_band_hi if np.isfinite(atr_pct.iloc[i]) else False
            slope_fit = (bias_dir == 1 and bool(slope_up.iloc[i])) or (bias_dir == -1 and not bool(slope_up.iloc[i]))
            stretched = (bias_dir == 1 and r_osc.iloc[i] > 70) or (bias_dir == -1 and r_osc.iloc[i] < 30)
            osc_smooth_up = osc_smooth.iloc[i] > osc_smooth.iloc[i - 1] if i > 0 else False
            aligned = (bias_dir == 1 and up_trend) or (bias_dir == -1 and down_trend)

            gates_pass = (
                (not self.use_trend_gate or aligned)
                and (not self.use_vol_band or vol_healthy)
                and not bool(chop_now.iloc[i])
            )
            prev_stance = stance_state
            if bias_dir == 1 and gates_pass:
                stance_state = 1
            elif bias_dir == -1 and gates_pass:
                stance_state = -1
            stance_changed = stance_state != prev_stance
            early_flip = stance_changed and last_stance_changed
            stance_age = 0 if stance_changed else stance_age + 1
            last_stance_changed = stance_changed

            rank = _rank_score(
                bias_dir,
                agree_frac,
                gap_tight,
                slope_fit,
                stretched,
                aligned,
                vol_healthy,
                float(atr_pct.iloc[i]) if np.isfinite(atr_pct.iloc[i]) else np.nan,
                float(osc_reg.iloc[i]) if np.isfinite(osc_reg.iloc[i]) else np.nan,
                osc_smooth_up,
                bool(chop_raw.iloc[i]),
                stance_age,
                early_flip,
                k_count,
                self.k_neighbors,
                self.vol_band_lo,
            )
            conf = _conf_score(bias_dir, agree_frac, gap_tight, slope_fit, stance_age, early_flip, k_count, self.k_neighbors)
            rank_smoothed = _ema_next(rank_smoothed, rank, 3)
            intensity = max(0.0, min(1.0, rank_smoothed / 100.0))
            ml_tilt = max(-1.0, min(1.0, conv_smoothed)) * intensity * 18.0
            ml_rsi = np.nan
            if np.isfinite(r_osc.iloc[i]):
                raw_ml_rsi = max(0.0, min(100.0, float(r_osc.iloc[i]) + ml_tilt))
                prev_ml = out_cols["ml_rsi"][i - 1] if i > 0 and np.isfinite(out_cols["ml_rsi"][i - 1]) else raw_ml_rsi
                alpha = 2.0 / (3.0 + 1.0)
                ml_rsi = alpha * raw_ml_rsi + (1.0 - alpha) * prev_ml

            flip_long = stance_state == 1 and prev_stance != 1
            flip_short = stance_state == -1 and prev_stance != -1
            qualifies = rank >= self.gate_rank and conf >= self.gate_conf
            cool_ok = last_entry_bar is None or i - last_entry_bar >= self.cool_bars
            trigger_long = flip_long and qualifies and cool_ok
            trigger_short = flip_short and qualifies and cool_ok
            if trigger_long or trigger_short:
                last_entry_bar = i

            out_cols["ml_rsi"][i] = ml_rsi
            out_cols["ml_rank"][i] = rank
            out_cols["ml_conf"][i] = conf
            out_cols["ml_bias"][i] = bias_dir
            out_cols["ml_st_dir"][i] = st_dir
            out_cols["ml_st_line"][i] = st_long if st_dir == 1 else st_short
            out_cols["ml_trigger_long"][i] = trigger_long
            out_cols["ml_trigger_short"][i] = trigger_short

        for col, values in out_cols.items():
            df[col] = values
        return df

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        prepared = self.prepare_indicators(data)
        entries = np.where(prepared["ml_trigger_long"], 1, np.where(prepared["ml_trigger_short"], -1, 0))
        entry = prepared["close"].astype(float)
        atr = prepared["atr14"].astype(float)

        stop = np.full(len(prepared), np.nan)
        take = np.full(len(prepared), np.nan)
        if self.stop_atr is not None and self.stop_atr > 0:
            stop = np.where(entries > 0, entry - self.stop_atr * atr, np.where(entries < 0, entry + self.stop_atr * atr, np.nan))
        if self.take_atr is not None and self.take_atr > 0:
            take = np.where(entries > 0, entry + self.take_atr * atr, np.where(entries < 0, entry - self.take_atr * atr, np.nan))

        comments = np.where(
            entries > 0,
            "ml_rsi_long",
            np.where(entries < 0, "ml_rsi_short", ""),
        )
        return pd.DataFrame(
            {
                "datetime": prepared["datetime"],
                "signal": entries,
                "entry_price": entry,
                "stop_price": stop,
                "take_price": take,
                "size": np.where(entries != 0, self.fixed_lot, np.nan),
                "comment": comments,
            }
        )


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _scale01(series: pd.Series, length: int) -> pd.Series:
    lo = series.rolling(length).min()
    hi = series.rolling(length).max()
    return ((series - lo) / (hi - lo).replace(0, np.nan)).fillna(0.5)


def _percent_rank(series: pd.Series, length: int) -> pd.Series:
    rolling = series.rolling(length, min_periods=1)
    if hasattr(rolling, "rank"):
        return rolling.rank(pct=True) * 100.0

    def rank_last(values: np.ndarray) -> float:
        last = values[-1]
        if not np.isfinite(last):
            return np.nan
        valid = values[np.isfinite(values)]
        if len(valid) == 0:
            return np.nan
        return 100.0 * np.sum(valid <= last) / len(valid)

    return series.rolling(length, min_periods=1).apply(rank_last, raw=True)


def _compress(value: float) -> float:
    return float(np.log1p(abs(value)))


def _classify_outcome(move: float, band: float) -> int:
    if not np.isfinite(move) or not np.isfinite(band):
        return 0
    if move > 2 * band:
        return 3
    if move > band:
        return 2
    if move > 0:
        return 1
    if move < -2 * band:
        return -3
    if move < -band:
        return -2
    if move < 0:
        return -1
    return 0


def _auto_feature_weights(bank: list[list[float]], min_rows: int, floor: float) -> np.ndarray:
    if len(bank) < min_rows:
        return np.ones(8, dtype=float)
    arr = np.asarray(bank, dtype=float)
    bull = arr[arr[:, 8] > 0, :8]
    bear = arr[arr[:, 8] < 0, :8]
    if len(bull) <= 2 or len(bear) <= 2:
        return np.ones(8, dtype=float)
    fish = (bull.mean(axis=0) - bear.mean(axis=0)) ** 2 / (bull.var(axis=0) + bear.var(axis=0) + 1e-6)
    max_f = float(np.nanmax(fish)) if np.isfinite(fish).any() else 0.0
    if max_f <= 0:
        return np.ones(8, dtype=float)
    return np.maximum(floor, (fish / max_f) * 10.0)


def _nearest_neighbors(
    cur: np.ndarray,
    bank: list[list[float]],
    weights: np.ndarray,
    k_max: int,
    spacing: int,
    memory_depth: int,
) -> list[_Neighbor]:
    if not np.isfinite(cur).all() or not bank:
        return []
    scan_end = min(memory_depth - 1, len(bank) - 1)
    rows = np.asarray(bank[: scan_end + 1 : spacing], dtype=float)
    if rows.size == 0:
        return []
    gaps = np.sum(weights * np.log1p(np.abs(rows[:, :8] - cur)), axis=1)
    valid = np.isfinite(gaps)
    if not valid.any():
        return []
    rows = rows[valid]
    gaps = gaps[valid]
    take = min(k_max, len(gaps))
    best_idx = np.argpartition(gaps, take - 1)[:take]
    return [_Neighbor(gap=float(gaps[j]), cls=int(rows[j, 8])) for j in best_idx]


def _vote(neighbors: list[_Neighbor], weights: np.ndarray) -> tuple[float, float, float, int]:
    total = bull = bear = score = gap_sum = 0.0
    for n in neighbors:
        vote_weight = 1.0 / (1.0 + n.gap)
        total += vote_weight
        score += n.cls * vote_weight
        gap_sum += n.gap
        if n.cls > 0:
            bull += vote_weight
        elif n.cls < 0:
            bear += vote_weight
    analog_score = score / total if total > 0 else 0.0
    bias_dir = 1 if analog_score > 0.15 else -1 if analog_score < -0.15 else 0
    agree_frac = ((bull if bias_dir == 1 else bear) / total) if total > 0 and bias_dir != 0 else 0.0
    avg_gap = gap_sum / len(neighbors) if neighbors else 0.0
    gap_scale = float(np.sum(weights)) * 0.45 + 1e-9
    gap_tight = max(0.0, min(1.0, 1.0 - avg_gap / gap_scale))
    return analog_score, agree_frac, gap_tight, len(neighbors)


def _rank_score(
    bias_dir: int,
    agree_frac: float,
    gap_tight: float,
    slope_fit: bool,
    stretched: bool,
    aligned: bool,
    vol_healthy: bool,
    atr_pct: float,
    osc_reg: float,
    osc_smooth_up: bool,
    chop_raw: bool,
    age: int,
    flip: bool,
    k_count: int,
    k_neighbors: int,
    vol_band_lo: int,
) -> float:
    if bias_dir == 0:
        return 0.0
    p_agree = 25.0 * agree_frac
    p_gap = 15.0 * gap_tight
    p_struct = (10.0 if slope_fit else 0.0) + (0.0 if stretched else 5.0)
    p_trend = 10.0 if aligned else 0.0
    p_vol = 10.0 if vol_healthy else 5.0 if atr_pct < vol_band_lo else 3.0
    reg_fit = (bias_dir == 1 and osc_reg > 55) or (bias_dir == -1 and osc_reg < 45)
    p_reg = 10.0 if reg_fit else 4.0 if 45 <= osc_reg <= 55 else 6.0
    p_smooth = 5.0 if (bias_dir == 1 and osc_smooth_up) or (bias_dir == -1 and not osc_smooth_up) else 0.0
    p_hold = min(5.0, float(age))
    p_pen = min(
        20.0,
        (8.0 if chop_raw else 0.0)
        + (6.0 if stretched else 0.0)
        + (6.0 if flip else 0.0)
        + (5.0 * (k_neighbors - k_count) / k_neighbors if k_count < k_neighbors else 0.0),
    )
    return max(0.0, min(100.0, p_agree + p_gap + p_struct + p_trend + p_vol + p_reg + p_smooth + p_hold - p_pen))


def _conf_score(
    bias_dir: int,
    agree_frac: float,
    gap_tight: float,
    slope_fit: bool,
    age: int,
    flip: bool,
    k_count: int,
    k_neighbors: int,
) -> float:
    if bias_dir == 0:
        return 0.0
    raw = (
        40.0 * agree_frac
        + 25.0 * gap_tight
        + 15.0 * min(1.0, age / 5.0)
        + 10.0 * (1.0 if slope_fit else 0.0)
        - (15.0 if flip else 0.0)
        - (10.0 * (k_neighbors - k_count) / k_neighbors if k_count < k_neighbors else 0.0)
    )
    return max(0.0, min(100.0, raw))


def _ema_next(prev: float, value: float, period: int) -> float:
    if not np.isfinite(value):
        return prev
    if not np.isfinite(prev):
        return float(value)
    alpha = 2.0 / (period + 1.0)
    return float(alpha * value + (1.0 - alpha) * prev)


def _rolling_value(series: pd.Series, idx: int) -> float:
    return float(series.iloc[idx]) if idx < len(series) else np.nan
