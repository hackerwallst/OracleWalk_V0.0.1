from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class DataQualityReport:
    rows: int
    duplicate_datetimes: int
    null_ohlcv_rows: int
    invalid_candles: int
    gaps: int | None = None

    @property
    def ok(self) -> bool:
        return (
            self.duplicate_datetimes == 0
            and self.null_ohlcv_rows == 0
            and self.invalid_candles == 0
            and (self.gaps in (None, 0))
        )


def validate_ohlcv(df: pd.DataFrame, expected_freq: str | None = None) -> DataQualityReport:
    data = df.copy()
    if "datetime" not in data.columns and isinstance(data.index, pd.DatetimeIndex):
        data = data.reset_index().rename(columns={"index": "datetime"})

    required = ["datetime", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"data is missing columns: {missing}")

    data["datetime"] = pd.to_datetime(data["datetime"])
    duplicates = int(data["datetime"].duplicated().sum())
    null_rows = int(data[required].isna().any(axis=1).sum())
    invalid = int(((data["high"] < data[["open", "close", "low"]].max(axis=1)) | (data["low"] > data[["open", "close", "high"]].min(axis=1))).sum())

    gaps = None
    if expected_freq:
        ordered = data.drop_duplicates("datetime").sort_values("datetime")
        expected = pd.date_range(ordered["datetime"].min(), ordered["datetime"].max(), freq=expected_freq)
        gaps = int(len(expected.difference(pd.DatetimeIndex(ordered["datetime"]))))

    return DataQualityReport(
        rows=len(data),
        duplicate_datetimes=duplicates,
        null_ohlcv_rows=null_rows,
        invalid_candles=invalid,
        gaps=gaps,
    )
