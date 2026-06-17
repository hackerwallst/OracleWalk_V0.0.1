"""Generic trade-by-trade parity comparison between a BacktestCore trade export and
an MT5 EA trade export.

Strategy-agnostic: it only assumes the canonical trade schema (entry_time,
direction/side, entry_price, exit_time, exit_price, exit_reason/reason). It pairs
trades greedily by nearest entry time within a tolerance, computes per-pair deltas,
flags the FIRST divergence, and writes:
  * comparison_report.csv  — one row per paired/unpaired trade with deltas
  * comparison_summary.md   — headline counts, tolerances, first divergence

Usage:
  python scripts/parity_compare.py --py reports/parity/python_tick_trades.csv \
      --mt5 ".../FVG_..._trades.csv" --out reports/parity \
      --start 2026-05-01 --end 2026-05-19 \
      --price-tol 0.00010 --time-tol 120
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

_MT5_TIME = "%Y.%m.%d %H:%M:%S"


def _norm_dir(value) -> str:
    s = str(value).strip().lower()
    if s in {"1", "buy", "long"}:
        return "long"
    if s in {"-1", "sell", "short"}:
        return "short"
    return s


def _parse_time(series: pd.Series) -> pd.Series:
    # MT5 exports use dotted dates; BacktestCore uses ISO. Try both.
    out = pd.to_datetime(series, format=_MT5_TIME, errors="coerce")
    if out.isna().all():
        out = pd.to_datetime(series, errors="coerce")
    else:
        fallback = pd.to_datetime(series, errors="coerce")
        out = out.fillna(fallback)
    return out


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    direction = cols.get("direction") or cols.get("side")
    reason = cols.get("exit_reason") or cols.get("reason")
    # Prefer the trigger mid when present (lets us compare entry logic without spread).
    entry_mid = cols.get("entry_mid_price")
    out = pd.DataFrame({
        "entry_time": _parse_time(df[cols["entry_time"]]),
        "direction": df[direction].map(_norm_dir),
        "entry_price": pd.to_numeric(df[cols["entry_price"]], errors="coerce"),
        "exit_time": _parse_time(df[cols["exit_time"]]),
        "exit_price": pd.to_numeric(df[cols["exit_price"]], errors="coerce"),
        "reason": df[reason].astype(str).str.lower() if reason else "",
    })
    out["entry_mid"] = pd.to_numeric(df[entry_mid], errors="coerce") if entry_mid else out["entry_price"]
    return out.sort_values("entry_time").reset_index(drop=True)


def _slice(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if start:
        df = df[df["entry_time"] >= pd.Timestamp(start)]
    if end:
        df = df[df["entry_time"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)


def pair_trades(py: pd.DataFrame, mt5: pd.DataFrame, time_tol_s: float) -> list[dict]:
    """Greedy nearest-entry-time pairing within tolerance, preserving chronology."""
    used_mt5: set[int] = set()
    rows: list[dict] = []
    mt5_times = mt5["entry_time"].to_numpy()
    for _, p in py.iterrows():
        best, best_dt = None, None
        for j in range(len(mt5)):
            if j in used_mt5:
                continue
            dt = abs((p["entry_time"] - mt5_times[j]) / np.timedelta64(1, "s"))
            if dt <= time_tol_s and (best_dt is None or dt < best_dt):
                best, best_dt = j, dt
        if best is None:
            rows.append({"status": "py_only", "py": p, "mt5": None, "dt": None})
        else:
            used_mt5.add(best)
            rows.append({"status": "paired", "py": p, "mt5": mt5.iloc[best], "dt": best_dt})
    for j in range(len(mt5)):
        if j not in used_mt5:
            rows.append({"status": "mt5_only", "py": None, "mt5": mt5.iloc[j], "dt": None})
    # chronological by whichever side exists
    rows.sort(key=lambda r: (r["py"]["entry_time"] if r["py"] is not None else r["mt5"]["entry_time"]))
    return rows


def build_report(rows: list[dict], price_tol: float, time_tol_s: float) -> pd.DataFrame:
    out = []
    for r in rows:
        p, m = r["py"], r["mt5"]
        rec = {"status": r["status"], "entry_dt_s": r["dt"]}
        rec["py_entry_time"] = None if p is None else p["entry_time"]
        rec["mt5_entry_time"] = None if m is None else m["entry_time"]
        rec["py_dir"] = None if p is None else p["direction"]
        rec["mt5_dir"] = None if m is None else m["direction"]
        rec["py_entry_mid"] = None if p is None else p["entry_mid"]
        rec["mt5_entry"] = None if m is None else m["entry_price"]
        rec["py_entry_px"] = None if p is None else p["entry_price"]
        rec["py_exit_px"] = None if p is None else p["exit_price"]
        rec["mt5_exit_px"] = None if m is None else m["exit_price"]
        rec["py_reason"] = None if p is None else p["reason"]
        rec["mt5_reason"] = None if m is None else m["reason"]
        if r["status"] == "paired":
            rec["entry_mid_delta"] = abs(p["entry_mid"] - m["entry_price"])
            rec["entry_px_delta"] = abs(p["entry_price"] - m["entry_price"])
            rec["exit_px_delta"] = abs(p["exit_price"] - m["exit_price"]) if pd.notna(p["exit_price"]) and pd.notna(m["exit_price"]) else np.nan
            rec["exit_dt_s"] = abs((p["exit_time"] - m["exit_time"]) / pd.Timedelta(seconds=1)) if pd.notna(p["exit_time"]) and pd.notna(m["exit_time"]) else np.nan
            rec["dir_match"] = p["direction"] == m["direction"]
            rec["reason_match"] = p["reason"] == m["reason"]
            rec["ok"] = bool(
                rec["dir_match"] and rec["reason_match"]
                and rec["entry_mid_delta"] <= price_tol
                and (np.isnan(rec["exit_px_delta"]) or rec["exit_px_delta"] <= price_tol)
            )
        else:
            rec["ok"] = False
        out.append(rec)
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", required=True)
    ap.add_argument("--mt5", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--price-tol", type=float, default=0.00010)  # 1.0 pip on a 5-digit FX
    ap.add_argument("--time-tol", type=float, default=120.0)     # entry pairing tolerance (s)
    args = ap.parse_args()

    py = _slice(_load(Path(args.py)), args.start, args.end)
    mt5 = _slice(_load(Path(args.mt5)), args.start, args.end)

    rows = pair_trades(py, mt5, args.time_tol)
    report = build_report(rows, args.price_tol, args.time_tol)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report.to_csv(out_dir / "comparison_report.csv", index=False)

    paired = report[report["status"] == "paired"]
    n_ok = int(paired["ok"].sum())
    first_div = report[~report["ok"]].head(1)

    lines = []
    lines.append("# Execution Parity — Comparison Summary\n")
    lines.append(f"- Window: **{args.start or 'all'} .. {args.end or 'all'}**")
    lines.append(f"- Tolerances: price ≤ **{args.price_tol}** ({args.price_tol/0.0001:.1f} pips), "
                 f"entry pairing ≤ **{args.time_tol:.0f}s**")
    lines.append(f"- BacktestCore trades: **{len(py)}**  |  MT5 trades: **{len(mt5)}**")
    lines.append(f"- Paired: **{len(paired)}**  |  within tolerance: **{n_ok}/{len(paired)}**")
    lines.append(f"- Unpaired — py_only: **{int((report['status']=='py_only').sum())}**, "
                 f"mt5_only: **{int((report['status']=='mt5_only').sum())}**")
    if len(paired):
        lines.append(f"- Max entry-mid Δ: **{paired['entry_mid_delta'].max():.6f}**  |  "
                     f"max exit-px Δ: **{paired['exit_px_delta'].max():.6f}**  |  "
                     f"max exit-time Δ: **{paired['exit_dt_s'].max():.0f}s**")
    lines.append("")
    if first_div.empty:
        lines.append("**No divergence** — every trade pairs within tolerance, "
                     "same direction and exit reason. ✅")
    else:
        r = first_div.iloc[0]
        lines.append("## First divergence\n")
        lines.append(f"- status: **{r['status']}**")
        lines.append(f"- py entry: {r['py_entry_time']} {r['py_dir']} mid={r['py_entry_mid']}")
        lines.append(f"- mt5 entry: {r['mt5_entry_time']} {r['mt5_dir']} px={r['mt5_entry']}")
        if r["status"] == "paired":
            lines.append(f"- entry_mid Δ={r['entry_mid_delta']:.6f}, exit_px Δ={r['exit_px_delta']:.6f}, "
                         f"exit_time Δ={r['exit_dt_s']}s, dir_match={r['dir_match']}, "
                         f"reason_match={r['reason_match']}")
    (out_dir / "comparison_summary.md").write_text("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"\nWrote {out_dir/'comparison_report.csv'} and {out_dir/'comparison_summary.md'}")


if __name__ == "__main__":
    main()
