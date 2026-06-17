#!/usr/bin/env python3
"""Compare MT5 Strategy Tester trades against BacktestCore trades.

This is the validation-track comparator. It pairs trades from both sides by
entry time (greedy nearest match within a tolerance) and reports where the two
engines agree or diverge on entry price, exit price and PnL.

It does NOT try to hide divergences. Unmatched trades on either side are
reported explicitly and written to the divergences CSV.

Inputs
------
--mt5   CSV produced by ReferenceEmaCrossEA.mq5 (schema:
        ticket,side,entry_time,entry_price,exit_time,exit_price,
        lots,pnl,commission,swap,reason)
--bt    BacktestCore trades.csv (the engine's per-trade export). Relevant
        columns: direction, entry_time, entry_price, exit_time, exit_price,
        size, pnl, exit_reason.

Example
-------
    python scripts/compare_mt5_trades.py \
        --mt5 validation_cases/eurusd_h4_ema_cross/mt5_trades.csv \
        --bt  reports/EURUSD_H4_ema_cross/trades.csv \
        --price-tol 0.00002 \
        --time-tol-seconds 5 \
        --out validation_cases/eurusd_h4_ema_cross/comparison.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd


# --- column normalisation ----------------------------------------------------

def _parse_dt(series: pd.Series) -> pd.Series:
    # Accept both "2023.03.16 08:00:00" (MT5) and ISO/pandas defaults.
    return pd.to_datetime(series, errors="coerce", dayfirst=False)


def _norm_side(value) -> str:
    s = str(value).strip().lower()
    if s in {"1", "long", "buy"}:
        return "long"
    if s in {"-1", "short", "sell"}:
        return "short"
    return s


def load_mt5(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"entry_time", "entry_price", "exit_time", "exit_price", "pnl"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"MT5 CSV missing columns: {sorted(missing)}")
    out = pd.DataFrame({
        "side": df.get("side", "").map(_norm_side),
        "entry_time": _parse_dt(df["entry_time"]),
        "entry_price": pd.to_numeric(df["entry_price"], errors="coerce"),
        "exit_time": _parse_dt(df["exit_time"]),
        "exit_price": pd.to_numeric(df["exit_price"], errors="coerce"),
        "pnl": pd.to_numeric(df["pnl"], errors="coerce"),
        "reason": df.get("reason", ""),
    })
    return out.sort_values("entry_time").reset_index(drop=True)


def load_backtestcore(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"entry_time", "entry_price", "exit_time", "exit_price", "pnl"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"BacktestCore CSV missing columns: {sorted(missing)}")
    out = pd.DataFrame({
        "side": df.get("direction", "").map(_norm_side),
        "entry_time": _parse_dt(df["entry_time"]),
        "entry_price": pd.to_numeric(df["entry_price"], errors="coerce"),
        "exit_time": _parse_dt(df["exit_time"]),
        "exit_price": pd.to_numeric(df["exit_price"], errors="coerce"),
        "pnl": pd.to_numeric(df["pnl"], errors="coerce"),
        "reason": df.get("exit_reason", ""),
    })
    return out.sort_values("entry_time").reset_index(drop=True)


# --- pairing -----------------------------------------------------------------

def pair_trades(mt5: pd.DataFrame, bt: pd.DataFrame, time_tol_seconds: float):
    """Greedy nearest-entry-time pairing within tolerance, same side preferred."""
    tol = pd.Timedelta(seconds=time_tol_seconds)
    used_bt: set[int] = set()
    pairs = []
    missing_in_bt = []

    for mi, mrow in mt5.iterrows():
        best_j = None
        best_dt = None
        for bj, brow in bt.iterrows():
            if bj in used_bt:
                continue
            if pd.isna(mrow["entry_time"]) or pd.isna(brow["entry_time"]):
                continue
            delta = abs(mrow["entry_time"] - brow["entry_time"])
            if delta > tol:
                continue
            if mrow["side"] and brow["side"] and mrow["side"] != brow["side"]:
                continue
            if best_dt is None or delta < best_dt:
                best_dt = delta
                best_j = bj
        if best_j is None:
            missing_in_bt.append(mi)
        else:
            used_bt.add(best_j)
            pairs.append((mi, best_j))

    missing_in_mt5 = [bj for bj in bt.index if bj not in used_bt]
    return pairs, missing_in_bt, missing_in_mt5


def _stat(values: list[float]) -> dict:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return {"count": 0, "mean": None, "max": None}
    abs_vals = [abs(v) for v in clean]
    return {
        "count": len(clean),
        "mean_abs": sum(abs_vals) / len(abs_vals),
        "max_abs": max(abs_vals),
    }


def compare(mt5: pd.DataFrame, bt: pd.DataFrame, price_tol: float, time_tol_seconds: float):
    pairs, missing_in_bt, missing_in_mt5 = pair_trades(mt5, bt, time_tol_seconds)

    entry_diffs, exit_diffs, pnl_diffs = [], [], []
    rows = []
    price_mismatches = 0
    for mi, bj in pairs:
        m = mt5.loc[mi]
        b = bt.loc[bj]
        ed = float(m["entry_price"] - b["entry_price"]) if pd.notna(m["entry_price"]) and pd.notna(b["entry_price"]) else float("nan")
        xd = float(m["exit_price"] - b["exit_price"]) if pd.notna(m["exit_price"]) and pd.notna(b["exit_price"]) else float("nan")
        pd_ = float(m["pnl"] - b["pnl"]) if pd.notna(m["pnl"]) and pd.notna(b["pnl"]) else float("nan")
        entry_diffs.append(ed)
        exit_diffs.append(xd)
        pnl_diffs.append(pd_)
        within = (not math.isnan(ed) and abs(ed) <= price_tol) and (not math.isnan(xd) and abs(xd) <= price_tol)
        if not within:
            price_mismatches += 1
        rows.append({
            "mt5_entry_time": str(m["entry_time"]),
            "bt_entry_time": str(b["entry_time"]),
            "side": m["side"] or b["side"],
            "mt5_entry_price": m["entry_price"],
            "bt_entry_price": b["entry_price"],
            "entry_diff": ed,
            "mt5_exit_price": m["exit_price"],
            "bt_exit_price": b["exit_price"],
            "exit_diff": xd,
            "mt5_pnl": m["pnl"],
            "bt_pnl": b["pnl"],
            "pnl_diff": pd_,
            "within_price_tol": within,
            "mt5_reason": m["reason"],
            "bt_reason": b["reason"],
        })

    summary = {
        "mt5_total_trades": int(len(mt5)),
        "backtestcore_total_trades": int(len(bt)),
        "paired_trades": len(pairs),
        "missing_in_backtestcore": len(missing_in_bt),
        "missing_in_mt5": len(missing_in_mt5),
        "price_tol": price_tol,
        "time_tol_seconds": time_tol_seconds,
        "trades_outside_price_tol": price_mismatches,
        "entry_price_diff": _stat(entry_diffs),
        "exit_price_diff": _stat(exit_diffs),
        "pnl_diff": _stat(pnl_diffs),
        "mt5_total_pnl": float(mt5["pnl"].sum(skipna=True)),
        "backtestcore_total_pnl": float(bt["pnl"].sum(skipna=True)),
    }
    return summary, pd.DataFrame(rows), missing_in_bt, missing_in_mt5


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compare MT5 vs BacktestCore trades, trade by trade.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--mt5", required=True, help="Path to MT5 trades CSV (from ReferenceEmaCrossEA).")
    ap.add_argument("--bt", required=True, help="Path to BacktestCore trades.csv.")
    ap.add_argument("--price-tol", type=float, default=0.00002, help="Max abs price diff to count as a match.")
    ap.add_argument("--time-tol-seconds", type=float, default=5.0, help="Max entry-time gap to pair two trades.")
    ap.add_argument("--out", default=None, help="Optional path for comparison.json summary.")
    ap.add_argument("--divergences-csv", default=None, help="Optional path for the per-pair divergences CSV.")
    args = ap.parse_args(argv)

    mt5 = load_mt5(Path(args.mt5))
    bt = load_backtestcore(Path(args.bt))
    summary, detail, missing_in_bt, missing_in_mt5 = compare(
        mt5, bt, args.price_tol, args.time_tol_seconds
    )

    # Console report.
    print("=== MT5 vs BacktestCore ===")
    print(f"MT5 trades:          {summary['mt5_total_trades']}")
    print(f"BacktestCore trades: {summary['backtestcore_total_trades']}")
    print(f"Paired:              {summary['paired_trades']}")
    print(f"Missing in BT:       {summary['missing_in_backtestcore']}")
    print(f"Missing in MT5:      {summary['missing_in_mt5']}")
    print(f"Outside price tol:   {summary['trades_outside_price_tol']} (tol={args.price_tol})")
    for label, key in (("Entry price diff", "entry_price_diff"),
                       ("Exit price diff", "exit_price_diff"),
                       ("PnL diff", "pnl_diff")):
        s = summary[key]
        if s["count"]:
            mean_key = "mean_abs" if "mean_abs" in s else "mean"
            print(f"{label:18s} mean|Δ|={s[mean_key]:.6g}  max|Δ|={s['max_abs']:.6g}  (n={s['count']})")
    print(f"Total PnL  MT5={summary['mt5_total_pnl']:.2f}  BT={summary['backtestcore_total_pnl']:.2f}")

    div_csv = args.divergences_csv
    if div_csv is None and args.out:
        div_csv = str(Path(args.out).with_name("divergences.csv"))
    if div_csv:
        Path(div_csv).parent.mkdir(parents=True, exist_ok=True)
        detail.to_csv(div_csv, index=False)
        print(f"Divergences CSV -> {div_csv}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Summary JSON   -> {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
