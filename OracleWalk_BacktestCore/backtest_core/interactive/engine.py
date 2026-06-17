"""Pausable, step-by-step backtester for the interactive replay track.

Inherits from the classic ``Backtester`` and **reuses** all of its execution
helpers (fill, SL/TP, trailing, slippage, commission, swap, finalize). The only
thing rewritten is the *cadence*: instead of one tight loop over precomputed
signals, it advances one bar at a time and asks the strategy for an intent on
each bar, consulting the causal ``ZoneStore`` for the zones visible right now.

The classic ``core/engine.py`` is not modified.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from ..core.engine import Backtester
from ..data import resample_ohlcv
from .strategy_base import BarContext, InteractiveStrategyBase
from .zones import ZoneStore


_SIGNAL_PAYLOAD = ("entry_price", "stop_price", "take_price", "size", "risk", "trailing_distance", "comment")


class InteractiveBacktester(Backtester):
    def __init__(
        self,
        data: pd.DataFrame,
        strategy: InteractiveStrategyBase,
        config: dict[str, Any] | None = None,
        base_timeframe: str = "",
        higher_timeframes: dict[str, str] | None = None,
        timeframe_data: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        prepared = strategy.prepare_indicators(data)
        super().__init__(prepared, config)
        self.strategy = strategy
        # Rows as namedtuples — exactly what the classic loop feeds its helpers.
        self._rows = list(self.data.itertuples(index=False))
        self.n = len(self._rows)

        # Multi-timeframe: derive higher TFs (e.g. H4 from an H1 base) and map
        # each base bar to the last *closed* higher-TF bar, so a zone can be
        # evaluated on its own timeframe without any lookahead.
        self.base_tf = str(base_timeframe or "").upper()
        self._higher = self._build_higher_tfs(data, higher_timeframes or {})
        self._higher.update(self._build_external_tfs(data, timeframe_data or {}))

        self.capital = float(self.config.initial_capital)
        self.open_trades: list[dict[str, Any]] = []
        self.closed_trades: list[dict[str, Any]] = []
        self._trade_id = 0
        self.warmup = max(int(getattr(strategy, "warmup_bars", 1)), 1)
        self.warmup = max(self.warmup, self._mtf_warmup_bars())
        self.cursor = -1
        self.finished = False
        # Trades closed on the previous bar — handed to the strategy on the next
        # bar so it can react (e.g. cooldown after a stop loss).
        self._last_closed: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ API
    def start(self) -> int:
        """Position the cursor at the end of warmup. History 0..cursor is context."""
        self.reset()
        return self.cursor

    def reset(self) -> int:
        """Reset replay state while keeping prepared data/indicators intact."""
        if hasattr(self.strategy, "reset_state"):
            self.strategy.reset_state()
        self.capital = float(self.config.initial_capital)
        self.open_trades = []
        self.closed_trades = []
        self._trade_id = 0
        self.cursor = min(self.warmup - 1, self.n - 1) if self.n else -1
        self.finished = False
        self._last_closed = []
        # Running peak of equity — the basis for the live drawdown HUD.
        self.peak_equity = self.capital
        return self.cursor

    def step_one(self, zone_store: ZoneStore) -> tuple[bool, list[dict[str, Any]]]:
        """Advance exactly one bar. Returns (advanced, trades_closed_this_bar)."""
        if self.cursor >= self.n - 1:
            self.finished = True
            return False, []
        self.cursor += 1
        closed_now = self._process_bar(self.cursor, zone_store)
        # Hand this bar's closes to the strategy on the *next* bar.
        self._last_closed = closed_now
        self.peak_equity = max(self.peak_equity, self.equity())
        if self.cursor >= self.n - 1:
            self.finished = True
        return True, closed_now

    def finish(self) -> pd.DataFrame:
        """Close anything still open at the current bar and finalize the trades."""
        if self.open_trades and self.cursor >= 0:
            row = self._rows[self.cursor]
            spread_price = self._row_spread_price(row)
            for trade in self.open_trades:
                self._close_trade(trade, float(row.close), row.datetime, self.cursor, "eod", spread_price, row)
                self.closed_trades.append(trade)
                self.capital += float(trade["pnl"])
            self.open_trades = []
        return self._finalize_trades(self.closed_trades)

    # -------------------------------------------------------------- internals
    def _process_bar(self, bar_index: int, zone_store: ZoneStore) -> list[dict[str, Any]]:
        row = self._rows[bar_index]
        dt = row.datetime
        high = float(row.high)
        low = float(row.low)
        close = float(row.close)
        volume = float(row.volume)
        spread_price = self._row_spread_price(row)
        can_execute = self._can_execute(dt)

        intent = self.strategy.on_bar(self._make_context(bar_index, zone_store))
        sigv = int(intent.signal) if intent is not None else 0
        sig_row = self._make_sig_row(row, intent)

        closed_now: list[dict[str, Any]] = []
        open_pnl = sum(self._unrealized_pnl(t, close, spread_price) for t in self.open_trades)
        used_margin = sum(float(t.get("margin_required", 0.0)) for t in self.open_trades)
        equity_now = self.capital + open_pnl
        margin_level_pct = (equity_now / used_margin * 100.0) if used_margin > 0 else np.inf

        still_open = []
        for trade in self.open_trades:
            self._update_excursions(trade, high, low, spread_price)
            self._update_trailing_stop(trade, close)

            exit_price, exit_reason = self._check_stop_take(trade, high, low, spread_price) if can_execute else (None, None)
            if (
                exit_reason is None
                and can_execute
                and self.config.stop_out_level_pct is not None
                and used_margin > 0
                and margin_level_pct <= self.config.stop_out_level_pct
            ):
                exit_price, exit_reason = close, "stop_out"
            if exit_reason is None and can_execute and self._should_close_on_signal(trade, sigv):
                exit_price, exit_reason = close, "signal"

            if exit_reason is None:
                still_open.append(trade)
                continue

            self._close_trade(trade, exit_price, dt, bar_index, exit_reason, spread_price, row)
            closed_now.append(trade)
            self.closed_trades.append(trade)
            self.capital += float(trade["pnl"])

        self.open_trades = still_open

        if sigv == 0 or not can_execute:
            return closed_now
        if self.config.single_position_mode and self.open_trades:
            return closed_now

        open_pnl = sum(self._unrealized_pnl(t, close, spread_price) for t in self.open_trades)
        used_margin = sum(float(t.get("margin_required", 0.0)) for t in self.open_trades)
        free_margin = self.capital + open_pnl - used_margin

        entry_sig = getattr(sig_row, "entry_price", np.nan)
        entry_price = float(entry_sig) if not pd.isna(entry_sig) else close
        if not pd.isna(entry_sig) and not self._entry_price_touched(sig_row, entry_price):
            return closed_now

        trade = self._open_trade_from_row(
            trade_id=self._trade_id,
            dt=dt,
            price=entry_price,
            volume=volume,
            spread_price=spread_price,
            bar_index=bar_index,
            sig_row=sig_row,
            has_stop=True,
            has_take=True,
            has_size=True,
            has_risk=True,
            has_trail=True,
            capital_now=self.capital,
            free_margin=free_margin,
        )
        if trade is not None:
            # Carry the strategy's comment (e.g. "BUY|SEM") onto the trade so it
            # can be inspected later (open_trades view, AMBOS-mode dedupe).
            if intent is not None and intent.comment:
                trade["comment"] = intent.comment
            # Carry the triggering zone's identity (per-zone edge analytics).
            if intent is not None:
                if intent.zone_id is not None:
                    trade["zone_id"] = intent.zone_id
                if intent.zone_tf:
                    trade["zone_tf"] = intent.zone_tf
                if intent.zone_side:
                    trade["zone_side"] = intent.zone_side
            self.open_trades.append(trade)
            self._trade_id += 1
        return closed_now

    def _make_context(self, bar_index: int, zone_store: ZoneStore) -> BarContext:
        row = self._rows[bar_index]
        window = self.data.iloc[: bar_index + 1]
        return BarContext(
            bar_index=bar_index,
            bar=row,
            window=window,
            zones=zone_store.active_zones(bar_index),
            open_trades=self.open_trades,
            indicators=self.indicators_at(bar_index),
            recent_closed=self._last_closed,
            tf_indicators=self.tf_indicators_at(bar_index),
            tf_series_tail=self.tf_series_tail(bar_index),
        )

    # --------------------------------------------------------- multi-timeframe
    def _build_higher_tfs(self, base_data: pd.DataFrame, higher: dict[str, str]) -> dict[str, dict]:
        if not higher:
            return {}
        out: dict[str, dict] = {}
        for name, rule in higher.items():
            resampled = self.strategy.prepare_indicators(resample_ohlcv(base_data, rule))
            out[name.upper()] = self._frame_for_tf(base_data, resampled)
        return out

    def _build_external_tfs(self, base_data: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for name, data in frames.items():
            tf = str(name or "").upper()
            if not tf or tf == self.base_tf or data is None or data.empty:
                continue
            prepared = self.strategy.prepare_indicators(data)
            out[tf] = self._frame_for_tf(base_data, prepared)
        return out

    def _frame_for_tf(self, base_data: pd.DataFrame, tf_data: pd.DataFrame) -> dict[str, Any]:
        base_secs = pd.to_datetime(base_data["datetime"]).astype("int64").to_numpy() // 10**9
        base_dur = int(np.median(np.diff(base_secs))) if len(base_secs) > 1 else 0
        base_close = base_secs + base_dur

        tf_secs = pd.to_datetime(tf_data["datetime"]).astype("int64").to_numpy() // 10**9
        tf_dur = int(np.median(np.diff(tf_secs))) if len(tf_secs) > 1 else base_dur
        tf_close = tf_secs + tf_dur
        # Last bar of that timeframe fully closed by each base bar's close time.
        mapping = np.searchsorted(tf_close, base_close, side="right") - 1
        # A TF is "coarser" when its bars last longer than the base's. Only coarser
        # TFs gate the warmup (they need more base bars to form); finer TFs are
        # always available early and must NOT drag the replay's start forward —
        # especially finer CSVs whose history begins much later than the base's.
        return {"rows": list(tf_data.itertuples(index=False)), "map": mapping, "coarser": tf_dur > base_dur}

    def _mtf_warmup_bars(self) -> int:
        cols = list(getattr(self.strategy, "indicator_columns", []) or [])
        if not cols or not self._higher:
            return 1
        min_base_idx = 0
        for frame in self._higher.values():
            # Only coarser TFs need extra base bars to warm up. Finer TFs (which
            # may start much later in history) must not push the replay start.
            if not frame.get("coarser", True):
                continue
            first_valid = self._first_valid_indicator_row(frame["rows"], cols)
            if first_valid is None:
                continue
            mapping = frame["map"]
            hits = np.flatnonzero(mapping >= first_valid)
            if len(hits) == 0:
                continue
            min_base_idx = max(min_base_idx, int(hits[0]))
        return min_base_idx + 1

    @staticmethod
    def _first_valid_indicator_row(rows, cols) -> int | None:
        for idx, row in enumerate(rows):
            ok = True
            for col in cols:
                value = getattr(row, col, None)
                if value is None or pd.isna(value):
                    ok = False
                    break
            if ok:
                return idx
        return None

    def tf_indicators_at(self, idx: int) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        if self.base_tf:
            result[self.base_tf] = self.indicators_at(idx)
        for name, frame in self._higher.items():
            mapping = frame["map"]
            j = int(mapping[idx]) if 0 <= idx < len(mapping) else -1
            result[name] = self._indicators_from_row(frame["rows"][j]) if j >= 0 else {}
        return result

    def tf_series_tail(self, idx: int, cols=("close", "sma60"), k: int = 2) -> dict[str, dict[str, list]]:
        """Last `k` closed bars of `cols` per timeframe (for the SMA-cross trigger)."""
        result: dict[str, dict[str, list]] = {}
        if self.base_tf:
            result[self.base_tf] = self._tail_from_rows(self._rows, idx, cols, k)
        for name, frame in self._higher.items():
            mapping = frame["map"]
            j = int(mapping[idx]) if 0 <= idx < len(mapping) else -1
            result[name] = self._tail_from_rows(frame["rows"], j, cols, k) if j >= 0 else {}
        return result

    def _tail_from_rows(self, rows, end_idx: int, cols, k: int) -> dict[str, list]:
        out: dict[str, list] = {c: [] for c in cols}
        if end_idx < 0:
            return out
        for i in range(max(0, end_idx - k + 1), end_idx + 1):
            r = rows[i]
            for c in cols:
                v = getattr(r, c, None)
                out[c].append(float(v) if v is not None and not pd.isna(v) else None)
        return out

    def _make_sig_row(self, row, intent) -> SimpleNamespace:
        data = dict(row._asdict())
        if intent is not None:
            data["signal"] = int(intent.signal)
            for field in _SIGNAL_PAYLOAD:
                value = getattr(intent, field, None)
                if value is not None:
                    data[field] = value
        else:
            data["signal"] = 0
        return SimpleNamespace(**data)

    # ----------------------------------------------------------- serializers
    @staticmethod
    def _ts(dt) -> int:
        return int(pd.Timestamp(dt).timestamp())

    def bar_dict(self, idx: int) -> dict[str, Any]:
        r = self._rows[idx]
        return {
            "time": self._ts(r.datetime),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }

    def series_at(self, idx: int, tf: str | None = None) -> dict[str, list]:
        """OHLCV + indicator arrays up to bar `idx` for timeframe `tf`.

        Powers the chart's indicator sub-panes (RSI/Stoch/UO), the SMA overlay,
        and lets the UI switch the candle display to a higher TF (e.g. show H4
        candles) — all causally truncated at the current cursor.
        """
        tf = (tf or self.base_tf or "").upper()
        cols = list(getattr(self.strategy, "indicator_columns", []) or [])
        if not tf or tf == self.base_tf:
            rows, end = self._rows, idx
        elif tf in self._higher:
            mapping = self._higher[tf]["map"]
            rows = self._higher[tf]["rows"]
            end = int(mapping[idx]) if 0 <= idx < len(mapping) else -1
        else:
            return {"time": [], "open": [], "high": [], "low": [], "close": [], "volume": [], **{c: [] for c in cols}}

        out: dict[str, list] = {k: [] for k in ("time", "open", "high", "low", "close", "volume")}
        for c in cols:
            out[c] = []
        for i in range(0, end + 1):
            r = rows[i]
            out["time"].append(self._ts(r.datetime))
            out["open"].append(float(r.open))
            out["high"].append(float(r.high))
            out["low"].append(float(r.low))
            out["close"].append(float(r.close))
            out["volume"].append(float(r.volume))
            for c in cols:
                v = getattr(r, c, None)
                out[c].append(None if v is None or pd.isna(v) else float(v))
        return out

    def indicators_at(self, idx: int) -> dict[str, float]:
        return self._indicators_from_row(self._rows[idx])

    def _indicators_from_row(self, r) -> dict[str, float]:
        out: dict[str, float] = {}
        for col in getattr(self.strategy, "indicator_columns", []) or []:
            if hasattr(r, col):
                value = getattr(r, col)
                if value is not None and not pd.isna(value):
                    out[col] = float(value)
        return out

    def equity(self) -> float:
        if self.cursor < 0:
            return self.capital
        r = self._rows[self.cursor]
        close = float(r.close)
        spread_price = self._row_spread_price(r)
        open_pnl = sum(self._unrealized_pnl(t, close, spread_price) for t in self.open_trades)
        return self.capital + open_pnl

    def equity_point(self) -> dict[str, Any]:
        """One (bar, time, equity, balance) sample for the live equity sparkline."""
        if self.cursor < 0:
            return {"bar": self.cursor, "time": None, "equity": self.capital, "balance": self.capital}
        r = self._rows[self.cursor]
        return {"bar": self.cursor, "time": self._ts(r.datetime), "equity": self.equity(), "balance": self.capital}

    def hud(self) -> dict[str, Any]:
        """Instantaneous risk/performance state up to the cursor (live HUD)."""
        equity = self.equity()
        peak = max(getattr(self, "peak_equity", self.capital), equity)
        dd_pct = ((equity - peak) / peak * 100.0) if peak > 0 else 0.0
        open_risk = sum(float(t["risk"]) for t in self.open_trades if t.get("risk") is not None)
        realized = sum(float(t.get("pnl", 0.0)) for t in self.closed_trades)
        n_closed = len(self.closed_trades)
        wins = sum(1 for t in self.closed_trades if float(t.get("pnl", 0.0)) > 0)
        return {
            "peak_equity": peak,
            "drawdown_pct": dd_pct,
            "open_risk": open_risk,
            "open_risk_pct": (open_risk / equity * 100.0) if equity > 0 else 0.0,
            "realized_pnl": realized,
            "trades_closed": n_closed,
            "win_rate_so_far": (wins / n_closed * 100.0) if n_closed else 0.0,
            "current_streak": self._current_streak(),
        }

    def _current_streak(self) -> int:
        """Signed streak from the most recent closes: +N wins / -N losses."""
        streak = 0
        for t in reversed(self.closed_trades):
            pnl = float(t.get("pnl", 0.0))
            if pnl > 0:
                if streak < 0:
                    break
                streak += 1
            elif pnl < 0:
                if streak > 0:
                    break
                streak -= 1
            else:
                break
        return streak

    def open_trades_public(self) -> list[dict[str, Any]]:
        if self.cursor < 0:
            return []
        r = self._rows[self.cursor]
        close = float(r.close)
        spread_price = self._row_spread_price(r)
        out = []
        for t in self.open_trades:
            out.append(
                {
                    "id": t["id"],
                    "direction": t["direction"],
                    "entry_time": self._ts(t["entry_time"]),
                    "entry_price": t["entry_price"],
                    "stop_price": t.get("stop_price"),
                    "take_price": t.get("take_price"),
                    "size": t["size"],
                    "comment": t.get("comment", ""),
                    "unrealized_pnl": self._unrealized_pnl(t, close, spread_price),
                }
            )
        return out

    def trade_public(self, t: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": t["id"],
            "direction": t["direction"],
            "entry_price": t["entry_price"],
            "exit_price": t.get("exit_price"),
            "exit_reason": t.get("exit_reason"),
            "pnl": t.get("pnl"),
            "entry_time": self._ts(t["entry_time"]),
            "exit_time": self._ts(t["exit_time"]) if t.get("exit_time") is not None else None,
        }
