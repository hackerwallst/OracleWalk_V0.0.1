"""Engine parity armor — regression locks for the execution behaviour proven during
the MT5 parity work (June 2026). These guard the exact fixes/invariants so any future
change that breaks them fails immediately.

Self-contained and fast: tiny synthetic OHLC, NO external data/ticks. Runs under
pytest OR standalone (`python tests/test_engine_parity_armor.py`) since the venv has
no pytest.

What is locked (each maps to something we found/fixed):
  1. trailing_start_profit survives the next-bar-open shift   (the CrossTendency bug)
  2. trailing only arms AFTER the profit threshold            (no premature trailing)
  3. reject_invalid_pending drops wrong-side resting orders   (no phantom fills)
  4. a VALID resting order is still booked                    (rejection isn't over-eager)
  5. PnL scales with contract_size/point                      (multi-asset, US30/XAU)
  6. market entry = next bar open                             (timing)
  7. opposite signal closes + reverses                        (flip mechanics)
  8. SL / TP exits resolve at the declared level              (intrabar)

The heavy FVG tick parity (8/8, 7/7) stays a manual gate via the homolog scripts —
it needs the broker tick package and minutes to run, so it is not in this fast suite.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_core.core.engine import BacktestConfig, Backtester


# --------------------------------------------------------------------------- #
def _bars(prices, spread_points=0, start="2024-01-06 00:00"):
    """Hourly OHLC from a list of (open, high, low, close) tuples."""
    n = len(prices)
    dt = pd.date_range(start, periods=n, freq="h")
    o, h, l, c = zip(*prices)
    return pd.DataFrame({
        "datetime": dt, "open": o, "high": h, "low": l, "close": c,
        "volume": [100] * n, "spread": [spread_points] * n,
    })


def _cfg(**over):
    base = dict(
        initial_capital=10000.0, fixed_lot=0.1, risk_per_trade_pct=0.0,
        leverage=100.0, contract_size=100000.0, point=0.00001,
        use_spread=False, slippage=0.0, commission_per_lot=0.0,
        swap_long_per_lot=0.0, swap_short_per_lot=0.0,
        single_position_mode=True, close_on_signal="opposite",
    )
    base.update(over)
    return base


def _run(data, signals, **cfg_over):
    return Backtester(data, _cfg(**cfg_over)).run(signals)


# --------------------------------------------------------------------------- #
def test_trailing_start_profit_survives_entry_timing_shift():
    """BUG #1 guard: _apply_entry_timing must shift trailing_start_profit with the
    signal, not leave it behind as NaN (NaN broke the threshold guard → premature
    trailing). The opened trade must carry the 1% threshold."""
    data = _bars([
        (1.1000, 1.1005, 1.0995, 1.1000),
        (1.1000, 1.1010, 1.0995, 1.1005),  # entry bar (next_bar_open)
        (1.1005, 1.1015, 1.1000, 1.1010),
        (1.1010, 1.1012, 1.0980, 1.0985),  # dips, but never +1% so trailing stays off
        (1.0985, 1.0990, 1.0970, 1.0975),
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]],
        "signal": [1],
        "stop_price": [1.0950],            # initial fixed stop, far below
        "trailing_distance": [1.1000 * 0.005],
        "trailing_start_profit": [0.01],   # arm only after +1%
    })
    trades = _run(data, signals, entry_timing="next_bar_open")
    assert len(trades) == 1
    tsp = trades.iloc[0]["trailing_start_profit"]
    assert tsp is not None and not pd.isna(tsp), "threshold lost in entry-timing shift"
    assert abs(float(tsp) - 0.01) < 1e-9, f"threshold corrupted: {tsp}"


def test_trailing_does_not_arm_before_threshold():
    """With the threshold intact, a trade that never reaches +1% must NOT get a
    trailed stop — it exits on the fixed stop, not an early ratcheted one."""
    data = _bars([
        (1.1000, 1.1005, 1.0995, 1.1000),
        (1.1000, 1.1010, 1.0995, 1.1005),  # enter ~1.1000
        (1.1005, 1.1020, 1.1000, 1.1015),  # +~0.14%, well under +1%
        (1.1015, 1.1018, 1.0940, 1.0945),  # drops to fixed stop 1.0950
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]],
        "signal": [1],
        "stop_price": [1.0950],
        "trailing_distance": [1.1000 * 0.005],   # ~55 pip trail if it armed
        "trailing_start_profit": [0.01],
    })
    trades = _run(data, signals, entry_timing="next_bar_open")
    assert len(trades) == 1
    # Exit must be the fixed stop, not a trailed level near the recent high.
    assert trades.iloc[0]["exit_reason"] == "sl"
    assert abs(float(trades.iloc[0]["exit_price"]) - 1.0950) < 1e-6


def test_reject_invalid_pending_drops_wrong_side_buy_limit():
    """A buy limit placed ABOVE the market is rejected by MT5 at placement; the engine
    must not book it (no phantom fill) when reject_invalid_pending is on."""
    data = _bars([
        (1.1000, 1.1005, 1.0995, 1.1000),  # signal bar (order placed here)
        (1.1000, 1.1010, 1.0990, 1.1005),  # active bar; open 1.1000
        (1.1005, 1.1015, 1.0995, 1.1010),
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]],
        "signal": [1],
        "order_type": ["limit"],
        "entry_price": [1.1050],  # ABOVE market -> invalid buy limit
        "stop_price": [1.1000],
        "take_price": [1.1100],
    })
    trades = _run(data, signals, entry_timing="signal_close",
                  pending_order_book=True, reject_invalid_pending=True)
    assert len(trades) == 0, "wrong-side buy limit should not be booked"


def test_valid_pending_is_still_booked():
    """Rejection must not be over-eager: a VALID buy limit (below market) that the
    price trades down to must still fill."""
    data = _bars([
        (1.1000, 1.1005, 1.0995, 1.1000),  # signal bar
        (1.1000, 1.1002, 1.0940, 1.0945),  # active bar trades down through 1.0950
        (1.0945, 1.0980, 1.0940, 1.0975),
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]],
        "signal": [1],
        "order_type": ["limit"],
        "entry_price": [1.0950],  # below market -> valid buy limit
        "stop_price": [1.0900],
        "take_price": [1.1100],
    })
    trades = _run(data, signals, entry_timing="signal_close",
                  pending_order_book=True, reject_invalid_pending=True)
    assert len(trades) == 1, "valid buy limit should fill"
    assert abs(float(trades.iloc[0]["entry_price"]) - 1.0950) < 1e-6


def test_pnl_scales_with_contract_and_point_us30_like():
    """Multi-asset: PnL = (exit-entry) * size * contract_size, at any price scale.
    US30-like: contract_size=1, point=0.01, price ~42000."""
    data = _bars([
        (42000.0, 42010.0, 41990.0, 42000.0),
        (42000.0, 42010.0, 41990.0, 42000.0),  # enter at next open = 42000
        (42000.0, 42120.0, 41990.0, 42100.0),  # TP at 42100
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]],
        "signal": [1],
        "take_price": [42100.0],
        "stop_price": [41000.0],
    })
    trades = _run(data, signals, entry_timing="next_bar_open",
                  contract_size=1.0, point=0.01)
    assert len(trades) == 1
    t = trades.iloc[0]
    expected = (42100.0 - 42000.0) * float(t["size"]) * 1.0
    assert abs(float(t["pnl"]) - expected) < 1e-6, f"PnL {t['pnl']} != {expected}"


def test_market_entry_is_next_bar_open():
    data = _bars([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1060, 1.1100, 1.1050, 1.1080),  # entry = this open 1.1060
        (1.1080, 1.1090, 1.1040, 1.1050),
    ])
    signals = pd.DataFrame({"datetime": [data["datetime"].iloc[0]], "signal": [1]})
    trades = _run(data, signals, entry_timing="next_bar_open")
    assert len(trades) == 1
    assert trades.iloc[0]["entry_time"] == data["datetime"].iloc[1]
    assert abs(float(trades.iloc[0]["entry_mid_price"]) - 1.1060) < 1e-9


def test_opposite_signal_closes_and_reverses():
    data = _bars([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1005, 1.1015, 1.0995, 1.1010),  # long enters
        (1.1010, 1.1020, 1.1000, 1.1015),
        (1.1015, 1.1025, 1.1005, 1.1020),  # short enters (closes long, reverses)
        (1.1020, 1.1030, 1.1010, 1.1025),
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0], data["datetime"].iloc[2]],
        "signal": [1, -1],
    })
    trades = _run(data, signals, entry_timing="next_bar_open")
    assert len(trades) >= 1
    first = trades.iloc[0]
    assert first["direction"] == "long"
    assert first["exit_reason"] == "signal"


def test_take_profit_resolves_at_level():
    data = _bars([
        (1.1000, 1.1010, 1.0990, 1.1000),
        (1.1000, 1.1010, 1.0990, 1.1005),  # enter ~1.1000
        (1.1005, 1.1120, 1.1000, 1.1110),  # hits TP 1.1100
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]],
        "signal": [1],
        "stop_price": [1.0900],
        "take_price": [1.1100],
    })
    trades = _run(data, signals, entry_timing="next_bar_open", intrabar_mode="mt5_like_ohlc")
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "tp"
    assert abs(float(trades.iloc[0]["exit_price"]) - 1.1100) < 1e-6


def test_config_defaults_locked():
    """Lock the safety-critical defaults so they can't silently flip."""
    c = BacktestConfig()
    assert c.reject_invalid_pending is True
    assert c.pending_order_book is True
    assert c.entry_timing == "next_bar_open"
    assert c.execution_model == "realistic"
    assert c.close_on_signal == "opposite"


def test_equity_curve_exported_and_honest():
    """The engine exports a per-bar equity track; equity_low never exceeds equity, and
    the last bar's equity equals the final balance (all positions closed by EOD)."""
    data = _bars([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1005, 1.1015, 1.0995, 1.1010),  # long enters
        (1.1010, 1.1120, 1.1000, 1.1110),  # hits TP 1.1100
        (1.1110, 1.1115, 1.1090, 1.1100),
    ])
    signals = pd.DataFrame({
        "datetime": [data["datetime"].iloc[0]], "signal": [1],
        "stop_price": [1.0900], "take_price": [1.1100],
    })
    bt = Backtester(data, _cfg(entry_timing="next_bar_open"))
    trades = bt.run(signals)
    ec = bt.equity_curve
    assert len(ec) == len(data)
    assert (ec["equity_low"] <= ec["equity"] + 1e-9).all()
    final_balance = 10000.0 + float(trades["pnl"].sum())
    assert abs(float(ec["equity"].iloc[-1]) - final_balance) < 1e-6


def test_propfirm_flags_daily_loss_breach_from_intrabar():
    """Prop-firm: a >5% INTRABAR dip (green close) must still breach max daily loss —
    the rule reads equity_low, not the close (no hiding behind a recovered close)."""
    from backtest_core.analytics import prop_firm

    # Day 1 flat at 100k; day 2 dips to ~93.5k intrabar (-6.5%) then closes green.
    ec = pd.DataFrame({
        "datetime": pd.to_datetime([
            "2025-01-06 00:00", "2025-01-06 12:00",
            "2025-01-07 00:00", "2025-01-07 12:00", "2025-01-07 20:00",
        ]),
        "equity":     [100000, 100000, 100000, 94000, 100500],
        "equity_low": [100000, 100000, 100000, 93500, 96000],
    })
    daily = prop_firm.daily_frame(ec, 100000.0)
    res = prop_firm.evaluate_single(daily, prop_firm.FTMO_CHALLENGE)
    assert res["checks"]["max_daily_loss"] is False
    assert res["binding_rule"] == "max_daily_loss"
    assert res["worst_daily_dd_pct"] < -5.0


# --------------------------------------------------------------------------- #
def _main() -> int:
    tests = sorted(
        (name, obj) for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed"
          + ("" if not failed else f"  ({failed} FAILED)"))
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
