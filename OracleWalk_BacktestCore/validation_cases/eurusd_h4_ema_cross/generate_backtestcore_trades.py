#!/usr/bin/env python3
"""Reproducibly generate the BacktestCore side of the EURUSD H4 EMA Cross case.

Runs EmaCrossStrategy through the candle-by-candle Backtester directly (no CLI,
no tick mode) against the FTMO EURUSD H4 broker-package candles, using engine
settings aligned to the broker's symbol_spec.json. Writes backtestcore_trades.csv
next to this script.

Run:
    .venv/bin/python validation_cases/eurusd_h4_ema_cross/generate_backtestcore_trades.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Repo root = three levels up from this file.
ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))

from backtest_core.core.engine import Backtester
from backtest_core.strategies.examples import EmaCrossStrategy

CASE_DIR = Path(__file__).resolve().parent
PACKAGE = ROOT / "data" / "broker_exports" / "FTMO Global Markets Ltd" / "EURUSD" / "H4"

# Strategy params (must match the EA inputs).
STRAT = dict(fast=12, slow=36, atr_period=14, stop_atr=1.5, take_atr=3.0)
LOTS = 0.10

# Engine config aligned to symbol_spec.json / account_spec.json.
ENGINE = dict(
    initial_capital=10000.0,
    risk_per_trade_pct=0.0,        # respect the fixed lot we inject below
    contract_size=100000.0,
    point=0.00001,
    leverage=30.0,
    use_spread=True,
    spread_column="spread",
    fixed_spread_points=None,
    commission_per_lot=0.0,        # isolate: set to match broker if known
    commission_perc=0.0,
    slippage=0.0,
    swap_long_per_lot=-10.46,
    swap_short_per_lot=0.20,
    triple_swap_weekday=2,
    single_position_mode=True,
    close_on_signal="opposite",
)


def load_candles(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={"time": "datetime", "tick_volume": "volume"})
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y.%m.%d %H:%M")
    return df[["datetime", "open", "high", "low", "close", "volume", "spread"]]


def main() -> None:
    candles = load_candles(PACKAGE / "candles.csv")
    strat = EmaCrossStrategy(**STRAT)
    prepared = strat.prepare_indicators(candles)
    signals = strat.generate_signals(prepared)
    # Inject a fixed lot so the engine sizes exactly like the EA (Lots input).
    signals["size"] = LOTS

    trades = Backtester(prepared, ENGINE).run(signals)
    out = CASE_DIR / "backtestcore_trades.csv"
    trades.to_csv(out, index=False)

    net = float(trades["pnl"].sum()) if not trades.empty else 0.0
    meta = {
        "package": str(PACKAGE.relative_to(ROOT)),
        "bars": int(len(prepared)),
        "strategy_params": STRAT,
        "lots": LOTS,
        "engine": ENGINE,
        "total_trades": int(len(trades)),
        "net_pnl": round(net, 2),
        "first_entry": str(trades["entry_time"].iloc[0]) if not trades.empty else None,
        "last_exit": str(trades["exit_time"].iloc[-1]) if not trades.empty else None,
    }
    (CASE_DIR / "backtestcore_run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {out}  ({meta['total_trades']} trades, net {meta['net_pnl']})")


if __name__ == "__main__":
    main()
