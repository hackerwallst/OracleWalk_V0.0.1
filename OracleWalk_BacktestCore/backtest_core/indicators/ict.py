from __future__ import annotations

import pandas as pd


def detect_fvg(
    df: pd.DataFrame,
    filter_percent: float = 0.5,
) -> pd.DataFrame:
    """
    Three-candle Fair Value Gap detector.

    Returns columns:
      index, type, top, bottom, mid, gap_pct
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    rows = []

    for i in range(2, len(df)):
        h0, h1, h2 = highs[i - 2], highs[i - 1], highs[i]
        l0, l1, l2 = lows[i - 2], lows[i - 1], lows[i]

        gap_up_pct = ((l2 - h0) / l2 * 100.0) if l2 else 0.0
        if h0 < l2 and h0 < h1 and l0 < l2 and gap_up_pct > filter_percent:
            top = float(l2)
            bottom = float(h0)
            rows.append(
                {
                    "index": i,
                    "type": "bullish",
                    "top": top,
                    "bottom": bottom,
                    "mid": (top + bottom) / 2.0,
                    "gap_pct": float(gap_up_pct),
                }
            )

        gap_down_pct = ((l0 - h2) / l0 * 100.0) if l0 else 0.0
        if l0 > h2 and l0 > l1 and h0 > h2 and gap_down_pct > filter_percent:
            top = float(l0)
            bottom = float(h2)
            rows.append(
                {
                    "index": i,
                    "type": "bearish",
                    "top": top,
                    "bottom": bottom,
                    "mid": (top + bottom) / 2.0,
                    "gap_pct": float(gap_down_pct),
                }
            )

    return pd.DataFrame(rows, columns=["index", "type", "top", "bottom", "mid", "gap_pct"])


def detect_orderblocks(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    rows = []
    swing_high = df["high"].rolling(lookback).max()
    swing_low = df["low"].rolling(lookback).min()

    for i in range(lookback, len(df)):
        close = df["close"].iloc[i]
        if close > swing_high.iloc[i - 1]:
            for j in range(i - 1, max(i - 1 - lookback, 0), -1):
                if df["close"].iloc[j] < df["open"].iloc[j]:
                    top = max(df["open"].iloc[j], df["close"].iloc[j])
                    bottom = min(df["open"].iloc[j], df["close"].iloc[j])
                    rows.append({"index": j, "type": "bullish", "top": top, "bottom": bottom, "mid": (top + bottom) / 2})
                    break
        elif close < swing_low.iloc[i - 1]:
            for j in range(i - 1, max(i - 1 - lookback, 0), -1):
                if df["close"].iloc[j] > df["open"].iloc[j]:
                    top = max(df["open"].iloc[j], df["close"].iloc[j])
                    bottom = min(df["open"].iloc[j], df["close"].iloc[j])
                    rows.append({"index": j, "type": "bearish", "top": top, "bottom": bottom, "mid": (top + bottom) / 2})
                    break

    return pd.DataFrame(rows, columns=["index", "type", "top", "bottom", "mid"])
