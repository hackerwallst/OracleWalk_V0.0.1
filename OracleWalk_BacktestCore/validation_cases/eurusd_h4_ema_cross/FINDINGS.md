# Resultado — EURUSD H4 EMA Cross (MT5 vs BacktestCore)

Run: EURUSD H4, 2023-03-16 → 2026-06-03, Lots 0.10, Stop/Take 1.5/3.0 ATR,
commission 0, MT5 em "Every tick based on real ticks".

## Números

| Métrica | Valor |
| --- | --- |
| Trades MT5 | 127 |
| Trades BacktestCore | 150 |
| Pareados (após alinhar +1 barra) | 125 |
| Dif. média de entrada | ~1,2 ponto (máx 9) |
| Dif. média de saída | ~1,5 ponto (1 outlier ~100 pts) |
| Exit reason divergente | 2 de 125 |
| PnL total MT5 | −115,10 |
| PnL total BacktestCore | +37,87 |

## As 3 divergências (todas explicadas)

1. **Timing de fill — offset constante de +4h (1 barra H4).**
   BacktestCore preenche no *fechamento* da barra do sinal; o EA preenche no
   *open da barra seguinte*. Por isso o pareamento só funciona deslocando 1
   barra. Uma vez alinhado, entradas batem dentro de ~1 ponto. Estrutural, por
   design.

2. **Warm-up — 2 trades só no MT5.**
   O MT5 tinha histórico antes de 2023-03-16, então sinaliza já no início do
   range. O BacktestCore parte do primeiro candle do pacote, então as ~36
   barras iniciais são aquecimento e ele perde esses 2 primeiros trades.

3. **Cascata de caminho — 25 trades extras no BacktestCore (+326,82).**
   O deslocamento de 1 barra + a regra intrabar "SL antes de TP" fazem o
   BacktestCore sair/reverter em barras ligeiramente diferentes, gerando 25
   sinais a mais. **Este é o real motor do gap de PnL**, não erro de execução.

## Decomposição do gap total (BT − MT5 = +152,97)

- Trades pareados: MT5 +128,45 (BT um pouco pior na sobreposição, ~$1/trade)
- 25 trades extras do BT: +326,82
- 2 trades extras do MT5: +45,40

→ −128,45 + 326,82 − 45,40 = **+152,97** ✔

## Leitura

No conjunto que os dois motores negociam (125 trades), eles concordam
trade-a-trade: mesmos lados, entradas/saídas dentro de ~1 ponto, só 2/125 com
exit reason diferente. A inversão de sinal do PnL total vem dos **25 trades
extras** do BacktestCore (efeito cascata do timing + SL-first intrabar), não de
erro de preço/contabilidade. Conclusão: o núcleo do engine é fiel ao MT5; as
diferenças se concentram em timing de fill e resolução intrabar — exatamente o
que o modo tick real existe para testar.

## Próximo passo recomendado

Rodar a variante **sem SL/TP** (`StopAtr=0, TakeAtr=0`) para remover a cascata
intrabar e isolar só o timing de fill. Aí os trade counts devem convergir.

---

# Caso 2 — sem SL/TP (StopAtr=0, TakeAtr=0)

Objetivo: remover a cascata intrabar e isolar o timing. Revelou uma divergência
mais profunda — de **dados**, não de lógica.

## Números

| Métrica | Valor |
| --- | --- |
| Trades MT5 | 109 |
| Trades BacktestCore | 150 |
| Pareados (BT+4h) | 107 |
| Entradas casadas EXATO com BT+4h | 107 de 109 |
| Dif. média de entrada | ~1,2 ponto |
| PnL total MT5 | +481,30 |
| PnL total BacktestCore | −768,32 |

## Diagnóstico (cadeia de evidências)

1. Há **150 cruzamentos de EMA** no `candles.csv`, e eles **alternam**. O BT abre
   1 trade por cruzamento = 150.
2. **107 das 109 entradas do MT5 batem na vírgula** com BT+4h. A lógica de
   entrada do engine está validada.
3. Os **43 cruzamentos que o MT5 não pegou NÃO são marginais** (separação mediana
   43 pts, igual aos pegos). Não é ruído de EMA encostando.
4. Ambos os lados **alternam direção** (0 entradas consecutivas mesmo lado), e o
   MT5 segura posição mais tempo (42 vs 33,5 barras). Ou seja, o MT5 enxerga
   **menos cruzamentos** — pula ~21 pares de reversões curtas.
5. Como a EMA é numericamente idêntica nos candles do pacote, a conclusão é:
   **as barras que o MT5 reconstrói por tick real no Strategy Tester não são
   bit-idênticas ao `candles.csv` exportado.** Pequenas diferenças de OHLC
   suprimem/criam cruzamentos inteiros, que cascateiam no PnL.

## Por que o caso COM SL/TP pareou melhor (125/127)

Com SL/TP, os trades são mais curtos e saem por nível de preço, não por um
cruzamento distante. Isso os torna menos sensíveis a se um cruzamento lá na
frente existe ou não — por isso o pareamento foi muito melhor.

## Próximo passo (clincher)

Remover a variável "dados": rodar o BacktestCore sobre **as mesmas barras** que
o MT5 usou. Duas opções:
- modo tick (trilha do Codex) consumindo `ticks.csv` do pacote, ou
- reexportar `candles.csv` exatamente do mesmo período/broker do teste e
  reconferir.

Com inputs idênticos, a contagem de trades deve convergir e sobra só o timing
de fill (+1 barra) como diferença real.

---

# CONCLUSÃO DEFINITIVA (log de sinais instrumentado)

O EA passou a logar todo cruzamento detectado + retcode da ordem
(`mt5_signals_nosl.csv`). Resultado do caso sem SL/TP:

- **150 cruzamentos detectados no MT5** — exatamente os mesmos 150 do BacktestCore.
- Execução: **109 OK (10009)** + **20 sem ação** (mesma direção, correto) +
  **21 rejeitadas com retcode 10018 = "Mercado Fechado"**.
- As 21 rejeições são **todas no bar das 00:00** (rollover diário do broker),
  espalhadas por vários dias úteis — não fim de semana.

## Cadeia de prova completa

1. Barras reconstruídas dos ticks reais == `candles.csv` (0 pts). → dados fiéis.
2. EMA/ATR do EA == pandas (0 diferença). → indicadores fiéis.
3. Lógica do EA emulada em Python == 151 ≈ 150 do BT. → lógica fiel.
4. MT5 detectou os 150 cruzamentos. → não é dado nem detecção.
5. 21 ordens caíram no rollover 00:00 e foram recusadas pelo broker. → execução.

## Veredito

**O BacktestCore é fiel à estratégia e ao MT5.** A única divergência é que o
engine **não modela horário de pregão / rollover** e, por isso, executa 21 de
150 reversões que um broker real recusa no instante da virada do dia (00:00).
É o engine ser otimista nesses pontos — não um erro de lógica, dados ou
contabilidade.

## Opções de correção

- **EA (recomendado p/ validação):** ao receber 10018, repetir a ordem no
  próximo tick (o mercado reabre segundos depois do rollover). Faz os dois
  lados convergirem para ~150 e prova a fidelidade ponta a ponta.
- **Engine (fidelidade real):** opção de pular/!abrir trades em janelas de
  mercado fechado (modelo de sessão). Mais pesado; fora do escopo atual.
