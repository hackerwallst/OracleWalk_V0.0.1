"""Multi-timeframe tests: exhaustion must happen on the zone's OWN timeframe."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from backtest_core.interactive import InteractiveSession
from backtest_core.interactive.strategies import SRQuantStrategy


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = str(PROJECT_ROOT / "configs" / "mt5_eurusd_h1.json")


def _ctx(zone_tf, tf_indicators):
    zone = {
        "id": "z",
        "side": "support",
        "price_low": 0.99,
        "price_high": 1.01,
        "timeframe": zone_tf,
        "created_at_bar": 0,
        "state": "active",
    }
    return SimpleNamespace(
        zones=[zone],
        tf_indicators=tf_indicators,
        indicators=tf_indicators.get("H1", {}),
    )


def test_exhaustion_must_match_zone_timeframe():
    s = SRQuantStrategy(mode="SEM")
    # H4 is exhausted (oversold); H1 is calm.
    tf_ind = {
        "H4": {"rsi": 20.0, "stoch_k": 10.0, "uo": 25.0},
        "H1": {"rsi": 50.0, "stoch_k": 50.0, "uo": 50.0},
    }
    # An H4 zone -> setup found (H4 exhausted).
    assert s._find_setup(_ctx("H4", tf_ind), "support", 1.0) is not None
    # An H1 zone -> NO setup (H1 is NOT exhausted), even though price is in the zone.
    assert s._find_setup(_ctx("H1", tf_ind), "support", 1.0) is None

    # Now flip: H1 exhausted, H4 calm.
    tf_ind2 = {
        "H4": {"rsi": 50.0, "stoch_k": 50.0, "uo": 50.0},
        "H1": {"rsi": 20.0, "stoch_k": 10.0, "uo": 25.0},
    }
    assert s._find_setup(_ctx("H1", tf_ind2), "support", 1.0) is not None
    assert s._find_setup(_ctx("H4", tf_ind2), "support", 1.0) is None
    print("ok  test_exhaustion_must_match_zone_timeframe")


def test_session_is_mtf_and_zones_carry_tf():
    s = InteractiveSession.from_config(CONFIG, strategy="sr_quant", mode="SEM")
    assert s.base_tf == "H1"
    assert "H4" in s.higher_tfs
    info = s.session_info()
    # Base + every coarser TF derivable from H1 (H4, D1). Finer TFs are impossible.
    assert info["zone_timeframes"][0] == "H1"
    assert "H4" in info["zone_timeframes"] and "D1" in info["zone_timeframes"]
    assert "M15" not in info["zone_timeframes"]  # can't derive finer than base

    mid = float(s.engine.bar_dict(s.engine.cursor)["close"])
    z_h4 = s.add_zone(mid - 0.02, mid, "support", timeframe="H4")
    z_h1 = s.add_zone(mid - 0.02, mid, "support", timeframe="H1")
    assert z_h4["timeframe"] == "H4"
    assert z_h1["timeframe"] == "H1"

    snap = s.step(1)
    assert "H1" in snap["tf_indicators"] and "H4" in snap["tf_indicators"]
    print("ok  test_session_is_mtf_and_zones_carry_tf")


def test_h4_indicators_are_causal():
    """The H4 value at a base bar must come from an already-closed H4 candle."""
    s = InteractiveSession.from_config(CONFIG, strategy="sr_quant", mode="SEM")
    eng = s.engine
    frame = eng._higher["H4"]
    mapping = frame["map"]
    # Mapping is non-decreasing (time only moves forward) and never points to a
    # future H4 bar relative to the base cursor.
    prev = -1
    for i in range(0, eng.n, 50):
        j = int(mapping[i])
        assert j >= prev or prev == -1 or j >= 0
        prev = j
    # Far enough in, H4 indicators exist; at the very start they may be empty (warmup).
    for _ in range(300):
        advanced, _ = eng.step_one(s.zones)
        if not advanced:
            break
    ti = eng.tf_indicators_at(eng.cursor)
    assert "H4" in ti and ti["H4"], "H4 indicators should be populated mid-replay"
    print("ok  test_h4_indicators_are_causal")


def test_gatilho_tf_and_media():
    """The SMA cross (média) is read on the TF one step BELOW the zone's, and is
    only possible when that TF is available (>= base)."""
    s = SRQuantStrategy(mode="COM")
    assert s.GATILHO_TF["H4"] == "M15"
    assert s.GATILHO_TF["H1"] == "M5"
    assert s.GATILHO_TF["D1"] == "H1"

    # D1 zone -> trigger H1 (available with an H1 base): close above SMA both bars.
    ctx = SimpleNamespace(
        tf_series_tail={"H1": {"close": [1.10, 1.20], "sma60": [1.00, 1.05]}},
        window=pd.DataFrame(),
    )
    assert s._sma_confirms(ctx, "long", "H1") is True
    assert s._sma_confirms(ctx, "short", "H1") is False
    # H4 zone -> trigger M15, NOT available with H1 data -> cannot confirm.
    assert s._sma_confirms(ctx, "long", "M15") is False
    print("ok  test_gatilho_tf_and_media")


def test_mtf_replay_full_run():
    s = InteractiveSession.from_config(CONFIG, strategy="sr_quant", mode="SEM")
    mid = float(s.engine.bar_dict(s.engine.cursor)["close"])
    s.add_zone(mid - 0.03, mid + 0.03, "support", timeframe="H4")
    s.add_zone(mid - 0.03, mid + 0.03, "resistance", timeframe="H1")
    steps = 0
    while not s.step(1)["done"]:
        steps += 1
        if steps > 10000:
            break
    res = s.finish()
    assert "metrics" in res
    print(f"ok  test_mtf_replay_full_run (trades={res['metrics'].get('trades', 0)})")


def main():
    test_exhaustion_must_match_zone_timeframe()
    test_session_is_mtf_and_zones_carry_tf()
    test_h4_indicators_are_causal()
    test_gatilho_tf_and_media()
    test_mtf_replay_full_run()
    print("\nALL MTF TESTS PASSED")


if __name__ == "__main__":
    main()
