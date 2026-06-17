from __future__ import annotations

import importlib
import os
from collections.abc import Iterable
from typing import TypeVar

from .base import StrategyBase


StrategyT = TypeVar("StrategyT", bound=type[StrategyBase])

STRATEGIES: dict[str, type[StrategyBase]] = {}

_DISCOVERED = False
_PUBLIC_MODULES = ("backtest_core.strategies.examples.ema_cross",)
_LOCAL_MODULES = ("backtest_core.strategies.local",)
_ENV_MODULES = "BACKTEST_CORE_STRATEGY_MODULES"


def normalize_strategy_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def register_strategy(
    name: str | None = None,
    aliases: Iterable[str] = (),
):
    def decorator(cls: StrategyT) -> StrategyT:
        register_strategy_class(cls, name=name, aliases=aliases)
        return cls

    return decorator


def register_strategy_class(
    cls: type[StrategyBase],
    name: str | None = None,
    aliases: Iterable[str] = (),
) -> type[StrategyBase]:
    if not issubclass(cls, StrategyBase):
        raise TypeError(f"{cls!r} is not a StrategyBase subclass")

    keys = [name or getattr(cls, "id", None) or cls.__name__]
    keys.extend(aliases)
    for key in keys:
        STRATEGIES[normalize_strategy_name(str(key))] = cls
    return cls


def discover_strategies(extra_modules: Iterable[str] | None = None) -> dict[str, type[StrategyBase]]:
    global _DISCOVERED
    if _DISCOVERED and not extra_modules:
        return STRATEGIES

    modules = [*_PUBLIC_MODULES, *_LOCAL_MODULES, *_modules_from_env()]
    if extra_modules:
        modules.extend(extra_modules)

    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue
            raise

    if not extra_modules:
        _DISCOVERED = True
    return STRATEGIES


def build_strategy(config: dict) -> StrategyBase:
    discover_strategies()
    strategy_cfg = config.get("strategy", {})
    strategy_name = normalize_strategy_name(strategy_cfg.get("name", "ema_cross"))
    params = strategy_cfg.get("params", {})
    if strategy_name not in STRATEGIES:
        available = ", ".join(sorted(STRATEGIES))
        raise KeyError(f"unknown strategy '{strategy_name}'. Available: {available}")
    return STRATEGIES[strategy_name](**params)


def available_strategies() -> list[str]:
    discover_strategies()
    return sorted(STRATEGIES)


def _modules_from_env() -> list[str]:
    raw = os.getenv(_ENV_MODULES, "")
    return [item.strip() for item in raw.split(",") if item.strip()]
