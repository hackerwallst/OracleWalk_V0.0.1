# novo handler simples para depth
# file: oraclewalk/data/orderbook_data.py

import threading
from queue import Queue, Empty
from typing import Optional, Dict, Any

from binance import ThreadedWebsocketManager
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class OrderBookHandler:
    def __init__(self, api_key: str, api_secret: str, symbol: str, limit: int = 25):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol
        self.limit = limit

        self._twm: Optional[ThreadedWebsocketManager] = None
        self._thread: Optional[threading.Thread] = None

        self._last_book: Dict[str, Any] = {"bids": [], "asks": []}
        self._lock = threading.Lock()

    def _process_depth(self, msg):
        """
        msg['b'] = bids  (lista de [price, qty])
        msg['a'] = asks
        """
        try:
            if msg.get("e") != "depthUpdate":
                return

            bids = msg.get("b", [])[: self.limit]
            asks = msg.get("a", [])[: self.limit]

            # converte para float
            bids = [[float(p), float(q)] for p, q in bids]
            asks = [[float(p), float(q)] for p, q in asks]

            with self._lock:
                self._last_book = {"bids": bids, "asks": asks}

        except Exception as e:
            logger.warning(f"[ORDERBOOK] Erro depthUpdate: {e}")

    def start(self):
        def _run():
            try:
                self._twm = ThreadedWebsocketManager(
                    api_key=self.api_key, api_secret=self.api_secret
                )
                self._twm.start()

                self._twm.start_depth_socket(
                    callback=self._process_depth, symbol=self.symbol
                )
            except Exception as e:
                logger.error(f"[ORDERBOOK] Erro ao iniciar TWM depth: {e}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        try:
            if self._twm:
                self._twm.stop()
        except Exception:
            pass

    def get_snapshot(self) -> Dict[str, Any]:
        # cópia segura
        with self._lock:
            return {
                "bids": list(self._last_book["bids"]),
                "asks": list(self._last_book["asks"]),
            }
