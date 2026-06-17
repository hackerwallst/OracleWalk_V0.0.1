# Indicator Registry

Built-in indicators are available through `apply_indicator` and `apply_pipeline`:

```python
from backtest_core.indicators import apply_pipeline

data = apply_pipeline(data, [
    {"name": "ema", "period": 20, "name": "ema20"},
    {"name": "rsi", "period": 14},
])
```

The public core includes a compact native set:

- trend: `sma`, `ema`, `adx`, `supertrend`
- momentum: `rsi`, `macd`, `stochastic`
- volatility: `atr`, `bbands`
- volume: `vwap`, `volume_features`

For a large indicator catalog, install the optional pack:

```bash
python -m pip install "backtest-core[indicators]"
```

Then call external indicators with the `ta:` prefix:

```python
data = apply_pipeline(data, [
    {"name": "ta:rsi", "length": 14},
    {"name": "ta:macd"},
    {"name": "ta:supertrend", "length": 10, "multiplier": 3.0},
])
```

`pandas-ta-classic` is used when available, with `pandas-ta` as fallback.
