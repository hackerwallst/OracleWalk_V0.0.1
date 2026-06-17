"""Fast tick storage: convert the giant MT5 ticks.csv to Parquet and read date
slices from it in seconds (row-group statistics → predicate pushdown).

The huge ticks.csv (10+ GB) is read once, chunk by chunk, and written as a
column-compressed Parquet file with one row group per chunk. Because MT5 exports
ticks chronologically, the row groups are time-ordered, so a date-range read only
touches the matching row groups instead of scanning the whole file.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Columns kept in the Parquet store (the engine only needs datetime/bid/ask; the
# rest is carried for completeness/tick flags).
_TICK_COLS = ["datetime", "time_msc", "bid", "ask", "last", "volume", "volume_real", "flags"]


def ticks_parquet_path(csv_path: str | Path) -> Path:
    """The Parquet sibling for a ticks.csv (same folder, .parquet extension)."""
    return Path(csv_path).with_suffix(".parquet")


def has_parquet(csv_path: str | Path) -> bool:
    p = ticks_parquet_path(csv_path)
    return p.exists() and p.stat().st_size > 0


def convert_ticks_csv_to_parquet(
    csv_path: str | Path,
    parquet_path: str | Path | None = None,
    chunksize: int = 2_000_000,
    compression: str = "zstd",
    progress: bool = True,
) -> Path:
    """Stream a ticks.csv into a Parquet file (one row group per chunk).

    Reads with the fast C parser. Returns the Parquet path. One-time cost: reads
    the whole CSV once; afterwards every date slice loads in seconds.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from .loaders import _normalize_mt5_ticks_frame

    csv_path = Path(csv_path)
    out = Path(parquet_path) if parquet_path else ticks_parquet_path(csv_path)
    tmp = out.with_suffix(".parquet.tmp")

    # Separator auto-detect: ExportBacktestPackage writes comma-separated
    # (time,time_msc,bid,ask,…); a raw MT5 table export is TAB-separated
    # (<DATE>\t<TIME>\t<BID>\t<ASK>…). Peek the header line to pick the parser sep.
    with open(csv_path, "r") as _fh:
        _header = _fh.readline()
    sep = "\t" if _header.count("\t") > _header.count(",") else ","

    writer = None
    total = 0
    schema = None
    try:
        reader = pd.read_csv(csv_path, sep=sep, chunksize=chunksize)
        for n, chunk in enumerate(reader):
            norm = _normalize_mt5_ticks_frame(chunk)
            for col in _TICK_COLS:
                if col not in norm.columns:
                    norm[col] = 0
            frame = norm[_TICK_COLS].copy()
            frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
            for c in ("time_msc", "volume", "flags"):
                frame[c] = pd.to_numeric(frame[c], errors="coerce").fillna(0).astype("int64")
            for c in ("bid", "ask", "last", "volume_real"):
                frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
            frame = frame.dropna(subset=["datetime"])
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                schema = table.schema
                writer = pq.ParquetWriter(tmp, schema, compression=compression)
            else:
                table = table.cast(schema)
            writer.write_table(table)
            total += len(frame)
            if progress:
                print(f"  chunk {n + 1}: +{len(frame):,} ticks (total {total:,})", flush=True)
    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        raise ValueError(f"no ticks parsed from {csv_path}")
    tmp.replace(out)
    if progress:
        print(f"Parquet pronto: {out}  ({total:,} ticks, {out.stat().st_size / 1e6:.1f} MB)", flush=True)
    return out


def load_ticks_parquet(
    parquet_path: str | Path,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read a tick slice from Parquet with row-group pushdown on `datetime`.

    By default only the columns the backtest engine and the chart replay actually
    use are loaded (``datetime``, ``time_msc``, ``bid``, ``ask``); ``volume``,
    ``last``, ``volume_real`` and ``flags`` are skipped. That roughly halves the
    memory footprint, so the full tick history fits in RAM instead of swapping.
    """
    import pyarrow.parquet as pq

    from .loaders import _is_date_only

    filters = []
    if start is not None:
        filters.append(("datetime", ">=", pd.Timestamp(start)))
    if end is not None:
        end_ts = pd.Timestamp(end)
        if isinstance(end, str) and _is_date_only(end):
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        filters.append(("datetime", "<=", end_ts))

    if columns is None:
        columns = ["datetime", "time_msc", "bid", "ask"]
    available = set(pq.ParquetFile(parquet_path).schema.names)
    cols = [c for c in columns if c in available] or None

    df = pd.read_parquet(parquet_path, engine="pyarrow", filters=filters or None, columns=cols)
    if "time_msc" in df.columns:
        df = df.sort_values("time_msc")
    return df.reset_index(drop=True)
