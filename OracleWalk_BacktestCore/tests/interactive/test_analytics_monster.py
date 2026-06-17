"""Tests for the monstrous analytics suite: institutional metrics, per-zone edge,
live HUD, and the extended finish() payload."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backtest_core.analytics import build_full_metrics, build_zone_analytics
from backtest_core.analytics.advanced import benchmark_block, monte_carlo_block
from backtest_core.interactive import InteractiveSession
from backtest_core.interactive.zones import ZoneStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _toy_trades(n=40, seed=1):
    rng = np.random.default_rng(seed)
    pnl = rng.normal(12.0, 80.0, n)  # slight positive edge
    start = pd.Timestamp("2024-01-01")
    entry = [start + pd.Timedelta(hours=4 * i) for i in range(n)]
    exit_ = [e + pd.Timedelta(hours=3) for e in entry]
    risk = np.full(n, 40.0)
    return pd.DataFrame({
        "direction": ["long" if p >= 0 else "short" for p in pnl],
        "entry_time": entry,
        "exit_time": exit_,
        "entry_price": 1.10,
        "exit_price": 1.10 + pnl / 1e5,
        "size": 0.1,
        "pnl": pnl,
        "risk": risk,
        "risk_reward": pnl / risk,
        "result": np.where(pnl > 0, "win", np.where(pnl < 0, "loss", "be")),
        "duration": [pd.Timedelta(hours=3)] * n,
        "bars_in_trade": 3,
        "commission_open": 0.35,
        "commission_close": 0.35,
        "swap": 0.0,
        "gross_pnl": pnl,
        "max_favor": np.abs(pnl) + 5,
        "max_adverse": -(np.abs(pnl) + 5),
    })


def test_full_metrics_sections_present():
    m = build_full_metrics(_toy_trades(), 10000.0, n_bars=2000)
    for sec in ("summary", "returns", "ratios", "risk", "streaks", "robustness", "costs"):
        assert sec in m, f"missing section {sec}"
    r = m["ratios"]
    for k in ("sqn", "sharpe_annual", "sortino", "calmar", "kelly_pct", "k_ratio", "omega", "recovery_factor"):
        assert k in r
    # SQN, Sharpe etc must be finite numbers for a real series.
    assert r["sqn"] is not None and np.isfinite(r["sqn"])
    assert m["summary"]["total_trades"] == 40
    rob = m["robustness"]
    assert 0.0 <= rob["prob_profit_pct"] <= 100.0
    assert 0.0 <= rob["risk_of_ruin_pct"] <= 100.0
    assert m["returns"]["exposure_pct"] is not None
    print("ok  test_full_metrics_sections_present")


def test_full_metrics_empty_is_safe():
    m = build_full_metrics(pd.DataFrame(), 10000.0)
    assert m["summary"]["total_trades"] == 0
    assert m["summary"]["final_balance"] == 10000.0
    assert m["ratios"]["sqn"] is None
    print("ok  test_full_metrics_empty_is_safe")


def test_monte_carlo_and_benchmark_blocks():
    t = _toy_trades()
    mc = monte_carlo_block(t, 10000.0, n_sims=200)
    for mode in ("shuffle", "bootstrap", "block_bootstrap", "execution_stress"):
        assert mode in mc and "final_balance_p50" in mc[mode]
    data = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=300, freq="h"),
        "close": np.linspace(1.10, 1.12, 300),
    })
    b = benchmark_block(t, data, 10000.0)
    assert b["buy_hold"] is not None and "net_return_pct" in b["buy_hold"]
    assert b["vs"] is not None and "alpha" in b["vs"]
    print("ok  test_monte_carlo_and_benchmark_blocks")


def test_zone_respect_rate_counts_bounces_and_breaks():
    store = ZoneStore()
    store.create(0, 1.00, 1.01, "support", timeframe="H1")
    # price: dips into [1.00,1.01] then bounces up (respect), later closes below (break)
    closes = [1.05, 1.005, 1.05, 1.005, 0.995, 1.05]
    data = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=len(closes), freq="h"),
        "high": [c + 0.002 for c in closes],
        "low": [c - 0.002 for c in closes],
        "close": closes,
    })
    za = build_zone_analytics(pd.DataFrame(), store, data, n_bars=len(closes))
    z = za["by_zone"][0]
    assert z["touches"] >= 2
    assert z["breaks"] >= 1
    assert z["respect_rate"] is not None
    assert za["totals"]["zones_drawn"] == 1
    print("ok  test_zone_respect_rate_counts_bounces_and_breaks")


def test_sr_quant_links_trades_to_zone_and_hud():
    """Real strategy: a fired trade must carry zone_id; snapshot must expose HUD."""
    s = InteractiveSession.from_config(None, strategy="sr_quant", mode="SEM", symbol="EURUSD", timeframe="H1")
    info = s.session_info()
    # Draw a support zone around an early-window low so exhaustion can fire inside it.
    lows = [b["low"] for b in info["history"][-80:]]
    lo = min(lows)
    s.add_zone(price_low=lo * 0.997, price_high=lo * 1.003, side="support", timeframe=info["base_timeframe"])
    snap = None
    for _ in range(info["total_bars"]):
        snap = s.step(25)
        assert "hud" in snap and "equity_point" in snap
        assert "drawdown_pct" in snap["hud"]
        if snap["done"]:
            break
    out = s.finish()
    assert set(("metrics_full", "zone_analytics", "benchmark", "monte_carlo")).issubset(out)
    # If any trade fired, at least one must be attributed to a drawn zone.
    trades = s.engine.closed_trades
    if trades:
        linked = [t for t in trades if t.get("zone_id")]
        assert linked, "sr_quant trades must carry a zone_id"
    print("ok  test_sr_quant_links_trades_to_zone_and_hud")


if __name__ == "__main__":
    test_full_metrics_sections_present()
    test_full_metrics_empty_is_safe()
    test_monte_carlo_and_benchmark_blocks()
    test_zone_respect_rate_counts_bounces_and_breaks()
    test_sr_quant_links_trades_to_zone_and_hud()
    print("\nall monster-analytics tests passed")
