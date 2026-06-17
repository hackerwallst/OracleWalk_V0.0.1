from __future__ import annotations

from pathlib import Path

import pandas as pd

from .engine import Backtester
from ..report import generate_report_bundle
from ..strategies.base import StrategyBase


def run_strategy_backtest(
    data: pd.DataFrame,
    strategy: StrategyBase,
    config: dict | None = None,
    ticks: pd.DataFrame | None = None,
    output_dir: str | Path = "reports/backtest_report",
    export_report: bool = True,
    tick_loader=None,
) -> dict:
    cfg = dict(config or {})
    cfg.setdefault("strategy_name", strategy.name)

    prepared = strategy.prepare_indicators(data)
    signals = strategy.generate_signals(prepared)
    trades = Backtester(prepared, cfg).run(signals, ticks=ticks, tick_loader=tick_loader)

    result = {
        "data": prepared,
        "signals": signals,
        "trades": trades,
    }

    if export_report and trades is not None and not trades.empty:
        result["report"] = generate_report_bundle(
            data=prepared,
            trades=trades,
            config=cfg,
            output_dir=output_dir,
            title=f"{strategy.name} Report",
        )

    return result
