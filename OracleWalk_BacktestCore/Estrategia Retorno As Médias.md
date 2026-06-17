# M1 Countertrend Scalping Strategy

> Estratégia completa documentada a partir do thread original do Forex Factory (#1190104), criado por **Abade** em novembro de 2022, com contribuições extensas de **cpfleger**, **niks**, **KoF (King of Forex)** e centenas de traders ao longo de mais de 900 páginas.

---

## Sumário

- [Visão Geral](#visão-geral)
- [Filosofia Central](#filosofia-central)
- [Indicadores e Setup do Gráfico](#indicadores-e-setup-do-gráfico)
- [Regras de Entrada (Buy)](#regras-de-entrada-buy)
- [Regras de Entrada (Sell)](#regras-de-entrada-sell)
- [Regras de Saída (Take Profit)](#regras-de-saída-take-profit)
- [Cost Averaging (Média de Custo)](#cost-averaging-média-de-custo)
- [Gestão de Risco](#gestão-de-risco)
- [Lot Size e Dimensionamento](#lot-size-e-dimensionamento)
- [Pares e Instrumentos Recomendados](#pares-e-instrumentos-recomendados)
- [Horários de Negociação](#horários-de-negociação)
- [Volume — Como Interpretar](#volume--como-interpretar)
- [Lidando com Tendências Fortes (Breakouts)](#lidando-com-tendências-fortes-breakouts)
- [Variações e Evoluções do Sistema](#variações-e-evoluções-do-sistema)
- [Psicologia do Trader](#psicologia-do-trader)
- [Plataformas e Brokers](#plataformas-e-brokers)
- [Resumo das Regras Rápidas](#resumo-das-regras-rápidas)
- [Fontes e Referências](#fontes-e-referências)
- [Aviso Legal (Disclaimer)](#aviso-legal-disclaimer)

---

## Visão Geral

A **M1 Countertrend Scalping Strategy** é uma estratégia de scalping no gráfico de 1 minuto (M1) baseada na premissa de que o preço tende a **retornar à média** (representada pelas EMAs) após se afastar significativamente delas. A estratégia opera **contra a tendência de curto prazo**, capturando os pequenos e numerosos pontos de virada que ocorrem antes de o preço voltar a tocar as médias móveis.

A estratégia foi inspirada pelo estilo de trading do **King of Forex (KoF)**, um trader conhecido por seus vídeos ao vivo no YouTube demonstrando scalping com médias móveis e cost averaging (média de custo). O thread foi criado por **Abade** com o objetivo de reunir traders que utilizam essa abordagem e aprimorá-la coletivamente.

**Contribuidor-chave: cpfleger** — trader aposentado que adaptou a estratégia do KoF adicionando indicadores auxiliares (SupDem, RSI, Heiken Ashi) e criou múltiplas versões do sistema (V1 a V5), compartilhando templates prontos para MT4/MT5.

---

## Filosofia Central

A lógica central da estratégia pode ser resumida em alguns princípios:

1. **Reversão à Média** — Quanto mais tempo o preço permanece distante das EMAs (em um "breakout" ou extensão), maiores são as chances de ele retornar à "média", representada pelas médias móveis. É como um elástico: quanto mais esticado, maior a força de retorno.

2. **Countertrend, não Trend-Following** — A estratégia é explicitamente contrária à tendência. Em vez de comprar com a tendência de alta, ela vende. Em vez de vender com a tendência de baixa, ela compra. O trader está essencialmente **"fading" (desafiando) os breakout traders** e tentando capturar as correções de volta às EMAs.

3. **EMAs como Alvos, não como Entradas** — As médias móveis exponenciais (9, 20, 50 e 200) são usadas como **alvos de saída (take profit)**, não como gatilhos de entrada. A entrada é baseada em price action, zonas de suporte/resistência, e indicadores auxiliares.

4. **Cost Averaging como Defesa** — Quando o preço se move contra a posição, novas ordens são abertas no mesmo sentido (cost averaging), diluindo o preço médio de entrada. Isso permite que o trader saia com lucro quando ocorre um pullback menor do que seria necessário se tivesse apenas uma posição.

5. **Mercados em Range são o Habitat Natural** — Estratégias contratendência funcionam melhor em mercados lateralizados (ranging). A maioria do tempo, o preço oscila entre as EMAs, gerando lucros consistentes a cada swing. O desafio surge quando um breakout forte ocorre.

---

## Indicadores e Setup do Gráfico

### Indicadores Obrigatórios (Core)

| Indicador | Função |
|---|---|
| **EMA 9** (Exponential Moving Average) | Alvo rápido de saída; primeiro sinal de fraqueza do breakout |
| **EMA 20** | Alvo principal em mercados ranging |
| **EMA 50** | Alvo em breakouts moderados |
| **EMA 200** | Guia direcional e alvo em breakouts fortes; bias de longo prazo |

### Indicadores Auxiliares (Sistema cpfleger)

| Indicador | Função |
|---|---|
| **SupDem (Supply & Demand)** | Identifica zonas de oferta e demanda onde o preço tem maior probabilidade de reverter |
| **RSI (Relative Strength Index)** | Confirma condição de sobrecompra/sobrevenda; cruzamento com a própria MA do RSI como gatilho |
| **Volume** | Volume padrão com uma EMA de 20 períodos sobreposta para filtrar combustível do movimento |
| **Heiken Ashi Candles** (opcional) | Suaviza o ruído do price action e ajuda a visualizar a direção do momentum |
| **APB Candles** (Average Price Bars) | Alternativa ao Heiken Ashi, usada na versão MT5 |

### Template cpfleger para MT4

O setup completo pode ser instalado no MetaTrader 4 seguindo estes passos:

1. Colocar os arquivos `.ex4` na pasta `indicators` do MT4.
2. Colocar o arquivo `Original KoF Template M1.tpl` na pasta `templates`.
3. Clicar em "Refresh" ou reiniciar o MT4 para carregar os arquivos.
4. Aplicar o template em um gráfico M1.

---

## Regras de Entrada (Buy)

As regras de compra (buy) segundo o sistema cpfleger/Abade:

1. **Não há notícias de impacto** agendadas para os próximos minutos.
2. **O preço está abaixo** das EMAs 20 e 50 (distância significativa = "overextension").
3. O preço foi **rejeitado em uma zona de suporte** próxima (usar o indicador SupDem).
4. O candle **Heiken Ashi está mudando para verde** (sinal de reversão de momentum).
5. O candle HA está **cruzando a EMA 9 para cima**.
6. O **RSI está tocando sua própria MA** e mudou para verde (virada para alta).
7. O **volume aumentou recentemente** acima de sua EMA de 20 períodos (combustível para a reversão).

**Nota importante**: Não use entradas aleatórias. A vantagem da estratégia não vem do cost averaging sozinho — ela vem da **lógica de entrada** combinada com a tendência natural do preço de reverter à média.

---

## Regras de Entrada (Sell)

Espelho invertido das regras de Buy:

1. **Não há notícias de impacto** agendadas.
2. **O preço está acima** das EMAs 20 e 50 (distância significativa).
3. O preço foi **rejeitado em uma zona de resistência** (SupDem).
4. O candle **Heiken Ashi está mudando para vermelho**.
5. O candle HA está **cruzando a EMA 9 para baixo**.
6. O **RSI está tocando sua MA** e mudou para vermelho.
7. O **volume** confirma a fraqueza do movimento de alta.

---

## Regras de Saída (Take Profit)

As saídas são baseadas no toque do preço nas EMAs. A escolha da EMA depende do contexto:

| Situação | EMA Alvo |
|---|---|
| **Mercado ranging / lento** | EMA 20 (excelente opção padrão) |
| **Capturou boa parte do topo/fundo** | EMA 9 (saída rápida) |
| **Breakout moderado, várias posições perdedoras** | EMA 50 |
| **Breakout forte, posições profundamente negativas** | EMA 200 |

### Regras adicionais de saída

- **Nunca deixe trades abertos** enquanto estiver distraído.
- **Nunca deixe trades abertos overnight** (durante a noite).
- A maioria das saídas é **manual** — o trader deve monitorar ativamente.
- **Zoom in**: Ao estar em uma posição, faça zoom no gráfico e observe o tamanho dos candles e dos pavios (wicks). Quando o corpo do candle diminuir e o momentum desacelerar, considere sair.
- A **regra dos 3 candles** (cpfleger): procure por 3 candles de um único pavio (sem pavio na direção contrária), que são candles de momentum. Quando o padrão se desfaz, é hora de sair.

---

## Cost Averaging (Média de Custo)

O cost averaging é o mecanismo de defesa e recuperação da estratégia. Em vez de usar stop loss fixo, quando o preço se move contra sua posição, você abre novas posições no mesmo sentido.

### Como funciona

1. Abra **1 a 3 posições iniciais** com o mesmo lot size.
2. Se o preço se move contra você, **espere** a EMA 9 furar seus níveis de entrada.
3. Quando a EMA 9 tocar/cruzar seu nível de entrada, **adicione UMA nova posição** com o mesmo lot size.
4. Quando o preço voltar a tocar a EMA 9 (sinal de fraqueza do breakout), considere adicionar mais posições visando a saída na EMA 20, 50, ou 200.
5. O efeito da média de custo faz com que um pullback menor seja suficiente para fechar todas as posições em lucro.

### O que NÃO fazer

- **Não sobrecarregue rapidamente** — adicionar muitas posições de uma vez é a receita para explodir a conta.
- **Não use grids fixos** — o mercado não é fixo, e a estratégia é sobre timing, não sobre níveis pré-determinados.
- **Não confunda** com um sistema mecânico de grid. A diferença fundamental é que as EMAs representam níveis dinâmicos de significância do mercado, não níveis arbitrários baseados no equity da conta.
- **Limite o número de posições** — geralmente não mais que 10 posições simultâneas. O limite real depende do lot size, margem disponível, e alavancagem.

---

## Gestão de Risco

| Parâmetro | Recomendação |
|---|---|
| **Drawdown máximo catastrófico** | 20-30% do equity — fechar TUDO se atingido |
| **Drawdown típico aceitável** | 1-5% por operação |
| **Meta de consistência** | 85-90%+ de taxa de acerto antes de pensar em lucro |
| **Lot size por $1.000** | 0.01 (conservador) a 0.05 (agressivo) |
| **Máximo de posições abertas** | 10 (regra geral; depende da margem) |

### Princípios de Gestão

1. **Acostume-se com altos e baixos no equity** — drawdowns são inevitáveis com qualquer estratégia.
2. **Defina um DD máximo catastrófico** (20-30%) antes de fechar tudo — este é seu stop loss de emergência. Melhore-se para nunca atingi-lo.
3. **Trade com lot size mínimo** para reduzir a chance de atingir o limite de DD.
4. **Conheça a volatilidade média do instrumento** para espaçar suas entradas. Regra geral: mais espaço entre entradas = mais segurança.
5. **Se estiver em DD profundo**, tente sair no próximo pullback (suporte virando resistência ou vice-versa).
6. **Continue procurando oportunidades lucrativas** mesmo durante um drawdown — os lucros acumulados durante o DD aumentam sua capacidade de suportar a operação ruim.

---

## Lot Size e Dimensionamento

### Tabela de Referência

| Capital | Lot Size Conservador | Lot Size Moderado | Lot Size Agressivo |
|---|---|---|---|
| $1.000 | 0.01 | 0.02-0.03 | 0.05 |
| $5.000 | 0.05 | 0.10-0.15 | 0.25 |
| $10.000 | 0.10 | 0.20-0.30 | 0.50 |

O lot size deve ser **o mesmo para todas as posições** dentro de uma operação (como o KoF faz). O objetivo não é perseguir lucro, mas seguir o processo de scalping.

Para calcular o número total de ordens possíveis: divida o capital disponível pelo (lot size × requisito de margem do par) na moeda da conta.

---

## Pares e Instrumentos Recomendados

### Primários (Melhor desempenho com a estratégia)

- **EURUSD** — Par principal; boa volatilidade e spread baixo
- **GBPUSD** — Movimentos claros; bom para scalping

### Secundários (Use com cautela)

- **AUDUSD** — Tende a movimentos de momentum; mais difícil de gerenciar
- **BTCUSD** — Volatilidade alta; funciona bem para traders experientes
- **XAUUSD (Ouro)** — Spread alto pode ser problema no M1; tendência forte
- **DAX (DE40)** — Boa volatilidade mas spread pode ser muito alto para M1

### Evitar Inicialmente

- Pares JPY (maior complexidade)
- Pares exóticos (spreads proibitivos)
- Pares AUD e Ouro para iniciantes (muito direcionais / "trend-friendly")

---

## Horários de Negociação

- **Sessões com menor atividade** tendem a favorecer a estratégia (mercados mais rangey).
- **Evite operar durante notícias de alto impacto** (NFP, decisões de juros, etc.) — breakouts fortes e spreads alargados podem devastar posições.
- A **sessão de Nova York tardia** e a **sessão asiática** tendem a ter mais movimentos lateralizados em pares europeus.
- Use um **calendário econômico** integrado ao gráfico para filtrar momentos de risco.

---

## Volume — Como Interpretar

O volume no Forex de varejo é **tick volume** (dependente do broker), mas ainda oferece valor:

- **Volume abaixo da EMA 20 do volume** → O movimento atual pode estar perdendo força (bom para entradas contra-tendência).
- **Volume acima da EMA 20 do volume** → O preço ainda pode ter combustível para continuar no mesmo sentido (cautela com entradas).
- **Divergência de volume** → O preço faz nova máxima/mínima, mas o volume diminui — sinal clássico de exaustão.
- **Volume de compradores vs vendedores** (indicadores especializados): quando a diferença chega a zero, pode ser um bom momento para entrar na direção contrária.

---

## Lidando com Tendências Fortes (Breakouts)

Este é o **maior desafio** da estratégia e o motivo pelo qual Abade criou o thread — para aprender como outros traders lidam com as perdas em breakouts fortes.

### Estratégias de Sobrevivência

1. **Filtro de EMA 50**: Atrase suas entradas após um cruzamento forte das EMAs + breakout. Se a EMA 50 não foi tocada, espere.

2. **EMA 9 como sinal de fraqueza**: Após um breakout forte, o preço geralmente toca a EMA 9 antes de retornar às EMAs mais lentas. Não abra novas posições de recuperação até que isso aconteça.

3. **Movimentos parabólicos**: Um breakout parabólico forte é geralmente seguido por um pullback igualmente forte e profundo. Se estiver preso, considere usar uma EMA mais lenta (50 ou 200) como alvo de saída para se beneficiar desse pullback maior.

4. **Scratching de lucros pequenos**: Durante uma tendência forte, pegue lucros pequenos ao longo do caminho — quanto mais tempo segurar, pior pode ficar.

5. **Hedging** (avançado): Alguns traders trancam a perda abrindo uma posição oposta de tamanho igual à soma de todas as posições perdedoras. Isso congela o prejuízo e libera margem, mas requer experiência para desfazer corretamente.

6. **Higher Timeframe POIs (Pontos de Interesse)**: Use zonas de suporte/demanda de timeframes maiores (15min, 1H, 4H) para identificar onde o preço tem maior probabilidade de reverter.

### O que reduz o risco de ser pego em breakouts

- Filtro de tendência (operar apenas na direção da tendência do timeframe superior)
- Melhores entradas (volume fraco, S/R, falhas de nova máxima/mínima, bandas de volatilidade)
- Operar em horários de menor atividade
- Operar instrumentos que tendem a lateralizar mais

---

## Variações e Evoluções do Sistema

### Sistema Original (Abade / KoF Básico)

- 4 EMAs (9, 20, 50, 200) no gráfico M1
- Entradas baseadas em distância do preço às EMAs
- Cost averaging com lot size uniforme
- Saídas nos toques das EMAs

### Sistema cpfleger (V1 a V5)

Cada versão adicionou camadas de confirmação:

- **V1**: EMAs + SupDem + RSI + Volume
- **V3**: Adição de TDI (Traders Dynamic Index), candles Synergy/APB
- **V4**: Regras específicas de zoom, observação de wick/body, regra dos 3 candles
- **V5**: Keltner Channels, Cap Channel, refinamentos de trailing stop

### Variação com SMC (Smart Money Concepts)

Traders incorporaram conceitos de ICT/SMC:

- Order blocks de 4H/1H como filtro para entradas no M1
- Fair Value Gaps (FVG) como zonas de acumulação de posições
- Liquidity zones no gráfico de 15 segundos para timing preciso
- EMA 80 no 15s (equivale à EMA 20 no M1)

### Indicadores adicionais usados pela comunidade

- **Cap Channel Indicator** — Bandas dinâmicas; entradas quando o preço sai das bandas (atenção: pode repintar)
- **Keltner Channels** — Filtro de volatilidade para extensão
- **Contrarian Indicator** (MQL5) — Indicador não-repintante para timing de entradas e saídas
- **Supertrend** — Filtro de direção
- **TDI (Traders Dynamic Index)** — Elbow do TDI como gatilho
- **BB Stops** — Period 10, Deviation 0.4
- **Trailing Stop de 3 pips** — Sugestão de cpfleger para melhorar taxa de acerto

---

## Psicologia do Trader

Lições compartilhadas ao longo do thread:

1. **"Não observe o dinheiro, aprenda o processo."** — cpfleger. Foco na consistência, não no P/L.

2. **"Pratique 20 vezes antes de permitir qualquer pensamento no cérebro."** — O sistema é como andar de bicicleta: você vai cair, mas precisa se preparar para isso.

3. **"Calibre seu dedo no mouse."** — Em scalping, a precisão e a velocidade de entrada/saída são críticas.

4. **"Temos um plano até levarmos um soco na cara."** (Mike Tyson) — Situações ao vivo revelam suas verdadeiras reações. Pratique extensivamente em demo.

5. **"Ninguém vai encontrar seu graal por você."** — Cada trader precisa adaptar o sistema ao seu perfil de risco e temperamento.

6. **"Paciência é o verdadeiro molho secreto do Forex."** — Mesmo no M1, os melhores setups requerem espera.

7. **Meta: 85-90%+ de consistência** antes de pensar em aumentar lot size ou operar com dinheiro real.

8. **"Faça o oposto"** — Um conselho dado por um trader que cresceu conta de $100 para $4.000 em 4 meses: se você perde consistentemente de uma forma, tente inverter sua abordagem.

9. **Publique suas perdas** — O thread valoriza traders que mostram como lidam com perdas, não apenas vitórias. É onde acontece o verdadeiro aprendizado.

---

## Plataformas e Brokers

### Plataformas

- **MetaTrader 4 (MT4)** — Plataforma principal do thread; todos os templates e indicadores foram feitos para ela
- **MetaTrader 5 (MT5)** — Suportada com indicadores equivalentes (APB candles, etc.)
- **TradingView** — Usada por alguns traders, mas falta o indicador SupDem equivalente
- **cTrader** — Alternativa mencionada por alguns membros

### Brokers Recomendados

- **IC Markets** — Spreads baixos, confiável, alavancagem 1:500. Pontos negativos: spreads altos no fim de semana e suporte ao cliente mediano.
- **Blueberry Markets** — Spreads um pouco mais altos, mas bom suporte ao cliente.

### Tipo de Conta

- **Conta Standard** (sem comissão = spreads maiores) — KoF usa esta opção
- **Conta ECN/Raw Spread** (spreads menores + comissão por trade) — cpfleger prefere esta para scalping
- Para scalping no M1, **custos de transação são um fator crítico**. Cada pip conta.

---

## Resumo das Regras Rápidas

```
SETUP:
├── Gráfico: M1 (1 minuto)
├── EMAs: 9, 20, 50, 200 (Exponential Moving Average)
├── Auxiliares: SupDem, RSI, Volume com EMA 20, HA Candles (opcional)
└── Pares: EURUSD, GBPUSD (primários)

ENTRADA (BUY):
├── Preço abaixo das EMAs 20/50 (distância significativa)
├── Rejeição em zona de suporte (SupDem)
├── HA candle verde cruzando EMA 9 para cima
├── RSI virando para alta
└── Sem notícias de impacto

SAÍDA:
├── Ranging → toque na EMA 20
├── Breakout leve → EMA 50
├── Breakout forte → EMA 200
└── Captura do topo/fundo → EMA 9

COST AVERAGING:
├── 1-3 posições iniciais
├── Adicionar 1 por vez quando EMA 9 fura nível de entrada
├── Mesmo lot size para todas
├── Máximo ~10 posições
└── NUNCA overleveragear rapidamente

RISCO:
├── 0.01 lot por $1.000 (conservador)
├── DD catastrófico: 20-30% → fechar tudo
├── Nunca deixar trades overnight
└── Meta: 85%+ taxa de acerto
```

---

## Fontes e Referências

- **Thread original**: [M1 Countertrend Scalping Strategy — Forex Factory](https://www.forexfactory.com/thread/1190104-m1-countertrend-scalping-strategy)
- **King of Forex (KoF)**: Canal no YouTube com vídeos ao vivo de scalping
- **EA baseada no sistema**: [Thread do EA no Forex Factory](https://www.forexfactory.com/thread/1260962-m1-countertrend-scalping-strategy-ea-trading-system)
- **Indicador Contrarian (MQL5)**: Disponível no marketplace MQL5 (versões MT4 e MT5)
- **Conceitos SMC/ICT**: TTrades (YouTube) para zonas de liquidez no 15s

---

## Aviso Legal (Disclaimer)

> **Este documento é apenas para fins educacionais e informativos.** Trading no mercado Forex envolve risco substancial de perda financeira. O cost averaging sem stop loss pode levar à perda total do capital investido. Resultados passados não garantem resultados futuros. Pratique extensivamente em contas demo antes de operar com dinheiro real. Nunca invista dinheiro que você não pode perder. Este documento não constitui aconselhamento financeiro, de investimento, ou de trading.
