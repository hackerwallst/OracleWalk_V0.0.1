# Codex Handoff — Backtest Interativo (Replay Manual + EA)

## A ideia (contexto do dono do projeto)

A estratégia real do dono é de **suporte e resistência**, robusta no MQL5. O
problema: hoje o único jeito de testar é **voltar o gráfico manualmente e
desenhar as zonas** — só que desenhar num gráfico já formado é **trapaça**, você
já viu onde o preço respeitou e onde rompeu (viés de retrospectiva / lookahead).
O backtest fica desonesto e nunca se sabe se a estratégia tem edge de verdade.

A evolução: transformar o BacktestCore num **simulador de replay interativo**
(estilo TradingView Bar Replay), onde:

1. O gráfico avança **candle a candle**, mostrando só o passado até o "agora".
2. O usuário **desenha as zonas de S/R ao vivo**, sem ver o futuro → mata o
   lookahead. Uma zona só vale para candles **posteriores** ao momento em que
   foi desenhada.
3. Um **EA roda junto, automático**, e entra sozinho quando as condições baterem
   (no caso real: preço dentro de zona ativa + exaustão de osciladores).
4. No fim, sai o **mesmo relatório robusto** que já existe.

> **IMPORTANTE:** NÃO é pra codar a estratégia real do dono (os osciladores de
> exaustão etc.). O foco é a **infraestrutura de backtest interativo**. A
> estratégia entra depois, plugada numa base própria. Para validar, usa-se só um
> stub bobo de estratégia.

### Particularidade obrigatória: trilho separado

Isto **não pode quebrar nem se misturar** ao backtest clássico que já existe. É
um **modo separado**, escolhido conscientemente pelo usuário quando vai rodar uma
estratégia de alto grau (interação humana + EA). Separação nas duas camadas:

- **Código:** tudo novo vive em caminhos próprios. Ninguém edita o motor batch
  atual (`core/engine.py`, `core/runner.py`) nem a estratégia batch
  (`strategies/base.py`).
- **Interface:** o modo interativo é uma **página separada**. A UI clássica de
  hoje (`ui/static/index.html`, `app.js`) continua intocada.

---

## Princípio da divisão (anti-conflito)

> **Claude escreve o BACKEND (motor, estado, API). Codex escreve o FRONTEND
> (gráfico, desenho, replay visual).** Os dois se encontram só no **contrato REST**
> documentado abaixo. Nenhum agente edita arquivo do outro.

Backend roda o replay e é a fonte da verdade. Frontend desenha e manda comandos.

## Propriedade de arquivos

| Arquivo / módulo | Dono | Observação |
| --- | --- | --- |
| `backtest_core/interactive/` (pacote novo) | **Claude** | motor pausável, zonas, base de estratégia, sessão |
| `backtest_core/interactive/routes.py` | **Claude** | rotas REST `/interactive/*` |
| `backtest_core/ui/server.py` | **Claude** | só o Claude liga as rotas/página novas aqui |
| `backtest_core/ui/static/interactive/` (pasta nova) | **Codex** | TODO o frontend do modo interativo |
| `tests/interactive/` (pasta nova) | **Claude** | testes do backend |
| Tudo já existente (`core/engine.py`, `runner.py`, `ui/static/app.js`, etc.) | **ninguém toca** | trilho clássico congelado |

Regra dura: se você (Codex) sentir que precisa editar **qualquer arquivo `.py`**,
**pare** e registre a necessidade de endpoint no fim deste arquivo, na seção
"Pedidos de interface". Não edite Python.

---

## Escopo do CODEX — Frontend do modo interativo

Crie **uma pasta nova** e trabalhe só dentro dela:

```text
backtest_core/ui/static/interactive/
  index.html       # página do modo interativo (separada da UI clássica)
  chart.js         # candlestick estilo TradingView (use lightweight-charts)
  zones.js         # desenhar / mover / apagar retângulos de zona (overlay)
  replay.js        # controles play / pause / step / velocidade
  styles.css       # estilo da página
  vendor/          # lightweight-charts (standalone, sem build/npm)
```

Restrições técnicas:

- **Sem build step, sem npm.** O servidor é um `http.server` simples que entrega
  arquivos estáticos. Use `lightweight-charts` na versão **standalone**
  (um `.js` em `vendor/`). Tudo em JS puro (vanilla) — pode usar ES modules.
- A página é servida pelo Claude na rota **`GET /interactive`** (o Claude liga
  isso no `server.py`). Você só precisa garantir que os arquivos existam na pasta
  acima; eles serão acessíveis em `/static/interactive/...`.
- Você constrói **contra o contrato REST abaixo**. Pode começar já, em paralelo,
  **mockando** as respostas se o backend ainda não estiver pronto.

### Tarefas do Codex (Fase 2)

1. **Gráfico** (`chart.js`): candlestick que renderiza o histórico inicial
   devolvido por `/interactive/session/new` e vai **anexando** cada novo candle
   conforme `/interactive/step`. Tempo no formato UNIX em segundos (UTC).
2. **Camada de zonas** (`zones.js`): ferramenta de desenho de **retângulos** por
   cima do gráfico (arrasta pra criar uma faixa de preço). Cada ação chama a API:
   - criar → `POST /interactive/zone`
   - mover/redimensionar → `PUT /interactive/zone/{id}`
   - apagar → `DELETE /interactive/zone/{id}`
   Renderize zonas distinguindo `support` (ex.: verde) de `resistance` (ex.:
   vermelho), e marque visualmente quando `state == "broken"`.
3. **Controles de replay** (`replay.js`): botões **play / pause / step (+1) /
   velocidade**. O play é dirigido pelo frontend: chame `POST /interactive/step`
   num timer na velocidade escolhida (ex.: 4 candles/seg). Botão **Finalizar**
   chama `POST /interactive/finish` e abre o relatório retornado.
4. **Painel de estado**: mostre o que vier em cada snapshot — equity, balance,
   trades abertos (entry/SL/TP/PnL não realizado) e o bloco `indicators`
   (mostre genericamente as chaves que vierem; os osciladores reais entram
   depois). Desenhe marcadores de entrada/saída dos trades no gráfico.

> Não assuma nomes de indicadores fixos. O `indicators` do snapshot é um dicionário
> aberto; renderize as chaves que existirem.

---

## ⭐ Multi-timeframe (MTF) — a nova missão do gráfico

A estratégia real é **multi-timeframe e dirigida pela ZONA** (não por um preset fixo).
Regras duras:
- **Exaustão na TF da zona.** Zona de **H4** exige exaustão em **H4**; zona de **H1**,
  em **H1**; zona de **D1**, em **D1**. Quem manda é a TF da zona, não o gráfico.
- **Média (cruzamento, modo COM) na TF um degrau ABAIXO da zona:** D1→H1, H4→M15,
  H1→M5, M15→M1. (No backtest só dá pra derivar TFs **mais grossas** que o dado base,
  então a média de uma zona H4/H1 só existe quando houver dado fino tipo M1; com dado
  H1, a zona D1 já tem média (H1). No modo **SEM** isso não importa — não usa média.)

O backend já faz tudo isso (deriva as TFs coarser do base, lê osciladores e a média
por TF, causalmente). As TFs que a zona pode ter vêm em `session_info.zone_timeframes`
(ex.: base H1 → `["H1","H4","D1"]`). **Falta o gráfico aguentar zonas de TFs diferentes
ao mesmo tempo, sem se anularem.**

O que o frontend precisa fazer (tudo dentro de `ui/static/interactive/`):

1. **Seletor de TF da zona ao desenhar.** Hoje você já tem Suporte/Resistência; some
   um seletor de **TF** (H1/H4) — as opções vêm de `session_info.zone_timeframes`
   (ex.: `["H1","H4"]`). Ao criar, mande `timeframe` no `POST /interactive/zone`.
2. **Zonas de TFs diferentes coexistem.** Desenhar uma zona H4 **não pode apagar**
   nem sobrescrever as zonas H1, e vice-versa. Todas ficam visíveis juntas. (O backend
   já guarda todas; é só renderizar todas as que vierem em `snapshot.zones`, cada uma
   com seu `timeframe`.)
3. **Distinção visual por TF.** Diferencie a TF da zona — ex.: H4 com borda mais grossa
   ou um rótulo "H4"/"H1" no canto da zona, além da cor de suporte/resistência. O
   objetivo é o usuário bater o olho e saber em que TF cada zona está.
4. **Painel de osciladores por TF.** O snapshot agora traz `tf_indicators`
   (veja abaixo): `{ "H1": {...}, "H4": {...} }`. Mostre os osciladores das duas TFs
   lado a lado (H4 pode vir vazio no começo — é warmup, vai preenchendo).

> Não precisa trocar o stream de candles do gráfico (continua na TF base, ex.: H1).
> As zonas são faixas de **preço**, então convivem naturalmente sobre o mesmo gráfico,
> independentemente da TF — o trabalho é tag + render + não-anular.

`session_info` (resposta do `session/new`) ganhou: `base_timeframe` (ex.: `"H1"`) e
`zone_timeframes` (ex.: `["H1","H4"]`). O snapshot (`step`/`state`) ganhou
`tf_indicators` (dict TF→indicadores). O objeto-zona ganhou `timeframe`.

---

## ⭐⭐ Missão grande: deixar o gráfico ~99% TradingView

Objetivo: a experiência do gráfico do backtester interativo o mais próxima possível
do TradingView — ferramentas, replay, fluidez. **Não é scraping do app do TradingView**
(proprietário/ofuscado, fora dos termos, não reusável). Em vez disso, **puxe o
open-source oficial do próprio TradingView** e a comunidade:

- **Lightweight Charts (Apache-2.0)** — já vendorizado (`vendor/`). É o motor do gráfico.
- **`lightweight-charts` › `plugin-examples` (Apache-2.0)** — exemplos prontos de
  **drawing tools** (retângulo, trend line, linha horizontal/vertical, brush, etc.).
  Vendorize/adapte os que precisar (sem npm/build, vanilla JS).
- **Panes nativos do Lightweight Charts v5** — use para os **sub-painéis de
  osciladores** (RSI/Stoch/UO) abaixo dos candles, e para o volume.

Tudo continua dentro de `ui/static/interactive/`, sem tocar em Python. O backend já
expõe os dados necessários (séries, seek, metadata) — veja os endpoints novos abaixo.

### Checklist de paridade com o TradingView (dono do Codex)

**Gráfico / núcleo**
- [ ] Tipos: candle, barra, linha, área (toggle). Escala log/linear. Tema escuro.
- [ ] Crosshair com legenda OHLC no topo (estilo TV) + valores dos indicadores.
- [ ] Zoom/scroll suave, auto-fit, botão "ir pro fim".
- [ ] **Troca de timeframe do gráfico** (H1/H4…): use `POST /interactive/series {tf}`
      pra trocar os candles exibidos pela TF escolhida (o backend devolve OHLCV+indicadores
      daquela TF até o cursor). As **zonas continuam visíveis** (são faixas de preço).

**Barra de ferramentas de desenho (lateral, como no TV)**
- [ ] **Zona/Retângulo** (já é a ferramenta de trading — manda pro `/zone` com `timeframe`).
- [ ] Trend line, linha horizontal/ray, linha vertical, fib retracement, texto, brush,
      régua/measure. (Essas são **visuais**; podem viver no cliente. Persistência no
      backend é opcional/futura — se quiser, peça um endpoint.)
- [ ] Selecionar/mover/redimensionar/apagar desenho; snap; borracha; "remover todos".

**Sub-painéis de indicadores (panes)**
- [ ] RSI, Stoch %K, Ultimate Oscillator em panes próprios (0–100) com linhas de
      sobrecompra/sobrevenda. Use `session_info.indicators_meta` (quais são overlay vs
      pane + thresholds) e `POST /interactive/series` pra desenhar a série inteira;
      a cada `step`, anexe o ponto novo (`snapshot.indicators` / `snapshot.tf_indicators`).
- [ ] **SMA60** como **overlay** na faixa de preço (vem em `indicators_meta.overlays`).

**Replay (como o Bar Replay do TV)**
- [ ] Play/Pause/Step/velocidade (já existe). Adicione uma **timeline arrastável
      (scrubber)**: use `POST /interactive/seek {bar}` pra pular pra qualquer candle
      (pra trás reexecuta determinístico — pode arrastar livre). `POST /interactive/reset`
      volta ao início.
- [ ] Marcadores de entrada/saída dos trades, linhas de SL/TP da posição aberta.

**Fluidez / UX**
- [ ] Atalhos de teclado (espaço = play/pause, →/← = step, etc.).
- [ ] Menu de contexto (botão direito) no gráfico e nos desenhos.
- [ ] Persistência de layout/desenhos no `localStorage` (visual).

> Estratégia de implementação sugerida: comece pelos **panes de osciladores** + **SMA
> overlay** + **scrubber** (tudo já tem backend). Depois a **barra de drawing tools**
> (adaptando o `plugin-examples`). Por último o polimento (atalhos, menus, temas).

---

## Contrato REST (a fronteira entre Codex e Claude)

Base: `http://127.0.0.1:8765`. Tudo sob o prefixo **`/interactive`**.
Corpo e resposta em **JSON**. Há **uma sessão ativa** por vez (ferramenta local
mono-usuário).

### `GET /interactive/catalog`
Lista o que está disponível pra montar os seletores da UI (ativo, TF, modo).
Response:
```json
{
  "datasets": [
    {"symbol": "EURUSD", "timeframe": "H1", "path": "data/raw/EURUSD/H1/EURUSD_H1.csv"},
    {"symbol": "XAUUSD", "timeframe": "H4", "path": "data/raw/XAUUSD/H4/XAUUSD_H4.csv"}
  ],
  "strategies": ["sr_quant", "stub"],
  "modes": ["SEM", "COM", "AMBOS"]
}
```
**UI pedida:** dois dropdowns — **Ativo** (symbols distintos) e **Timeframe** (TFs do
symbol escolhido) — alimentados por este endpoint, mais o seletor de **Modo**
(SEM/COM/AMBOS; default **SEM**). Ao criar a sessão, manda `symbol` + `timeframe`
escolhidos (ver abaixo). O backend já carrega o CSV certo e aplica os parâmetros do
instrumento (point/contract size de ouro ≠ forex).

### `POST /interactive/session/new`
Carrega dados + estratégia stub e posiciona o cursor no fim do warmup.

Request:
```json
{ "symbol": "XAUUSD", "timeframe": "H4", "strategy": "sr_quant", "mode": "SEM" }
```
`symbol` + `timeframe` (vindos do `/interactive/catalog`): escolhem o ativo/TF. Se
omitidos, cai no `config` (ex.: `{ "config": "configs/mt5_eurusd_h1.json" }`).
`strategy` (opcional, default `"sr_quant"`): `"sr_quant"` (a estratégia real S&R) ou
`"stub"` (toque-de-zona, só pra testar o motor). `mode` (opcional, default `"SEM"`,
só vale pro sr_quant): `"SEM"`, `"COM"` ou `"AMBOS"`. **Sugestão de UI:** um seletor
de modo (SEM/COM/AMBOS) na tela de nova sessão. Os indicadores que o snapshot
devolve pra esse strategy são `rsi`, `stoch_k`, `uo`, `sma60` (lembre: renderize as
chaves que vierem, não fixe nomes).

Response:
```json
{
  "session_id": "s1",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "total_bars": 5000,
  "warmup_bars": 150,
  "cursor": 150,
  "base_timeframe": "H1",
  "zone_timeframes": ["H1", "H4", "D1"],
  "history": [
    {"time": 1700000000, "open": 1.084, "high": 1.085, "low": 1.083, "close": 1.0845, "volume": 1200}
  ]
}
```
`history` traz os candles de 0..cursor pro gráfico desenhar o contexto inicial.

### `POST /interactive/step`
Avança N candles (default 1). Devolve o estado novo.

Request: `{ "n": 1 }`
Response (snapshot):
```json
{
  "cursor": 151,
  "total_bars": 5000,
  "done": false,
  "bars": [
    {"time": 1700003600, "open": 1.0845, "high": 1.086, "low": 1.0840, "close": 1.0852, "volume": 980}
  ],
  "indicators": {"rsi": 31.2, "stoch_k": 12.0, "uo": 28.5, "sma60": 1.0851},
  "tf_indicators": {
    "H1": {"rsi": 31.2, "stoch_k": 12.0, "uo": 28.5, "sma60": 1.0851},
    "H4": {"rsi": 41.0, "stoch_k": 35.0, "uo": 47.0, "sma60": 1.0860}
  },
  "equity": 1042.5,
  "balance": 1000.0,
  "open_trades": [
    {"id": 3, "direction": "long", "entry_time": 1700000000, "entry_price": 1.0840,
     "stop_price": 1.0820, "take_price": 1.0880, "size": 0.1, "unrealized_pnl": 12.5}
  ],
  "closed_now": [
    {"id": 2, "direction": "short", "entry_price": 1.090, "exit_price": 1.088,
     "exit_reason": "tp", "pnl": 20.0, "entry_time": 1699990000, "exit_time": 1700003600}
  ],
  "zones": [
    {"id": "z1", "price_low": 1.0840, "price_high": 1.0855, "side": "support",
     "created_at_bar": 150, "state": "active"}
  ]
}
```
`bars` = candle(s) novo(s) pra anexar. `closed_now` = trades fechados neste passo
(pra plotar marcador de saída). `done: true` quando chega no fim dos dados.

### `GET /interactive/state`
Mesmo formato do snapshot do `step`, sem avançar (útil pra ressincronizar a UI).

### `POST /interactive/seek`  — timeline arrastável (scrubber)
Pula o replay pra um candle absoluto. Pra frente só avança; pra trás reexecuta do
início de forma determinística (o log de zonas é causal). Devolve o snapshot no alvo.
Request: `{ "bar": 250 }`  → Response: snapshot (igual ao `step`).

### `POST /interactive/reset`
Rebobina pro início (warmup), preservando o log de zonas. Response: `session_info` com `"reset": true`.

### `POST /interactive/series`  — séries pros sub-painéis / troca de TF
Devolve OHLCV + indicadores **em arrays** até o cursor, na TF pedida. Use pra desenhar
os panes de osciladores e pra trocar os candles exibidos pra uma TF maior.
Request: `{ "tf": "H4" }` (omita pra TF base). Response:
```json
{
  "time": [1700000000, ...], "open": [...], "high": [...], "low": [...],
  "close": [...], "volume": [...],
  "rsi": [...], "stoch_k": [...], "uo": [...], "sma60": [...]
}
```
(Valores ainda em warmup vêm como `null`.) `session_info`/`snapshot` trazem
`indicators_meta`: `{ "overlays": ["sma60"], "panes": [{"key":"rsi","range":[0,100],"oversold":27,"overbought":72}, ...] }`.

### `POST /interactive/zone`
Cria uma zona. O servidor **carimba** `created_at_bar = cursor atual`.

Request:
```json
{ "price_low": 1.0840, "price_high": 1.0855, "side": "support", "timeframe": "H4" }
```
`timeframe` (multi-timeframe): em que TF a zona vive (`"H1"` ou `"H4"` — veja
`zone_timeframes` no `session/new`). Se omitido, usa a TF base da sessão. A
estratégia só dispara uma entrada nessa zona se a **exaustão acontecer na TF da
zona** (zona H4 → exaustão em H4; zona H1 → exaustão em H1). Response: o objeto-zona
criado, agora com o campo `"timeframe"`.

### `PUT /interactive/zone/{id}`
Edita preço/lado. A mudança vale só do cursor atual em diante (registrada com
carimbo de tempo no backend).
Request: `{ "price_low": 1.0838, "price_high": 1.0856, "side": "support" }`
Response: o objeto-zona atualizado.

### `DELETE /interactive/zone/{id}`
Remove a zona a partir do cursor atual. Response: `{ "id": "z1", "state": "deleted" }`.

### `GET /interactive/zones`
Lista as zonas **ativas no cursor atual** (já respeitando a causalidade).

### `POST /interactive/finish`
Fecha trades abertos no último candle processado, finaliza e **gera o relatório
completo** (o mesmo de sempre).
Response:
```json
{
  "report_dir": "reports/interactive_run_2026xxxx",
  "report_html": "/reports/interactive_run_2026xxxx/report.html",
  "metrics": { "net_profit": 412.0, "profit_factor": 1.7, "max_drawdown": -88.0, "trades": 37 }
}
```

### `POST /interactive/reset`  *(opcional, fase posterior)*
Rebobina o replay pro início, reaproveitando o log de mutações das zonas.

### Regra de causalidade (garantida pelo backend, o frontend só confia)
Toda zona carrega `created_at_bar`. O motor **nunca** deixa uma zona influenciar
candles anteriores ao seu carimbo. Edição/remoção também só valem dali pra frente.
Isso é o que torna o backtest honesto — é o coração da feature.

---

## Escopo do CLAUDE (pra Codex saber a fronteira e não invadir)

O Claude constrói o backend inteiro, sem tocar no frontend:

- **`interactive/zones.py`** — `ZoneStore`: zonas com carimbo de tempo + log de
  mutações; `active_zones(bar_index)` com causalidade.
- **`interactive/engine.py`** — `InteractiveBacktester(Backtester)`: reusa
  fill/SL/TP/trailing/slippage do engine atual por **herança**, e troca o loop
  por um **gerador `step()`** pausável.
- **`interactive/strategy_base.py`** — `InteractiveStrategyBase` com
  `on_bar(ctx) -> Intent | None` (event-driven), separada da `StrategyBase` batch.
  Mais um **stub** de estratégia só pra teste.
- **`interactive/session.py`** — estado da sessão (cursor, zonas, trades abertos).
- **`interactive/routes.py`** + ligação mínima em `ui/server.py` — os endpoints
  acima e a rota `GET /interactive` servindo o `index.html` do Codex.
- **Relatório**: no `finish`, reaproveita `generate_report_bundle` (igual hoje).
- **Testes** em `tests/interactive/`.

---

## Regras anti-conflito (resumo)

1. **Codex só mexe em `backtest_core/ui/static/interactive/`.** Nada de Python.
2. **Claude não mexe em frontend.** Só define e mantém o contrato REST.
3. O contrato REST acima é a única fronteira. Mudou o contrato → avisa antes
   (anote na seção de pedidos abaixo).
4. Trilho clássico (engine batch, UI clássica) **congelado** — ninguém encosta.
5. Sem build/npm no frontend: `lightweight-charts` standalone em `vendor/`.

## Critérios de aceite (Codex)

- Página `/interactive` abre separada da UI clássica, sem afetá-la.
- Gráfico desenha o histórico inicial e anexa candles a cada `step`.
- Dá pra desenhar, mover e apagar zonas, e cada ação chama o endpoint certo.
- Play/pause/step/velocidade funcionam dirigidos pelo frontend.
- "Finalizar" chama `/finish` e abre o relatório retornado.
- Tudo funciona contra o contrato (pode demonstrar com mock se o backend atrasar).
- Nenhum arquivo `.py` foi alterado pelo Codex.

## Ordem sugerida (Codex)

1. `index.html` + `chart.js` desenhando candles de um `session/new` mockado.
2. `replay.js`: step/play/pause/velocidade chamando `/step`.
3. `zones.js`: desenho/edição/remoção batendo nos endpoints de zona.
4. Painel de estado + marcadores de trade + botão Finalizar.
5. Trocar o mock pela API real quando o backend estiver de pé.

---

## Pedidos de interface (Codex → Claude)

Se faltar algum dado no contrato pra UI funcionar, anote aqui (não edite Python):

- (vazio por enquanto)

---

## ⚠️ Exceção pontual (2026-06-06): Claude mexeu no FRONTEND

O dono pediu **direto ao Claude** 4 correções de UX e o Claude editou arquivos
que normalmente são do Codex. Isto é uma exceção autorizada pelo dono, não uma
mudança da regra. **Arquivos do Codex alterados pelo Claude:**
`ui/static/interactive/chart.js`, `zones.js`, `replay.js`, `index.html`,
`styles.css`. **Arquivos do Claude (backend) também alterados:**
`interactive/session.py`, `interactive/routes.py` (contrato estendido — ver abaixo).

A partir daqui o **Codex volta a ser o dono do frontend**: revisa, testa e mantém.
Se discordar de alguma escolha visual/estrutural, pode refatorar à vontade dentro
de `ui/static/interactive/` — só **preserve o contrato REST** novo.

### Mudanças no contrato REST (Claude → backend)

1. `POST /interactive/session/new` agora aceita um campo opcional **`engine`**
   (objeto) com overrides do motor. Chaves suportadas:
   `initial_capital`, `leverage`, `risk_per_trade_pct`, `commission_per_lot`.
   Campo ausente/None/"" = mantém o default. Exemplo de corpo:
   ```json
   {"strategy":"sr_quant","mode":"SEM","symbol":"EURUSD","timeframe":"H1",
    "engine":{"initial_capital":25000,"leverage":50,"risk_per_trade_pct":1.5,"commission_per_lot":7.0}}
   ```
2. `POST /interactive/finish` agora devolve, além de `report_dir`/`report_html`/`metrics`:
   - **`metrics_full`**: dict completo de métricas (net_profit, net_return_pct,
     final_balance, win_rate, profit_factor, max_drawdown_pct, expectancy,
     payoff_ratio, sharpe_per_trade, total_trades, ...).
   - **`images`**: lista `[{name, title, url}]` dos PNGs do relatório, servidos em
     `/reports/...`. Vazia se não houver trades fechados.

---

## 🧪 Plano de ação — Codex testar as 4 modificações do Claude

> Objetivo: o Codex valida visualmente/funcionalmente as 4 correções abaixo no
> navegador (o Claude não consegue dirigir o browser). Sintaxe ESM dos 3 JS já
> passou; backend já testado (`tests/interactive/*` verdes); HTTP smoke OK.

### Passo 0 — Subir o ambiente
```bash
.venv/bin/python -m backtest_core.ui.server --config configs/mt5_eurusd_h1.json --port 8765
# abrir http://127.0.0.1:8765/interactive/
```
> O `build_session` no boot roda um backtest do dataset inteiro (~100k barras),
> então o servidor pode levar alguns segundos pra começar a responder. Espere o
> log `BacktestCore UI: http://...` antes de abrir a página.
> Para iterar só no frontend sem backend, abra com `?mock` (usa o `MockApi`):
> `http://127.0.0.1:8765/interactive/?mock` — mas o `engine` override, `metrics_full`
> e `images` reais só vêm do backend de verdade.

### Teste 1 — Buffer rolante de 10k candles (fluidez)
- **O que mudou:** `chart.js` mantém ≤10.000 candles (`maxBars`), descartando os
  mais antigos em lotes de 1.000 (`enforceWindow`). Indicadores guardados em
  `overlayData`/`indicatorData` cortam junto; `baseIndexOffset` remapeia índices
  absolutos de barra (ex.: `created_at_bar` da zona).
- **Como testar:**
  1. Inicie uma sessão, coloque a velocidade no **MAX** e deixe rodar bastante
     (passe de 10k candles — dá pra usar "Voltar no tempo"/seek pro fim também).
  2. Observe a fluidez: não deve travar/engasgar como antes ao acumular candles.
  3. **Teste-chave do `baseIndexOffset`:** desenhe uma zona BEM no início, deixe o
     replay avançar muito além de 10k candles, e confirme que a zona continua
     ancorada na posição/tempo certo (começando da borda esquerda quando o candle
     de criação já saiu da janela) — não deve "saltar" pro lugar errado.
- **Esperado:** sem degradação de performance; zonas antigas continuam coerentes.
- **Regressão a vigiar:** seek/"Voltar no tempo" após o descarte; troca de TF do
  gráfico (`chartTimeframeSelect`) com a janela já cortada.

### Teste 2 — Zonas: clamp na caixa + sem "pular" no zoom
- **O que mudou:** `zones.js` prende cada zona em `[0, altura]` e
  `.zone-overlay{overflow:hidden}`; um loop `requestAnimationFrame`
  (`startSyncLoop`/`viewportSignature`) re-renderiza quando o mapeamento
  preço↔pixel muda (o zoom vertical não dispara o evento nativo do LW-charts).
- **Como testar:**
  1. Desenhe 2–3 zonas (suporte e resistência).
  2. **Overflow:** force o preço a se afastar muito (avance o replay ou dê scroll/
     zoom vertical até a zona sair da área visível). A zona deve **sumir/cortar na
     borda da caixa do gráfico**, nunca pintar por cima do cabeçalho, da barra de
     replay ou do painel lateral direito.
  3. **Jumping:** gire o scroll do mouse (zoom in/out) sobre o gráfico, repetidas
     vezes e rápido. As zonas devem ficar **coladas** ao preço durante o zoom, sem
     piscar/saltar e re-encaixar.
  4. Confirme que ainda dá pra **mover** a zona (arrastar o corpo) e **redimensionar**
     pelas alças de cima/baixo — as alças agora ficam dentro da caixa (`top:0`/`bottom:0`).
- **Esperado:** zonas sempre dentro da moldura; zero "pulo" no zoom; drag/resize OK.
- **Regressão a vigiar:** criar zona nova durante zoom (o loop pula render enquanto
  `this.drag` está ativo — preview não deve sumir); seleção/label/badge visíveis.

### Teste 3 — Relatório inline abaixo do gráfico + Exportar PDF
- **O que mudou:** `finish()` devolve `metrics_full` + `images`; `replay.js`
  monta `#reportDashboard` (grid de métricas + PNGs empilhados) abaixo do gráfico;
  `body.report-open` faz `.chart-column` rolar. "Exportar PDF" abre o `report_html`
  em nova aba e chama `window.print()`.
- **Como testar (precisa de TRADES, então com backend real):**
  1. Como a `sr_quant` só entra **dentro de zona**, desenhe uma ou mais zonas perto
     do preço e deixe rodar (ou use a estratégia **`stub`**, que entra ao tocar a
     zona — caminho mais rápido pra gerar trades).
  2. Clique **Finalizar**. Deve surgir a seção **abaixo do gráfico de candles** com:
     cabeçalho (símbolo/TF/estratégia), **grid de métricas** e os **gráficos PNG**
     empilhados (Equity, Drawdown, Z-Sharp, Monte Carlo, etc.).
  3. A página deve **rolar pra baixo** suavemente até o relatório (a coluna do
     gráfico vira rolável; o gráfico em si mantém ~55vh de altura).
  4. Clique **Exportar PDF** → abre o relatório HTML completo em nova aba e dispara
     o diálogo de impressão (Salvar como PDF).
  5. Clique **Fechar** → some o relatório e o layout volta ao normal.
  6. Inicie **Nova sessão** → o relatório anterior deve fechar sozinho.
- **Esperado:** relatório inline igual ao espírito do dashboard clássico; export OK.
- **Sem trades / mock:** o painel mostra aviso ("sem trades fechados" ou "só com
  backend real") e o botão Exportar fica desabilitado — comportamento correto.

### Teste 4 — Janela de setup antes de iniciar
- **O que mudou:** `#setupModal` abre **no load** (não auto-inicia mais) e pelo
  botão "Nova sessão". Campos: Estratégia, Modo, Ativo(CSV), Timeframe + Capital,
  Alavancagem, Risco %, Comissão. Os params de motor vão no `request.engine`.
- **Como testar:**
  1. Recarregue a página → o **modal de setup aparece** e **não há sessão rodando
     atrás** (o "Cancelar" fica escondido na 1ª vez, pois não há pra onde voltar).
  2. Troque o **Ativo** → o select de **Timeframe** deve repopular conforme o CSV.
  3. Selecione **`stub`** → o campo **Modo** desabilita (modo só vale pra `sr_quant`).
  4. Ajuste **Capital=25000** e **Alavancagem=50**, clique **Iniciar Backtest**.
  5. Confirme no painel lateral que o **Balance inicia em $25.000** (override aplicado).
  6. Com uma sessão ativa, clique **Nova sessão** → o modal reabre, agora **com
     "Cancelar" visível** e pré-preenchido com a config atual; Cancelar fecha sem
     recriar a sessão.
- **Esperado:** nada roda antes do "Iniciar"; params do motor refletem na sessão.
- **Validação rápida via curl (sem browser):**
  ```bash
  curl -s -X POST localhost:8765/interactive/session/new -H 'Content-Type: application/json' \
    -d '{"strategy":"stub","symbol":"EURUSD","timeframe":"H1","engine":{"initial_capital":25000,"leverage":50}}' \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('balance',d['balance'])"
  # esperado: balance 25000.0
  ```

### Checklist de aceite (Codex)
- [ ] Roda além de 10k candles sem perder fluidez; zona antiga segue ancorada.
- [ ] Zona nunca vaza da caixa do gráfico; sem "pulo" no zoom; drag/resize OK.
- [ ] Finalizar mostra métricas + gráficos inline abaixo do candle; Exportar abre PDF.
- [ ] Setup abre antes de tudo; Ativo→TF repopula; Modo desabilita p/ `stub`;
      Capital/Alavancagem do setup chegam na sessão.
- [ ] `tests/interactive/test_interactive.py` e `test_sr_quant.py` continuam verdes.
- [ ] Nada do trilho clássico foi tocado.

### Pendência aberta pro dono (decisão de UX)
Os seletores antigos (Ativo/TF/Estratégia/Modo) continuam na **barra superior**
*além* do modal de setup. O dono ainda vai decidir se remove eles da barra (agora
que o setup é a porta de entrada) ou mantém pra troca rápida. Não mexer até ele
definir.

---

# 🐲 MISSÃO MONSTRO (2026-06-07) — Análise de dados no ápice

> O dono pediu: tornar o modo interativo a coisa **mais robusta e profunda em
> análise de dados** que ele já viu na vida. Três pilares. **Claude faz os Pilares
> 1 e 2 (backend/analytics + contrato). Codex faz o Pilar 3 (frontend): renderizar
> tudo isso em nível TradingView + dashboard institucional.** A fronteira continua
> sendo o contrato REST — agora estendido abaixo (versão 2 do `finish` + HUD ao vivo).

## O diferencial que só ESTE produto tem

As zonas são desenhadas **ao vivo e causais** (sem lookahead). Isso permite a
pergunta que nenhum backtester comum responde: **"minhas zonas têm edge? quais?"**
O backend vai medir edge **por zona, por TF, por lado (suporte/resistência), por
modo**, e a **taxa de respeito** de cada zona (toques que respeitaram × que
romperam). O Codex precisa dar a essa análise o palco principal.

## Divisão desta missão

| Pilar | Dono | Entrega |
| --- | --- | --- |
| 1. Suíte de métricas institucional | **Claude** | `analytics/advanced.py`; `metrics_full` seccionado; `benchmark`, `monte_carlo`, `robustness` no `finish()` |
| 2. Edge por zona / estratégia | **Claude** | linkagem trade↔zona; `analytics/zone_edge.py`; `zone_analytics` no `finish()`; novos gráficos |
| 3. UX TradingView + dashboard | **Codex** | renderizar 1+2; paridade TV; HUD ao vivo; dashboard seccionado |

---

## Contrato REST v2 (Claude → backend; Codex constrói contra isto)

> Compatível pra trás: tudo que já existia continua. As novidades são **campos
> novos**. Onde um número não dá pra calcular (poucos trades, sem dados), vem
> `null` — **renderize defensivamente** (mostre "—").

### `POST /interactive/finish` — resposta estendida

Mantém `report_dir`, `report_html`, `metrics` (slim, igual). **Muda/ganha:**

```jsonc
{
  "metrics_full": {                       // AGORA SECCIONADO (era dict plano)
    "summary":   { "net_profit", "net_return_pct", "final_balance", "initial_capital",
                   "total_trades", "cagr_pct", "best_trade", "worst_trade" },
    "returns":   { "expectancy", "expectancy_r", "avg_win", "avg_loss", "payoff_ratio",
                   "avg_trade_duration_h", "exposure_pct" },
    "ratios":    { "profit_factor", "sharpe_per_trade", "sharpe_annual", "sortino",
                   "calmar", "mar", "omega", "k_ratio", "sqn", "recovery_factor",
                   "gain_to_pain", "tail_ratio", "kelly_pct" },
    "risk":      { "max_drawdown_pct", "max_drawdown_abs", "ulcer_index", "var_95",
                   "cvar_95", "tuw_max", "tuw_mean", "tuw_median", "n_drawdowns" },
    "streaks":   { "win_rate", "wins", "losses", "breakeven",
                   "max_consec_wins", "max_consec_losses", "largest_win", "largest_loss" },
    "robustness":{ "psr", "risk_of_ruin_pct", "prob_profit_pct",
                   "mc_final_p05", "mc_final_p50", "mc_final_p95", "mc_maxdd_p95" },
    "costs":     { "total_commissions", "total_swap", "gross_profit", "gross_loss" }
  },

  "zone_analytics": {                      // ⭐ o diferencial
    "totals":  { "zones_drawn", "zones_with_trades", "unused_zones" },
    "by_zone": [ { "zone_id":"z3", "side":"support", "timeframe":"H4",
                   "price_low", "price_high", "created_at_bar",
                   "trades", "wins", "win_rate", "net_pnl", "avg_r", "profit_factor",
                   "touches", "bounces", "breaks", "respect_rate" } ],
    "by_tf":   [ { "timeframe":"H4", "trades", "win_rate", "net_pnl", "avg_r", "profit_factor" } ],
    "by_side": [ { "side":"support", "trades", "win_rate", "net_pnl", "avg_r", "profit_factor" } ],
    "by_mode": [ { "mode":"SEM", "trades", "win_rate", "net_pnl", "avg_r" } ]
  },

  "benchmark": {                           // estratégia × comprar-e-segurar
    "buy_hold": { "net_return_pct", "max_drawdown_pct", "final_balance" },
    "vs":       { "alpha", "beta", "correlation", "information_ratio", "excess_return_pct" }
  },

  "monte_carlo": {                         // 4 modos, números (não só PNG)
    "shuffle":          { "final_balance_p05","final_balance_p50","final_balance_p95",
                          "max_drawdown_p05","max_drawdown_p95" },
    "bootstrap":        { ... },
    "block_bootstrap":  { ... },
    "execution_stress": { ... }
  },

  "images": [ { "name", "title", "url", "group" } ]  // group = seção do dashboard
}
```

`images[].group` ∈ `"equity" | "risk" | "distribution" | "calendar" | "montecarlo" | "zones" | "market"`.
Use pra agrupar os PNGs em abas/seções no dashboard, em vez de uma pilha única.

### Snapshot ao vivo (`step` / `state`) — campos novos pro HUD

```jsonc
{
  // ...tudo que já vinha (cursor, bars, indicators, equity, balance, zones, etc.)...
  "equity_point": { "bar": 1234, "time": 1700000000, "equity": 10420.5, "balance": 10000.0 },
  "hud": {
    "peak_equity", "drawdown_pct", "open_risk", "open_risk_pct",
    "realized_pnl", "trades_closed", "win_rate_so_far", "current_streak"
  }
}
```
`equity_point` é **um ponto por step** — acumule no cliente pra desenhar uma
**sparkline de equity ao vivo** (mini-curva que cresce durante o replay). `hud` é
o estado instantâneo de risco/desempenho até o cursor.

---

## Pilar 3 — Tarefas do Codex (frontend, só em `ui/static/interactive/`)

### A. Paridade TradingView (o que ainda falta do checklist antigo)
- [ ] **Sub-painéis de osciladores** (panes nativos LW v5): RSI, Stoch %K, Ultimate
      Oscillator em panes 0–100 com linhas de OB/OS (`indicators_meta.panes` +
      `POST /interactive/series` pra série inteira; a cada `step`, anexe o ponto).
- [ ] **SMA60 overlay** na faixa de preço (`indicators_meta.overlays`).
- [ ] **Barra de drawing tools** (lateral, estilo TV): trend line, horizontal/ray,
      vertical, fib, texto, brush, régua. Adapte o `plugin-examples` (vanilla, sem npm).
      Persistência visual em `localStorage`.
- [ ] **Scrubber arrastável** na timeline (`POST /interactive/seek {bar}`), linhas de
      SL/TP da posição aberta, marcadores de entrada/saída.
- [ ] Tipos de gráfico (candle/barra/linha/área), escala log/linear, tema escuro,
      atalhos (espaço=play, ←/→=step), menu de contexto.

### B. HUD analítico AO VIVO (durante o replay) — novo
- [ ] **Sparkline de equity** crescendo a cada step (acumule `equity_point`).
- [ ] **Medidor de drawdown** (`hud.drawdown_pct`) e **gauge de risco aberto**
      (`hud.open_risk_pct`).
- [ ] Tira de stats correntes: PnL realizado, win-rate até agora, streak atual,
      nº de trades fechados (`hud.*`).
- [ ] Tudo discreto, num canto — não pode atrapalhar o desenho de zonas.

### C. Dashboard de relatório SECCIONADO (no Finalizar) — o monstro
- [ ] Trocar a pilha única atual por **seções/abas**: Resumo · Retornos · Risco ·
      Robustez · **Zonas** · Calendário · Monte Carlo · Mercado.
- [ ] Cada seção: **grid de métricas** (de `metrics_full[secao]`) + os PNGs do
      `images` cujo `group` casa com a seção.
- [ ] **Seção Zonas (destaque):** tabela `by_zone` ordenável (edge por zona) com
      win-rate, avg R, profit factor, **respect rate** (barra/heat); resumos
      `by_tf` / `by_side` / `by_mode`; e o card `totals` (quantas zonas desenhadas,
      quantas geraram trade, quantas ficaram ociosas).
- [ ] **Robustez:** PSR, risk-of-ruin, prob. de lucro, banda P05/P50/P95 do Monte
      Carlo (use o fan chart `montecarlo` + os números de `monte_carlo`).
- [ ] **Benchmark:** card estratégia × buy&hold (alpha/beta/IR + retorno excedente).
- [ ] Manter "Exportar PDF" funcionando.

> Sugestão de ordem: (1) panes de osciladores + SMA overlay; (2) HUD ao vivo
> (rápido, só consome `hud`/`equity_point`); (3) dashboard seccionado renderizando
> `metrics_full`/`zone_analytics`/`benchmark`/`monte_carlo`; (4) drawing tools; (5)
> polimento (temas, atalhos, menus).

## Critérios de aceite (Codex, Pilar 3)
- [ ] Osciladores em panes próprios + SMA overlay, causais (acompanham o cursor).
- [ ] HUD ao vivo: sparkline de equity + DD/risco + stats, sem atrapalhar zonas.
- [ ] Dashboard seccionado mostra TODAS as seções de `metrics_full` + PNGs por `group`.
- [ ] Seção Zonas com tabela por zona (edge + respect rate) e resumos por TF/lado/modo.
- [ ] Robustez e Benchmark renderizados; Exportar PDF segue OK.
- [ ] Defensivo a `null`; nada do trilho clássico tocado; nenhum `.py` editado pelo Codex.

## Status do backend (Claude) — o que já está pronto pra Codex consumir
> ✅ **Backend dos Pilares 1 e 2 ENTREGUE e testado (2026-06-07).** Tudo abaixo já
> sai do `finish()` / snapshot reais. Suítes verdes: `tests/interactive/*` +
> `tests/interactive/test_analytics_monster.py`; baseline clássico (`run_demo.py`) OK.
- [x] `metrics_full` **seccionado** (summary/returns/ratios/risk/streaks/robustness/costs)
      + `benchmark` + `monte_carlo` (4 modos) + `robustness` (PSR, risk-of-ruin,
      prob-profit, MC P05/P50/P95) no `finish`.
- [x] `zone_analytics` no `finish` — `by_zone` (com **respect_rate** = bounces/breaks),
      `by_tf`, `by_side`, `by_mode`, `totals`. Trade↔zona linkado via `zone_id`/`zone_tf`/
      `zone_side` (carimbado pela `sr_quant`, carregado pelo engine no trade).
- [x] `hud` + `equity_point` em **todo** snapshot (`step`/`state`): peak_equity,
      drawdown_pct, open_risk(_pct), realized_pnl, trades_closed, win_rate_so_far,
      current_streak (sinalizado).
- [x] Novos PNGs com `group` no `images`: underwater, rolling_sharpe,
      strategy_vs_buyhold, returns_qq, monthly_returns_table, monte_carlo_fan,
      **zone_edge**, **zone_respect** (grupos: equity/risk/distribution/calendar/
      montecarlo/zones/market).

> Implementação (arquivos do Claude, caso o Codex queira espiar os campos exatos):
> `analytics/advanced.py` (métricas institucionais), `analytics/zone_edge.py`
> (edge por zona), `report/exporters.py` (8 gráficos novos), `interactive/engine.py`
> (HUD + linkagem), `interactive/session.py` (montagem do payload).

---

# 🧪 MISSÃO CODEX (2026-06-08): teste visual do painel "Robustez" (dashboard clássico)

O Claude adicionou ao **dashboard clássico** (`ui/static/index.html` + `app.js` + `styles.css`)
uma seção nova **"Robustez"** que roda uma bateria de testes anti-overfit e renderiza o
resultado. O backend está pronto e testado por HTTP (endpoint `/api/robustness`, ~34s,
veredito "Robusta", 6 imagens). **Falta validar o VISUAL no navegador — é o que o Claude
não consegue fazer.**

## Como subir e abrir
```bash
.venv/bin/python -m backtest_core.ui.server --config configs/fvg_eurusd_h1_real.json --port 8765
# abrir http://127.0.0.1:8765/  (dashboard clássico)
```

## Passos do teste
1. Espere a sessão carregar (FVG EURUSD H1, custos reais FTMO). **Role até o fim da página** —
   depois de "Gráficos interativos" tem a seção **"Robustez"** com o botão **"Rodar robustez"**.
2. Clique em **"Rodar robustez"**. O botão deve mudar para "Rodando… (~30-60s)" e desabilitar;
   o corpo mostra uma mensagem de loading. (A bateria roda dezenas de backtests — ~30-60s.)
3. Quando terminar, confira:
   - **Badge de veredito** ao lado do título "Robustez" (Robusta/Aceitável/Frágil), com cor.
   - **4 flags** coloridas (Out-of-Sample, Overfit (PBO), Walk-Forward, Stress de Custo) — verde/âmbar/vermelho.
   - **6 cards de métricas** (IS PF, PF Retention, PBO, Deflated Sharpe, degradação WFO, custo breakeven) + linha de meta (barras usadas, período, multi-mercado).
   - **6 gráficos** (PNG): IS×OOS, Walk-Forward, Sensibilidade, Heatmap, Stress de custo, Multi-mercado.

## O que reportar de volta pro Claude
- **Print(s)** do painel renderizado (com os gráficos).
- Erros no **console do navegador** (DevTools) — se houver.
- Problemas de **layout/responsividade**: cards quebrando, imagens estourando, cores ilegíveis,
  flags/badge desalinhados, scroll travado, etc.
- Se o botão **trava/duplica** ao clicar várias vezes, ou se o loading não some.
- Sugestões visuais (espaçamento, hierarquia, ordem dos gráficos).

## Arquivos do Claude nesta feature (pra Codex saber onde mexer, se for ajustar visual)
- Frontend: `ui/static/index.html` (seção `#robustnessPane`), `ui/static/app.js`
  (`runRobustness`/`renderRobustness`/`robustSummaryHtml`), `ui/static/styles.css` (`.robust-*`).
- Backend (NÃO mexer): `analytics/robustness.py`, `report/robustness_charts.py`,
  endpoint `GET /api/robustness` em `ui/server.py` (`run_robustness_for_session`).
  O endpoint roda nas **últimas 40k barras** (`ROBUSTNESS_BARS_CAP`) pra velocidade.

> Regra: ajuste só o VISUAL (`ui/static/*`). O contrato do endpoint (`/api/robustness` →
> `{ok, scorecard, images}`) é estável; não mude o backend.
