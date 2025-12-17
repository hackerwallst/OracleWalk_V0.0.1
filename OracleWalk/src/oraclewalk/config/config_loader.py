"""Configuration loading utilities."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from binance.client import Client
from dotenv import load_dotenv

DEFAULT_CONFIG_FILE = "config.txt"


def _load_kv_file(path: Path) -> Dict[str, str]:
    """Reads key=value pairs ignoring comments and blank lines."""
    data: Dict[str, str] = {}
    if not path.exists():
        return data

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def _env(key: str) -> str:
    """Returns the first non-empty env var among KEY / ORACLEWALK_KEY."""
    for env_key in (key.upper(), f"ORACLEWALK_{key.upper()}"):
        val = os.getenv(env_key)
        if val is not None and str(val).strip() != "":
            return val
    return ""


@dataclass
class AppConfig:
    """In-memory configuration used by the trading engine."""

    binance_api_key: str
    binance_api_secret: str
    telegram_token: str
    telegram_chat_id: str

    initial_balance: float = 10_000.0
    slippage: float = 0.1
    commission_maker: float = 0.02
    commission_taker: float = 0.04
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT"])
    leverage: int = 1
    risk_per_trade: float = 1.0
    ma_short_period: int = 10
    ma_long_period: int = 50
    rsi_period: int = 14
    rsi_buy_threshold: float = 55.0
    rsi_sell_threshold: float = 45.0
    timeframe: str = "1m"
    mode: str = "backtest"  # ou live
    optimization_window_days: int = 30
    reoptimize_interval_days: int = 7
    use_futures: bool = False
    dry_run: bool = True

    @classmethod
    def from_sources(cls, config_path: str | None = None) -> "AppConfig":
        """
        Loads configuration with the following precedence:
        1) Environment variables (.env is loaded automatically)
        2) key=value file (default: config.txt or path passed)

        Environment vars accepted: BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_TOKEN,
        TELEGRAM_CHAT_ID, SYMBOLS, TIMEFRAME, MODE, INITIAL_BALANCE, RISK_PER_TRADE,
        SLIPPAGE, COMMISSION_MAKER, COMMISSION_TAKER, MA_SHORT_PERIOD, MA_LONG_PERIOD,
        RSI_PERIOD, RSI_BUY_THRESHOLD, RSI_SELL_THRESHOLD, OPTIMIZATION_WINDOW_DAYS,
        REOPTIMIZE_INTERVAL_DAYS, USE_FUTURES, DRY_RUN, LEVERAGE.
        """
        load_dotenv()

        cfg_path = (
            Path(config_path)
            if config_path
            else Path(os.getenv("ORACLEWALK_CONFIG") or DEFAULT_CONFIG_FILE)
        )
        file_data = _load_kv_file(cfg_path)

        def get_str(key: str, default: str = "") -> str:
            return _env(key) or file_data.get(key, default)

        def get_float(key: str, default: float) -> float:
            try:
                raw = get_str(key, default)
                return float(raw)
            except Exception:
                return default

        def get_int(key: str, default: int) -> int:
            try:
                raw = get_str(key, default)
                return int(raw)
            except Exception:
                return default

        def get_bool(key: str, default: bool) -> bool:
            raw = get_str(key, str(default)).lower()
            return raw in ("1", "true", "yes", "y", "on")

        symbols_str = get_str("symbols", "BTCUSDT")
        symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

        return cls(
            binance_api_key=get_str("binance_api_key"),
            binance_api_secret=get_str("binance_api_secret"),
            telegram_token=get_str("telegram_token"),
            telegram_chat_id=get_str("telegram_chat_id"),
            initial_balance=get_float("initial_balance", 10_000.0),
            slippage=get_float("slippage", 0.1),
            commission_maker=get_float("commission_maker", 0.02),
            commission_taker=get_float("commission_taker", 0.04),
            symbols=symbols,
            leverage=get_int("leverage", 1),
            risk_per_trade=get_float("risk_per_trade", 1.0),
            ma_short_period=get_int("ma_short_period", 10),
            ma_long_period=get_int("ma_long_period", 50),
            rsi_period=get_int("rsi_period", 14),
            rsi_buy_threshold=get_float("rsi_buy_threshold", 55.0),
            rsi_sell_threshold=get_float("rsi_sell_threshold", 45.0),
            timeframe=get_str("timeframe", "1m"),
            mode=get_str("mode", "backtest").lower(),
            optimization_window_days=get_int("optimization_window_days", 30),
            reoptimize_interval_days=get_int("reoptimize_interval_days", 7),
            use_futures=get_bool("use_futures", False),
            dry_run=get_bool("dry_run", True),
        )

    @staticmethod
    def from_file(path: str = DEFAULT_CONFIG_FILE) -> "AppConfig":
        """
        Backward-compatible loader that only reads from a key=value file.
        Prefer AppConfig.from_sources for env + file support.
        """
        return AppConfig.from_sources(config_path=path)

    def get_client(self):
        """
        Retorna o cliente Binance pronto para uso em modo histórico/backtest.
        """
        return Client(self.binance_api_key, self.binance_api_secret)
