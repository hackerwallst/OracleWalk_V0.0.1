import unittest
import pandas as pd

from oraclewalk.optimization.backtester import Backtester
from oraclewalk.execution.risk_manager import RiskManager


class _DummyCfg:
    initial_balance = 1000
    risk_per_trade = 1


class _DummyDB:
    pass


class _DummyStrategy:
    def __init__(self, signal_value=0):
        self.signal_value = signal_value

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"signal": [self.signal_value] * len(df)})


class BacktesterTest(unittest.TestCase):
    def setUp(self):
        cfg = _DummyCfg()
        db = _DummyDB()
        self.risk = RiskManager(cfg, db)

    def test_uses_price_from_input_df(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="h")
        data = pd.DataFrame(
            {
                "close": [100, 105, 95],
                "open": [99, 104, 96],
                "high": [101, 106, 97],
                "low": [98, 103, 94],
                "volume": [1, 1, 1],
            },
            index=idx,
        )
        strat = _DummyStrategy(signal_value=1)  # sempre compra

        bt = Backtester(self.risk)
        result = bt.run(data, strat)

        self.assertIn("equity_final", result)
        self.assertGreater(result["equity_final"], 0)


if __name__ == "__main__":
    unittest.main()
