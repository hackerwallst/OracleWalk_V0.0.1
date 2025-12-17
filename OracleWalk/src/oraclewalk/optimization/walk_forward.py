# file: oraclewalk/optimization/walk_forward.py

from datetime import datetime, timedelta
from typing import Dict, Any, List

import pandas as pd

from oraclewalk.data.data_handler import HistoricalDataHandler
from oraclewalk.strategy.ma_rsi_strategy import MaRsiStrategy
from oraclewalk.execution.risk_manager import RiskManager
from oraclewalk.optimization.backtester import Backtester
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class WalkForwardOptimizer:
    """Otimização simples em janela rolante (walk-forward)."""

    def __init__(
        self,
        data_handler: HistoricalDataHandler,
        risk: RiskManager,
        window_days: int,
    ):
        self.dh = data_handler
        self.risk = risk
        self.window_days = window_days
        self.backtester = Backtester(risk)

    def optimize(
        self,
        end: datetime,
        ma_short_grid: List[int],
        ma_long_grid: List[int],
        rsi_buy_grid: List[float],
        rsi_sell_grid: List[float],
    ) -> Dict[str, Any]:
        start = end - timedelta(days=self.window_days)
        df = self.dh.get_ohlcv(start, end)
        if len(df) < 200:
            logger.warning("Poucos dados para otimização.")
            return {}

        best = None
        best_equity = -1e9

        for ma_s in ma_short_grid:
            for ma_l in ma_long_grid:
                if ma_s >= ma_l:
                    continue
                for rsi_b in rsi_buy_grid:
                    for rsi_s in rsi_sell_grid:
                        strat = MaRsiStrategy(
                            ma_short=ma_s,
                            ma_long=ma_l,
                            rsi_period=14,
                            rsi_buy_threshold=rsi_b,
                            rsi_sell_threshold=rsi_s,
                        )
                        original_eq = self.risk.equity
                        self.risk.equity = original_eq
                        result = self.backtester.run(df, strat)
                        self.risk.equity = original_eq

                        if result["equity_final"] > best_equity:
                            best_equity = result["equity_final"]
                            best = {
                                "ma_short": ma_s,
                                "ma_long": ma_l,
                                "rsi_buy": rsi_b,
                                "rsi_sell": rsi_s,
                                "equity_final": result["equity_final"],
                                "win_rate": result["win_rate"],
                            }

        if best:
            logger.info(f"Melhor conjunto: {best}")
        return best or {}
