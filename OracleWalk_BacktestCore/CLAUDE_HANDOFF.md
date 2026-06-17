# Claude Handoff - MT5 Validation Track

## Objetivo

Construir a trilha de validacao externa contra o MetaTrader 5, sem alterar o motor principal do BacktestCore. O foco do Claude deve ser provar, com casos pequenos e auditaveis, onde o BacktestCore bate ou diverge do Strategy Tester do MT5.

## Escopo do Claude

### 1. EA MQL5 de referencia

Criar um Expert Advisor MQL5 simples para Strategy Tester, preferencialmente em:

```text
backtest_core/brokers/mt5/mql5/ReferenceEmaCrossEA.mq5
```

Requisitos:

- Usar a mesma ideia da estrategia `ema_cross` do BacktestCore.
- Parametros:
  - `FastPeriod`
  - `SlowPeriod`
  - `Lots`
  - `StopAtr`
  - `TakeAtr`
  - `AtrPeriod`
  - `CloseOnOpposite`
- Registrar entradas e saidas em CSV com:

```text
ticket,side,entry_time,entry_price,exit_time,exit_price,lots,pnl,commission,swap,reason
```

### 2. Exportar resultados do Strategy Tester

Criar um roteiro documentado para rodar o EA no MT5 usando:

- mesmo simbolo;
- mesmo timeframe;
- mesmo intervalo;
- modo `Every tick based on real ticks`;
- mesmo saldo inicial;
- mesma alavancagem;
- mesmos custos configuraveis quando o MT5 permitir.

O roteiro deve ficar em:

```text
docs/mt5_validation.md
```

### 3. Comparador trade a trade

Criar script Python para comparar trades do MT5 com trades do BacktestCore:

```text
scripts/compare_mt5_trades.py
```

Entrada sugerida:

```bash
python scripts/compare_mt5_trades.py \
  --mt5 path/to/mt5_trades.csv \
  --bt reports/some_run/trades.csv \
  --price-tol 0.00002 \
  --time-tol-seconds 5
```

Saida esperada:

- total de trades em cada lado;
- trades pareados;
- trades ausentes no MT5;
- trades ausentes no BacktestCore;
- diferenca media/maxima de entrada;
- diferenca media/maxima de saida;
- diferenca media/maxima de PnL;
- CSV de divergencias.

### 4. Casos de validacao pequenos

Criar casos pequenos e reprodutiveis:

```text
validation_cases/
  eurusd_h4_ema_cross/
    README.md
    mt5_trades.csv
    backtestcore_trades.csv
    comparison.json
```

Prioridade:

1. EURUSD H4 EMA Cross sem SL/TP.
2. EURUSD H4 EMA Cross com SL/TP.
3. EURUSD M1 mean reversion, se o EA de referencia ficar viavel.

## Fora do escopo do Claude

Nao alterar:

- `backtest_core/core/engine.py`
- `backtest_core/core/runner.py`
- `backtest_core/ui/server.py`
- `backtest_core/ui/static/app.js`

Esses arquivos ficam com o Codex neste ciclo, para evitar conflito na implementacao de execucao tick-by-tick.

## Contexto importante

O exportador MT5 atual fica em:

```text
backtest_core/brokers/mt5/mql5/ExportBacktestPackage.mq5
```

Ele exporta:

```text
candles.csv
ticks.csv
symbol_spec.json
account_spec.json
export_manifest.json
```

O pacote deve ser copiado para:

```text
data/broker_exports/<Broker>/<Symbol>/<Timeframe>/
```

## Criterios de aceite

- EA compila no MetaEditor com 0 erros.
- Roteiro `docs/mt5_validation.md` permite repetir o teste manualmente.
- Comparador roda com `--help`.
- Pelo menos um caso pequeno tem resultado documentado.
- Divergencias devem ser explicadas, nao escondidas.
