# OracleWalk — Arquitetura

## Visão geral
OracleWalk é um motor de trading para Binance com dois modos:
- **backtest**: simula sinais/execução sobre histórico recente.
- **live**: consome WebSockets, executa estratégia ICT em tempo real, publica resultados no dashboard e Telegram.

## Componentes
- **core/engine.py**: orquestra backtest e live; inicializa dependências, controla o loop principal e integra dashboard + notificações.
- **config/config_loader.py**: carrega configurações de `.env` e/ou `config.txt` (chaves, risco, timeframe, flags de modo).
- **data/**:
  - `data_handler.py`: histórico REST via Binance.
  - `live_data.py`: WebSocket multiplex (kline + bookTicker + aggTrade) com fila thread-safe.
  - `orderbook_data.py`: depth socket dedicado.
  - `indicators.py`: indicadores (RSI, ATR, MACD, BBands, FVG, orderblocks).
- **strategy/**:
  - `inner_circle_trader.py`: estratégia ICT/FVG (retornos de sinal, SL/TP, reteste 50%, EMA50).
  - `ma_rsi_strategy.py`: estratégia MA+RSI com modo intrabar/close.
  - `base_strategy.py`: contrato base.
- **execution/**:
  - `risk_manager.py`: sizing por percentual de risco, tracking de equity.
  - `execution_price_model.py`: simulação de execução (bid/ask, slippage, taxas maker/taker).
  - `trade_executor.py`: abre/fecha posição, atualiza PnL, envia para DB, dashboard e Telegram; persiste posição aberta.
  - `trade_logger.py`: CSVs (principal + diário) com preços brutos/execução.
  - `order_model.py`: dataclass de posição.
- **dashboard/server.py**: Flask + Lightweight Charts; serve candles (histórico + live), trades, orderbook, FVGs e equity.
- **notifications/telegram_notifier.py**: wrapper resiliente para envio de mensagens (fallback a log se lib indisponível).
- **optimization/**: `backtester.py` (simples) e `walk_forward.py` (grid search com janela rolante).
- **storage/database.py**: SQLite para trades e curva de equity.

## Fluxos principais
### Backtest
```
main -> core.engine.run_backtest
    -> config_loader.AppConfig
    -> HistoricalDataHandler (REST Binance)
    -> RiskManager + InnerCircleTrader
    -> Backtester.run (gera sinais, simula entradas/saídas)
    -> TelegramNotifier envia resumo
```

### Live
```
main -> core.engine.run_live
    -> AppConfig (env + config.txt)
    -> TelegramNotifier, DatabaseManager, RiskManager
    -> OrderBookHandler (depth WS)
    -> DashboardServer (Flask thread)
    -> LiveDataHandler (WS kline/bookTicker/aggTrade, fila)
    -> TradeExecutor (execução/dry-run + persistência + dashboard + telegram)
    -> HistoricalDataHandler (preload de histórico p/ indicadores + dashboard)
    -> InnerCircleTrader.process_live_candle (sinal + FVGs)
    -> Loop infinito: lê candle da fila, processa sinal, push para dashboard, monitora conexão, checa SL/TP, envia ordens/alertas.
```

### Dados e buffers
- **Fila de candles**: `LiveDataHandler` empilha mensagens do WS; engine consome via `get_next_candle`.
- **Dashboard**:
  - `_history_buffer`: candles fechados (maxlen configurável).
  - `_live_candle`: candle em formação.
  - `_trades`: deque de trades para plotagem.
  - `fvg_buffer`: últimas FVGs geradas.
  - `orderbook` snapshot.
- **Persistência**:
  - `trades.csv` + `logs/trades_YYYY-MM-DD.csv`
  - `oraclewalk.db` (SQLite) para trades/equity.
  - `open_position.json` para restaurar posição após restart.

## Configuração e segurança
- Config preferencial via `.env` (gitignored); `config.txt` opcional (`config.example.txt` incluído).
- Campos críticos: chaves Binance, credenciais Telegram, `mode`, `dry_run`, `risk_per_trade`, taxas/slippage.
- `dry_run=true` evita ordens reais; mantenha até validar comportamento.
- Arquivos sensíveis ignorados em `.gitignore` (config.txt, .env, db, logs, trades.csv).

## Pontos de extensão
- Estratégias: implemente `StrategyBase` e injete no engine.
- Execução: ajuste `ExecutionPriceModel` para cenários de fee/slippage diferentes.
- Dashboard: adicione endpoints em `DashboardServer` ou novos dados via setters (`set_fvg`, `set_orderbook`, `set_equity`, `push_trade`, `push_candle`).
- Otimização: expanda grids em `walk_forward.py` ou substitua o `Backtester`.
