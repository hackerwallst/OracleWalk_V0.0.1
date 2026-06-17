"""End-to-end + unit checks for the interactive replay track (Phase 1).

Runs standalone (``python tests/interactive/test_interactive.py``) since the venv
has no pytest yet; also discoverable by pytest later (test_* functions).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backtest_core.interactive import InteractiveSession, ZoneStore, ZoneTouchStub


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = str(PROJECT_ROOT / "configs" / "mt5_eurusd_h1.json")


def test_zone_store_causality():
    """A zone must not exist before the bar where it was drawn."""
    store = ZoneStore()
    zid = store.create(bar_index=100, price_low=1.10, price_high=1.11, side="support")

    assert store.active_zones(99) == [], "zone leaked into the past (lookahead!)"
    active = store.active_zones(100)
    assert len(active) == 1 and active[0]["id"] == zid
    assert active[0]["created_at_bar"] == 100

    # Edit at bar 150 only applies from 150 onward.
    store.update(zid, bar_index=150, fields={"price_low": 1.105, "price_high": 1.115})
    assert store.active_zones(120)[0]["price_low"] == 1.10
    assert store.active_zones(150)[0]["price_low"] == 1.105

    # Delete at bar 200 only applies from 200 onward.
    store.delete(zid, bar_index=200)
    assert len(store.active_zones(199)) == 1
    assert store.active_zones(200) == []
    print("ok  test_zone_store_causality")


def test_zone_store_orders_prices():
    store = ZoneStore()
    zid = store.create(bar_index=0, price_low=1.20, price_high=1.10, side="resistance")
    zone = store.active_zones(0)[0]
    assert zone["price_low"] == 1.10 and zone["price_high"] == 1.20
    assert zone["side"] == "resistance"
    print("ok  test_zone_store_orders_prices")


def _make_session() -> InteractiveSession:
    # Phase 1 tests exercise the engine via the simple zone-touch stub.
    return InteractiveSession.from_config(CONFIG, strategy="stub")


def test_session_loads_and_steps():
    s = _make_session()
    info = s.session_info()
    assert info["total_bars"] > 10
    assert info["cursor"] == s.engine.warmup - 1
    assert len(info["history"]) == info["cursor"] + 1

    snap = s.step(1)
    assert snap["cursor"] == info["cursor"] + 1
    assert len(snap["bars"]) == 1
    assert snap["balance"] == s.config["initial_capital"]
    print("ok  test_session_loads_and_steps")


def test_replay_trades_and_reports():
    """Draw a zone around the current price; the stub should enter, and finish
    must produce a report with at least one trade."""
    s = _make_session()
    s.step(5)
    close = s.engine.bar_dict(s.engine.cursor)["close"]
    eps = close * 0.0008
    s.add_zone(price_low=close - eps, price_high=close + eps, side="support")

    # Step forward enough bars for an entry and an SL/TP exit to occur.
    opened = False
    for _ in range(400):
        snap = s.step(1)
        if snap["open_trades"]:
            opened = True
        if snap["done"]:
            break
    assert opened, "stub never entered despite a zone around price"

    result = s.finish()
    assert result["metrics"]["trades"] >= 1, "no trades finalized"
    if result["report_dir"] is not None:
        assert (Path(result["report_dir"]) / "trades.csv").exists()
    print(f"ok  test_replay_trades_and_reports (trades={result['metrics']['trades']})")


def test_zone_not_visible_before_creation_in_engine():
    """Causality through the engine: stub cannot trade on a zone drawn 'now' for
    bars already in the past."""
    s = _make_session()
    s.step(10)
    cursor_at_draw = s.engine.cursor
    close = s.engine.bar_dict(cursor_at_draw)["close"]
    s.add_zone(price_low=close - 1, price_high=close + 1, side="support")  # huge zone
    # The zone is stamped at cursor_at_draw; earlier bars never saw it.
    assert s.zones.active_zones(cursor_at_draw - 1) == []
    assert len(s.zones.active_zones(cursor_at_draw)) == 1
    print("ok  test_zone_not_visible_before_creation_in_engine")


def main():
    test_zone_store_causality()
    test_zone_store_orders_prices()
    test_session_loads_and_steps()
    test_zone_not_visible_before_creation_in_engine()
    test_replay_trades_and_reports()
    print("\nALL INTERACTIVE TESTS PASSED")


if __name__ == "__main__":
    main()
