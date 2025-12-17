# file: oraclewalk/execution/trade_logger.py

import os
import csv
from typing import Any


class ProTradeLogger:
    """
    Logger PRO:
    - trades.csv (histórico completo)
    - logs/trades_YYYY-MM-DD.csv (histórico diário)
    Inclui:
      - preço bruto (raw) e executado
      - volume em USDT
      - comissão em USDT
      - PnL no preço bruto (mid) e PnL real (execução)
    Tudo protegido com try/except para nunca quebrar o engine.
    """

    def __init__(self, main_filename: str = "trades.csv", log_dir: str = "logs") -> None:
        self.main_filename = main_filename
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        self._ensure_main_header()
        self._counter = self._load_existing_count()

    # -----------------------------------------------------
    def _ensure_main_header(self) -> None:
        if os.path.exists(self.main_filename):
            return

        try:
            with open(self.main_filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "id",
                        "open_time",
                        "close_time",
                        "symbol",
                        "side",
                        "entry_raw",
                        "entry_exec",
                        "close_raw",
                        "close_exec",
                        "quantity",
                        "notional_entry_exec",
                        "notional_close_exec",
                        "commission_usdt",
                        "pnl_mid",
                        "pnl_exec",
                    ]
                )
        except Exception:
            pass

    # -----------------------------------------------------
    def _load_existing_count(self) -> int:
        try:
            if not os.path.exists(self.main_filename):
                return 0
            with open(self.main_filename, "r") as f:
                total = sum(1 for _ in f) - 1  # header
                return max(total, 0)
        except Exception:
            return 0

    # -----------------------------------------------------
    def _ensure_daily_file(self, date_str: str) -> str:
        path = os.path.join(self.log_dir, f"trades_{date_str}.csv")
        if not os.path.exists(path):
            try:
                with open(path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            "id",
                            "open_time",
                            "close_time",
                            "symbol",
                            "side",
                            "entry_raw",
                            "entry_exec",
                            "close_raw",
                            "close_exec",
                            "quantity",
                            "notional_entry_exec",
                            "notional_close_exec",
                            "commission_usdt",
                            "pnl_mid",
                            "pnl_exec",
                        ]
                    )
            except Exception:
                pass
        return path

    # -----------------------------------------------------
    @staticmethod
    def _extract_date(iso_ts: str) -> str:
        if not iso_ts:
            return ""
        for sep in ("T", " "):
            if sep in iso_ts:
                return iso_ts.split(sep)[0]
        return iso_ts[:10]

    # -----------------------------------------------------
    def _safe_get(self, obj: Any, attr: str, default: Any) -> Any:
        try:
            return getattr(obj, attr, default)
        except Exception:
            return default

    # -----------------------------------------------------
    def log_trade(self, pos, cfg) -> None:
        """
        Registra um trade encerrado em:
        - trades.csv
        - logs/trades_YYYY-MM-DD.csv

        Espera que o executor tenha preenchido:
          - pos.opened_at, pos.closed_at
          - pos.symbol, pos.side
          - pos.entry_price  (preço executado)
          - pos.quantity
          - pos.pnl          (PnL real)
        E de preferência:
          - pos.entry_raw
          - pos.close_raw
          - pos.close_exec
        """
        try:
            self._counter += 1

            open_time = self._safe_get(pos, "opened_at", "")
            close_time = self._safe_get(pos, "closed_at", "")
            symbol = self._safe_get(pos, "symbol", "")
            side = self._safe_get(pos, "side", "")

            entry_exec = self._safe_get(pos, "entry_price", 0.0)
            close_exec = self._safe_get(pos, "close_exec", entry_exec)

            entry_raw = self._safe_get(pos, "entry_raw", entry_exec)
            close_raw = self._safe_get(pos, "close_raw", close_exec)

            qty = self._safe_get(pos, "quantity", 0.0)
            pnl_exec = self._safe_get(pos, "pnl", 0.0)

            # comissões (aproximação): aplica comissão de taker na entrada e saída
            com_taker_pct = 0.0
            try:
                com_taker_pct = float(getattr(cfg, "commission_taker", 0.0)) / 100.0
            except Exception:
                com_taker_pct = 0.0

            notional_entry_exec = entry_exec * qty
            notional_close_exec = close_exec * qty

            commission_usdt = (
                notional_entry_exec * com_taker_pct
                + notional_close_exec * com_taker_pct
            )

            # PnL no preço "mid" bruto (sem execução realista)
            if str(side).lower() in ("buy", "long"):
                pnl_mid = (close_raw - entry_raw) * qty
            else:
                pnl_mid = (entry_raw - close_raw) * qty

            # arquivo diário
            date_str = self._extract_date(open_time)
            daily_path = self._ensure_daily_file(date_str) if date_str else None

            row = [
                self._counter,
                open_time,
                close_time,
                symbol,
                side,
                entry_raw,
                entry_exec,
                close_raw,
                close_exec,
                qty,
                notional_entry_exec,
                notional_close_exec,
                commission_usdt,
                pnl_mid,
                pnl_exec,
            ]

            # trades.csv
            try:
                with open(self.main_filename, "a", newline="") as f:
                    csv.writer(f).writerow(row)
            except Exception:
                pass

            # logs/trades_YYYY-MM-DD.csv
            if daily_path:
                try:
                    with open(daily_path, "a", newline="") as f:
                        csv.writer(f).writerow(row)
                except Exception:
                    pass

        except Exception:
            # Nunca quebra o engine
            pass
