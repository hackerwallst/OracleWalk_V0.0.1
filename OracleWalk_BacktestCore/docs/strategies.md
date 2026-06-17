# Plug-in Strategies

The backtester keeps the engine separate from strategy ideas.

Public strategies can be registered with a decorator:

```python
from backtest_core.strategies import StrategyBase, register_strategy


@register_strategy("my_strategy")
class MyStrategy(StrategyBase):
    name = "My Strategy"

    def generate_signals(self, data):
        ...
```

The CLI reads the strategy name from the config:

```json
{
  "strategy": {
    "name": "my_strategy",
    "params": {}
  }
}
```

Local/private strategies should stay outside the public release. There are two supported paths:

- add imports/registrations in `backtest_core/strategies/local.py`;
- or point to modules with `BACKTEST_CORE_STRATEGY_MODULES`, separated by commas.

Example:

```bash
BACKTEST_CORE_STRATEGY_MODULES=my_private_strategies.fvg,my_private_strategies.scalper \
python -m backtest_core.cli --config configs/my_config.json
```
