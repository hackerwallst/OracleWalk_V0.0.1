# file: oraclewalk/dashboard/server.py

import os
import sys
import time
import webbrowser
from collections import deque
from threading import Thread
from typing import Dict, Any, Deque, List, Optional

import pandas as pd
from flask import Flask, jsonify, send_from_directory
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class DashboardServer:
    """
    Servidor para exibir dados via Lightweight Charts.
    Agora:
      - /api/candles  → candles de preço/indicadores
      - /api/trades   → trades (para desenhar setas, SL/TP etc.)
    """

    def __init__(self, max_points: int = 10000, port: int = 8000):
        # Quando empacotado com PyInstaller, os arquivos estáticos ficam em sys._MEIPASS.
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
        static_folder = os.path.join(base_dir, "static")

        self.app = Flask(__name__, static_folder=static_folder, static_url_path="/static")
        self.port = port
        self.max_points = max_points

        # --- SEPARAÇÃO ESTRITA: HISTÓRICO vs LIVE ---
        # _history_buffer: guarda APENAS candles fechados (is_closed=True)
        self._history_buffer: Deque[Dict[str, Any]] = deque(maxlen=max_points)
        
        # _live_candle: guarda APENAS o candle atual em formação (is_closed=False)
        self._live_candle: Optional[Dict[str, Any]] = None

        # snapshot do livro de ordens (para /api/orderbook)
        self._orderbook = {"bids": [], "asks": []}

        # buffer circular de trades
        self._trades: Deque[Dict[str, Any]] = deque(maxlen=500)
        
        # Carrega trades do CSV se existir
        self._load_trades_from_csv()

        # inicial balance (tenta ler config.txt)
        self.initial_balance = self._load_initial_balance()

        # info de equity (saldo/pnl aberto)
        self._equity: Dict[str, Any] = self._compute_equity_from_trades()

        # buffer de FVGs (lista de dicts)
        self.fvg_buffer: List[Dict[str, Any]] = []

        # para controlar atualização 
        self.last_candle_ts = None

        # ------------- ROTAS -------------
        @self.app.route("/")
        def index():
            return send_from_directory(static_folder, "index.html")

        @self.app.route("/api/candles")
        def api_candles():
            # 1. Combina histórico + live (se existir)
            raw_candles = list(self._history_buffer)
            if self._live_candle:
                raw_candles.append(self._live_candle)
            
            # 2. Filtragem e Deduplicação Estrita
            # - Remove timestamps inválidos (<= 0)
            # - Remove duplicatas de timestamp (mantendo o último inserido/atualizado)
            unique_candles = {}
            for c in raw_candles:
                t = c.get("time", 0)
                if t > 0:
                    unique_candles[t] = c
            
            # 3. Converte volta para lista e ordena
            final_list = list(unique_candles.values())
            final_list.sort(key=lambda x: x["time"])
            
            return jsonify(self._sanitize_json(final_list))

        @self.app.route("/api/trades")
        def api_trades():
            """
            Endpoint usado pelo OracleView para desenhar:
                - seta de entrada
                - seta de saída
                - linha pontilhada entre elas
                - linhas de SL / TP
            """
            return jsonify(self._sanitize_json(list(self._trades)))

        @self.app.route("/api/orderbook")
        def api_orderbook():
            return jsonify(self._orderbook)

        @self.app.route("/api/fvg")
        def api_fvg():
            return jsonify(self._sanitize_json(self.fvg_buffer))

        @self.app.route("/api/equity")
        def api_equity():
            # se não tiver equity calculada, tenta fallback via trades
            if self._equity.get("balance") is None:
                self._equity = self._compute_equity_from_trades()
            return jsonify(self._sanitize_json(self._equity))
        
        @self.app.route("/api/debug")
        def api_debug():
            """Endpoint de debug para verificar status do dashboard"""
            return jsonify({
                "history_candles": len(self._history_buffer),
                "live_candle_present": self._live_candle is not None,
                "trades_in_buffer": len(self._trades),
                "fvgs_in_buffer": len(self.fvg_buffer),
                "last_candle_ts": self.last_candle_ts,
                "equity_timestamp": self._equity.get("timestamp"),
            })


    def push_candle(self, candle: Dict[str, Any]):
        """
        Lógica de Separação Estrita:
        - Se is_closed=True: VAI PARA O HISTÓRICO. Limpa live.
        - Se is_closed=False: VAI PARA LIVE. Não toca no histórico.
        """
        is_closed = candle.get("is_closed", False)
        ts = candle["time"]
        
        if is_closed:
            # === CANDLE FECHADO ===
            # Adiciona ao histórico (deduplicando se necessário)
            
            # Verifica se já existe último candle com mesmo TS (pode acontecer reenvio)
            if len(self._history_buffer) > 0 and self._history_buffer[-1]["time"] == ts:
                # Atualiza (overwrite) o último fechado
                self._history_buffer[-1] = candle
            else:
                # Novo candle fechado
                self._history_buffer.append(candle)
                
            # Limpa o live, pois agora ele virou histórico
            self._live_candle = None
            self.last_candle_ts = ts
            
            logger.info(f"[DASHBOARD] 🟡 Candle FECHADO e arquivado: {ts}")
            
        else:
            # === CANDLE LIVE (EM FORMAÇÃO) ===
            # Só atualiza a variável temporária. NUNCA toca no buffer de histórico.
            self._live_candle = candle
            # logger.debug(f"[DASHBOARD] Live candle update: {ts}")

        # Mantém tamanho do histórico
        while len(self._history_buffer) > self.max_points:
            self._history_buffer.popleft()


    def _load_trades_from_csv(self):
        """Carrega os últimos 10 trades do arquivo trades.csv."""
        import csv
        from datetime import datetime
        
        filename = "trades.csv"
        if not os.path.exists(filename):
            return

        try:
            trades_list = []
            with open(filename, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades_list.append(row)
            
            # Pega os últimos 10
            last_trades = trades_list[-10:]
            
            for t in last_trades:
                try:
                    # Converte timestamps
                    def _parse_ts(ts_str):
                        try:
                            return int(datetime.fromisoformat(ts_str).timestamp())
                        except:
                            return None

                    time_entry = _parse_ts(t.get("open_time"))
                    time_exit = _parse_ts(t.get("close_time"))
                    
                    if not time_entry:
                        continue

                    qty = None
                    try:
                        qty = float(t.get("quantity")) if t.get("quantity") not in (None, "") else None
                    except Exception:
                        qty = None

                    trade_obj = {
                        "side": t.get("side", "buy"),
                        "time_entry": time_entry,
                        "time_exit": time_exit,
                        "price_entry": float(t.get("entry_exec", 0.0)),
                        "price_exit": float(t.get("close_exec", 0.0)),
                        "quantity": qty,
                        # SL/TP não existem no CSV, mas tudo bem
                        "sl": None,
                        "tp": None
                    }
                    self._trades.append(trade_obj)
                except Exception:
                    continue
            
            logger.info(f"[DASHBOARD] Carregados {len(self._trades)} trades do CSV.")
            
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao carregar trades.csv: {e}")

    def _load_initial_balance(self) -> float:
        """
        Lê config.txt para obter initial_balance; se falhar, retorna 0.
        """
        path = os.path.join(os.getcwd(), "config.txt")
        if not os.path.exists(path):
            return 0.0
        bal = 0.0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "initial_balance" in line and "=" in line:
                        try:
                            bal = float(line.split("=", 1)[1].strip())
                        except Exception:
                            pass
                        break
        except Exception as e:
            logger.warning(f"[DASHBOARD] Falha ao ler initial_balance do config.txt: {e}")
        return bal

    def _compute_equity_from_trades(self) -> Dict[str, Any]:
        """
        Fallback: calcula saldo/equity a partir de initial_balance + trades fechados.
        Não computa PnL aberto (retorna 0 se não souber).
        """
        balance = self.initial_balance
        open_pnl = 0.0
        try:
            for t in list(self._trades):
                qty = t.get("quantity")
                try:
                    qty = float(qty) if qty not in (None, "") else None
                except Exception:
                    qty = None
                side = (t.get("side") or "").lower()

                # Se já veio PnL do CSV, usa direto
                pnl_direct = t.get("pnl_exec") or t.get("pnl_mid")
                if pnl_direct is not None:
                    try:
                        pnl = float(pnl_direct)
                        balance += pnl
                        continue
                    except Exception:
                        pass

                entry = t.get("price_entry") or t.get("entry_price")
                exit_p = t.get("price_exit") or t.get("exit_price")
                if entry is None or exit_p is None:
                    continue
                try:
                    entry = float(entry)
                    exit_p = float(exit_p)
                except Exception:
                    continue

                eff_qty = qty if (qty is not None and qty != 0) else 1.0
                if side in ("buy", "long"):
                    pnl = (exit_p - entry) * eff_qty
                else:
                    pnl = (entry - exit_p) * eff_qty
                balance += pnl
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao computar equity dos trades: {e}")
        equity = balance + open_pnl
        return {
            "balance": balance,
            "equity": equity,
            "open_pnl": open_pnl,
            "timestamp": time.time(),
        }


    def _sanitize_json(self, data):
        """
        Recursively replace NaN/Infinity with None to ensure valid JSON.
        """
        import math
        
        if isinstance(data, dict):
            return {k: self._sanitize_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_json(v) for v in data]
        elif isinstance(data, float):
            if math.isnan(data) or math.isinf(data):
                return None
            return data
        return data

    # -----------------------------
    # TRADES
    # -----------------------------
    def push_trade(self, trade: Dict[str, Any]):
        """
        Adiciona/atualiza um trade no buffer.

        Esperado pelo front (mas é flexível):
          - side: "buy" / "sell"
          - time_entry / time_exit: int (timestamp em segundos)
          - price_entry / price_exit: float
          - sl / tp: float ou None

        O JS faz fallback de nomes:
          time_entry  || entry_time  || open_time
          time_exit   || exit_time   || close_time
          price_entry || entry_price || open_price
          price_exit  || exit_price  || close_price
          sl          || stop_loss
          tp          || take_profit
        """
        trade_dict = dict(trade)
        
        # Deduplicação baseada em time_entry
        # Se já existe um trade com mesmo time_entry, atualiza
        updated = False
        for i, t in enumerate(self._trades):
            if t.get("time_entry") == trade_dict.get("time_entry"):
                self._trades[i] = trade_dict
                updated = True
                break
        
        if not updated:
            self._trades.append(trade_dict)

        # limite de segurança (já tem maxlen, mas deixo explícito)
        while len(self._trades) > self._trades.maxlen:
            self._trades.popleft()

    def clear_trades(self):
        """Limpa todos os trades (se um dia você quiser resetar)."""
        self._trades.clear()
    
    def get_buffer_size(self) -> int:
        """Retorna o tamanho atual do buffer de candles."""
        return len(self._history_buffer)

    # -----------------------------
    # SERVER
    # -----------------------------
    def start(self):
        """Inicia servidor Flask em background e abre navegador."""
        print(f"[DASHBOARD] Iniciando servidor Flask em thread separada...", flush=True)

        def run():
            logger.info(f"Iniciando dashboard em http://127.0.0.1:{self.port}")
            print(f"[DASHBOARD-THREAD] Flask rodando em http://127.0.0.1:{self.port}", flush=True)
            self.app.run(
                host="127.0.0.1",
                port=self.port,
                debug=False,
                use_reloader=False,
            )

        t = Thread(target=run, daemon=True, name="DashboardServer")
        print(f"[DASHBOARD] Criando thread '{t.name}'...", flush=True)
        t.start()
        print(f"[DASHBOARD] ✅ Thread iniciada (ID: {t.ident}, Alive: {t.is_alive()})", flush=True)

        print(f"[DASHBOARD] Aguardando 1.2s para servidor iniciar...", flush=True)
        time.sleep(1.2)
        print(f"[DASHBOARD] Tentando abrir navegador...", flush=True)
        try:
            webbrowser.open(f"http://127.0.0.1:{self.port}")
            print(f"[DASHBOARD] ✅ Navegador aberto", flush=True)
        except Exception as e:
            logger.warning(f"Não foi possível abrir o navegador automaticamente: {e}")
            print(f"[DASHBOARD] ⚠️ Não foi possível abrir navegador: {e}", flush=True)
        
        print(f"[DASHBOARD] start() finalizado, retornando...", flush=True)

    def set_orderbook(self, book: Dict[str, Any]):
        """
        Atualiza o snapshot do order book que será servido em /api/orderbook.
        book = {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}
        """
        try:
            bids = book.get("bids", [])[:50]
            asks = book.get("asks", [])[:50]
            self._orderbook = {"bids": bids, "asks": asks}
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao setar orderbook: {e}")

    def set_fvg(self, fvgs_df: pd.DataFrame):
        """
        Recebe DataFrame de FVGs e converte para lista de dicts.
        Esperado: columns=['start_time', 'top', 'bottom', 'type', ...]
        """
        try:
            if fvgs_df.empty:
                self.fvg_buffer = []
                return

            # Converte para dict
            # orient='records' -> [{col: val}, ...]
            self.fvg_buffer = fvgs_df.to_dict(orient="records")
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao setar FVG: {e}")

    def set_equity(self, balance: float, equity: float, open_pnl: float, ts: float = None):
        """
        Armazena snapshot de equity/saldo/pnl aberto.
        """
        try:
            self._equity = {
                "balance": float(balance) if balance is not None else None,
                "equity": float(equity) if equity is not None else None,
                "open_pnl": float(open_pnl) if open_pnl is not None else None,
                "timestamp": ts if ts is not None else time.time(),
            }
        except Exception as e:
            logger.warning(f"[DASHBOARD] Erro ao setar equity: {e}")


if __name__ == "__main__":
    # Permite rodar o dashboard isoladamente para teste
    server = DashboardServer(port=5000)
    server.start()

    # Mantém a thread principal viva
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Encerrando dashboard...")
