# file: oraclewalk/execution/order_model.py

from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: str
    closed_at: Optional[str] = None
    pnl: float = 0.0
    is_open: bool = True
