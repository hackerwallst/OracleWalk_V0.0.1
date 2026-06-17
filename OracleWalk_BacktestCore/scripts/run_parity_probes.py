"""Run the deterministic parity probes through the engine and export their trades.

These probes (backtest_core/strategies/parity_probes.py) trigger only on exact,
feed-robust quantities (datetime, bar index, exact daily H/L/C) so any divergence
vs the MT5 EA port is unambiguously the ENGINE — not indicators or data noise.

Each probe is run with the engine config its order type requires (market probes
enter next-bar-open; pending probes rest from the signal bar). Costs are OFF by
default (phase 1: prove the mechanics; then re-run with --costs for the full stack).

Output: one canonical trade CSV per probe under <out>/<probe>_py_trades.csv, ready
to feed scripts/parity_compare.py against the MT5 export:

  python scripts/run_parity_probes.py --data "data/broker_exports/.../candles.csv" \
      --start 2025-01-01 --end 2026-01-01 --out reports/parity_probes
  python scripts/parity_compare.py --py reports/parity_probes/p2_daily_breakout_py_trades.csv \
      --mt5 ".../P2_DailyBreakout_trades.csv" --out reports/parity_probes/p2
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from backtest_core.analytics.metrics import compute_metrics
from backtest_core.core.engine import Backtester
from backtest_core.data.loaders import load_mt5_ticks_csv
from backtest_core.optimization.objective import evaluate
from backtest_core.strategies.parity_probes import (
    P1ClockFlip,
    P2DailyBreakout,
    P3DailyLimitFade,
    P4WeeklyTrailing,
    P5NBarAlternator,
)


def make_tick_loader(ticks_path: str, win_s, win_e):
    """Stream ticks one engine-chunk (calendar month) at a time, bounded to the
    test window. Uses the ticks.parquet sibling automatically (fast date slice)."""
    def loader(cs, ce):
        s = pd.Timestamp(cs) if win_s is None else max(pd.Timestamp(cs), win_s)
        e = pd.Timestamp(ce) if win_e is None else min(pd.Timestamp(ce), win_e)
        if s > e:
            return None
        return load_mt5_ticks_csv(ticks_path, start=s, end=e)
    return loader

# (key, class, entry_timing) — market probes shift to next bar; pending probes rest.
PROBES = [
    ("p1_clock_flip",      P1ClockFlip,      "next_bar_open"),
    ("p2_daily_breakout",  P2DailyBreakout,  "signal_close"),
    ("p3_daily_limit_fade", P3DailyLimitFade, "signal_close"),
    ("p4_weekly_trailing", P4WeeklyTrailing, "next_bar_open"),
    ("p5_nbar_alternator", P5NBarAlternator, "next_bar_open"),
]

_EXPORT_COLS = [
    "entry_time", "direction", "entry_price", "entry_mid_price",
    "stop_price", "take_price", "exit_time", "exit_price", "exit_reason", "pnl",
]


def load_symbol_spec(data_path: Path) -> dict:
    """Read the broker symbol_spec.json sitting next to the candles, if present, so
    point/contract_size adapt to the asset (EURUSD 5-digit vs an index vs a metal)."""
    spec_path = data_path.parent / "symbol_spec.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text())
        return {
            "point": float(spec.get("point", 0.00001)),
            "contract_size": float(spec.get("contract_size", 100000.0)),
            "symbol": spec.get("symbol", data_path.parent.parent.name),
        }
    return {"point": 0.00001, "contract_size": 100000.0, "symbol": "UNKNOWN"}


def probe_kwargs(key: str, point: float, place_hour: int, dist_mult: float) -> dict:
    """Per-probe constructor args adapted to the asset: the session hour the order is
    placed (FX opens 00:00, an index may open 01:00) and a distance multiplier that
    scales the point-based SL/TP/offset so they stay meaningful at the asset's scale.
    The MT5 EA must use the SAME inputs (InpPlaceHour, InpSlPoints*dist_mult, …)."""
    m = dist_mult
    if key == "p1_clock_flip":
        return {"entry_hour": place_hour}
    if key == "p2_daily_breakout":
        return {"place_hour": place_hour, "point": point,
                "buffer_points": 10 * m, "sl_points": 200 * m, "tp_points": 400 * m}
    if key == "p3_daily_limit_fade":
        return {"place_hour": place_hour, "point": point,
                "offset_points": 150 * m, "sl_points": 200 * m, "tp_points": 300 * m}
    if key == "p4_weekly_trailing":
        return {"entry_hour": place_hour, "point": point,
                "init_stop_points": 300 * m, "trailing_distance_points": 150 * m,
                "trailing_start_points": 100 * m}
    return {}  # p5_nbar_alternator: timestamp-anchored, no asset params


def load_candles(path: Path) -> pd.DataFrame:
    """Load an MT5-style candles export (dotted datetime, tick_volume)."""
    df = pd.read_csv(path)
    if "time" in df.columns:
        df = df.rename(columns={"time": "datetime"})
    if "tick_volume" in df.columns:
        df = df.rename(columns={"tick_volume": "volume"})
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y.%m.%d %H:%M", errors="coerce")
    if df["datetime"].isna().any():
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    return df[["datetime", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)


def base_config(costs: bool, tick: bool, point: float, contract_size: float) -> dict:
    cfg = dict(
        initial_capital=10000.0,
        fixed_lot=0.1,
        risk_per_trade_pct=0.0,     # fixed-lot audit, not %-risk
        leverage=100.0,             # so 0.1 lot fits margin (FTMO-like)
        close_on_signal="opposite",
        single_position_mode=True,
        intrabar_mode="mt5_like_ohlc",
        point=point,
        contract_size=contract_size,
    )
    if tick:
        # Tick mode uses the real bid/ask from ticks for fills (matches MT5 "every
        # tick"), so the spread is already baked in — don't add a synthetic one.
        cfg["execution_mode"] = "tick"
        cfg.update(use_spread=False, slippage=0.0)
        cfg.update(commission_per_lot=(3.5 if costs else 0.0),
                   swap_long_per_lot=(-7.0 if costs else 0.0),
                   swap_short_per_lot=(2.0 if costs else 0.0))
    elif costs:
        cfg.update(use_spread=True, fixed_spread_points=8.0, commission_per_lot=3.5,
                   swap_long_per_lot=-7.0, swap_short_per_lot=2.0)
    else:
        cfg.update(use_spread=False, slippage=0.0, commission_per_lot=0.0,
                   swap_long_per_lot=0.0, swap_short_per_lot=0.0)
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="Path to the candles CSV (same bars MT5 will test).")
    ap.add_argument("--out", default="reports/parity_probes")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--costs", action="store_true", help="Turn on spread/commission/swap (phase 2).")
    ap.add_argument("--tick", action="store_true", help="Tick execution vs candle (apples-to-apples with MT5 'every tick').")
    ap.add_argument("--ticks", default=None, help="Path to ticks.csv (parquet sibling used if present). Required with --tick.")
    ap.add_argument("--only", default=None, help="Comma-separated probe keys to run (default: all).")
    ap.add_argument("--place-hour", type=int, default=0, help="Session hour orders are placed (FX=0; an index may open 1). Must exist in the data.")
    ap.add_argument("--dist-mult", type=float, default=1.0, help="Scale the point-based SL/TP/offset for the asset (EURUSD=1; ~50 for US30). EA inputs must match.")
    args = ap.parse_args()

    if args.tick and not args.ticks:
        ap.error("--tick requires --ticks <path to ticks.csv>")

    spec = load_symbol_spec(Path(args.data))
    df = load_candles(Path(args.data))
    if args.start:
        df = df[df["datetime"] >= pd.Timestamp(args.start)]
    if args.end:
        df = df[df["datetime"] <= pd.Timestamp(args.end)]
    df = df.reset_index(drop=True)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    win_s = pd.Timestamp(args.start) if args.start else None
    win_e = pd.Timestamp(args.end) if args.end else None
    tick_loader = make_tick_loader(args.ticks, win_s, win_e) if args.tick else None

    print(f"Asset: {spec['symbol']} | point={spec['point']} contract={spec['contract_size']} | "
          f"place_hour={args.place_hour} dist_mult={args.dist_mult}")
    print(f"Data: {df['datetime'].min()} -> {df['datetime'].max()} | bars: {len(df)} | "
          f"mode: {'TICK' if args.tick else 'candle'} | costs: {'ON' if args.costs else 'OFF'}\n")

    for key, cls, timing in PROBES:
        if only and key not in only:
            continue
        cfg = base_config(args.costs, args.tick, spec["point"], spec["contract_size"])
        cfg["entry_timing"] = timing
        strat = cls(**probe_kwargs(key, spec["point"], args.place_hour, args.dist_mult))
        t0 = time.time()
        if args.tick:
            prepared = strat.prepare_indicators(df)
            signals = strat.generate_signals(prepared)
            trades = Backtester(prepared, cfg).run(signals, tick_loader=tick_loader)
            metrics = compute_metrics(trades, float(cfg["initial_capital"]))
        else:
            trades, metrics = evaluate(strat, df, cfg)
        elapsed = time.time() - t0
        path = out_dir / f"{key}_py_trades.csv"
        if len(trades):
            cols = [c for c in _EXPORT_COLS if c in trades.columns]
            trades[cols].to_csv(path, index=False)
            reasons = dict(trades["exit_reason"].value_counts())
        else:
            pd.DataFrame(columns=_EXPORT_COLS).to_csv(path, index=False)
            reasons = {}
        print(f"{cls.name:20s} [{timing:13s}] trades={len(trades):4d} "
              f"net={metrics.get('net_profit', 0):+9.2f} reasons={reasons} ({elapsed:.0f}s)")
        print(f"  -> {path}")


if __name__ == "__main__":
    main()
