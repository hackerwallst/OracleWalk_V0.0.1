"""FVG tick-parity gate — the HEAVY guard for the execution engine.

Runs the FVG strategy through the carried pending-order book in TICK mode and prints
the trade count in a window, to compare against the MT5 FVG_SMA9_Body60_TickTouch
export. This is the gold-standard parity check (validated 8/8 on 2026-05-01..05-19 and
7/7 on 2025-03-01..03-20). Run it BEFORE and AFTER any change to the engine's
tick-fill / pending-order / entry-timing code — the count must not regress.

Needs the broker tick package (data/broker_exports/.../EURUSD/H1/ticks.csv|.parquet).
Slow (minutes) — not part of the fast armor suite (tests/test_engine_parity_armor.py).

Usage:
  python scripts/homolog_fvg_tick.py                              # default 8/8 window
  python scripts/homolog_fvg_tick.py --start 2025-03-01 --end 2025-03-20 --leadin 2025-02-01
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtest_core.analytics.robustness import date_slice
from backtest_core.core.engine import Backtester
from backtest_core.data import load_mt5_csv, load_mt5_ticks_csv
from backtest_core.strategies.fvg_imbalance import FairValueGapStrategy

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "data/broker_exports/FTMO Global Markets Ltd/EURUSD/H1"
COMMON = Path("/Users/cyberlord/Library/Application Support/net.metaquotes.wine.metatrader5/"
              "drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files")
MT5_TRADES = COMMON / "FVG_SMA9_Body60_TickTouch_trades.csv"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-05-19")
    ap.add_argument("--leadin", default="2026-04-01", help="warmup start (SMA9 + carry zones)")
    args = ap.parse_args()

    candles = date_slice(load_mt5_csv(PKG / "candles.csv"), args.leadin, args.end)
    ticks = load_mt5_ticks_csv(str(PKG / "ticks.csv"), start=args.leadin, end=args.end)
    print(f"candles {len(candles)}  ticks {len(ticks):,}")

    strat = FairValueGapStrategy(sma_period=9, min_body_ratio=0.6, emit_pending_orders=True)
    prepared = strat.prepare_indicators(candles)
    signals = strat.generate_signals(prepared)

    cfg = dict(
        initial_capital=10000.0, contract_size=100000.0, point=0.00001, leverage=30.0,
        risk_per_trade_pct=0.0, commission_per_lot=0.0, swap_long_per_lot=0.0,
        swap_short_per_lot=0.0, slippage=0.0, use_spread=False,
        execution_mode="tick", entry_timing="signal_close", pending_order_book=True,
        single_position_mode=True, close_on_signal="never",
    )
    trades = Backtester(prepared, cfg).run(signals, ticks=ticks)
    tt = trades.copy()
    tt["entry_time"] = pd.to_datetime(tt["entry_time"])
    win = tt[(tt["entry_time"] >= pd.Timestamp(args.start)) & (tt["entry_time"] <= pd.Timestamp(args.end))]
    print(f"\nPYTHON FVG tick trades in {args.start}..{args.end} = {len(win)}")

    if MT5_TRADES.exists():
        mt5 = pd.read_csv(MT5_TRADES)
        mt5["entry_time"] = pd.to_datetime(mt5["entry_time"], format="%Y.%m.%d %H:%M:%S", errors="coerce")
        mw = mt5[(mt5["entry_time"] >= pd.Timestamp(args.start)) & (mt5["entry_time"] <= pd.Timestamp(args.end))]
        print(f"MT5    FVG tick trades in {args.start}..{args.end} = {len(mw)}")
        print("PARITY OK" if len(win) == len(mw) else "PARITY MISMATCH — investigate before shipping")


if __name__ == "__main__":
    main()
