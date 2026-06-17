from __future__ import annotations

import pandas as pd


def performance_by_hour(trades: pd.DataFrame) -> pd.DataFrame:
    df = trades.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["hour"] = df["entry_time"].dt.hour
    return df.groupby("hour")["pnl"].agg(["count", "sum", "mean"]).reset_index()


def performance_by_weekday(trades: pd.DataFrame) -> pd.DataFrame:
    df = trades.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["weekday"] = df["entry_time"].dt.weekday
    return df.groupby("weekday")["pnl"].agg(["count", "sum", "mean"]).reset_index()


def performance_by_month(trades: pd.DataFrame) -> pd.DataFrame:
    df = trades.copy()
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["month"] = df["exit_time"].dt.to_period("M").astype(str)
    return df.groupby("month")["pnl"].agg(["count", "sum", "mean"]).reset_index()
