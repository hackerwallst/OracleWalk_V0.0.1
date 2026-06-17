"""Interactive replay backtesting (human-in-the-loop + EA).

Separate track from the classic batch backtester. Nothing here edits or imports
mutable state from the classic engine beyond *reusing* ``core.engine.Backtester``
helper methods by inheritance. The classic track stays frozen.
"""

from .engine import InteractiveBacktester
from .session import InteractiveSession
from .strategy_base import BarContext, Intent, InteractiveStrategyBase
from .stub import ZoneTouchStub
from .zones import ZoneStore

__all__ = [
    "BarContext",
    "Intent",
    "InteractiveBacktester",
    "InteractiveSession",
    "InteractiveStrategyBase",
    "ZoneStore",
    "ZoneTouchStub",
]
