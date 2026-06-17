from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class StrategyBase(ABC):
    name = "Unnamed Strategy"

    @classmethod
    def robustness_space(cls) -> dict | None:
        """Return sweep config for the robustness battery, or None to skip sweeps.

        Keys: space, sensitivity_param, sensitivity_values, grid_x, grid_y.
        """
        return None

    def prepare_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        return data.copy()

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Return a signals DataFrame.

        Required columns:
          datetime, signal

        Optional columns:
          order_type, entry_price, stop_price, take_price, size, risk, trailing_distance, comment

        `order_type` may be "market", "limit", or "stop". In the default
        realistic execution model, explicit intrabar prices must be declared as
        limit/stop orders or shifted to a future executable bar.
        """
