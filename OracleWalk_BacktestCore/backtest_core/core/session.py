from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class SessionCalendar:
    trading_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    daily_open: str = "00:00"
    daily_close: str = "23:59:59"
    rollover_start: str | None = None
    rollover_end: str | None = None
    holidays: set[date] = field(default_factory=set)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "SessionCalendar":
        cfg = dict(config or {})
        holidays = {
            pd.to_datetime(value).date()
            for value in cfg.get("holidays", [])
        }
        weekdays = tuple(int(day) for day in cfg.get("trading_weekdays", (0, 1, 2, 3, 4)))
        return cls(
            trading_weekdays=weekdays,
            daily_open=str(cfg.get("daily_open", "00:00")),
            daily_close=str(cfg.get("daily_close", "23:59:59")),
            rollover_start=cfg.get("rollover_start"),
            rollover_end=cfg.get("rollover_end"),
            holidays=holidays,
        )

    def is_open(self, dt) -> bool:
        ts = pd.to_datetime(dt)
        if ts.date() in self.holidays:
            return False
        if ts.weekday() not in self.trading_weekdays:
            return False
        current = ts.time()
        if not _contains_time(current, _parse_time(self.daily_open), _parse_time(self.daily_close)):
            return False
        if self.rollover_start and self.rollover_end:
            if _contains_time(current, _parse_time(self.rollover_start), _parse_time(self.rollover_end)):
                return False
        return True

    def next_open(self, dt, step: timedelta = timedelta(minutes=1)) -> datetime:
        current = pd.to_datetime(dt).to_pydatetime()
        limit = current + timedelta(days=14)
        while current <= limit:
            if self.is_open(current):
                return current
            current += step
        raise ValueError("No open market session found within 14 days")


def _parse_time(value: str) -> time:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return time(parts[0], parts[1])
    if len(parts) == 3:
        return time(parts[0], parts[1], parts[2])
    raise ValueError(f"Invalid time value: {value!r}")


def _contains_time(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end
