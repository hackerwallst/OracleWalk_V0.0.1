from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backtest_core import run_strategy_backtest
from backtest_core.data import add_atr
from backtest_core.strategies.examples import EmaCrossStrategy


CONFIG = {
    "strategy_name": "EMA Crossover Demo",
    "initial_capital": 1000.0,
    "risk_per_trade_pct": 1.0,
    "commission_perc": 0.0004,
    "slippage": 0.0001,
    "single_position_mode": True,
    "close_on_signal": "opposite",
}


def make_demo_ohlcv(rows: int = 1600) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dt = pd.date_range("2023-01-01", periods=rows, freq="h")
    returns = rng.normal(0.00015, 0.012, rows)
    close = 100 * np.exp(np.cumsum(returns))
    spread = close * rng.uniform(0.002, 0.018, rows)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(mean=8.5, sigma=0.45, size=rows)

    return pd.DataFrame(
        {
            "datetime": dt,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def main():
    data = make_demo_ohlcv()
    data = add_atr(data, 14)
    strategy = EmaCrossStrategy(fast=12, slow=36, atr_period=14)

    result = run_strategy_backtest(
        data=data,
        strategy=strategy,
        config=CONFIG,
        output_dir=Path("reports") / "demo",
    )
    paths = result["report"]
    print("Generated report:")
    for key, value in paths.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
