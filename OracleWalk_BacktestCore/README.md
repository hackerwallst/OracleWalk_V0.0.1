# OracleWalk BacktestCore

Pasta enxuta para iniciar um novo projeto usando apenas o motor de backtest e o exportador de relatorio.

Nao inclui:
- Binance
- Telegram
- dashboard live
- executor live
- WebSocket
- banco SQLite

Inclui:
- `Backtester` candle-by-candle com SL, TP, trailing, MFE, MAE, slippage, comissao e sizing por risco.
- Estrategias plugaveis via `StrategyBase`.
- Indicadores nativos separados por familia.
- CLI por arquivo JSON.
- Metricas de performance.
- Exportacao de `trades.csv`, `metrics.json`, graficos PNG e HTML com imagens embutidas.
- Exemplo executavel em `examples/run_demo.py`.

## Estrutura do projeto

```text
backtest_core/
  core/          # motor, contratos e runner oficial
  data/          # loaders CSV, validacao e resample
  indicators/    # trend, momentum, volatility, volume, ICT e registry
  strategies/    # base.py + exemplos plugaveis
  execution/     # custos, slippage e comissao
  risk/          # sizing
  analytics/     # metricas, regimes e Monte Carlo
  report/        # exportacao de relatorio
configs/         # configs JSON para rodar backtest
data/raw/        # CSV bruto por ativo/timeframe
reports/         # saida dos backtests
```

## Instalar

### Instalacao automatica (recomendado)

Use o instalador nativo do seu sistema. Ele cuida de tudo: detecta Python 3.9+, instala se faltar (via `brew` no Mac ou `winget` no Windows), cria o ambiente virtual `.venv`, atualiza o `pip`, instala o pacote em modo editavel e valida a instalacao rodando o exemplo MT5 incluido no projeto.

- **macOS**: clique duplo em `install.command` no Finder. Tambem da pra rodar pelo Terminal:

  ```bash
  bash install.command
  ```

- **Windows**: clique duplo em `install.bat` no Explorer. Tambem da pra rodar pelo `cmd`:

  ```bat
  install.bat
  ```

Se Python nao estiver instalado e o gerenciador nativo (`brew`/`winget`) tambem nao existir, o script aborta com o link de download oficial.

Depois de instalar, abra a interface web por duplo clique:

- **macOS**: `run_ui.command`
- **Windows**: `run_ui.bat`

A interface abre em:

```text
http://127.0.0.1:8765
```

### Instalacao manual

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

## Rodar demo

```bash
python examples/run_demo.py
```

O relatorio sai em:

```text
reports/demo/backtest_report.html
```

## Rodar com config JSON

Coloque o CSV em:

```text
data/raw/BTCUSDT/1h/BTCUSDT_1h.csv
```

Depois rode:

```bash
python -m backtest_core.cli --config configs/demo.json
```

Se instalar com `pip install -e .`, tambem pode usar:

```bash
backtest-core --config configs/demo.json
```

## CSV exportado do MT5

O loader nativo para MT5 aceita CSV como:

```text
time,open,high,low,close,tick_volume,spread
2026.04.29 00:00,1.17104,1.17146,1.17104,1.17112,211,22
```

Para rodar o exemplo EURUSD organizado em `data/raw/EURUSD/H1/`:

```bash
python -m backtest_core.cli --config configs/mt5_eurusd_h1.json
```

O loader normaliza para:

```text
datetime, open, high, low, close, volume, tick_volume, spread
```

No MT5, `spread` vem em pontos. O motor converte para preco usando `point`.

## Exportador oficial MT5

O script fica em:

```text
backtest_core/brokers/mt5/mql5/ExportBacktestPackage.mq5
```

Como usar:

1. Abra o MetaEditor.
2. Copie `ExportBacktestPackage.mq5` para `MQL5/Scripts/`.
3. Compile.
4. No MT5, abra o grafico do ativo/timeframe desejado e rode o script.
5. Ele exporta uma pasta com:

```text
candles.csv
ticks.csv
symbol_spec.json
account_spec.json
export_manifest.json
```

Esses arquivos formam um pacote auditavel:

```text
data/broker_exports/
  NomeDaCorretora/
    EURUSD/
      H1/
        candles.csv
        ticks.csv
        symbol_spec.json
        account_spec.json
        export_manifest.json
```

Por padrao, o exportador usa:

- ativo do grafico atual, se `InpSymbol` estiver vazio;
- timeframe do grafico atual, se `InpTimeframe = PERIOD_CURRENT`;
- todos os candles disponiveis, se `InpBars = 0`;
- todos os ticks disponiveis no intervalo exportado, se `InpMaxTicks = 0`.

Para rodar diretamente esse pacote:

```bash
python -m backtest_core.cli \
  --broker-package data/broker_exports/NomeDaCorretora/EURUSD/H1
```

Nesse modo, o BacktestCore le automaticamente:

- candles e spread;
- ticks reais exportados pelo MT5, quando `ticks.csv` existir no pacote;
- `contract_size`;
- `point`;
- `digits`;
- lote minimo/maximo/step;
- swap long/short;
- dados de conta;
- servidor/corretora/data da exportacao.

Observacao: muitas corretoras nao expoem a comissao de forma confiavel para scripts MT5. Quando `symbol_spec.json` vier com `commission_per_lot: null`, preencha manualmente ou use um config JSON de override.

### Ticks reais no pacote MT5

O campo `tick_volume` em `candles.csv` e apenas a quantidade de ticks dentro do candle. Ele nao traz a ordem real do movimento.

Para backtests/replays intrabar mais fieis, o exportador tambem gera `ticks.csv` usando `CopyTicksRange(COPY_TICKS_ALL)`, com:

```text
time,time_msc,bid,ask,last,volume,volume_real,flags
```

Por padrao `InpMaxTicks = 0`, ou seja, sem limite. Se quiser evitar arquivos gigantes, defina um limite manual no input do script dentro do MT5.

### Execucao tick-by-tick

Quando um pacote MT5 tiver `ticks.csv`, o BacktestCore pode executar SL, TP, trailing stop e stop-out na sequencia real de ticks `bid/ask`.

Pelo CLI:

```bash
python -m backtest_core.cli \
  --config configs/mt5_eurusd_h1.json \
  --broker-package data/broker_exports/NomeDaCorretora/EURUSD/H1 \
  --execution-mode tick \
  --entry-timing next_bar_open
```

Ou no JSON:

```json
{
  "engine": {
    "execution_model": "realistic",
    "execution_mode": "tick",
    "entry_timing": "next_bar_open"
  }
}
```

Use `"execution_mode": "candle"` para manter o comportamento candle-by-candle classico.

`execution_model` controla a causalidade da execução:

- `"realistic"`: padrão. Um sinal confirmado no fechamento não pode entrar em um preço intrabar daquele mesmo candle. Use `entry_timing = "next_bar_open"` para ordens a mercado, ou declare `order_type = "limit"` / `"stop"` para preços pendentes causais.
- `"idealized"`: comportamento legado de pesquisa. Pode aceitar `entry_price` dentro do candle do sinal e, portanto, pode conter viés de execução.

`entry_timing` controla quando um sinal de candle vira ordem:

- `"next_bar_open"`: padrão realista; entra no próximo candle, ou no primeiro tick desse candle quando `execution_mode = "tick"`.
- `"signal_close"`: só é seguro para preço de mercado no fechamento. Entradas intrabar explícitas são rejeitadas no modo realista.

## Onde colocar CSV de ativo/timeframe

Use a pasta `data/raw` neste formato:

```text
data/raw/
  BTCUSDT/
    1h/
      BTCUSDT_1h.csv
    15m/
      BTCUSDT_15m.csv
  EURUSD/
    M5/
      EURUSD_M5.csv
```

O CSV precisa conter:

```text
datetime, open, high, low, close, volume
```

Tambem sao aceitos aliases para tempo:

```text
time, timestamp, date, open_time
```

## Custos de corretora

O engine aceita estes campos em `engine` no JSON:

```json
{
  "contract_size": 100000.0,
  "leverage": 30.0,
  "margin_rate": null,
  "stop_out_level_pct": null,
  "point": 0.00001,
  "use_spread": true,
  "spread_column": "spread",
  "fixed_spread_points": null,
  "commission_per_lot": 3.5,
  "commission_perc": 0.0,
  "swap_long_per_lot": -7.5,
  "swap_short_per_lot": 2.5,
  "triple_swap_weekday": 2
}
```

Significado:

- `contract_size`: unidades por lote. Em forex normalmente `100000`.
- `leverage`: alavancagem da conta. Ex.: `30`, `100`, `500`.
- `margin_rate`: margem direta, se quiser sobrescrever a alavancagem. Ex.: `0.033333` equivale a 1:30.
- `stop_out_level_pct`: se definido, fecha posicoes quando equity/margem usada cair abaixo desse nivel.
- `point`: tamanho de 1 ponto do ativo. Em EURUSD com 5 digitos, `0.00001`.
- `use_spread`: aplica spread no preco de entrada/saida.
- `spread_column`: coluna do CSV com spread em pontos.
- `fixed_spread_points`: se preencher, ignora o spread do CSV e usa valor fixo.
- `commission_per_lot`: comissao por lote por lado da operacao.
- `commission_perc`: comissao percentual sobre nocional, util para cripto/acoes.
- `swap_long_per_lot`: swap diario por lote para posicao long.
- `swap_short_per_lot`: swap diario por lote para posicao short.
- `triple_swap_weekday`: dia do swap triplo, `2` = quarta-feira.

O `trades.csv` exportado inclui:

```text
gross_pnl, commission_open, commission_close, swap,
entry_spread_points, exit_spread_points,
notional_value, leverage, margin_required, free_margin_at_entry,
pnl
```

Ou seja: `pnl` ja e liquido de spread, comissoes e swap.

Alavancagem nao muda o PnL do trade. Ela muda:

- margem requerida;
- tamanho maximo possivel pela margem livre;
- risco de stop-out, se `stop_out_level_pct` estiver ativo.

## Contrato dos dados

`data` precisa ter:

```text
datetime, open, high, low, close, volume
```

`signals` precisa ter:

```text
datetime, signal
```

Colunas opcionais aceitas em `signals`:

```text
entry_price, stop_price, take_price, size, risk, trailing_distance
```

`signal`:
- `1`: long
- `-1`: short
- `0`: sem acao

## Onde encaixar estrategia

Crie uma classe em `backtest_core/strategies/` herdando de `StrategyBase`:

```python
from backtest_core.strategies import StrategyBase

class MinhaEstrategia(StrategyBase):
    name = "Minha Estrategia"

    def prepare_indicators(self, data):
        return data

    def generate_signals(self, data):
        return signals
```

A estrategia so deve devolver sinais. Execucao, custos, risco, metricas e relatorio ficam fora dela.

### Estrategia M1 Retorno as Medias

A estrategia documentada em `Estrategia Retorno As Médias.md` foi automatizada em:

```text
backtest_core/strategies/mean_reversion_m1.py
```

Ela fica disponivel no CLI pelo nome:

```text
m1_mean_reversion
```

Config pronta para o pacote MT5 EURUSD M1:

```text
configs/mt5_eurusd_m1_mean_reversion.json
```

Versao crua, somente a ideia base de retorno as medias:

```text
configs/mt5_eurusd_m1_mean_reversion_raw.json
```

Comando:

```bash
PYTHONPATH=. python3 -m backtest_core.cli \
  --config configs/mt5_eurusd_m1_mean_reversion.json \
  --broker-package "data/broker_exports/FTMO Global Markets Ltd/EURUSD/M1"
```

Observacao: essa primeira versao e uma traducao mecanica/auditavel da ideia do README. Filtros discricionarios como noticia, zonas SupDem desenhadas manualmente e leitura contextual de breakout foram aproximados por distancia das EMAs, rejeicao por pavio, Heiken Ashi, RSI e volume.

## Interface grafica de replay

O cockpit web interativo fica em:

```text
backtest_core/ui/
```

Comando para abrir a estrategia crua no pacote MT5 EURUSD M1:

```bash
PYTHONPATH=. python3 -m backtest_core.ui.server \
  --config configs/mt5_eurusd_m1_mean_reversion_raw.json \
  --broker-package "data/broker_exports/FTMO Global Markets Ltd/EURUSD/M1"
```

Depois abra:

```text
http://127.0.0.1:8765
```

A interface reutiliza `trades.csv` e `metrics.json` do relatorio quando eles ja existem, para abrir rapido. Use `--no-reuse-report` se quiser forcar um backtest novo antes de abrir o replay.

## Indicadores nativos

```text
backtest_core/indicators/trend.py       # SMA, EMA, ADX, Supertrend
backtest_core/indicators/momentum.py    # RSI, MACD, Stochastic
backtest_core/indicators/volatility.py  # ATR, Bollinger Bands
backtest_core/indicators/volume.py      # VWAP, volume features
backtest_core/indicators/ict.py         # FVG, order blocks
backtest_core/indicators/registry.py    # pipeline declarativa
```

## Uso minimo

```python
from backtest_core import Backtester, generate_report_bundle

config = {
    "initial_capital": 1000.0,
    "risk_per_trade_pct": 1.0,
    "commission_perc": 0.0004,
    "slippage": 0.0001,
}

bt = Backtester(data, config)
trades = bt.run(signals)

generate_report_bundle(
    data=data,
    trades=trades,
    config=config,
    output_dir="reports/minha_estrategia",
)
```
