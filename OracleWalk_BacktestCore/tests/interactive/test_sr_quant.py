"""Tests for the S&R Quant 0.2.0 Python port (single-TF v1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from backtest_core.data import load_mt5_csv
from backtest_core.interactive import InteractiveSession
from backtest_core.interactive.strategies import SRQuantStrategy
from backtest_core.interactive.strategies.sr_quant import (
    stochastic_slowed_k,
    ultimate_oscillator_atr,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EURUSD_CSV = PROJECT_ROOT / "data" / "raw" / "EURUSD" / "H1" / "EURUSD_H1.csv"


def _toy_df(n=120):
    rng = np.random.default_rng(3)
    close = np.linspace(1.20, 1.00, n) + rng.normal(0, 0.0005, n)
    high = close + 0.001
    low = close - 0.001
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="h"),
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_indicators_bounds():
    df = _toy_df()
    uo = ultimate_oscillator_atr(df)
    stoch = stochastic_slowed_k(df)
    uo_valid = uo.dropna()
    stoch_valid = stoch.dropna()
    assert len(uo_valid) > 50 and len(stoch_valid) > 50
    assert (uo_valid >= -1).all() and (uo_valid <= 101).all()
    assert (stoch_valid >= -1).all() and (stoch_valid <= 101).all()
    # A long decline should leave the stochastic oversold near the end.
    assert stoch_valid.iloc[-1] < 40
    print("ok  test_indicators_bounds")


def test_indicator_thresholds_match_strategy_constants():
    s = SRQuantStrategy(mode="SEM")
    assert s.indicator_thresholds() == {
        "rsi": {"oversold": s.RSI_BUY, "overbought": s.RSI_SELL},
        "stoch_k": {"oversold": s.STOCH_BUY, "overbought": s.STOCH_SELL},
        "uo": {"oversold": s.UO_BUY, "overbought": s.UO_SELL},
    }
    print("ok  test_indicator_thresholds_match_strategy_constants")


def _ctx(close, rsi, stoch, uo, zones, mode_bar_index=10, open_trades=None, recent_closed=None):
    window = pd.DataFrame(
        {"close": [close, close, close], "sma60": [close + 1, close + 1, close + 1]}
    )
    return SimpleNamespace(
        bar_index=mode_bar_index,
        bar=SimpleNamespace(close=close, datetime=pd.Timestamp("2024-01-01 10:00")),
        window=window,
        zones=zones,
        open_trades=open_trades or [],
        indicators={"rsi": rsi, "stoch_k": stoch, "uo": uo},
        recent_closed=recent_closed or [],
    )


def test_sem_entry_buy():
    s = SRQuantStrategy(mode="SEM")
    zone = {"id": "z1", "side": "support", "price_low": 0.99, "price_high": 1.01, "created_at_bar": 0, "state": "active"}
    # Candle replay has no intrabar tick after opening the EA's waiting window,
    # so SEM must fire on the same candle where exhaustion + zone are present.
    intent = s.on_bar(_ctx(1.00, 20, 10, 25, [zone], mode_bar_index=10))
    assert intent is not None and intent.signal == 1
    assert intent.stop_price < 1.00 < intent.take_price
    assert "SEM" in intent.comment
    # SL = zmin - 50% height = 0.99 - 0.5*0.02 = 0.98 ; TP = close + 3*risk
    assert abs(intent.stop_price - 0.98) < 1e-9
    print("ok  test_sem_entry_buy")


def test_com_requires_sma():
    s = SRQuantStrategy(mode="COM")
    zone = {"id": "z1", "side": "resistance", "price_low": 1.09, "price_high": 1.11, "created_at_bar": 0, "state": "active"}
    # Resistance exhaustion. window sma60 = close+1, so close is BELOW sma -> sell confirm holds.
    intent = s.on_bar(_ctx(1.10, 80, 90, 75, [zone], mode_bar_index=10))
    assert intent is not None and intent.signal == -1 and "COM" in intent.comment
    print("ok  test_com_requires_sma")


def test_cooldown_blocks_after_sl():
    s = SRQuantStrategy(mode="SEM")
    zone = {"id": "z1", "side": "support", "price_low": 0.99, "price_high": 1.01, "created_at_bar": 0, "state": "active"}
    closed = [{"direction": "long", "exit_reason": "sl", "exit_time": pd.Timestamp("2024-01-01 09:30")}]
    # SL closed 30 min ago -> 4h cooldown active -> no entry even with exhaustion.
    assert s.on_bar(_ctx(1.00, 20, 10, 25, [zone], mode_bar_index=10, recent_closed=closed)) is None
    assert s.on_bar(_ctx(1.00, 20, 10, 25, [zone], mode_bar_index=11)) is None
    print("ok  test_cooldown_blocks_after_sl")


def test_full_replay_runs():
    data = load_mt5_csv(EURUSD_CSV)
    strat = SRQuantStrategy(mode="AMBOS")
    session = InteractiveSession(
        data=data,
        strategy=strat,
        config={"initial_capital": 10000.0, **strat.engine_overrides()},
        symbol="EURUSD",
        timeframe="H1",
    )
    # Draw broad S/R zones covering the price range so touches can happen.
    mid = float(session.engine.bar_dict(session.engine.cursor)["close"])
    session.add_zone(price_low=mid - 0.02, price_high=mid, side="support")
    session.add_zone(price_low=mid, price_high=mid + 0.02, side="resistance")
    steps = 0
    while not session.step(1)["done"]:
        steps += 1
        if steps > 10000:
            break
    result = session.finish()
    assert "metrics" in result
    print(f"ok  test_full_replay_runs (trades={result['metrics'].get('trades', 0)})")


def main():
    test_indicators_bounds()
    test_indicator_thresholds_match_strategy_constants()
    test_sem_entry_buy()
    test_com_requires_sma()
    test_cooldown_blocks_after_sl()
    test_full_replay_runs()
    print("\nALL S&R QUANT TESTS PASSED")


if __name__ == "__main__":
    main()
