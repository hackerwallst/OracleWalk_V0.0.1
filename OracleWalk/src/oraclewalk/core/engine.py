# file: oraclewalk/core/engine.py

import time
import os
import csv
from datetime import datetime, timedelta
import pandas as pd

from oraclewalk.config.config_loader import AppConfig
from oraclewalk.data.data_handler import HistoricalDataHandler
from oraclewalk.data.live_data import LiveDataHandler
from oraclewalk.execution.risk_manager import RiskManager
from oraclewalk.execution.trade_executor import TradeExecutor
from oraclewalk.notifications.telegram_notifier import TelegramNotifier
from oraclewalk.optimization.backtester import Backtester
from oraclewalk.storage.database import DatabaseManager
from oraclewalk.strategy.inner_circle_trader import InnerCircleTrader
from oraclewalk.data.indicators import calc_rsi
from oraclewalk.utils.logger import setup_logger
from oraclewalk.dashboard.server import DashboardServer
from oraclewalk.data.orderbook_data import OrderBookHandler

logger = setup_logger(__name__)


def _pnl_from_csv(path: str) -> float:
    """Soma PnL realizado do trades.csv (pnl_exec se existir, senão calcula)."""
    if not os.path.exists(path):
        return 0.0
    pnl_total = 0.0
    try:
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    if row.get("pnl_exec") not in (None, ""):
                        pnl_total += float(row["pnl_exec"])
                        continue
                except Exception:
                    pass
                try:
                    entry = float(row.get("entry_exec") or row.get("entry_raw") or 0.0)
                    exit_p = float(row.get("close_exec") or row.get("close_raw") or 0.0)
                    qty = float(row.get("quantity") or 0.0) if row.get("quantity") not in (None, "") else 1.0
                    side = (row.get("side") or "").lower()
                    if side in ("buy", "long"):
                        pnl_total += (exit_p - entry) * qty
                    else:
                        pnl_total += (entry - exit_p) * qty
                except Exception:
                    continue
    except Exception:
        return 0.0
    return pnl_total


def run_backtest(cfg: AppConfig):
    client = cfg.get_client()
    dh = HistoricalDataHandler(client, cfg.symbols[0], cfg.timeframe)

    end = datetime.utcnow()
    start = end - timedelta(days=2)

    df = dh.get_ohlcv(start, end)

    db = DatabaseManager()
    risk = RiskManager(cfg, db)
    strategy = InnerCircleTrader(cfg)

    backtester = Backtester(risk)
    result = backtester.run(df, strategy)

    notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id)
    notifier.send(
        f"📊 Backtest {cfg.symbols[0]}\n"
        f"Equity: {result['equity_final']:.2f}\n"
        f"PnL: {result['pnl']:.2f}\n"
        f"Win rate: {result['win_rate']*100:.2f}%"
    )

    logger.info("Backtest concluído. Equity salva em backtest_equity.csv")


def run_live(cfg: AppConfig):
    logger.info(f"Iniciando OracleWalk em modo LIVE para símbolo: {cfg.symbols[0]}")

    notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id)
    db = DatabaseManager()
    risk = RiskManager(cfg, db)
    # Ajusta saldo inicial com PnL já realizado do CSV para não resetar equity após carregar candles
    pnl_csv = _pnl_from_csv("trades.csv")
    if pnl_csv != 0:
        risk.current_balance += pnl_csv
        logger.info(f"[ENGINE] Ajustando saldo inicial com PnL do CSV: {pnl_csv:.4f} → balance={risk.current_balance:.4f}")

    # Estratégia exemplo
    strategy = InnerCircleTrader(cfg)

    # --- ORDER BOOK: handler independente, em thread própria ---
    ob_handler = OrderBookHandler(
        cfg.binance_api_key,
        cfg.binance_api_secret,
        cfg.symbols[0],
        limit=25,
    )
    ob_handler.start()
    last_ob_update = 0.0

    # --- Dashboard (HTTP + buffers internos) ---
    print("\n" + "="*70, flush=True)
    print("📊 INICIANDO DASHBOARD", flush=True)
    print("="*70, flush=True)
    print("[ENGINE] Criando DashboardServer...", flush=True)
    dashboard = DashboardServer(max_points=10000, port=8000)
    print("[ENGINE] DashboardServer criado, chamando start()...", flush=True)
    dashboard.start()
    print("[ENGINE] ✅ Dashboard iniciado em http://127.0.0.1:8000", flush=True)
    print("[ENGINE] Continuando execução após dashboard.start()...", flush=True)

    # --- TESTE DE CONEXÃO COM BINANCE ---
    print("\n" + "="*70, flush=True)
    print("🔌 TESTANDO CONEXÃO COM BINANCE", flush=True)
    print("="*70, flush=True)
    try:
        print("[ENGINE] Criando cliente Binance...", flush=True)
        test_client = cfg.get_client()
        print("[ENGINE] Cliente Binance criado, testando conexão...", flush=True)
        
        # Testa se consegue buscar informações básicas
        print("[ENGINE] Testando get_server_time()...", flush=True)
        server_time = test_client.get_server_time()
        print(f"[ENGINE] ✅ Conexão com Binance OK! Server time: {server_time}", flush=True)
        
        # Testa se consegue buscar informações do símbolo
        print(f"[ENGINE] Testando get_symbol_ticker({cfg.symbols[0]})...", flush=True)
        ticker = test_client.get_symbol_ticker(symbol=cfg.symbols[0])
        print(f"[ENGINE] ✅ Símbolo {cfg.symbols[0]} encontrado! Preço atual: {ticker['price']}", flush=True)
        
    except Exception as e:
        print(f"[ENGINE] ❌ ERRO ao conectar com Binance: {e}", flush=True)
        import traceback
        traceback.print_exc()
        logger.error(f"Erro ao testar conexão Binance: {e}", exc_info=True)
        raise

    # --- Live data (candles) ---
    print("\n" + "="*70, flush=True)
    print("🚀 INICIANDO LIVE DATA HANDLER (WEBSOCKET)", flush=True)
    print("="*70, flush=True)
    print(f"[ENGINE] Configuração:", flush=True)
    print(f"  - Símbolo: {cfg.symbols[0]}", flush=True)
    print(f"  - Timeframe: {cfg.timeframe}", flush=True)
    api_key_display = cfg.binance_api_key[:10] + "..." + cfg.binance_api_key[-5:] if len(cfg.binance_api_key) > 15 else "***"
    print(f"  - API Key: {api_key_display}", flush=True)
    
    print("[ENGINE] Criando LiveDataHandler...", flush=True)
    live = LiveDataHandler(
        cfg.binance_api_key,
        cfg.binance_api_secret,
        cfg.symbols[0],
        cfg.timeframe,
    )
    print(f"[ENGINE] ✅ LiveDataHandler criado", flush=True)
    
    print("[ENGINE] Iniciando WebSocket...", flush=True)
    live.start()
    print("[ENGINE] ✅ LiveDataHandler.start() chamado", flush=True)
    
    # Aguarda um pouco e verifica status
    print("[ENGINE] Aguardando 5 segundos para conexão WebSocket estabelecer...", flush=True)
    time.sleep(5)
    print("\n[ENGINE] Verificando status inicial do WebSocket...", flush=True)
    live.print_status()
    
    # Verifica se a thread está rodando
    if live._thread and live._thread.is_alive():
        print(f"[ENGINE] ✅ Thread do WebSocket está RODANDO (ID: {live._thread.ident})", flush=True)
    else:
        print("[ENGINE] ❌ ERRO: Thread do WebSocket NÃO está rodando!", flush=True)
        logger.error("Thread do WebSocket não está ativa!")

    # Executor agora recebe o dashboard (pra desenhar trades etc.)
    executor = TradeExecutor(cfg, risk, db, notifier, dashboard=dashboard)

    notifier.send("🚀 OracleWalk LIVE iniciado!")

    # ==============================
    # HISTÓRICO INICIAL (10 horas)
    # ==============================
    client = cfg.get_client()
    history_handler = HistoricalDataHandler(client, cfg.symbols[0], cfg.timeframe)

    # Calcula start baseado em N candles (2000) para garantir histórico suficiente
    # independente do timeframe
    tf_str = cfg.timeframe
    minutes = 1
    if tf_str.endswith("m"):
        minutes = int(tf_str[:-1])
    elif tf_str.endswith("h"):
        minutes = int(tf_str[:-1]) * 60
    elif tf_str.endswith("d"):
        minutes = int(tf_str[:-1]) * 1440
    
    needed_candles = 10000 
    duration_min = minutes * needed_candles
    
    end = datetime.utcnow()
    start = end - timedelta(minutes=duration_min)

    logger.info(f"Buscando histórico de {needed_candles} candles ({duration_min/60:.1f} horas)...")
    df_hist = history_handler.get_ohlcv(start, end)

    # REMOÇÃO DO ÚLTIMO CANDLE DO HISTÓRICO
    # A API REST costuma retornar o candle atual (ainda aberto) no final da lista.
    # Como estamos marcando tudo como is_closed=True, se deixarmos esse candle,
    # ele vai aparecer duplicado (uma versão "fechada" falsa + a versão live real).
    # O WebSocket (LiveDataHandler) já está rodando e vai prover o candle atual corretamente.
    if not df_hist.empty:
        df_hist = df_hist.iloc[:-1]

    # Indicadores no histórico
    df_hist["rsi"] = calc_rsi(df_hist["close"], period=cfg.rsi_period)
    last_close_hist = float(df_hist["close"].iloc[-1]) if not df_hist.empty else None
    last_dt_hist = df_hist.index[-1].to_pydatetime() if not df_hist.empty else None

    # Envia histórico para o dashboard
    print(f"\n[ENGINE] Enviando histórico inicial ({len(df_hist)} candles) para o dashboard...", flush=True)
    candles_sent = 0
    for idx, row in df_hist.iterrows():
        dashboard.push_candle(
            {
                "time": int(idx.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "rsi": float(row["rsi"]) if not pd.isna(row["rsi"]) else None,
                "is_closed": True,
            }
        )
        candles_sent += 1
        if candles_sent % 100 == 0:
            print(f"[ENGINE] Enviados {candles_sent}/{len(df_hist)} candles...", flush=True)
    
    print(f"[ENGINE] ✅ {candles_sent} candles históricos enviados ao dashboard", flush=True)
    print(f"[ENGINE] Buffer do dashboard agora tem {dashboard.get_buffer_size()} candles", flush=True)


    # Envia FVGs iniciais (se a estratégia já rodou no histórico?
    # A estratégia é instanciada mas não processou o histórico ainda no código original.
    # Vamos forçar um generate_signals no histórico pra popular os FVGs iniciais)
    logger.info("Gerando sinais e FVGs para o histórico inicial...")
    
    # Inicializa o DataFrame interno da estratégia com o histórico
    strategy.df = df_hist.copy()
    
    strategy.generate_signals(df_hist)
    if hasattr(strategy, "last_fvgs") and hasattr(dashboard, "set_fvg"):
        dashboard.set_fvg(strategy.last_fvgs)

    # Tenta restaurar posição aberta do disco (se existir)
    if hasattr(executor, "restore_position_from_disk"):
        executor.restore_position_from_disk(last_price=last_close_hist, last_dt=last_dt_hist)


    # ==============================
    # LOOP PRINCIPAL DO LIVE
    # ==============================
    last_status_check = 0.0
    last_fvg_push = 0.0
    consecutive_none_candles = 0
    max_consecutive_none = 3  # Após 3 timeouts, verifica status
    
    try:
        while True:
            candle = live.get_next_candle(timeout=30)

            if candle is None:
                consecutive_none_candles += 1
                logger.warning(f"⚠️ Nenhum candle recebido... (tentativa {consecutive_none_candles})")
                
                # A cada 3 timeouts consecutivos, verifica status do WebSocket
                if consecutive_none_candles >= max_consecutive_none:
                    logger.warning("🔍 Verificando status do WebSocket após múltiplos timeouts...")
                    print("\n⚠️ ATENÇÃO: Múltiplos timeouts detectados! Verificando WebSocket...")
                    live.print_status()
                    
                    status = live.check_connection_status()
                    
                    # Se não está conectado, avisa
                    if not status['connected']:
                        logger.error("❌ WebSocket NÃO está conectado!")
                        print("❌ ERRO: WebSocket Binance NÃO está conectado!")
                        notifier.send("⚠️ ALERTA: WebSocket Binance desconectado! Verifique a conexão.")
                    
                    # Se está muito tempo sem candles
                    elif status['seconds_since_last_candle'] and status['seconds_since_last_candle'] > 120:
                        elapsed_min = status['seconds_since_last_candle'] / 60
                        logger.error(f"❌ Sem candles há {elapsed_min:.1f} minutos!")
                        print(f"❌ ERRO: Sem receber candles há {elapsed_min:.1f} minutos!")
                        notifier.send(f"⚠️ ALERTA: Sem candles há {elapsed_min:.1f} minutos! WebSocket pode estar inativo.")
                    
                    consecutive_none_candles = 0  # Reseta contador
                
                continue
            
            # Reset contador quando recebe candle
            consecutive_none_candles = 0

            # Se for apenas um tick (update de preço real-time), não loga no console
            is_tick = candle.get("is_tick", False)
            now = time.time()

            if not is_tick:
                logger.info(
                    f"Candle recebido: {candle['datetime']} close={candle['close']}"
                )
                print(f"[ENGINE] ✅ Candle recebido: {candle['datetime']} | Close={candle['close']:.2f}")

            # 1) Estratégia processa candle (gera sinal + atualiza df interno)
            strategy_result = strategy.process_live_candle(candle)
            
            # Compatibilidade com versões antigas que retornavam int
            if isinstance(strategy_result, int):
                signal = strategy_result
                sl = 0.0
                tp = 0.0
                fvg_updated = False
            else:
                signal = strategy_result.get('signal', 0)
                sl = strategy_result.get('sl', 0.0)
                tp = strategy_result.get('tp', 0.0)
                fvg_updated = strategy_result.get('fvg_updated', False)

            # 1.1) Atualiza FVGs no dashboard (Apenas se candle fechou, para não pesar no front)
            push_fvg = False
            if hasattr(strategy, "last_fvgs") and hasattr(dashboard, "set_fvg"):
                if fvg_updated:
                    push_fvg = True  # sempre que recalculamos FVG, envia imediatamente
                elif candle.get("is_closed", False):
                    push_fvg = True
                elif (not is_tick) and (now - last_fvg_push > 5):
                    # Envia FVGs intrabar a cada poucos segundos para refletir gaps em tempo real
                    push_fvg = True

                if push_fvg:
                    fvgs_to_send = strategy.last_fvgs if strategy.last_fvgs is not None else pd.DataFrame()
                    try:
                        fvg_len = len(fvgs_to_send) if hasattr(fvgs_to_send, "__len__") else 0
                    except Exception:
                        fvg_len = 0
                    dashboard.set_fvg(fvgs_to_send)
                    last_fvg_push = now
                    logger.info(f"[ENGINE] FVGs enviados ao dashboard: {fvg_len}")

            # 2) Pega últimos indicadores internos da estratégia (se já tiver dados)
            ma_short = ma_long = rsi_val = None
            if hasattr(strategy, "df") and not strategy.df.empty:
                last_row = strategy.df.iloc[-1]
                if "ma_short" in last_row and pd.notna(last_row["ma_short"]):
                    ma_short = float(last_row["ma_short"])
                if "ma_long" in last_row and pd.notna(last_row["ma_long"]):
                    ma_long = float(last_row["ma_long"])
                if "rsi" in last_row and pd.notna(last_row["rsi"]):
                    rsi_val = float(last_row["rsi"])

            # 3) Envia candle ao dashboard
            dashboard.push_candle(
                {
                    "time": int(candle["datetime"].timestamp()),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle["volume"]),
                    "ma_short": ma_short,
                    "ma_long": ma_long,
                    "rsi": rsi_val,
                    "is_closed": candle.get("is_closed", False),  # <--- NOVA FLAG IMPRESCINDÍVEL
                }
            )

            # 3.1) Atualiza equity/saldo/pnl aberto no dashboard
            if hasattr(dashboard, "set_equity") and hasattr(executor, "current_position"):
                balance = risk.current_balance if hasattr(risk, "current_balance") else None
                open_pnl = 0.0
                if executor.current_position is not None:
                    pos = executor.current_position
                    qty = getattr(pos, "quantity", 0.0) or 0.0
                    entry = getattr(pos, "entry_price", 0.0) or 0.0
                    side_pos = getattr(pos, "side", "").lower()
                    last_price = float(candle["close"])
                    if side_pos in ("buy", "long"):
                        open_pnl = (last_price - entry) * qty
                    elif side_pos in ("sell", "short"):
                        open_pnl = (entry - last_price) * qty
                equity = balance + open_pnl if balance is not None else None
                dashboard.set_equity(balance, equity, open_pnl, ts=time.time())

            # 4) Atualiza orderbook no dashboard (a cada ~0.5s) SEM quebrar o loop
            if hasattr(dashboard, "set_orderbook") and now - last_ob_update > 0.5:
                try:
                    book_snapshot = ob_handler.get_snapshot()
                    dashboard.set_orderbook(book_snapshot)
                except Exception as e:
                    logger.warning(f"Falha ao atualizar orderbook no dashboard: {e}")
                finally:
                    last_ob_update = now
            
            # 4.1) Verifica status do WebSocket periodicamente (a cada 5 minutos)
            if now - last_status_check > 300:  # 5 minutos
                status = live.check_connection_status()
                if not status['connected']:
                    logger.error("❌ WebSocket desconectado detectado na verificação periódica!")
                    print("❌ ALERTA: WebSocket desconectado na verificação periódica!")
                    notifier.send("⚠️ ALERTA: WebSocket Binance desconectado!")
                elif status['seconds_since_last_candle'] and status['seconds_since_last_candle'] > 180:
                    elapsed_min = status['seconds_since_last_candle'] / 60
                    logger.warning(f"⚠️ Verificação periódica: Sem candles há {elapsed_min:.1f} minutos")
                    print(f"⚠️ Verificação: Sem candles há {elapsed_min:.1f} minutos")
                
                last_status_check = now

            # 4.2) VERIFICAR STOPS E TAKES (NOVO)
            if executor.current_position is not None:
                pos = executor.current_position
                sl = pos.stop_loss
                tp = pos.take_profit
                
                # LONG
                if pos.side == "buy":
                    # Checa SL (Low <= SL)
                    if sl and sl > 0 and candle["low"] <= sl:
                        logger.info(f"🛑 STOP LOSS atingido no LONG! Low={candle['low']} <= SL={sl}")
                        executor.close_position(
                            cfg.symbols[0],
                            sl, # Executa no preço do SL
                            candle["datetime"],
                            reason="Stop Loss 🛑"
                        )
                    # Checa TP (High >= TP)
                    elif tp and tp > 0 and candle["high"] >= tp:
                        logger.info(f"💰 TAKE PROFIT atingido no LONG! High={candle['high']} >= TP={tp}")
                        executor.close_position(
                            cfg.symbols[0],
                            tp, # Executa no preço do TP
                            candle["datetime"],
                            reason="Take Profit 💰"
                        )

                # SHORT
                elif pos.side == "sell":
                    # Checa SL (High >= SL)
                    if sl and sl > 0 and candle["high"] >= sl:
                        logger.info(f"🛑 STOP LOSS atingido no SHORT! High={candle['high']} >= SL={sl}")
                        executor.close_position(
                            cfg.symbols[0],
                            sl,
                            candle["datetime"],
                            reason="Stop Loss 🛑"
                        )
                    # Checa TP (Low <= TP)
                    elif tp and tp > 0 and candle["low"] <= tp:
                        logger.info(f"💰 TAKE PROFIT atingido no SHORT! Low={candle['low']} <= TP={tp}")
                        executor.close_position(
                            cfg.symbols[0],
                            tp,
                            candle["datetime"],
                            reason="Take Profit 💰"
                        )

            # 5) Execução de trades (fora da parte do orderbook)
            if signal == 1:
                notifier.send("📈 Sinal de COMPRA detectado")

                # Se estiver vendido, fecha
                if executor.current_position and executor.current_position.side.lower() == "sell":
                    executor.close_position(
                        cfg.symbols[0],
                        candle["close"],
                        candle["datetime"],
                        bid=candle.get("bid"),
                        ask=candle.get("ask"),
                        reason="Signal Reversal 🔄"
                    )

                # Tenta abrir compra
                executor.open_long(
                    cfg.symbols[0],
                    candle["close"],
                    candle["datetime"],
                    bid=candle.get("bid"),
                    ask=candle.get("ask"),
                    sl=sl,
                    tp=tp
                )

            elif signal == -1:
                notifier.send("📉 Sinal de VENDA detectado")

                # Se estiver comprado, fecha
                if executor.current_position and executor.current_position.side.lower() == "buy":
                    executor.close_position(
                        cfg.symbols[0],
                        candle["close"],
                        candle["datetime"],
                        bid=candle.get("bid"),
                        ask=candle.get("ask"),
                        reason="Signal Reversal 🔄"
                    )

                # Tenta abrir venda
                executor.open_short(
                    cfg.symbols[0],
                    candle["close"],
                    candle["datetime"],
                    bid=candle.get("bid"),
                    ask=candle.get("ask"),
                    sl=sl,
                    tp=tp
                )

            # 6) Atualiza PnL em aberto (informativo)
            executor.update_position(cfg.symbols[0], candle["close"])

    except KeyboardInterrupt:
        logger.info("Encerrando OracleWalk LIVE...")
        live.stop()
        notifier.send("🛑 OracleWalk LIVE finalizado.")
