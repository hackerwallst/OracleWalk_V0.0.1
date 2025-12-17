# file: oraclewalk/data/data_handler.py

from datetime import datetime
from typing import Optional
import pandas as pd
from binance.client import Client
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class HistoricalDataHandler:
    """Carrega OHLCV histórico da Binance."""

    def __init__(self, client: Client, symbol: str, timeframe: str):
        self.client = client
        self.symbol = symbol
        self.timeframe = timeframe

    def get_ohlcv(self, start: datetime, end: Optional[datetime] = None) -> pd.DataFrame:
        start_str = start.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end.strftime("%Y-%m-%d %H:%M:%S") if end else None

        logger.info(f"Baixando histórico {self.symbol} [{self.timeframe}] {start_str} -> {end_str}")
        klines = self.client.get_historical_klines(
            symbol=self.symbol,
            interval=self.timeframe,
            start_str=start_str,
            end_str=end_str
        )

        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
        ]
        df = pd.DataFrame(klines, columns=cols)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")

        df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
        df = df.rename(columns={"open_time": "datetime"})

        numeric_cols = ["open", "high", "low", "close", "volume"]
        for c in numeric_cols:
            df[c] = df[c].astype(float)

        df.set_index("datetime", inplace=True)
        return df
