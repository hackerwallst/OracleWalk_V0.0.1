import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from oraclewalk.config.config_loader import AppConfig


class ConfigLoaderTest(unittest.TestCase):
    def test_reads_key_value_file(self):
        with TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.txt"
            cfg_path.write_text(
                "\n".join(
                    [
                        "binance_api_key=FILE_KEY",
                        "binance_api_secret=FILE_SECRET",
                        "telegram_token=FILE_TG",
                        "telegram_chat_id=123",
                        "initial_balance=2500",
                        "symbols=BTCUSDT,ETHUSDT",
                        "mode=backtest",
                        "risk_per_trade=2.5",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = AppConfig.from_sources(str(cfg_path))

            self.assertEqual(cfg.binance_api_key, "FILE_KEY")
            self.assertEqual(cfg.binance_api_secret, "FILE_SECRET")
            self.assertEqual(cfg.telegram_token, "FILE_TG")
            self.assertEqual(cfg.telegram_chat_id, "123")
            self.assertEqual(cfg.symbols, ["BTCUSDT", "ETHUSDT"])
            self.assertEqual(cfg.mode, "backtest")
            self.assertAlmostEqual(cfg.initial_balance, 2500)
            self.assertAlmostEqual(cfg.risk_per_trade, 2.5)

    def test_environment_overrides_file(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "BINANCE_API_KEY": "ENV_KEY",
                "MODE": "live",
                "SYMBOLS": "ADAUSDT",
                "RISK_PER_TRADE": "5",
            },
            clear=False,
        ):
            cfg_path = Path(tmp) / "config.txt"
            cfg_path.write_text(
                "\n".join(
                    [
                        "binance_api_key=FILE_KEY",
                        "binance_api_secret=FILE_SECRET",
                        "telegram_token=FILE_TG",
                        "telegram_chat_id=123",
                    ]
                ),
                encoding="utf-8",
            )

            cfg = AppConfig.from_sources(str(cfg_path))

            self.assertEqual(cfg.binance_api_key, "ENV_KEY")
            self.assertEqual(cfg.mode, "live")
            self.assertEqual(cfg.symbols, ["ADAUSDT"])
            self.assertAlmostEqual(cfg.risk_per_trade, 5.0)


if __name__ == "__main__":
    unittest.main()
