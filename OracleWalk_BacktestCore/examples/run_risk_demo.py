#!/usr/bin/env python3
"""Demo: advanced risk metrics + buy & hold benchmark on EURUSD H4."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest_core.analytics import (
    buy_and_hold_equity,
    buy_and_hold_metrics,
    compute_metrics,
    compute_risk_metrics,
    equity_curve,
    strategy_vs_benchmark,
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


def load() -> pd.DataFrame:
    c = pd.read_csv(PACKAGE).rename(columns={"time": "datetime", "tick_volume": "volume"})
    c["datetime"] = pd.to_datetime(c["datetime"], format="%Y.%m.%d %H:%M")
    return c[["datetime", "open", "high", "low", "close", "volume", "spread"]]


def main() -> None:
    data = load()
    cap = ENGINE["initial_capital"]

    print("== Running strategy (EMA 12/36, SL 1.5 ATR, TP 3.0 ATR) ==")
    from backtest_core.optimization.objective import evaluate
    strat = EmaCrossStrategy(fast=12, slow=36, stop_atr=1.5, take_atr=3.0)
    trades, metrics = evaluate(strat, data, ENGINE)
    print(f"Trades: {metrics['total_trades']}  Net: {metrics['net_profit']:.2f}  "
          f"PF: {metrics['profit_factor']}  Sharpe: {metrics['sharpe_per_trade']}")

    print("\n== Advanced risk metrics ==")
    risk = compute_risk_metrics(trades, cap)
    for k, v in risk.items():
        label = k.replace("_", " ").title()
        if isinstance(v, float):
            print(f"  {label}: {v:.4f}")
        else:
            print(f"  {label}: {v}")

    print("\n== Buy & hold benchmark ==")
    bh = buy_and_hold_metrics(data, cap, contract_size=ENGINE["contract_size"])
    for k, v in bh.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")

    print("\n== Strategy vs benchmark ==")
    strat_eq = equity_curve(trades, cap)
    bh_eq = buy_and_hold_equity(data, cap, contract_size=ENGINE["contract_size"])
    comp = strategy_vs_benchmark(strat_eq, bh_eq, cap)
    for k, v in comp.items():
        if v is not None:
            print(f"  {k}: {v:.6f}")
        else:
            print(f"  {k}: None")


if __name__ == "__main__":
    main()
