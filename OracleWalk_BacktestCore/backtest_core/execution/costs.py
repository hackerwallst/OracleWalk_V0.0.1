from __future__ import annotations


def apply_entry_slippage(price: float, direction: str, slippage: float) -> float:
    factor = 1 if direction.lower() == "long" else -1
    return float(price) * (1 + factor * float(slippage))


def apply_exit_slippage(price: float, direction: str, slippage: float) -> float:
    factor = 1 if direction.lower() == "long" else -1
    return float(price) * (1 - factor * float(slippage))


def commission(price: float, size: float, commission_perc: float) -> float:
    return float(price) * float(size) * float(commission_perc)


def commission_per_lot(size_lots: float, commission_per_lot_side: float) -> float:
    return float(size_lots) * float(commission_per_lot_side)
