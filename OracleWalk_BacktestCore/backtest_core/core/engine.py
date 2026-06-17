from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BacktestConfig:
    initial_capital: float = 1000.0
    risk_per_trade_pct: float = 1.0
    # Lot size used when %-risk sizing is off (risk_per_trade_pct <= 0) and the signal
    # carries no explicit size — i.e. the fixed-lot audit lot.
    fixed_lot: float = 1.0
    commission_perc: float = 0.0
    commission_per_lot: float = 0.0
    slippage: float = 0.0
    single_position_mode: bool = True
    close_on_signal: str = "opposite"  # "opposite", "any", or "never"
    contract_size: float = 1.0
    point: float = 0.00001
    spread_column: str = "spread"
    fixed_spread_points: float | None = None
    use_spread: bool = True
    swap_long_per_lot: float = 0.0
    swap_short_per_lot: float = 0.0
    triple_swap_weekday: int | None = 2
    leverage: float = 1.0
    margin_rate: float | None = None
    stop_out_level_pct: float | None = None
    execution_model: str = "realistic"  # "realistic" or "idealized"
    execution_mode: str = "candle"  # "candle" or "tick"
    entry_timing: str = "next_bar_open"  # "signal_close" or "next_bar_open"
    # Intrabar SL/TP ambiguity (candle mode, when BOTH levels sit inside one bar and
    # there are no ticks to disambiguate):
    #   "conservative"  -> stop first (pessimistic, the safe default)
    #   "optimistic"    -> take first
    #   "mt5_like_ohlc" -> assume MT5's OHLC walk: bull candle O->L->H->C, bear
    #                      candle O->H->L->C, and hit whichever level lies on the
    #                      first-visited extreme. Ignored in tick mode (real ticks
    #                      already resolve the order).
    intrabar_mode: str = "conservative"
    session_calendar: Any | None = None
    session_policy: str = "ignore"  # "ignore", "skip", or "push"
    require_entry_touch: bool = False
    execution_latency_bars: int = 0
    slippage_spread_mult: float = 0.0
    slippage_atr_mult: float = 0.0
    slippage_atr_column: str = "atr"
    # Early-stop when the account is ruined: if realized balance OR equity (balance +
    # open P&L) reaches <= 0, there is no capital left to trade, so the backtest ends
    # right there instead of scanning the rest of the history. Honest and fast — a
    # losing strategy blows up early and stops.
    stop_on_ruin: bool = True
    # A resting order is a resting order: a signal carrying order_type 'limit'/'stop'
    # is placed in a carried pending-order book and filled on the later bar (candle
    # mode) or tick (tick mode) that crosses its trigger, subject to an optional
    # per-order expiry (`expiry_bars`) and price gate (`gate_column`/`gate_side`).
    # This is the correct, generic behaviour and is ON by default — the STRATEGY
    # decides market vs limit vs stop via the signal; the engine just executes it
    # causally. Set False only to force the legacy same-bar limit fill (research).
    pending_order_book: bool = True
    # Order-validity at placement, mirroring MT5: a pending order placed on the WRONG
    # side of the market is rejected (not booked), so the backtest cannot report a
    # "phantom" trade that a live broker would never have accepted. The wrong side is:
    #   buy limit  >= ask   |  buy stop  <= ask
    #   sell limit <= bid   |  sell stop >= bid
    # ON by default (fidelity). Set False for the legacy behaviour that books any
    # resting order regardless of side.
    reject_invalid_pending: bool = True


class Backtester:
    """
    Universal candle-by-candle backtester.

    DataFrame contract:
      data: datetime, open, high, low, close, volume
      signals: datetime, signal

    Optional data columns:
      spread

    Optional signal columns:
      order_type, entry_price, stop_price, take_price, size, risk, trailing_distance

    signal: 1 for long, -1 for short, 0 for no action.
    """

    REQUIRED_DATA_COLUMNS = ("datetime", "open", "high", "low", "close", "volume")

    def __init__(self, data: pd.DataFrame, config: dict[str, Any] | None = None):
        raw_config = config or {}
        allowed = {field.name for field in fields(BacktestConfig)}
        self.config = BacktestConfig(**{k: v for k, v in raw_config.items() if k in allowed})
        self._validate_config()
        self.data = self._prepare_data(data)
        # Per-bar equity track (datetime, equity, equity_low) populated by run();
        # consumed by prop-firm / drawdown analysis. Empty until a candle run.
        self.equity_curve = pd.DataFrame(columns=["datetime", "equity", "equity_low"])

    def _validate_config(self) -> None:
        if self.config.execution_model not in {"realistic", "idealized"}:
            raise ValueError("execution_model must be 'realistic' or 'idealized'")
        if self.config.execution_mode not in {"candle", "tick"}:
            raise ValueError("execution_mode must be 'candle' or 'tick'")
        if self.config.entry_timing not in {"signal_close", "next_bar_open"}:
            raise ValueError("entry_timing must be 'signal_close' or 'next_bar_open'")
        if self.config.intrabar_mode not in {"conservative", "optimistic", "mt5_like_ohlc"}:
            raise ValueError("intrabar_mode must be 'conservative', 'optimistic', or 'mt5_like_ohlc'")

    def run(self, signals: pd.DataFrame, ticks: pd.DataFrame | None = None, tick_loader=None) -> pd.DataFrame:
        """Run the backtest.

        ``ticks``: a full tick DataFrame held in memory (fine for bounded windows).
        ``tick_loader``: a callable ``(start, end) -> DataFrame`` used to stream ticks
        one calendar month at a time so the full history runs in bounded memory
        (~one month of ticks) — results are identical to passing all ticks at once.
        """
        if self.config.execution_mode == "tick" and (
            tick_loader is not None or (ticks is not None and not ticks.empty)
        ):
            return self._run_tick(signals, ticks=ticks, tick_loader=tick_loader)
        return self._run_candle(signals)

    def _run_candle(self, signals: pd.DataFrame) -> pd.DataFrame:
        if signals is None or signals.empty:
            return pd.DataFrame()

        sig = signals.copy()
        if "datetime" not in sig.columns or "signal" not in sig.columns:
            raise ValueError("signals must contain 'datetime' and 'signal' columns")

        sig["datetime"] = pd.to_datetime(sig["datetime"])
        sig = sig.sort_values("datetime").reset_index(drop=True)

        data = pd.merge(
            self.data,
            sig,
            on="datetime",
            how="left",
            suffixes=("", "_sig"),
        )
        data["signal"] = data["signal"].fillna(0).astype(int)
        data = self._apply_entry_timing(data)
        data = self._apply_execution_latency(data)
        data = self._apply_session_policy(data)

        has_stop = "stop_price" in data.columns
        has_take = "take_price" in data.columns
        has_size = "size" in data.columns
        has_risk = "risk" in data.columns
        has_trail = "trailing_distance" in data.columns
        has_entry = "entry_price" in data.columns

        gate_arrays = self._collect_gate_arrays(data)

        capital = self.config.initial_capital
        open_trades: list[dict[str, Any]] = []
        closed_trades: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        trade_id = 0
        equity_track: list[tuple] = []

        for bar_index, row in enumerate(data.itertuples(index=False)):
            dt = row.datetime
            open_ = float(row.open)
            high = float(row.high)
            low = float(row.low)
            close = float(row.close)
            volume = float(row.volume)
            spread_price = self._row_spread_price(row)
            sigv = int(row.signal)
            can_execute = self._can_execute(dt)

            open_pnl = sum(self._unrealized_pnl(trade, close, spread_price) for trade in open_trades)
            used_margin = sum(float(trade.get("margin_required", 0.0)) for trade in open_trades)
            equity_now = capital + open_pnl
            margin_level_pct = (equity_now / used_margin * 100.0) if used_margin > 0 else np.inf

            # Per-bar equity track for prop-firm / drawdown analysis. equity_low uses
            # each open trade's ADVERSE intrabar extreme (low for longs, high for
            # shorts) so the daily-loss rule sees the true intrabar dip, not just the
            # bar close. Cheap: only sums over currently-open trades.
            if open_trades:
                eq_low = capital + sum(
                    self._unrealized_pnl(t, low if t["direction"] == "long" else high, spread_price)
                    for t in open_trades
                )
            else:
                eq_low = equity_now
            equity_track.append((dt, equity_now, eq_low))

            still_open = []
            for trade in open_trades:
                self._update_excursions(trade, high, low, spread_price)
                self._update_trailing_stop(trade, close)

                exit_price, exit_reason = self._check_stop_take(trade, high, low, spread_price, open_, close) if can_execute else (None, None)
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
                closed_trades.append(trade)
                capital += float(trade["pnl"])

            open_trades = still_open

            # Wrong-side rejection: validate just-activated resting orders against this
            # bar's open (the placement reference in candle mode) before they can fill.
            if pending:
                pending = self._validate_pending_side(pending, bar_index, open_, open_ + spread_price)

            # Carried pending-order fills run BEFORE this bar's new signal so an order
            # placed on this bar cannot fill on its own bar (causal).
            if pending:
                capital, open_trades, pending, trade_id = self._fill_pending_candle(
                    row=row,
                    bar_index=bar_index,
                    pending=pending,
                    open_trades=open_trades,
                    closed_trades=closed_trades,
                    capital=capital,
                    trade_id=trade_id,
                    gate_arrays=gate_arrays,
                    can_execute=can_execute,
                    has_stop=has_stop,
                    has_take=has_take,
                    has_size=has_size,
                    has_risk=has_risk,
                    has_trail=has_trail,
                )

            if sigv == 0 or not can_execute:
                continue

            # Place a carried pending order (limit/stop). This is an execution
            # mechanism: the order is held and filled on a later bar that crosses it.
            if self.config.pending_order_book and self._order_type(row) in {"limit", "stop"}:
                order = self._make_pending(row, bar_index, gate_arrays)
                if order is not None:
                    pending.append(order)
                continue

            if self.config.single_position_mode and open_trades:
                continue

            open_pnl = sum(self._unrealized_pnl(trade, close, spread_price) for trade in open_trades)
            used_margin = sum(float(trade.get("margin_required", 0.0)) for trade in open_trades)
            free_margin = capital + open_pnl - used_margin

            market_entry_price = open_ if self.config.entry_timing == "next_bar_open" else close
            entry_price = self._resolve_entry_price(row, sigv, market_entry_price, has_entry)
            if entry_price is None:
                continue

            trade = self._open_trade_from_row(
                trade_id=trade_id,
                dt=dt,
                price=entry_price,
                volume=volume,
                spread_price=spread_price,
                bar_index=bar_index,
                sig_row=row,
                has_stop=has_stop,
                has_take=has_take,
                has_size=has_size,
                has_risk=has_risk,
                has_trail=has_trail,
                capital_now=capital,
                free_margin=free_margin,
            )
            if trade is not None:
                open_trades.append(trade)
                trade_id += 1

            # Account ruin: balance or equity wiped out -> stop the backtest.
            if self.config.stop_on_ruin:
                equity = capital + sum(self._unrealized_pnl(t, close, spread_price) for t in open_trades)
                if capital <= 0.0 or equity <= 0.0:
                    for trade in open_trades:
                        self._close_trade(trade, close, dt, bar_index, "ruin", spread_price, row)
                        closed_trades.append(trade)
                        capital += float(trade["pnl"])
                    open_trades = []
                    break

        if open_trades:
            last = data.iloc[-1]
            last_spread = self._row_spread_price(last)
            for trade in open_trades:
                self._close_trade(
                    trade,
                    float(last["close"]),
                    last["datetime"],
                    len(data) - 1,
                    "eod",
                    last_spread,
                    last,
                )
                closed_trades.append(trade)
                capital += float(trade["pnl"])

        self.equity_curve = pd.DataFrame(equity_track, columns=["datetime", "equity", "equity_low"])
        return self._finalize_trades(closed_trades)

    def _run_tick(self, signals: pd.DataFrame, ticks: pd.DataFrame | None = None, tick_loader=None) -> pd.DataFrame:
        if signals is None or signals.empty:
            return pd.DataFrame()

        sig = signals.copy()
        if "datetime" not in sig.columns or "signal" not in sig.columns:
            raise ValueError("signals must contain 'datetime' and 'signal' columns")

        sig["datetime"] = pd.to_datetime(sig["datetime"])
        sig = sig.sort_values("datetime").reset_index(drop=True)
        data = pd.merge(
            self.data,
            sig,
            on="datetime",
            how="left",
            suffixes=("", "_sig"),
        )
        data["signal"] = data["signal"].fillna(0).astype(int)
        data = self._apply_entry_timing(data)
        data = self._apply_execution_latency(data)
        data = self._apply_session_policy(data)

        gate_arrays = self._collect_gate_arrays(data)

        # Tick source. Streaming mode (tick_loader) loads ONE calendar month of ticks
        # at a time and rebuilds the per-bar index for that month only, so memory stays
        # bounded over the full history. All trade state (capital, open positions,
        # pending orders) lives in the loop and carries across months untouched, so the
        # streamed result is identical to holding every tick in memory.
        stream = tick_loader is not None
        if not stream:
            ticks_by_bar = self._ticks_by_bar(data, self._prepare_ticks(ticks))
        else:
            ticks_by_bar = {}
        current_chunk = None

        has_stop = "stop_price" in data.columns
        has_take = "take_price" in data.columns
        has_size = "size" in data.columns
        has_risk = "risk" in data.columns
        has_trail = "trailing_distance" in data.columns
        has_entry = "entry_price" in data.columns

        capital = self.config.initial_capital
        open_trades: list[dict[str, Any]] = []
        closed_trades: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        trade_id = 0

        for bar_index, row in enumerate(data.itertuples(index=False)):
            dt = row.datetime
            close = float(row.close)
            volume = float(row.volume)
            spread_price = self._row_spread_price(row)

            # Streaming: when this bar enters a new calendar month, load that month's
            # ticks and rebuild the per-bar index (global bar indices) for it only.
            if stream:
                chunk_key = (dt.year, dt.month)
                if chunk_key != current_chunk:
                    current_chunk = chunk_key
                    c_start = pd.Timestamp(year=dt.year, month=dt.month, day=1)
                    c_end = c_start + pd.offsets.MonthBegin(1) - pd.Timedelta(nanoseconds=1)
                    chunk_ticks = tick_loader(c_start, c_end)
                    if chunk_ticks is not None and len(chunk_ticks):
                        ticks_by_bar = self._ticks_by_bar(data, self._prepare_ticks(chunk_ticks))
                    else:
                        ticks_by_bar = {}
            sigv = int(row.signal)
            is_pending = (
                self.config.pending_order_book
                and sigv != 0
                and self._order_type(row) in {"limit", "stop"}
            )

            bar_ticks = ticks_by_bar.get(bar_index)
            # Wrong-side rejection: validate just-activated resting orders against this
            # bar's first tick (the EA's placement moment) before anything can fill.
            if pending and bar_ticks is not None and not bar_ticks.empty:
                _ft = bar_ticks.iloc[0]
                pending = self._validate_pending_side(pending, bar_index, _ft["bid"], _ft["ask"])
            if (not is_pending) and self.config.entry_timing == "next_bar_open" and sigv != 0:
                signal_time = dt
                signal_price = float(row.open)
                signal_spread = spread_price
                if bar_ticks is not None and not bar_ticks.empty:
                    first_tick = bar_ticks.iloc[0]
                    signal_time = first_tick["datetime"]
                    signal_price = float(first_tick["bid"])
                    signal_spread = max(float(first_tick["ask"]) - float(first_tick["bid"]), 0.0)
                capital, open_trades, trade_id = self._apply_bar_signal(
                    row=row,
                    sigv=sigv,
                    dt=signal_time,
                    price=signal_price,
                    volume=volume,
                    spread_price=signal_spread,
                    bar_index=bar_index,
                    capital=capital,
                    open_trades=open_trades,
                    closed_trades=closed_trades,
                    trade_id=trade_id,
                    has_stop=has_stop,
                    has_take=has_take,
                    has_size=has_size,
                    has_risk=has_risk,
                    has_trail=has_trail,
                    has_entry=has_entry,
                )

            if bar_ticks is not None and not bar_ticks.empty:
                # Bar-level skip: descending into every tick is the dominant cost, yet
                # the vast majority of bars can produce no event. Nothing can happen on
                # a bar unless (a) a position is open (exit / trailing / excursion /
                # blocked-zone consume), (b) a market signal needs tick execution, or
                # (c) an active pending order's trigger lies within the candle's price
                # range (the bid path is bounded by [low, high]). This is a strict
                # superset of the per-tick conditions, so results are identical.
                has_market_signal = sigv != 0 and not is_pending
                should_descend = (
                    bool(open_trades)
                    or has_market_signal
                    or self._pending_can_fill(pending, float(row.low), float(row.high), bar_index - 1)
                )
                if should_descend:
                    capital, open_trades, pending, trade_id = self._process_ticks_for_bar(
                        bar_ticks=bar_ticks,
                        bar_index=bar_index,
                        capital=capital,
                        open_trades=open_trades,
                        closed_trades=closed_trades,
                        pending=pending,
                        gate_arrays=gate_arrays,
                        trade_id=trade_id,
                        has_stop=has_stop,
                        has_take=has_take,
                        has_size=has_size,
                        has_risk=has_risk,
                        has_trail=has_trail,
                    )
                    last_tick = bar_ticks.iloc[-1]
                    close = float(last_tick["bid"])
                    spread_price = float(last_tick["ask"] - last_tick["bid"])
                elif pending:
                    # Skipped the ticks, but still drop orders whose validity elapsed.
                    pending = [o for o in pending if not self._pending_expired(o, bar_index - 1)]

            # Signal exits and entries are still evaluated once per strategy bar.
            if (not is_pending) and self.config.entry_timing != "next_bar_open" and sigv != 0:
                capital, open_trades, trade_id = self._apply_bar_signal(
                    row=row,
                    sigv=sigv,
                    dt=dt,
                    price=close,
                    volume=volume,
                    spread_price=spread_price,
                    bar_index=bar_index,
                    capital=capital,
                    open_trades=open_trades,
                    closed_trades=closed_trades,
                    trade_id=trade_id,
                    has_stop=has_stop,
                    has_take=has_take,
                    has_size=has_size,
                    has_risk=has_risk,
                    has_trail=has_trail,
                    has_entry=has_entry,
                )

            # The pending order is "created at bar close": placed AFTER this bar's
            # ticks so it can only fill from the next bar's ticks onward (causal,
            # mirroring the MT5 EA that adds a zone when a candle closes).
            if is_pending:
                order = self._make_pending(row, bar_index, gate_arrays)
                if order is not None:
                    pending.append(order)

            # Account ruin: balance or equity wiped out -> stop the backtest.
            if self.config.stop_on_ruin:
                equity = capital + sum(self._unrealized_pnl(t, close, spread_price) for t in open_trades)
                if capital <= 0.0 or equity <= 0.0:
                    for trade in open_trades:
                        self._close_trade(trade, close, dt, bar_index, "ruin", spread_price, None)
                        closed_trades.append(trade)
                        capital += float(trade["pnl"])
                    open_trades = []
                    break

        if open_trades:
            last = data.iloc[-1]
            last_spread = self._row_spread_price(last)
            last_price = float(last["close"])
            last_time = last["datetime"]
            if ticks_by_bar:
                last_ticks = next(reversed(ticks_by_bar.values()))
                if last_ticks is not None and not last_ticks.empty:
                    tick = last_ticks.iloc[-1]
                    last_price = float(tick["bid"])
                    last_spread = float(tick["ask"] - tick["bid"])
                    last_time = tick["datetime"]
            for trade in open_trades:
                self._close_trade(trade, last_price, last_time, len(data) - 1, "eod", last_spread, last)
                closed_trades.append(trade)
                capital += float(trade["pnl"])

        return self._finalize_trades(closed_trades)

    def _process_ticks_for_bar(
        self,
        bar_ticks: pd.DataFrame,
        bar_index: int,
        capital: float,
        open_trades: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        pending: list[dict[str, Any]] | None = None,
        gate_arrays: dict[str, np.ndarray] | None = None,
        trade_id: int = 0,
        has_stop: bool = False,
        has_take: bool = False,
        has_size: bool = False,
        has_risk: bool = False,
        has_trail: bool = False,
    ) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]], int]:
        current_open = open_trades
        pending = pending if pending is not None else []
        gate_arrays = gate_arrays or {}
        # During a forming bar's ticks the last CLOSED bar is bar_index - 1; that is
        # the index whose indicators (e.g. SMA) the MT5 EA reads on each tick.
        closed_idx = bar_index - 1
        # Reset the inter-tick bid baseline at the bar boundary (mirrors the EA
        # clearing g_have_last_bid when a new bar opens).
        prev_bid: float | None = None

        # Iterate over raw numpy arrays rather than itertuples: same logic and order,
        # but avoids per-row namedtuple construction over millions of ticks. Ticks
        # carry no ATR column, so the slippage source is None (atr slippage -> 0,
        # identical to passing the row when atr slippage is off).
        bids = bar_ticks["bid"].to_numpy(dtype=float)
        asks = bar_ticks["ask"].to_numpy(dtype=float)
        times = bar_ticks["datetime"].to_numpy()
        for _i in range(len(bids)):
            bid = bids[_i]
            ask = asks[_i]
            spread_price = ask - bid if ask > bid else 0.0
            tick_time = times[_i]
            can_execute = self._can_execute(tick_time)

            open_pnl = sum(self._unrealized_pnl(trade, bid, spread_price) for trade in current_open)
            used_margin = sum(float(trade.get("margin_required", 0.0)) for trade in current_open)
            equity_now = capital + open_pnl
            margin_level_pct = (equity_now / used_margin * 100.0) if used_margin > 0 else np.inf

            still_open = []
            for trade in current_open:
                self._update_excursions(trade, bid, bid, spread_price)
                self._update_trailing_stop(trade, ask if trade["direction"] == "short" else bid)

                exit_price, exit_reason = self._check_stop_take(trade, bid, bid, spread_price) if can_execute else (None, None)
                if (
                    exit_reason is None
                    and can_execute
                    and self.config.stop_out_level_pct is not None
                    and used_margin > 0
                    and margin_level_pct <= self.config.stop_out_level_pct
                ):
                    exit_price, exit_reason = bid, "stop_out"

                if exit_reason is None:
                    still_open.append(trade)
                    continue

                self._close_trade(trade, exit_price, pd.Timestamp(tick_time), bar_index, exit_reason, spread_price, None)
                closed_trades.append(trade)
                capital += float(trade["pnl"])

            current_open = still_open

            # Carried pending-order fills: the bid's travel between the previous tick
            # and this tick must cross the trigger (catches gaps over the level).
            if pending and can_execute:
                from_bid = prev_bid if prev_bid is not None else bid
                lo_t = min(from_bid, bid)
                hi_t = max(from_bid, bid)
                still_pending: list[dict[str, Any]] = []
                fired = False
                for order in pending:
                    if self._pending_expired(order, closed_idx):
                        continue  # validity elapsed -> drop
                    if fired or order["created_bar"] > closed_idx:
                        still_pending.append(order)  # already fired this tick, or not yet active
                        continue
                    touched = lo_t <= order["trigger"] <= hi_t
                    if not (touched and self._gate_ok(order, bid, gate_arrays, closed_idx)):
                        still_pending.append(order)
                        continue
                    # The level was reached: the zone is consumed (the EA drops it even
                    # when a position blocks the trade). One fill per tick.
                    fired = True
                    if self.config.single_position_mode and current_open:
                        continue  # blocked by open position -> consume zone, no trade
                    trade, capital, trade_id = self._open_pending_trade(
                        order=order,
                        tick_time=pd.Timestamp(tick_time),
                        bar_index=bar_index,
                        spread_price=spread_price,
                        slip_source=None,
                        current_open=current_open,
                        capital=capital,
                        trade_id=trade_id,
                        has_stop=has_stop,
                        has_take=has_take,
                        has_size=has_size,
                        has_risk=has_risk,
                        has_trail=has_trail,
                    )
                    if trade is not None:
                        current_open.append(trade)
                pending = still_pending

            prev_bid = bid
        return capital, current_open, pending, trade_id

    def _apply_bar_signal(
        self,
        row,
        sigv: int,
        dt,
        price: float,
        volume: float,
        spread_price: float,
        bar_index: int,
        capital: float,
        open_trades: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        trade_id: int,
        has_stop: bool,
        has_take: bool,
        has_size: bool,
        has_risk: bool,
        has_trail: bool,
        has_entry: bool,
    ) -> tuple[float, list[dict[str, Any]], int]:
        still_open = []
        for trade in open_trades:
            if self._can_execute(dt) and self._should_close_on_signal(trade, sigv):
                self._close_trade(trade, price, dt, bar_index, "signal", spread_price, row)
                closed_trades.append(trade)
                capital += float(trade["pnl"])
            else:
                still_open.append(trade)
        open_trades = still_open

        if sigv == 0:
            return capital, open_trades, trade_id
        if not self._can_execute(dt):
            return capital, open_trades, trade_id
        if self.config.single_position_mode and open_trades:
            return capital, open_trades, trade_id

        open_pnl = sum(self._unrealized_pnl(trade, price, spread_price) for trade in open_trades)
        used_margin = sum(float(trade.get("margin_required", 0.0)) for trade in open_trades)
        free_margin = capital + open_pnl - used_margin
        entry_price = self._resolve_entry_price(row, sigv, price, has_entry)
        if entry_price is None:
            return capital, open_trades, trade_id

        trade = self._open_trade_from_row(
            trade_id=trade_id,
            dt=dt,
            price=entry_price,
            volume=volume,
            spread_price=spread_price,
            bar_index=bar_index,
            sig_row=row,
            has_stop=has_stop,
            has_take=has_take,
            has_size=has_size,
            has_risk=has_risk,
            has_trail=has_trail,
            capital_now=capital,
            free_margin=free_margin,
        )
        if trade is not None:
            open_trades.append(trade)
            trade_id += 1
        return capital, open_trades, trade_id

    def _finalize_trades(self, closed_trades: list[dict[str, Any]]) -> pd.DataFrame:
        if not closed_trades:
            return pd.DataFrame()

        trades = pd.DataFrame(closed_trades)
        trades["duration"] = pd.to_datetime(trades["exit_time"]) - pd.to_datetime(trades["entry_time"])
        trades["bars_in_trade"] = trades["exit_bar_index"] - trades["entry_bar_index"]
        trades["result"] = np.where(
            trades["pnl"] > 0,
            "win",
            np.where(trades["pnl"] < 0, "loss", "be"),
        )

        if "risk" not in trades.columns:
            trades["risk"] = np.nan
        trades["risk"] = pd.to_numeric(trades["risk"], errors="coerce")
        trades["risk_reward"] = np.where(
            trades["risk"].notna() & (trades["risk"] != 0),
            trades["pnl"] / trades["risk"],
            np.nan,
        )
        return trades

    def _prepare_ticks(self, ticks: pd.DataFrame) -> pd.DataFrame:
        df = ticks.copy()
        missing = [col for col in ("datetime", "bid", "ask") if col not in df.columns]
        if missing:
            raise ValueError(f"ticks is missing columns: {missing}")
        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ("bid", "ask"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "time_msc" in df.columns:
            df["time_msc"] = pd.to_numeric(df["time_msc"], errors="coerce")
        sort_cols = ["datetime"] + (["time_msc"] if "time_msc" in df.columns else [])
        return df.dropna(subset=["datetime", "bid", "ask"]).sort_values(sort_cols).reset_index(drop=True)

    def _apply_entry_timing(self, data: pd.DataFrame) -> pd.DataFrame:
        timing = self.config.entry_timing
        if timing == "signal_close":
            return data
        if timing != "next_bar_open":
            raise ValueError("entry_timing must be 'signal_close' or 'next_bar_open'")

        out = data.copy()
        signal_cols = [
            "signal",
            "order_type",
            "stop_price",
            "take_price",
            "size",
            "risk",
            "trailing_distance",
            "trailing_start_profit",
            "comment",
        ]
        existing = [col for col in signal_cols if col in out.columns]
        out[existing] = out[existing].shift(1)
        out["signal"] = out["signal"].fillna(0).astype(int)
        if "entry_price" in out.columns:
            # A market order triggered by a closed-candle signal enters at the
            # next bar's market price, while SL/TP from the signal bar are kept.
            # Limit/stop signals keep their requested trigger price.
            if "order_type" in out.columns:
                pending = out["order_type"].astype(str).str.lower().isin({"limit", "stop"})
                out["entry_price"] = np.where((out["signal"] != 0) & ~pending, out["open"], out["entry_price"])
            else:
                out["entry_price"] = np.where(out["signal"] != 0, out["open"], np.nan)
        return out

    def _apply_execution_latency(self, data: pd.DataFrame) -> pd.DataFrame:
        bars = int(self.config.execution_latency_bars or 0)
        if bars <= 0:
            return data

        out = data.copy()
        existing = self._signal_payload_columns(out)
        out[existing] = out[existing].shift(bars)
        out["signal"] = out["signal"].fillna(0).astype(int)
        return out

    def _apply_session_policy(self, data: pd.DataFrame) -> pd.DataFrame:
        policy = self.config.session_policy
        if policy in ("ignore", "skip"):
            return data
        if policy != "push":
            raise ValueError("session_policy must be 'ignore', 'skip', or 'push'")

        out = data.copy()
        existing = self._signal_payload_columns(out)
        for idx, row in out.iterrows():
            if self._signal_value(row.get("signal", 0)) == 0 or self._can_execute(row["datetime"]):
                continue

            next_idx = self._next_executable_index(out, idx + 1)
            out.loc[idx, existing] = np.nan
            out.loc[idx, "signal"] = 0
            if next_idx is None or self._signal_value(out.loc[next_idx, "signal"]) != 0:
                continue
            out.loc[next_idx, existing] = row[existing]
        out["signal"] = out["signal"].fillna(0).astype(int)
        return out

    def _next_executable_index(self, data: pd.DataFrame, start_index: int) -> int | None:
        for idx in range(start_index, len(data)):
            if self._can_execute(data.iloc[idx]["datetime"]):
                return idx
        return None

    def _resolve_entry_price(self, row, signal: int, market_price: float, has_entry: bool) -> float | None:
        entry_sig = getattr(row, "entry_price", np.nan) if has_entry else np.nan
        has_explicit_entry = entry_sig is not None and not pd.isna(entry_sig)
        order_type = self._order_type(row)

        if self.config.execution_model == "idealized":
            entry_price = float(entry_sig) if has_explicit_entry else float(market_price)
            if has_explicit_entry and not self._entry_price_touched(row, entry_price):
                return None
            return entry_price

        if order_type == "market":
            if (
                self.config.entry_timing == "signal_close"
                and has_explicit_entry
                and not self._same_price(float(entry_sig), float(market_price))
            ):
                raise ValueError(
                    "Realistic execution rejected an intrabar entry_price on the signal candle. "
                    "Use entry_timing='next_bar_open', set order_type='limit'/'stop' with a causal "
                    "pending-order strategy, or set execution_model='idealized' only for research."
                )
            return float(market_price)

        if order_type not in {"limit", "stop"}:
            raise ValueError("order_type must be 'market', 'limit', or 'stop'")
        if not has_explicit_entry:
            raise ValueError(f"order_type='{order_type}' requires entry_price")
        entry_price = float(entry_sig)
        if not self._order_price_touched(row, entry_price, order_type, int(signal)):
            return None
        return entry_price

    # ----------------------------------------------------------- pending orders
    def _collect_gate_arrays(self, data: pd.DataFrame) -> dict[str, np.ndarray]:
        """Pre-extract every data column referenced by a signal's ``gate_column``.

        Generic price-gate support: an order may require its fill price to sit
        above/below a named indicator column at fill time (e.g. an SMA trend
        filter). We materialise those columns once as numpy arrays for O(1) lookup
        by bar index during the tick/candle loops.
        """
        if "gate_column" not in data.columns:
            return {}
        cols = {
            str(c)
            for c in data["gate_column"].dropna().unique()
            if str(c) and str(c) in data.columns
        }
        return {c: data[c].to_numpy(dtype=float) for c in cols}

    def _make_pending(self, row, bar_index: int, gate_arrays: dict[str, np.ndarray]) -> dict[str, Any] | None:
        """Build a carried pending-order record from a signal row.

        The order's trigger is the signal's ``entry_price``. ``expiry_bars`` (if
        present) bounds its validity; ``gate_column``/``gate_side`` carry an
        optional price gate. Returns ``None`` when there is no usable trigger.

        Wrong-side rejection (``reject_invalid_pending``) is applied later, at the
        first tick the order would be live, because that — not the signal bar's close
        — is the moment MT5 validates the order against the market.
        """
        trigger = getattr(row, "entry_price", np.nan)
        if trigger is None or pd.isna(trigger):
            return None
        direction = int(getattr(row, "signal", 0))
        if direction == 0:
            return None

        order_type = self._order_type(row)

        expiry_raw = getattr(row, "expiry_bars", np.nan)
        expiry_bar = None
        if expiry_raw is not None and not pd.isna(expiry_raw):
            expiry_bar = bar_index + int(expiry_raw)

        gate_column = getattr(row, "gate_column", None)
        if gate_column is None or (not isinstance(gate_column, str) and pd.isna(gate_column)):
            gate_column = None
        else:
            gate_column = str(gate_column)
            if gate_column not in gate_arrays:
                gate_column = None
        gate_side = getattr(row, "gate_side", None)
        if gate_side is not None and not (isinstance(gate_side, str) and gate_side):
            gate_side = None
        if isinstance(gate_side, str):
            gate_side = gate_side.strip().lower() or None

        return {
            "direction": direction,
            "order_type": order_type,
            "trigger": float(trigger),
            "stop_price": self._clean_optional(getattr(row, "stop_price", None)),
            "take_price": self._clean_optional(getattr(row, "take_price", None)),
            "size": self._clean_float(getattr(row, "size", 1.0), 1.0),
            "risk": self._clean_optional(getattr(row, "risk", None)),
            "trailing_distance": self._clean_optional(getattr(row, "trailing_distance", None)),
            "trailing_start_profit": self._clean_optional(getattr(row, "trailing_start_profit", None)),
            "comment": getattr(row, "comment", ""),
            "created_bar": int(bar_index),
            "expiry_bar": expiry_bar,
            "gate_column": gate_column,
            "gate_side": gate_side,
            "volume": float(getattr(row, "volume", 0.0) or 0.0),
        }

    @staticmethod
    def _pending_expired(order: dict[str, Any], closed_idx: int) -> bool:
        expiry = order.get("expiry_bar")
        return expiry is not None and closed_idx > int(expiry)

    @staticmethod
    def _pending_wrong_side(order: dict[str, Any], bid: float, ask: float) -> bool:
        """True if a resting order sits on the side of the market an MT5 broker would
        reject at placement: a buy fills at the ask, a sell at the bid, so a buy limit
        must be below ask / buy stop above ask, and a sell limit above bid / sell stop
        below bid."""
        order_type = order.get("order_type")
        if order_type not in {"limit", "stop"}:
            return False
        trig = float(order["trigger"])
        if int(order.get("direction", 0)) > 0:   # buy
            return trig >= ask if order_type == "limit" else trig <= ask
        return trig <= bid if order_type == "limit" else trig >= bid          # sell

    def _validate_pending_side(self, pending, bar_index, bid, ask):
        """Reject resting orders, once each, against the market at the first bar in
        which they are live (``bid``/``ask`` = the placement reference: the first tick
        in tick mode, the bar open in candle mode) — the moment the MT5 EA places them
        and the broker checks their side. Returns the surviving list (unchanged when
        validation is off or the book is empty)."""
        if not self.config.reject_invalid_pending or not pending:
            return pending
        bid = float(bid)
        ask = float(ask)
        active_idx = bar_index - 1
        kept = []
        for order in pending:
            if not order.get("validated") and order["created_bar"] <= active_idx:
                order["validated"] = True
                if self._pending_wrong_side(order, bid, ask):
                    continue  # broker would reject -> never book
            kept.append(order)
        return kept

    def _pending_can_fill(self, pending: list[dict[str, Any]], low: float, high: float, closed_idx: int) -> bool:
        """True if any active, non-expired pending order's trigger lies within the
        bar's price envelope — i.e. a fill is *possible* on this bar.

        The per-tick touch test uses the bid path, which is bounded by the candle's
        [low, high]; a tiny pad absorbs float rounding / candle-vs-tick edge noise so
        the envelope is a guaranteed superset (it can only ever descend more often,
        never miss a real fill)."""
        if not pending:
            return False
        pad = 3.0 * float(self.config.point or 0.0)
        lo, hi = low - pad, high + pad
        for o in pending:
            if self._pending_expired(o, closed_idx) or o["created_bar"] > closed_idx:
                continue
            if lo <= o["trigger"] <= hi:
                return True
        return False

    def _gate_ok(self, order: dict[str, Any], ref_price: float, gate_arrays: dict[str, np.ndarray], gate_idx: int) -> bool:
        """Evaluate the optional price gate: ``ref_price`` above/below the gate column.

        ``gate_idx`` is the bar index whose indicator value is authoritative — the
        last CLOSED bar during tick fills, or the fill bar itself for candle fills.
        """
        col = order.get("gate_column")
        side = order.get("gate_side")
        if not col or not side:
            return True
        arr = gate_arrays.get(col)
        if arr is None or gate_idx < 0 or gate_idx >= len(arr):
            return True
        value = arr[gate_idx]
        if np.isnan(value):
            return False
        if side == "above":
            return ref_price > value
        if side == "below":
            return ref_price < value
        return True

    def _open_pending_trade(
        self,
        order: dict[str, Any],
        tick_time,
        bar_index: int,
        spread_price: float,
        slip_source,
        current_open: list[dict[str, Any]],
        capital: float,
        trade_id: int,
        has_stop: bool,
        has_take: bool,
        has_size: bool,
        has_risk: bool,
        has_trail: bool,
    ) -> tuple[dict[str, Any] | None, float, int]:
        open_pnl = sum(self._unrealized_pnl(t, order["trigger"], spread_price) for t in current_open)
        used_margin = sum(float(t.get("margin_required", 0.0)) for t in current_open)
        free_margin = capital + open_pnl - used_margin
        sig_row = self._pending_sig_row(order, slip_source)
        trade = self._open_trade_from_row(
            trade_id=trade_id,
            dt=tick_time,
            price=order["trigger"],
            volume=order["volume"],
            spread_price=spread_price,
            bar_index=bar_index,
            sig_row=sig_row,
            has_stop=has_stop,
            has_take=has_take,
            has_size=has_size,
            has_risk=has_risk,
            has_trail=has_trail,
            capital_now=capital,
            free_margin=free_margin,
        )
        if trade is not None:
            trade_id += 1
        return trade, capital, trade_id

    def _pending_sig_row(self, order: dict[str, Any], slip_source) -> SimpleNamespace:
        """A signal-row-like object for ``_open_trade_from_row`` built from a pending
        order, carrying the slippage source's ATR column when present."""
        atr_col = self.config.slippage_atr_column
        atr_val = self._source_value(slip_source, atr_col) if atr_col else None
        ns = SimpleNamespace(
            signal=order["direction"],
            order_type=order["order_type"],
            entry_price=order["trigger"],
            stop_price=order["stop_price"],
            take_price=order["take_price"],
            size=order["size"],
            risk=order["risk"],
            trailing_distance=order["trailing_distance"],
            trailing_start_profit=order.get("trailing_start_profit"),
            comment=order.get("comment", ""),
        )
        if atr_val is not None:
            setattr(ns, atr_col, atr_val)
        return ns

    def _fill_pending_candle(
        self,
        row,
        bar_index: int,
        pending: list[dict[str, Any]],
        open_trades: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        capital: float,
        trade_id: int,
        gate_arrays: dict[str, np.ndarray],
        can_execute: bool,
        has_stop: bool,
        has_take: bool,
        has_size: bool,
        has_risk: bool,
        has_trail: bool,
    ) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]], int]:
        """Candle-mode pending fills: a bar that crosses the trigger fills the order.

        The gate is evaluated against this bar's close vs this bar's indicator value
        (closed-candle semantics), at most one order fills per bar, and a touch while
        a position blocks the trade still consumes the order."""
        spread_price = self._row_spread_price(row)
        close = float(row.close)
        still: list[dict[str, Any]] = []
        fired = False
        for order in pending:
            if self._pending_expired(order, bar_index):
                continue
            if fired or order["created_bar"] >= bar_index or not can_execute:
                still.append(order)
                continue
            if not self._order_price_touched(row, order["trigger"], order["order_type"], order["direction"]):
                still.append(order)
                continue
            if not self._gate_ok(order, close, gate_arrays, bar_index):
                still.append(order)
                continue
            fired = True
            if self.config.single_position_mode and open_trades:
                continue  # consumed but blocked
            trade, capital, trade_id = self._open_pending_trade(
                order=order,
                tick_time=row.datetime,
                bar_index=bar_index,
                spread_price=spread_price,
                slip_source=row,
                current_open=open_trades,
                capital=capital,
                trade_id=trade_id,
                has_stop=has_stop,
                has_take=has_take,
                has_size=has_size,
                has_risk=has_risk,
                has_trail=has_trail,
            )
            if trade is not None:
                open_trades.append(trade)
        return capital, open_trades, still, trade_id

    def _signal_payload_columns(self, data: pd.DataFrame) -> list[str]:
        candidates = [
            "signal",
            "order_type",
            "entry_price",
            "stop_price",
            "take_price",
            "size",
            "risk",
            "trailing_distance",
            "comment",
        ]
        return [col for col in candidates if col in data.columns]

    @staticmethod
    def _signal_value(value) -> int:
        if value is None or pd.isna(value):
            return 0
        return int(value)

    @staticmethod
    def _order_type(row) -> str:
        if isinstance(row, (pd.Series, dict)):
            raw = row.get("order_type", None)
        else:
            raw = getattr(row, "order_type", None)
        if raw is None or (not isinstance(raw, str) and pd.isna(raw)):
            return "market"
        value = str(raw).strip().lower()
        if not value:
            return "market"
        aliases = {
            "market_next_bar": "market",
            "market_on_close": "market",
            "pending_limit": "limit",
            "limit_order": "limit",
            "pending_stop": "stop",
            "stop_order": "stop",
        }
        return aliases.get(value, value)

    def _order_price_touched(self, row, entry_price: float, order_type: str, signal: int) -> bool:
        if hasattr(row, "high"):
            high = float(getattr(row, "high"))
            low = float(getattr(row, "low"))
        else:
            high = float(row["high"])
            low = float(row["low"])
        if order_type == "limit":
            return low <= float(entry_price) if signal > 0 else high >= float(entry_price)
        if order_type == "stop":
            return high >= float(entry_price) if signal > 0 else low <= float(entry_price)
        return False

    def _same_price(self, a: float, b: float) -> bool:
        tol = abs(float(self.config.point or 0.0)) / 2.0
        return abs(float(a) - float(b)) <= tol

    def _ticks_by_bar(self, data: pd.DataFrame, ticks: pd.DataFrame) -> dict[int, pd.DataFrame]:
        if ticks.empty or data.empty:
            return {}
        bar_times = pd.to_datetime(data["datetime"]).astype("int64").to_numpy()
        tick_times = pd.to_datetime(ticks["datetime"]).astype("int64").to_numpy()
        bar_index = np.searchsorted(bar_times, tick_times, side="right") - 1
        mask = (bar_index >= 0) & (bar_index < len(data))
        if not np.any(mask):
            return {}
        out = ticks.loc[mask].copy()
        out["_bar_index"] = bar_index[mask]
        return {int(idx): frame.drop(columns=["_bar_index"]) for idx, frame in out.groupby("_bar_index", sort=True)}

    def _prepare_data(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        if "datetime" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={"index": "datetime"})

        missing = [c for c in self.REQUIRED_DATA_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"data is missing columns: {missing}")

        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ("open", "high", "low", "close", "volume", self.config.spread_column):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=list(self.REQUIRED_DATA_COLUMNS)).sort_values("datetime")
        return df.reset_index(drop=True)

    def _open_trade_from_row(
        self,
        trade_id: int,
        dt,
        price: float,
        volume: float,
        spread_price: float,
        bar_index: int,
        sig_row,
        has_stop: bool,
        has_take: bool,
        has_size: bool,
        has_risk: bool,
        has_trail: bool,
        capital_now: float,
        free_margin: float,
    ) -> dict[str, Any] | None:
        sigv = int(sig_row.signal)
        if sigv == 0:
            return None

        direction = "long" if sigv > 0 else "short"
        default_size = float(self.config.fixed_lot)
        size = self._clean_float(getattr(sig_row, "size", default_size) if has_size else default_size, default_size)
        stop_price = self._clean_optional(getattr(sig_row, "stop_price", None) if has_stop else None)
        take_price = self._clean_optional(getattr(sig_row, "take_price", None) if has_take else None)
        trailing_distance = self._clean_optional(
            getattr(sig_row, "trailing_distance", None) if has_trail else None
        )
        trailing_start_profit = self._clean_optional(
            getattr(sig_row, "trailing_start_profit", None) if has_trail else None
        )
        risk = self._clean_optional(getattr(sig_row, "risk", None) if has_risk else None)

        per_unit_risk = abs(price - stop_price) if stop_price is not None else None
        if (
            self.config.risk_per_trade_pct > 0
            and per_unit_risk is not None
            and per_unit_risk > 0
        ):
            money_risk = capital_now * (self.config.risk_per_trade_pct / 100.0)
            size = money_risk / (per_unit_risk * self.config.contract_size)
            risk = money_risk
        elif risk is None and per_unit_risk is not None:
            risk = per_unit_risk * size * self.config.contract_size

        entry_slippage = self._execution_slippage_price(price, spread_price, sig_row)
        entry_price = self._entry_execution_price(price, direction, spread_price, sig_row)
        commission_open = self._commission(entry_price, size)
        notional = self._notional(entry_price, size)
        margin_required = self._margin_required(entry_price, size)
        if margin_required > free_margin:
            return None

        return {
            "id": trade_id,
            "direction": direction,
            "execution_model": self.config.execution_model,
            "order_type": self._order_type(sig_row),
            "entry_time": dt,
            "entry_bar_index": bar_index,
            "entry_price": entry_price,
            "entry_mid_price": price,
            "entry_spread_price": spread_price,
            "entry_spread_points": self._price_to_points(spread_price),
            "entry_slippage_price": entry_slippage,
            "entry_slippage_points": self._price_to_points(entry_slippage),
            "size": size,
            "contract_size": self.config.contract_size,
            "notional_value": notional,
            "leverage": self.config.leverage,
            "margin_required": margin_required,
            "free_margin_at_entry": free_margin,
            "stop_price": stop_price,
            "take_price": take_price,
            "trailing_distance": trailing_distance,
            "trailing_start_profit": trailing_start_profit,
            "risk": risk,
            "max_favor": 0.0,
            "max_adverse": 0.0,
            "volume_at_entry": volume,
            "exit_time": None,
            "exit_bar_index": None,
            "exit_price": None,
            "exit_mid_price": None,
            "exit_spread_price": None,
            "exit_spread_points": None,
            "pnl": None,
            "gross_pnl": None,
            "swap": 0.0,
            "commission_open": commission_open,
            "commission_close": 0.0,
            "exit_reason": None,
        }

    def _close_trade(
        self,
        trade: dict[str, Any],
        exit_price: float,
        exit_time,
        exit_bar_index: int,
        exit_reason: str,
        spread_price: float = 0.0,
        execution_source=None,
    ) -> None:
        direction_factor = 1 if trade["direction"] == "long" else -1
        exit_slippage = self._execution_slippage_price(exit_price, spread_price, execution_source)
        px = self._exit_execution_price(exit_price, trade["direction"], spread_price, execution_source)
        commission_close = self._commission(px, trade["size"])
        swap = self._swap(trade, exit_time)

        gross_pnl = (px - trade["entry_price"]) * trade["size"] * self.config.contract_size * direction_factor
        net_pnl = gross_pnl + swap - trade.get("commission_open", 0.0) - commission_close

        trade["exit_time"] = exit_time
        trade["exit_bar_index"] = exit_bar_index
        trade["exit_price"] = px
        trade["exit_mid_price"] = exit_price
        trade["exit_spread_price"] = spread_price
        trade["exit_spread_points"] = self._price_to_points(spread_price)
        trade["exit_slippage_price"] = exit_slippage
        trade["exit_slippage_points"] = self._price_to_points(exit_slippage)
        trade["gross_pnl"] = gross_pnl
        trade["swap"] = swap
        trade["commission_close"] = commission_close
        trade["pnl"] = net_pnl
        trade["exit_reason"] = exit_reason

    def _update_excursions(self, trade: dict[str, Any], high: float, low: float, spread_price: float) -> None:
        size = trade["size"]
        entry = trade["entry_price"]
        if trade["direction"] == "long":
            best_pnl = (high - entry) * size * self.config.contract_size
            worst_pnl = (low - entry) * size * self.config.contract_size
        else:
            best_pnl = (entry - (low + spread_price)) * size * self.config.contract_size
            worst_pnl = (entry - (high + spread_price)) * size * self.config.contract_size
        trade["max_favor"] = max(trade["max_favor"], best_pnl)
        trade["max_adverse"] = min(trade["max_adverse"], worst_pnl)

    def _update_trailing_stop(self, trade: dict[str, Any], close: float) -> None:
        dist = trade.get("trailing_distance")
        if dist is None:
            return

        start = trade.get("trailing_start_profit")
        if start is not None:
            entry = trade.get("entry_price", 0.0)
            if trade["direction"] == "long" and close < entry * (1.0 + start):
                return
            if trade["direction"] == "short" and close > entry * (1.0 - start):
                return

        if trade["direction"] == "long":
            new_stop = close - dist
            trade["stop_price"] = new_stop if trade["stop_price"] is None else max(trade["stop_price"], new_stop)
        else:
            new_stop = close + dist
            trade["stop_price"] = new_stop if trade["stop_price"] is None else min(trade["stop_price"], new_stop)

    def _check_stop_take(
        self,
        trade: dict[str, Any],
        high: float,
        low: float,
        spread_price: float,
        open_: float | None = None,
        close: float | None = None,
    ) -> tuple[float | None, str | None]:
        stop = trade.get("stop_price")
        take = trade.get("take_price")

        if trade["direction"] == "long":
            hit_stop = stop is not None and low <= stop
            hit_take = take is not None and high >= take
            if hit_stop and hit_take:
                return self._intrabar_first(trade["direction"], float(stop), float(take), open_, close)
            if hit_stop:
                return float(stop), "sl"
            if hit_take:
                return float(take), "tp"
            return None, None

        ask_high = high + spread_price
        ask_low = low + spread_price
        hit_stop = stop is not None and ask_high >= stop
        hit_take = take is not None and ask_low <= take
        if hit_stop and hit_take:
            level, reason = self._intrabar_first(trade["direction"], float(stop), float(take), open_, close)
            return level - spread_price, reason
        if hit_stop:
            return float(stop) - spread_price, "sl"
        if hit_take:
            return float(take) - spread_price, "tp"
        return None, None

    def _intrabar_first(
        self,
        direction: str,
        stop: float,
        take: float,
        open_: float | None,
        close: float | None,
    ) -> tuple[float, str]:
        """Resolve which of SL/TP is hit first when both lie inside one bar.

        Returns the (level, reason) of the first-hit side. ``mt5_like_ohlc`` infers
        the visit order from the candle's body direction; without open/close it falls
        back to ``conservative``. Tick mode never reaches the both-hit branch in a
        meaningful way (high==low), so this only matters for candle execution.
        """
        mode = self.config.intrabar_mode
        if mode == "optimistic":
            return take, "tp"
        if mode == "mt5_like_ohlc" and open_ is not None and close is not None:
            bull = float(close) >= float(open_)  # O->L->H->C (bull) vs O->H->L->C (bear)
            is_long = direction == "long"
            # On a bull candle the low extreme is visited before the high; for a long
            # the SL sits on the low side, so SL is first iff (bull and long) — and the
            # symmetric cases collapse to: SL first iff bull == is_long.
            sl_first = (bull == is_long)
            return (stop, "sl") if sl_first else (take, "tp")
        return stop, "sl"  # conservative default

    def _should_close_on_signal(self, trade: dict[str, Any], signal: int) -> bool:
        if signal == 0 or not self.config.single_position_mode:
            return False
        if self.config.close_on_signal == "never":
            return False
        if self.config.close_on_signal == "any":
            return True
        if self.config.close_on_signal == "opposite":
            return (trade["direction"] == "long" and signal < 0) or (
                trade["direction"] == "short" and signal > 0
            )
        raise ValueError("close_on_signal must be 'opposite', 'any', or 'never'")

    def _can_execute(self, dt) -> bool:
        if self.config.session_policy == "ignore":
            return True
        if self.config.session_policy not in ("skip", "push"):
            raise ValueError("session_policy must be 'ignore', 'skip', or 'push'")
        calendar = self.config.session_calendar
        if calendar is None:
            return True
        if isinstance(calendar, dict):
            from .session import SessionCalendar

            calendar = SessionCalendar.from_config(calendar)
            self.config.session_calendar = calendar
        if not hasattr(calendar, "is_open"):
            raise TypeError("session_calendar must expose is_open(dt)")
        return bool(calendar.is_open(dt))

    def _entry_price_touched(self, row, entry_price: float) -> bool:
        if not self.config.require_entry_touch:
            return True
        if hasattr(row, "high"):
            high = float(getattr(row, "high"))
            low = float(getattr(row, "low"))
        else:
            high = float(row["high"])
            low = float(row["low"])
        return low <= float(entry_price) <= high

    def _row_spread_price(self, row) -> float:
        if not self.config.use_spread:
            return 0.0
        if self.config.fixed_spread_points is not None:
            return float(self.config.fixed_spread_points) * self.config.point
        if not hasattr(row, self.config.spread_column):
            return 0.0
        value = getattr(row, self.config.spread_column)
        if value is None or pd.isna(value):
            return 0.0
        return float(value) * self.config.point

    def _entry_execution_price(
        self,
        price: float,
        direction: str,
        spread_price: float,
        execution_source=None,
    ) -> float:
        dynamic_slippage = self._execution_slippage_price(price, spread_price, execution_source)
        if direction == "long":
            return (price + spread_price) * (1 + self.config.slippage) + dynamic_slippage
        return price * (1 - self.config.slippage) - dynamic_slippage

    def _exit_execution_price(
        self,
        price: float,
        direction: str,
        spread_price: float,
        execution_source=None,
    ) -> float:
        dynamic_slippage = self._execution_slippage_price(price, spread_price, execution_source)
        if direction == "long":
            return price * (1 - self.config.slippage) - dynamic_slippage
        return (price + spread_price) * (1 + self.config.slippage) + dynamic_slippage

    def _execution_slippage_price(self, price: float, spread_price: float, execution_source=None) -> float:
        spread_component = max(float(spread_price), 0.0) * float(self.config.slippage_spread_mult or 0.0)
        atr_value = self._source_value(execution_source, self.config.slippage_atr_column)
        atr_component = 0.0 if atr_value is None else abs(float(atr_value)) * float(self.config.slippage_atr_mult or 0.0)
        return spread_component + atr_component

    @staticmethod
    def _source_value(source, name: str):
        if source is None or not name:
            return None
        if hasattr(source, name):
            value = getattr(source, name)
        elif isinstance(source, pd.Series) and name in source.index:
            value = source[name]
        elif isinstance(source, dict) and name in source:
            value = source[name]
        else:
            return None
        if value is None or pd.isna(value):
            return None
        return value

    def _commission(self, price: float, size: float) -> float:
        percent_cost = self.config.commission_perc * float(price) * float(size) * self.config.contract_size
        lot_cost = self.config.commission_per_lot * float(size)
        return percent_cost + lot_cost

    def _notional(self, price: float, size: float) -> float:
        return abs(float(price) * float(size) * self.config.contract_size)

    def _margin_required(self, price: float, size: float) -> float:
        margin_rate = self.config.margin_rate
        if margin_rate is None:
            leverage = max(float(self.config.leverage or 1.0), 1.0)
            margin_rate = 1.0 / leverage
        return self._notional(price, size) * float(margin_rate)

    def _unrealized_pnl(self, trade: dict[str, Any], mid_price: float, spread_price: float) -> float:
        direction_factor = 1 if trade["direction"] == "long" else -1
        exit_price = self._exit_execution_price(mid_price, trade["direction"], spread_price)
        return (exit_price - trade["entry_price"]) * trade["size"] * self.config.contract_size * direction_factor

    def _swap(self, trade: dict[str, Any], exit_time) -> float:
        long_rate = self.config.swap_long_per_lot
        short_rate = self.config.swap_short_per_lot
        if long_rate == 0 and short_rate == 0:
            return 0.0

        entry_time = pd.to_datetime(trade["entry_time"])
        exit_dt = pd.to_datetime(exit_time)
        if exit_dt.date() <= entry_time.date():
            return 0.0

        daily_rate = long_rate if trade["direction"] == "long" else short_rate
        total = 0.0
        current = entry_time.date() + timedelta(days=1)
        while current <= exit_dt.date():
            multiplier = 1
            if self.config.triple_swap_weekday is not None and current.weekday() == self.config.triple_swap_weekday:
                multiplier = 3
            total += daily_rate * float(trade["size"]) * multiplier
            current += timedelta(days=1)
        return total

    def _price_to_points(self, price_distance: float) -> float:
        if not self.config.point:
            return 0.0
        return price_distance / self.config.point

    @staticmethod
    def _clean_optional(value):
        if value is None or pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def _clean_float(value, default: float) -> float:
        if value is None or pd.isna(value):
            return default
        return float(value)
