# file: oraclewalk/data/live_data.py

import asyncio
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any
from queue import Queue

from binance import AsyncClient, BinanceSocketManager
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class LiveDataHandler:
    """
    Handler LIVE com BinanceSocketManager (async).
    Agora:
      - Usa multiplex de KLINE + BOOKTICKER (aggTrade removido para evitar overflow de fila)
      - Anexa bid/ask reais em cada candle
      - Tem reconexão automática (anti-crash)
      - Verificação de status do WebSocket
      - Logs detalhados para debug
    """

    def __init__(self, api_key: str, api_secret: str, symbol: str, interval: str = "1m"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol = symbol
        self.interval = interval

        self.queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # último bid/ask conhecido (atualizado pelo bookTicker)
        self.last_bid: Optional[float] = None
        self.last_ask: Optional[float] = None
        
        # Status e métricas para debug
        self._is_connected = False
        self._last_candle_time: Optional[datetime] = None
        self._last_kline: Optional[Dict[str, Any]] = None  # Cache do último candle completo para os ticks
        self._candles_received = 0
        self._bookticker_updates = 0
        self._connection_attempts = 0
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    async def _run_websocket(self):

        symbol_lower = self.symbol.lower()
        kline_stream = f"{symbol_lower}@kline_{self.interval}"
        book_stream = f"{symbol_lower}@bookTicker"

        while not self._stop_event.is_set():

            try:
                with self._lock:
                    self._connection_attempts += 1
                    self._is_connected = False
                
                logger.info(f"[LIVE] 🔌 Tentativa de conexão #{self._connection_attempts}")
                logger.info(f"[LIVE] Conectando WebSocket multiplex: {kline_stream}, {book_stream}")
                print(f"\n[LIVE-WS] 🔌 Tentativa #{self._connection_attempts}: Conectando WebSocket Binance...")
                print(f"[LIVE-WS] Streams: {kline_stream}, {book_stream}")

                print(f"[LIVE-WS] Criando AsyncClient...")
                client = await AsyncClient.create(self.api_key, self.api_secret)
                print(f"[LIVE-WS] ✅ AsyncClient criado")
                
                print(f"[LIVE-WS] Criando BinanceSocketManager...")
                bsm = BinanceSocketManager(client)
                print(f"[LIVE-WS] ✅ BinanceSocketManager criado")

                # multiplex com kline + bookTicker (aggTrade removido para evitar overflow de fila)
                print(f"[LIVE-WS] Criando multiplex socket...")
                socket = bsm.multiplex_socket([kline_stream, book_stream])
                print(f"[LIVE-WS] ✅ Multiplex socket criado")

                print(f"[LIVE-WS] Abrindo conexão WebSocket...")
                async with socket as stream:
                    print(f"[LIVE-WS] ✅ Conexão WebSocket aberta!")
                    with self._lock:
                        self._is_connected = True
                        self._last_error = None
                    
                    logger.info(f"[LIVE] ✅ WebSocket CONECTADO para {self.symbol} ({self.interval} + bookTicker)")
                    print(f"[LIVE] ✅ WebSocket Binance CONECTADO! Aguardando candles...")
                    
                    # Contador de tempo sem receber dados
                    last_data_time = time.time()
                    heartbeat_interval = 30  # avisa a cada 30s se não receber dados

                    while not self._stop_event.is_set():
                        try:
                            # Timeout de 5 segundos para recv (para verificar conexão)
                            try:
                                msg = await asyncio.wait_for(stream.recv(), timeout=5.0)
                            except asyncio.TimeoutError:
                                # Verifica se está muito tempo sem dados
                                elapsed = time.time() - last_data_time
                                if elapsed > heartbeat_interval:
                                    logger.warning(f"[LIVE] ⚠️ Sem dados há {elapsed:.0f}s. WebSocket pode estar inativo.")
                                    print(f"[LIVE] ⚠️ AVISO: Sem receber dados há {elapsed:.0f} segundos!")
                                    last_data_time = time.time()  # reseta contador
                                continue
                            
                            if not msg:
                                logger.debug("[LIVE] Mensagem vazia recebida")
                                continue

                            # Atualiza timestamp de último dado recebido
                            last_data_time = time.time()

                            # Verifica estrutura mínima
                            if "data" not in msg:
                                logger.debug("[LIVE] Mensagem sem campo 'data'")
                                continue

                            data = msg["data"]

                            # Evento precisa existir
                            event_type = data.get("e")
                            if event_type is None:
                                logger.debug("[LIVE] Mensagem sem tipo de evento")
                                continue

                            # ---- AGG TRADE (Real-time Ticks) ----
                            if event_type == "aggTrade":
                                try:
                                    price = float(data["p"])
                                    trade_ts = int(data["T"]) // 1000
                                    
                                    if trade_ts <= 0:
                                        continue

                                    # Precisa de referência do último candle para preencher open/high/low/volume
                                    # Se não tiver, descarta o tick (espera primeiro candle chegar)
                                    if self._last_kline is None:
                                        continue
                                    
                                    # SE O ÚLTIMO CANDLE ESTÁ FECHADO, NÃO DEVEMOS ATUALIZÁ-LO COM TICK.
                                    # Isso evita "sujar" o candle recém-fechado com preços do novo candle que ainda não abriu (gap de ms).
                                    # Devemos esperar o evento 'kline' abrir o novo candle.
                                    if self._last_kline.get("is_closed", False):
                                        continue

                                    # THROTTLING: 200ms
                                    now_sys = time.time()
                                    if not hasattr(self, "_last_tick_emit"):
                                        self._last_tick_emit = 0.0
                                    
                                    if now_sys - self._last_tick_emit > 0.2:
                                        self._last_tick_emit = now_sys
                                        
                                        with self._lock:
                                            # Cria cópia do último estado conhecido
                                            tick_candle = self._last_kline.copy()
                                        
                                        # Atualiza com dados do tick
                                        tick_candle["close"] = price
                                        # Atualiza High/Low caso o preço rompa limites do candle atual
                                        if price > tick_candle["high"]:
                                            tick_candle["high"] = price
                                        if price < tick_candle["low"]:
                                            tick_candle["low"] = price
                                            
                                        # Sobrescreve tempo se necessário, ou mantém do candle?
                                        # Se mantiver do candle, ele "atualiza" aquele candle na UI.
                                        # tick_candle["datetime"] já vem do _last_kline
                                        
                                        tick_candle["is_tick"] = True
                                        tick_candle["bid"] = self.last_bid
                                        tick_candle["ask"] = self.last_ask
                                        
                                        self.queue.put(tick_candle)

                                except Exception as e:
                                    pass
                                continue

                            # ---- BOOKTICKER ----
                            if event_type == "bookTicker":
                                try:
                                    bid = float(data["b"])
                                    ask = float(data["a"])
                                    with self._lock:
                                        self.last_bid = bid
                                        self.last_ask = ask
                                        self._bookticker_updates += 1
                                    
                                    # Log menos frequente
                                    if self._bookticker_updates % 1000 == 0:
                                        logger.debug(f"[LIVE] BookTicker update {self._bookticker_updates}")
                                        
                                except Exception as e:
                                    pass
                                continue

                            # ---- KLINE ----
                            if event_type == "kline":
                                k = data.get("k")
                                if not k:
                                    logger.debug("[LIVE] Kline sem dados 'k'")
                                    print("[LIVE-WS] ⚠️ Kline sem dados 'k'")
                                    continue

                                ts = int(k.get("t", 0)) // 1000
                                dt = datetime.utcfromtimestamp(ts)
                                is_closed = bool(k.get("x", False))

                                candle = {
                                    "datetime": dt,
                                    "open": float(k.get("o", 0.0)),
                                    "high": float(k.get("h", 0.0)),
                                    "low": float(k.get("l", 0.0)),
                                    "close": float(k.get("c", 0.0)),
                                    "volume": float(k.get("v", 0.0)),
                                    "is_closed": is_closed,
                                    "bid": self.last_bid,
                                    "ask": self.last_ask,
                                }

                                with self._lock:
                                    self._candles_received += 1
                                    self._last_candle_time = dt
                                    self._last_kline = candle
                                    count = self._candles_received
                                
                                # Log detalhado para candles fechados
                                if is_closed:
                                    logger.info(f"[LIVE] 📊 Candle FECHADO recebido: {dt} | Close={candle['close']:.2f} | Volume={candle['volume']:.2f}")
                                    print(f"[LIVE-WS] 📊 Candle FECHADO: {dt.strftime('%Y-%m-%d %H:%M:%S')} | Close={candle['close']:.2f} | Volume={candle['volume']:.2f} | Total: {count}")
                                else:
                                    logger.debug(f"[LIVE] Candle intrabar: {dt} | Close={candle['close']:.2f}")
                                    print(f"[LIVE-WS] 🔄 Candle intrabar: {dt.strftime('%H:%M:%S')} | Close={candle['close']:.2f}")

                                self.queue.put(candle)
                                print(f"[LIVE-WS] ✅ Candle adicionado à fila (fila tem {self.queue.qsize()} itens)")
                                continue

                        except asyncio.TimeoutError:
                            # Já tratado acima
                            continue
                        except Exception as e:
                            logger.warning(f"[LIVE] ❌ Erro interno no multiplex: {e}")
                            print(f"[LIVE] ❌ Erro ao processar mensagem: {e}")
                            with self._lock:
                                self._last_error = str(e)
                            await asyncio.sleep(1)
                            break  # força reconectar

                # fecha conexão do client antes de tentar novamente
                with self._lock:
                    self._is_connected = False
                
                try:
                    await client.close_connection()
                    logger.info("[LIVE] Conexão fechada")
                except Exception as e:
                    logger.debug(f"[LIVE] Erro ao fechar conexão: {e}")

            except Exception as e:
                with self._lock:
                    self._is_connected = False
                    self._last_error = str(e)
                
                logger.error(f"[LIVE] ❌ Erro crítico no WebSocket: {e}", exc_info=True)
                print(f"[LIVE-WS] ❌ ERRO CRÍTICO: {type(e).__name__}: {e}")
                import traceback
                print(f"[LIVE-WS] Traceback:")
                traceback.print_exc()

            logger.warning("[LIVE] 🔄 WebSocket desconectado. Tentando reconectar em 2s...")
            print("[LIVE-WS] 🔄 WebSocket desconectado. Reconectando em 2 segundos...")
            await asyncio.sleep(2)

    def start(self):
        print(f"\n[LIVE] {'='*60}")
        print(f"[LIVE] Iniciando WebSocket para {self.symbol} ({self.interval})...")
        print(f"[LIVE] Streams: {self.symbol.lower()}@kline_{self.interval}, {self.symbol.lower()}@bookTicker")
        logger.info(f"[LIVE] Iniciando WebSocket para {self.symbol} ({self.interval})")
        
        # Verifica se já tem thread rodando
        if self._thread and self._thread.is_alive():
            print("[LIVE] ⚠️ AVISO: Thread já está rodando! Parando antes de reiniciar...")
            self.stop()
            time.sleep(1)
        
        loop = asyncio.new_event_loop()

        def runner():
            try:
                print(f"[LIVE-THREAD] Thread iniciada, criando event loop...")
                asyncio.set_event_loop(loop)
                print(f"[LIVE-THREAD] Event loop criado, iniciando _run_websocket()...")
                loop.run_until_complete(self._run_websocket())
                print(f"[LIVE-THREAD] _run_websocket() finalizou")
            except Exception as e:
                print(f"[LIVE-THREAD] ❌ ERRO na thread: {e}")
                logger.error(f"Erro na thread do WebSocket: {e}", exc_info=True)

        self._thread = threading.Thread(target=runner, daemon=True, name="BinanceWebSocket")
        print(f"[LIVE] Criando thread '{self._thread.name}'...")
        self._thread.start()
        print(f"[LIVE] ✅ Thread iniciada (ID: {self._thread.ident}, Alive: {self._thread.is_alive()})")
        
        # Aguarda um pouco para verificar se conectou
        print("[LIVE] Aguardando 2 segundos para thread iniciar...")
        time.sleep(2)
        
        if not self._thread.is_alive():
            print("[LIVE] ❌ ERRO: Thread morreu imediatamente após iniciar!")
            logger.error("Thread do WebSocket morreu imediatamente")
        else:
            print("[LIVE] ✅ Thread ainda está viva")

    def stop(self):
        logger.info("Parando WebSocket...")
        print("[LIVE] 🛑 Parando WebSocket...")
        self._stop_event.set()
        with self._lock:
            self._is_connected = False

    def get_next_candle(self, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        try:
            candle = self.queue.get(timeout=timeout)
            if candle:
                logger.debug(f"[LIVE] Candle retirado da fila: {candle.get('datetime')}")
            return candle
        except Exception as e:
            logger.debug(f"[LIVE] Timeout ao buscar candle: {e}")
            return None
    
    def check_connection_status(self) -> Dict[str, Any]:
        """
        Verifica o status da conexão WebSocket e retorna informações de debug.
        """
        with self._lock:
            is_connected = self._is_connected
            candles_count = self._candles_received
            bookticker_count = self._bookticker_updates
            last_candle = self._last_candle_time
            attempts = self._connection_attempts
            last_error = self._last_error
        
        status = {
            "connected": is_connected,
            "candles_received": candles_count,
            "bookticker_updates": bookticker_count,
            "last_candle_time": last_candle.isoformat() if last_candle else None,
            "connection_attempts": attempts,
            "last_error": last_error,
            "thread_alive": self._thread.is_alive() if self._thread else False,
        }
        
        # Calcula tempo desde último candle
        if last_candle:
            elapsed = (datetime.utcnow() - last_candle).total_seconds()
            status["seconds_since_last_candle"] = elapsed
        else:
            status["seconds_since_last_candle"] = None
        
        return status
    
    def print_status(self):
        """
        Imprime status detalhado do WebSocket (útil para debug).
        """
        status = self.check_connection_status()
        
        print("\n" + "="*60)
        print("📡 STATUS DO WEBSOCKET BINANCE")
        print("="*60)
        print(f"✅ Conectado: {'SIM' if status['connected'] else '❌ NÃO'}")
        print(f"📊 Candles recebidos: {status['candles_received']}")
        print(f"📈 BookTicker atualizações: {status['bookticker_updates']}")
        print(f"🔄 Tentativas de conexão: {status['connection_attempts']}")
        print(f"🧵 Thread ativa: {'SIM' if status['thread_alive'] else 'NÃO'}")
        
        if status['last_candle_time']:
            print(f"⏰ Último candle: {status['last_candle_time']}")
            if status['seconds_since_last_candle']:
                elapsed = status['seconds_since_last_candle']
                if elapsed > 120:
                    print(f"⚠️  ATENÇÃO: Sem candles há {elapsed:.0f} segundos ({elapsed/60:.1f} minutos)!")
                else:
                    print(f"⏱️  Tempo desde último candle: {elapsed:.0f}s")
        else:
            print("⏰ Último candle: NENHUM RECEBIDO AINDA")
        
        if status['last_error']:
            print(f"❌ Último erro: {status['last_error']}")
        
        print("="*60 + "\n")
        
        # Log também
        logger.info(f"[LIVE] Status: conectado={status['connected']}, candles={status['candles_received']}, "
                   f"último_candle={status['last_candle_time']}, thread_viva={status['thread_alive']}")
