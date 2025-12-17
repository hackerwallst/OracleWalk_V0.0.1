# file: oraclewalk/storage/database.py

import sqlite3
import threading
from typing import Optional
import pandas as pd
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class DatabaseManager:
    """Persistência básica de trades e equity em SQLite."""

    def __init__(self, db_path: str = "oraclewalk.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._create_tables()

    def _create_tables(self) -> None:
        cur = self.conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            pnl REAL,
            opened_at TEXT,
            closed_at TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS equity_curve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            equity REAL
        )
        """)

        self.conn.commit()

    def insert_trade(self, symbol: str, side: str, entry_price: float,
                     exit_price: float, quantity: float, pnl: float,
                     opened_at: str, closed_at: str) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO trades
                (symbol, side, entry_price, exit_price, quantity, pnl, opened_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, side, entry_price, exit_price, quantity, pnl, opened_at, closed_at)
            )
            self.conn.commit()

    def insert_equity(self, timestamp: str, equity: float) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO equity_curve (timestamp, equity) VALUES (?, ?)",
                (timestamp, equity)
            )
            self.conn.commit()

    def export_equity_csv(self, path: str = "equity_curve.csv") -> None:
        df = pd.read_sql_query("SELECT * FROM equity_curve", self.conn)
        df.to_csv(path, index=False)
        logger.info(f"Equity curve exportada para {path}")
