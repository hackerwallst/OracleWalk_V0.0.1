from __future__ import annotations

import pandas as pd

from backtest_core.core.engine import Backtester


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=3, freq="h"),
            "open": [1.1000, 1.1050, 1.1060],
            "high": [1.1010, 1.1100, 1.1080],
            "low": [1.0990, 1.1000, 1.1040],
            "close": [1.1005, 1.1080, 1.1050],
            "volume": [100, 120, 110],
            "spread": [1, 1, 1],
        }
    )


def _intrabar_signal() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2024-01-01 01:00:00")],
            "signal": [1],
            "entry_price": [1.1010],
            "stop_price": [1.0990],
            "take_price": [1.1090],
            "size": [1.0],
        }
    )


def test_realistic_rejects_same_bar_intrabar_entry():
    try:
        Backtester(
            _bars(), {"execution_model": "realistic", "entry_timing": "signal_close", "risk_per_trade_pct": 0.0}
        ).run(_intrabar_signal())
    except ValueError as exc:
        assert "intrabar entry_price" in str(exc)
    else:
        raise AssertionError("realistic mode accepted an impossible intrabar entry")


def test_idealized_allows_legacy_same_bar_entry():
    trades = Backtester(
        _bars(), {"execution_model": "idealized", "entry_timing": "signal_close", "risk_per_trade_pct": 0.0}
    ).run(_intrabar_signal())
    assert len(trades) == 1
    assert trades.iloc[0]["entry_time"] == pd.Timestamp("2024-01-01 01:00:00")
    assert trades.iloc[0]["entry_mid_price"] == 1.1010


def test_default_realistic_enters_next_bar_open():
    trades = Backtester(_bars(), {"risk_per_trade_pct": 0.0}).run(_intrabar_signal())
    assert len(trades) == 1
    assert trades.iloc[0]["entry_time"] == pd.Timestamp("2024-01-01 02:00:00")
    assert trades.iloc[0]["entry_mid_price"] == 1.1060
    assert trades.iloc[0]["execution_model"] == "realistic"
    assert trades.iloc[0]["order_type"] == "market"
