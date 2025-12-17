# file: oraclewalk/execution/trade_executor.py

import time
from datetime import datetime
from typing import Optional
import json
import os

from binance.client import Client

from oraclewalk.config.config_loader import AppConfig
from oraclewalk.execution.order_model import Position
from oraclewalk.execution.risk_manager import RiskManager
from oraclewalk.notifications.telegram_notifier import TelegramNotifier
from oraclewalk.storage.database import DatabaseManager
from oraclewalk.utils.logger import setup_logger

from oraclewalk.execution.trade_logger import ProTradeLogger
from oraclewalk.execution.execution_price_model import ExecutionPriceModel

logger = setup_logger(__name__)


class TradeExecutor:
    """
    Executor de trades:
    - Modo live: envia ordens reais (se dry_run=False)
    - Modo simulação: apenas loga (dry_run=True)
    - Integra com DashboardServer para desenhar trades no OracleView.
    """

    def __init__(
        self,
        cfg: AppConfig,
        risk_manager: RiskManager,
        database: DatabaseManager,
        notifier: TelegramNotifier,
        dashboard=None,
    ):
        self.cfg = cfg
        self.risk = risk_manager
        self.db = database
        self.notifier = notifier
        self.dashboard = dashboard

        self.client: Client = cfg.get_client()

        # posição atual (None se não tiver nada aberto)
        self.current_position: Optional[Position] = None

        # modelo de execução realista
        self.exec_price_model = ExecutionPriceModel(
            slippage_pct=self.cfg.slippage,
            commission_maker=self.cfg.commission_maker,
            commission_taker=self.cfg.commission_taker,
        )

        # logger PRO de trades
        self.trade_logger = ProTradeLogger()
        # persistência de posição aberta
        self._persist_path = os.path.join(os.getcwd(), "open_position.json")

    # ========== HELPERS ==========

    def _fmt_price(self, value: float) -> str:
        try:
            return f"{float(value):,.2f}"
        except Exception:
            return str(value)

    def _fmt_time(self, dt: datetime) -> str:
        try:
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return str(dt)

    def _fmt_msg_open(self, side: str, symbol: str, entry: float, sl: float, tp: float, dt: datetime) -> str:
        side_norm = side.lower()
        is_long = side_norm in ("buy", "long")
        emoji_side = "🟩" if is_long else "🟥"
        label = "LONG" if is_long else "SHORT"
        return (
            f"🚀 {label} ABERTO {emoji_side}\n"
            f"• Símbolo: {symbol}\n"
            f"• Entrada: {self._fmt_price(entry)}\n"
            f"• Stop Loss 🛑: {self._fmt_price(sl)}\n"
            f"• Take Profit 🎯: {self._fmt_price(tp)}\n"
            f"• Hora ⏰: {self._fmt_time(dt)}"
        )

    def _fmt_msg_close(self, reason: str, symbol: str, side: str, close_price: float, pnl: float, dt: datetime) -> str:
        emoji_side = "🟩" if side.lower() in ("buy", "long") else "🟥"
        return (
            f"🏁 POSIÇÃO FECHADA {emoji_side}\n"
            f"• Motivo: {reason}\n"
            f"• Símbolo: {symbol}\n"
            f"• Side: {side.upper()}\n"
            f"• Saída: {self._fmt_price(close_price)}\n"
            f"• PnL: {self._fmt_price(pnl)}\n"
            f"• Hora ⏰: {self._fmt_time(dt)}"
        )

    def _safe_db_call(self, method_name: str, *args, **kwargs):
        fn = getattr(self.db, method_name, None)
        if callable(fn):
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.warning(f"[DB] Erro em {method_name}: {e}")

    # ========== PERSISTÊNCIA ==========
    def _persist_open_position(self):
        """Salva posição aberta em disco para recuperação após restart."""
        if self.current_position is None:
            return
        try:
            data = {
                "symbol": self.current_position.symbol,
                "side": self.current_position.side,
                "quantity": float(self.current_position.quantity),
                "entry_price": float(self.current_position.entry_price),
                "stop_loss": float(self.current_position.stop_loss) if self.current_position.stop_loss else None,
                "take_profit": float(self.current_position.take_profit) if self.current_position.take_profit else None,
                "opened_at": self.current_position.opened_at,
                "risk_balance": getattr(self.risk, "current_balance", None),
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"[PERSIST] Falha ao salvar posição: {e}")

    def _clear_persisted_position(self):
        try:
            if os.path.exists(self._persist_path):
                os.remove(self._persist_path)
        except Exception as e:
            logger.warning(f"[PERSIST] Falha ao limpar posição salva: {e}")

    def restore_position_from_disk(self, last_price: float = None, last_dt: Optional[datetime] = None):
        """
        Recupera posição aberta salva em disco. Se já tiver posição, não faz nada.
        Se last_price for fornecido e SL/TP já tiverem sido atingidos, fecha imediatamente.
        """
        if self.current_position is not None:
            return
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            symbol = data.get("symbol")
            side = data.get("side")
            qty = float(data.get("quantity", 0))
            entry = float(data.get("entry_price", 0))
            sl = data.get("stop_loss")
            tp = data.get("take_profit")
            opened_at = data.get("opened_at") or datetime.utcnow().isoformat()
            risk_balance = data.get("risk_balance")

            if risk_balance is not None and hasattr(self.risk, "current_balance"):
                try:
                    self.risk.current_balance = float(risk_balance)
                except Exception:
                    pass

            pos = Position(
                symbol=symbol,
                side=side,
                quantity=qty,
                entry_price=entry,
                stop_loss=sl,
                take_profit=tp,
                opened_at=opened_at,
            )
            self.current_position = pos

            # Se já atingiu SL/TP enquanto estava offline, fecha imediatamente
            if last_price is not None:
                if side == "buy":
                    if sl and last_price <= sl:
                        self.close_position(
                            symbol,
                            sl,
                            last_dt or datetime.utcnow(),
                            reason="Recovered SL/TP"
                        )
                        return
                    if tp and last_price >= tp:
                        self.close_position(
                            symbol,
                            tp,
                            last_dt or datetime.utcnow(),
                            reason="Recovered SL/TP"
                        )
                        return
                else:
                    if sl and last_price >= sl:
                        self.close_position(
                            symbol,
                            sl,
                            last_dt or datetime.utcnow(),
                            reason="Recovered SL/TP"
                        )
                        return
                    if tp and last_price <= tp:
                        self.close_position(
                            symbol,
                            tp,
                            last_dt or datetime.utcnow(),
                            reason="Recovered SL/TP"
                        )
                        return

            # Reenvia para dashboard como aberta
            self._push_open_trade_to_dashboard(self.current_position)
            logger.info("[PERSIST] Posição aberta restaurada do disco.")
        except Exception as e:
            logger.warning(f"[PERSIST] Falha ao restaurar posição: {e}")

    def _push_closed_trade_to_dashboard(self, position: Position, close_price: float):
        if self.dashboard is None:
            return

        def _to_ts(iso_str: str) -> int:
            try:
                dt = datetime.fromisoformat(iso_str)
                return int(dt.timestamp())
            except Exception:
                return int(time.time())

        time_entry = _to_ts(position.opened_at)
        time_exit = _to_ts(position.closed_at) if position.closed_at else int(time.time())

        side_norm = "buy" if position.side.lower() in ("buy", "long") else "sell"

        trade_payload = {
            "side": side_norm,
            "time_entry": time_entry,
            "time_exit": time_exit,
            "price_entry": float(position.entry_price),
            "price_exit": float(close_price),
            "sl": float(position.stop_loss) if position.stop_loss else None,
            "tp": float(position.take_profit) if position.take_profit else None,
            "quantity": float(position.quantity) if hasattr(position, "quantity") else None,
        }

        try:
            self.dashboard.push_trade(trade_payload)
            logger.info(f"[DASHBOARD] Trade enviado: {trade_payload}")
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao enviar trade: {e}")

    def _push_open_trade_to_dashboard(self, position: Position):
        if self.dashboard is None:
            return

        def _to_ts(iso_str: str) -> int:
            try:
                dt = datetime.fromisoformat(iso_str)
                return int(dt.timestamp())
            except Exception:
                return int(time.time())

        time_entry = _to_ts(position.opened_at)
        
        side_norm = "buy" if position.side.lower() in ("buy", "long") else "sell"

        trade_payload = {
            "side": side_norm,
            "time_entry": time_entry,
            "price_entry": float(position.entry_price),
            "sl": float(position.stop_loss) if position.stop_loss else None,
            "tp": float(position.take_profit) if position.take_profit else None,
            "quantity": float(position.quantity) if hasattr(position, "quantity") else None,
        }

        try:
            self.dashboard.push_trade(trade_payload)
            logger.info(f"[DASHBOARD] Trade ABERTO enviado: {trade_payload}")
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao enviar trade aberto: {e}")

    # ========== ABERTURA ==========

    def open_long(self, symbol: str, price: float, candle_dt: datetime, bid: float = None, ask: float = None, sl: float = 0.0, tp: float = 0.0):

        if self.current_position is not None:
            logger.warning("Tentativa de abrir LONG com posição já aberta.")
            return

        size = self.risk.get_position_size(price)
        now_iso = candle_dt.isoformat()

        mid = price
        bid = bid if bid is not None else mid
        ask = ask if ask is not None else mid

        entry_exec = self.exec_price_model.exec_buy(bid=bid, ask=ask)

        self.current_position = Position(
            symbol=symbol,
            side="buy",
            quantity=size,
            entry_price=entry_exec,
            stop_loss=sl,
            take_profit=tp,
            opened_at=now_iso,
        )

        # extras pro logger
        self.current_position.entry_raw = mid
        self.current_position.entry_bid = bid
        self.current_position.entry_ask = ask


        if self.cfg.dry_run:
            logger.info(f"[DRY-RUN] LONG {symbol} @ {entry_exec} size={size} sl={sl} tp={tp}")
        else:
            logger.info(f"[ORDER] Enviando COMPRA REAL {symbol} @ {entry_exec} sl={sl} tp={tp}")

        self._safe_db_call("log_trade_open", symbol, "long", entry_exec, size)
        
        # Telegram message
        self.notifier.send(self._fmt_msg_open("long", symbol, entry_exec, sl, tp, candle_dt))
        
        self._push_open_trade_to_dashboard(self.current_position)
        self._persist_open_position()

    def open_short(self, symbol: str, price: float, candle_dt: datetime, bid: float = None, ask: float = None, sl: float = 0.0, tp: float = 0.0):
        if self.current_position is not None:
            logger.warning("Tentativa de abrir SHORT com posição já aberta.")
            return

        size = self.risk.get_position_size(price)
        now_iso = candle_dt.isoformat()

        mid = price
        bid = bid if bid is not None else mid
        ask = ask if ask is not None else mid

        entry_exec = self.exec_price_model.exec_sell(bid=bid, ask=ask)

        self.current_position = Position(
            symbol=symbol,
            side="sell",
            quantity=size,
            entry_price=entry_exec,
            stop_loss=sl,
            take_profit=tp,
            opened_at=now_iso,
        )

        self.current_position.entry_raw = mid
        self.current_position.entry_bid = bid
        self.current_position.entry_ask = ask


        if self.cfg.dry_run:
            logger.info(f"[DRY-RUN] SHORT {symbol} @ {entry_exec} size={size} sl={sl} tp={tp}")
        else:
            logger.info(f"[ORDER] Enviando VENDA REAL {symbol} @ {entry_exec} sl={sl} tp={tp}")

        self._safe_db_call("log_trade_open", symbol, "short", entry_exec, size)

        # Telegram message
        self.notifier.send(self._fmt_msg_open("short", symbol, entry_exec, sl, tp, candle_dt))
        
        self._push_open_trade_to_dashboard(self.current_position)
        self._persist_open_position()

    # ========== ATUALIZAÇÃO E FECHAMENTO ==========

    def update_position(self, symbol: str, price: float):
        if self.current_position is None:
            return

        pos = self.current_position

        # cálculo informativo (PnL bruto, no mid)
        if pos.side.lower() in ("buy", "long"):
            pnl = (price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - price) * pos.quantity

        self._safe_db_call("log_pnl", symbol, pnl)
        logger.debug(f"[PnL] {symbol} = {pnl:.4f}")

    def close_position(self, symbol: str, price: float, candle_dt: datetime, bid: float = None, ask: float = None, reason: str = "Signal"):
        print("🚨 DEBUG: close_position FOI CHAMADO", symbol, price)

        if self.current_position is None:
            return

        pos = self.current_position

        mid_close = price
        bid = bid if bid is not None else mid_close
        ask = ask if ask is not None else mid_close

        # definir preço REAL de fechamento
        if pos.side.lower() in ("buy", "long"):
            close_exec = self.exec_price_model.exec_sell(bid=bid, ask=ask)
        else:
            close_exec = self.exec_price_model.exec_buy(bid=bid, ask=ask)

        # cálculo PnL real
        if pos.side.lower() in ("buy", "long"):
            pnl_exec = (close_exec - pos.entry_price) * pos.quantity
        else:
            pnl_exec = (pos.entry_price - close_exec) * pos.quantity

        pos.closed_at = candle_dt.isoformat()
        pos.pnl = pnl_exec
        pos.is_open = False

        # extras pro logger PRO
        pos.close_raw = mid_close
        pos.close_exec = close_exec
        pos.close_bid = bid
        pos.close_ask = ask

        try:
            self.risk.update_balance(pnl_exec)
        except Exception as e:
            logger.warning(f"[RISK] Erro ao atualizar balance: {e}")

        self._safe_db_call("log_trade_close", symbol, pos.side, close_exec, pnl_exec)

        # salvar CSV PRO
        try:
            self.trade_logger.log_trade(pos, cfg=self.cfg)
        except Exception as e:
            logger.warning(f"[CSV] Erro ao salvar trade em CSV: {e}")

        self.notifier.send(self._fmt_msg_close(reason, symbol, pos.side, close_exec, pnl_exec, candle_dt))

        self._push_closed_trade_to_dashboard(pos, close_exec)
        self.current_position = None
        self._clear_persisted_position()
