from __future__ import annotations

from pathlib import Path

import pandas as pd


def market_data_path(
    symbol: str,
    timeframe: str,
    filename: str | None = None,
    root: str | Path = "data/raw",
) -> Path:
    name = filename or f"{symbol}_{timeframe}.csv"
    return Path(root) / symbol / timeframe / name


def load_market_csv(
    symbol: str,
    timeframe: str,
    filename: str | None = None,
    root: str | Path = "data/raw",
    source: str = "generic",
) -> pd.DataFrame:
    path = market_data_path(symbol, timeframe, filename, root)
    if source.lower() == "mt5":
        return load_mt5_csv(path)
    return load_ohlcv_csv(path)


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """
    Load a CSV with at least datetime/open/high/low/close/volume.

    Common timestamp aliases are normalized automatically:
      time, timestamp, date, open_time -> datetime
    """
    df = pd.read_csv(path, sep=None, engine="python")
    aliases = {
        "time": "datetime",
        "timestamp": "datetime",
        "date": "datetime",
        "open_time": "datetime",
    }
    for old, new in aliases.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})

    required = ["datetime", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing columns: {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=required).sort_values("datetime").reset_index(drop=True)


def load_mt5_csv(path: str | Path) -> pd.DataFrame:
    """
    Load MetaTrader 5 exported OHLCV CSV.

    Expected common columns:
      time, open, high, low, close, tick_volume, spread

    Output columns:
      datetime, open, high, low, close, volume, tick_volume, spread

    MT5 spread is kept in raw points. The engine converts it to price using
    BacktestConfig.point.
    """
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [str(col).strip().lower() for col in df.columns]

    aliases = {
        "<date>": "date",
        "<time>": "time",
        "<open>": "open",
        "<high>": "high",
        "<low>": "low",
        "<close>": "close",
        "<tickvol>": "tick_volume",
        "<vol>": "volume",
        "<spread>": "spread",
    }
    df = df.rename(columns={col: aliases.get(col, col) for col in df.columns})

    if "datetime" not in df.columns:
        if "date" in df.columns and "time" in df.columns:
            df["datetime"] = df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip()
        elif "time" in df.columns:
            df["datetime"] = df["time"]
        else:
            raise ValueError("MT5 CSV must contain 'time' or '<DATE>/<TIME>' columns")

    if "volume" not in df.columns:
        if "tick_volume" in df.columns:
            df["volume"] = df["tick_volume"]
        elif "real_volume" in df.columns:
            df["volume"] = df["real_volume"]
        else:
            df["volume"] = 0

    required = ["datetime", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"MT5 CSV is missing columns: {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume", "tick_volume", "spread"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "tick_volume" in df.columns and "volume" in df.columns:
        vol = df["volume"].fillna(0)
        tick = df["tick_volume"].fillna(0)
        tick_sum = float(tick.sum())
        # Tick volume is the meaningful series for forex/CFDs — it's what MT5 charts
        # by default. The exported real volume (`<VOL>`) is mostly zero with rare
        # huge spikes, which makes the volume profile (and any volume study) useless.
        # Prefer tick volume whenever it's populated and `volume` is empty OR sparse
        # (a high fraction of zero bars — the tell-tale of real-volume forex data).
        zero_frac = float((vol == 0).mean()) if len(vol) else 1.0
        if tick_sum > 0 and (float(vol.sum()) <= 0 or zero_frac > 0.2):
            df["volume"] = df["tick_volume"]

    keep = ["datetime", "open", "high", "low", "close", "volume"]
    for optional in ["tick_volume", "real_volume", "spread"]:
        if optional in df.columns and optional not in keep:
            keep.append(optional)

    return df[keep].dropna(subset=required).sort_values("datetime").reset_index(drop=True)


def load_mt5_ticks_csv(
    path: str | Path,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    chunksize: int = 500_000,
) -> pd.DataFrame:
    """
    Load BacktestCore MT5 tick CSV exported by ExportBacktestPackage.mq5.

    Expected columns:
      time, time_msc, bid, ask, last, volume, volume_real, flags

    Also accepts direct MT5 table exports with:
      <DATE>, <TIME>, <BID>, <ASK>, <LAST>, <VOLUME>, <FLAGS>

    Output is sorted by time_msc and keeps the raw MT5 flags for later replay
    decisions.

    Fast path: if a ``ticks.parquet`` sibling exists (see ``tick_store``), it is
    used instead — a date slice loads in seconds via row-group pushdown rather than
    scanning the whole CSV.
    """
    from .tick_store import has_parquet, load_ticks_parquet, ticks_parquet_path

    if has_parquet(path):
        return load_ticks_parquet(ticks_parquet_path(path), start=start, end=end)

    if start is None and end is None:
        df = pd.read_csv(path, sep=None, engine="python")
        return _normalize_mt5_ticks_frame(df)

    frames = []
    for chunk in pd.read_csv(path, sep=None, engine="python", chunksize=chunksize):
        normalized = _normalize_mt5_ticks_frame(chunk)
        if normalized.empty:
            continue
        mask = pd.Series(True, index=normalized.index)
        if start is not None:
            mask &= normalized["datetime"] >= pd.Timestamp(start)
        if end is not None:
            end_ts = pd.Timestamp(end)
            if _is_date_only(end):
                end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            mask &= normalized["datetime"] <= end_ts
        selected = normalized.loc[mask]
        if not selected.empty:
            frames.append(selected)

    if not frames:
        return pd.DataFrame(columns=["datetime", "time_msc", "bid", "ask", "last", "volume", "volume_real", "flags"])
    return pd.concat(frames, ignore_index=True).sort_values("time_msc").reset_index(drop=True)


def _normalize_mt5_ticks_frame(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(col).strip().lower() for col in df.columns]

    aliases = {
        "<date>": "date",
        "<time>": "time",
        "<bid>": "bid",
        "<ask>": "ask",
        "<last>": "last",
        "<volume>": "volume",
        "<volume_real>": "volume_real",
        "<flags>": "flags",
    }
    df = df.rename(columns={col: aliases.get(col, col) for col in df.columns})

    if "time" not in df.columns and "date" in df.columns:
        df["time"] = df["date"]
    elif "date" in df.columns and "time" in df.columns:
        df["time"] = df["date"].astype(str).str.strip() + " " + df["time"].astype(str).str.strip()

    required = ["time", "bid", "ask"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"MT5 ticks CSV is missing columns: {missing}")

    df["datetime"] = pd.to_datetime(df["time"], errors="coerce")
    if "time_msc" in df.columns:
        df["time_msc"] = pd.to_numeric(df["time_msc"], errors="coerce")
    else:
        df["time_msc"] = df["datetime"].astype("int64") // 1_000_000
    for col in ["bid", "ask", "last", "volume", "volume_real", "flags"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["bid", "ask"]:
        if col in df.columns:
            df[col] = df[col].ffill()
    if "last" not in df.columns:
        df["last"] = 0.0
    else:
        df["last"] = df["last"].fillna(0.0)

    keep = ["datetime", "time_msc", "bid", "ask", "last"]
    for optional in ["volume", "volume_real", "flags"]:
        if optional in df.columns:
            keep.append(optional)

    required_out = ["datetime", "time_msc", "bid", "ask", "last"]
    return df[keep].dropna(subset=required_out).sort_values("time_msc").reset_index(drop=True)


def _is_date_only(value) -> bool:
    text = str(value or "").strip()
    return bool(text) and " " not in text and "T" not in text and len(text) <= 10


def add_atr(df: pd.DataFrame, period: int = 14, name: str = "atr14") -> pd.DataFrame:
    out = df.copy()
    high = out["high"]
    low = out["low"]
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out[name] = tr.rolling(period).mean()
    return out
