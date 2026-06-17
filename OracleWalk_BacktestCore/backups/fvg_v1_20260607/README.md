# Backup — FVG Imbalance v1 (2026-06-07)

Snapshot **congelado** da estratégia Fair Value Gap que apresentou edge, feito
ANTES de novos updates. Não editar estes arquivos — são a referência de restauro.

## Arquivos
| Backup | Original |
| --- | --- |
| `fvg_imbalance.py` | `backtest_core/strategies/fvg_imbalance.py` (estratégia clássica + `detect_fvg_boxes`) |
| `interactive_fvg.py` | `backtest_core/interactive/strategies/fvg.py` (versão do replay interativo) |
| `fvg_eurusd_h1.json` | `configs/fvg_eurusd_h1.json` (config de execução) |

## Regras desta versão
- **FVG (3 candles):** alta = `high[i-2] < low[i]` → compra; baixa = `low[i-2] > high[i]` → venda.
- **Entrada:** limit no **50%** do gap, no candle que retorna e toca o nível.
- **Stop:** extremo das 3 velas (low mais baixo / high mais alto).
- **Alvo:** **1:3** sobre o risco entrada→stop.
- **Filtro volume:** vela de deslocamento (a do meio) > média de volume dos 5 candles anteriores.
- **Filtro SMA60** (fechamento), avaliado **na entrada:** compra só se close > SMA60, venda só se close < SMA60.
- **Expira após 20 candles** se não tocar o 50%.
- Parâmetros: `sma_period=60, vol_lookback=5, expiry_bars=20, rr=3.0, stop_buffer_points=0.0`.

## Métricas do edge (EURUSD H1, ~100k barras / ~15 anos, 1% de risco)
| Métrica | Valor |
| --- | --- |
| Trades | 3.159 |
| Win rate | 32,0% |
| Profit factor | 1,14 |
| Payoff | 2,42 |
| Sharpe (por trade) | 2,39 |
| Retorno líquido | +32.359% (compõe) |
| Max drawdown | −62% |

> Observação: DD alto é característico de 1:3 com win rate baixo + sizing que
> compõe. Os updates futuros provavelmente vão mirar suavizar isso (risco, filtros,
> expiry) sem matar o edge.

## Como restaurar
```bash
cd OracleWalk_BacktestCore
cp backups/fvg_v1_20260607/fvg_imbalance.py   backtest_core/strategies/fvg_imbalance.py
cp backups/fvg_v1_20260607/interactive_fvg.py backtest_core/interactive/strategies/fvg.py
cp backups/fvg_v1_20260607/fvg_eurusd_h1.json configs/fvg_eurusd_h1.json
```

Integridade (SHA-256) — confira com `shasum -a 256 backups/fvg_v1_20260607/*`:
- `fvg_imbalance.py`  → `7c01fdf9f6ae30b949dbebc83aa6ba366b963fde67ff8d1f0afbb58448f06cbb`
- `interactive_fvg.py` → `1b5783b1b2fc8e4e041827d0f22a2644cfef411335ef51b5029193986c9724ef`
- `fvg_eurusd_h1.json` → `900fba8677ab1033de2ab709780bdef6af17942ce28384ab3e94d60e780cce6f`
