from __future__ import annotations


def fixed_size(size: float = 1.0) -> float:
    return float(size)


def risk_percent_size(
    capital: float,
    entry_price: float,
    stop_price: float,
    risk_per_trade_pct: float,
) -> float:
    per_unit_risk = abs(float(entry_price) - float(stop_price))
    if per_unit_risk <= 0:
        raise ValueError("entry_price and stop_price must produce positive per-unit risk")
    money_risk = float(capital) * (float(risk_per_trade_pct) / 100.0)
    return money_risk / per_unit_risk
