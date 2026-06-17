# Optimization & Overfit Diagnostics

`backtest_core/optimization/` — parameter search, walk-forward, and the
anti-overfit metrics. It runs entirely on top of the engine's trade output and
never modifies the engine (Codex owns the core).

## Modules

| Module | What it does |
| --- | --- |
| `objective.py` | one-run `evaluate()` + objective registry (`net_profit`, `profit_factor`, `sharpe_per_trade`, `calmar`, …) |
| `search.py` | `optimize()` — grid/random search; returns ranked results + a bucketed per-config returns matrix |
| `walk_forward.py` | `walk_forward()` — optimize in-sample, evaluate out-of-sample, stitch OOS |
| `overfit.py` | `probability_of_backtest_overfitting()` (PBO/CSCV), `deflated_sharpe_*`, `probabilistic_sharpe_ratio` |

## Quick start

```python
from backtest_core.optimization import optimize, walk_forward, \
    probability_of_backtest_overfitting, deflated_sharpe_from_matrix
from backtest_core.strategies.examples import EmaCrossStrategy

space = {"fast": [8, 12, 16], "slow": [30, 36, 48],
         "stop_atr": [1.0, 1.5, 2.0], "take_atr": [2.0, 3.0, 4.0]}

opt = optimize(EmaCrossStrategy, data, engine_cfg, space, objective="sharpe_per_trade")
pbo = probability_of_backtest_overfitting(opt["returns_matrix"], n_splits=10)
dsr = deflated_sharpe_from_matrix(opt["returns_matrix"])
wf  = walk_forward(EmaCrossStrategy, data, engine_cfg, space, n_splits=5, scheme="anchored")
```

Full runnable example: `examples/run_optimization_demo.py`.

## How to read the numbers

- **PBO** (Probability of Backtest Overfitting, 0–1): chance that the in-sample
  best config underperforms the median out-of-sample. > 0.5 ≈ the optimization
  is likely fitting noise. Computed by CSCV (Bailey et al.).
- **Deflated Sharpe (DSR)**: the Probabilistic Sharpe after deflating for the
  number of trials. It asks "is the observed Sharpe real, given I tried N
  configs?" Low DSR = the winner is probably luck.
- **Walk-forward degradation**: `OOS_objective_mean − IS_objective_mean`. Large
  negative = the strategy only works on data it was tuned on.

> Trust the **out-of-sample** track, **PBO** and **DSR** — not the in-sample
> winner. A backtest that looks great on the full sample and collapses
> out-of-sample is overfit, and these tools make that visible.

## Interface notes (boundary with Codex)

This package only **reads** the engine's `trades` DataFrame (via
`core.engine.Backtester`) and `analytics.metrics`. When the multi-asset
`PortfolioResult` lands (Codex), the same search/WFO loop can target portfolio
objectives by swapping the evaluation function — no engine edits required.
