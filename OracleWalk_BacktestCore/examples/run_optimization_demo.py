#!/usr/bin/env python3
"""Demo: parameter search + walk-forward + overfit diagnostics on EURUSD H4.

Shows the headline lesson of robust strategy verification: a full-sample
optimization can look great while walk-forward out-of-sample and PBO reveal it
does not generalize.

Run:
    .venv/bin/python examples/run_optimization_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest_core.optimization import (
    deflated_sharpe_from_matrix,
    optimize,
    probability_of_backtest_overfitting,
    walk_forward,
)
from backtest_core.strategies.examples import EmaCrossStrategy

PACKAGE = ROOT / "data" / "broker_exports" / "FTMO Global Markets Ltd" / "EURUSD" / "H4" / "candles.csv"

ENGINE = dict(
    initial_capital=10000.0,
    risk_per_trade_pct=0.0,
    contract_size=100000.0,
    point=0.00001,
    leverage=30.0,
    use_spread=True,
    spread_column="spread",
    swap_long_per_lot=-10.46,
    swap_short_per_lot=0.20,
    single_position_mode=True,
    close_on_signal="opposite",
)

SPACE = {
    "fast": [8, 12, 16],
    "slow": [30, 36, 48],
    "stop_atr": [1.0, 1.5, 2.0],
    "take_atr": [2.0, 3.0, 4.0],
}


def load() -> pd.DataFrame:
    c = pd.read_csv(PACKAGE).rename(columns={"time": "datetime", "tick_volume": "volume"})
    c["datetime"] = pd.to_datetime(c["datetime"], format="%Y.%m.%d %H:%M")
    return c[["datetime", "open", "high", "low", "close", "volume", "spread"]]


def main() -> None:
    data = load()

    print("== Grid search (objective: sharpe_per_trade) ==")
    opt = optimize(EmaCrossStrategy, data, ENGINE, SPACE, objective="sharpe_per_trade", bucket="W")
    cols = ["fast", "slow", "stop_atr", "take_atr", "objective", "total_trades", "net_profit", "profit_factor"]
    print(opt["results"].head(5)[cols].to_string(index=False))

    print("\n== Overfit diagnostics ==")
    pbo = probability_of_backtest_overfitting(opt["returns_matrix"], n_splits=10)
    dsr = deflated_sharpe_from_matrix(opt["returns_matrix"])
    print(f"PBO (prob. of overfitting): {pbo['pbo']:.3f}  over {pbo['n_combinations']} CSCV splits")
    print(f"Deflated Sharpe: observed_SR={dsr['observed_sr']:.3f}  benchmark={dsr['expected_max_sr']:.3f}  DSR={dsr['dsr']:.3f}")

    print("\n== Walk-forward (anchored, 5 windows, out-of-sample) ==")
    wf = walk_forward(EmaCrossStrategy, data, ENGINE, SPACE, objective="sharpe_per_trade", n_splits=5, scheme="anchored")
    for w in wf["windows"]:
        print(f"  win{w['window']} {w['test_start'][:10]}->{w['test_end'][:10]}  "
              f"IS={w['is_objective']:.2f} OOS={w['oos_objective']:.2f}  trades={w['oos_trades']}")
    m = wf["oos_metrics"]
    print(f"OOS combined: trades={m['total_trades']} net={m['net_profit']:.2f} PF={m['profit_factor']}")
    print(f"IS->OOS degradation: {wf['is_to_oos_degradation']:.2f} "
          f"(IS_mean={wf['is_objective_mean']:.2f}, OOS_mean={wf['oos_objective_mean']:.2f})")

    print("\nLesson: a strong full-sample fit can collapse out-of-sample. "
          "Trust the OOS / PBO / DSR, not the in-sample winner.")


if __name__ == "__main__":
    main()
