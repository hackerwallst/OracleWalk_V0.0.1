"""Convert MT5 ticks.csv files to Parquet for fast date-sliced tick backtests.

Usage:
  python scripts/convert_ticks_to_parquet.py <path/to/ticks.csv>     # one file
  python scripts/convert_ticks_to_parquet.py <path/to/package_dir>   # finds ticks.csv
  python scripts/convert_ticks_to_parquet.py --all                   # every broker_export ticks.csv

The huge CSV is read once; afterwards `load_mt5_ticks_csv` uses the Parquet sibling
automatically (a date slice loads in seconds instead of scanning 10+ GB).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backtest_core.data.tick_store import convert_ticks_csv_to_parquet, ticks_parquet_path  # noqa: E402


def _resolve_csvs(target: str | None, do_all: bool) -> list[Path]:
    if do_all:
        return sorted((ROOT / "data" / "broker_exports").rglob("ticks.csv"))
    if not target:
        raise SystemExit("informe um ticks.csv, uma pasta de pacote, ou --all")
    p = Path(target)
    if not p.is_absolute():
        p = ROOT / p
    if p.is_dir():
        return [p / "ticks.csv"] if (p / "ticks.csv").exists() else sorted(p.rglob("ticks.csv"))
    return [p]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="ticks.csv, pasta do pacote, ou vazio com --all")
    ap.add_argument("--all", action="store_true", help="converte todos os ticks.csv em data/broker_exports")
    ap.add_argument("--force", action="store_true", help="reconverte mesmo se o .parquet já existir")
    ap.add_argument("--chunksize", type=int, default=2_000_000)
    args = ap.parse_args(argv)

    csvs = _resolve_csvs(args.target, args.all)
    if not csvs:
        raise SystemExit("nenhum ticks.csv encontrado")

    for csv in csvs:
        if not csv.exists():
            print(f"SKIP (não existe): {csv}")
            continue
        out = ticks_parquet_path(csv)
        if out.exists() and not args.force:
            print(f"SKIP (parquet já existe): {out}  — use --force pra refazer")
            continue
        size_gb = csv.stat().st_size / 1e9
        print(f"\n== Convertendo {csv}  ({size_gb:.1f} GB) ==")
        t = time.time()
        convert_ticks_csv_to_parquet(csv, out, chunksize=args.chunksize)
        print(f"   tempo: {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
