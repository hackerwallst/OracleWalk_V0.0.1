"""First-class, strategy-agnostic execution/cost presets for homologation.

These helpers take a *base* engine config (e.g. produced from a broker symbol spec)
and return a new config dict with the cost surface and sizing set to a named preset.
They never touch strategy parameters — only execution knobs — so the same strategy
can be run COSTS_OFF (isolate execution logic), COSTS_REALISTIC (honest performance),
or MT5_PARITY (bit-for-bit vs the MT5 tester), with an optional fixed-lot audit that
removes position sizing as a variable.

See EXECUTION_SPEC.md §7.
"""
from __future__ import annotations

from typing import Any

COST_MODES = ("COSTS_OFF", "COSTS_REALISTIC", "MT5_PARITY")

# Cost-surface fields a preset may zero/keep. Pure execution knobs (modes, timing,
# pending book, intrabar) are intentionally NOT touched here.
_COST_FIELDS = (
    "commission_per_lot",
    "commission_perc",
    "swap_long_per_lot",
    "swap_short_per_lot",
)


def apply_cost_mode(base: dict[str, Any], mode: str) -> dict[str, Any]:
    """Return a copy of ``base`` with the cost surface set to ``mode``.

    COSTS_OFF       -> spread off, zero commission/swap. (Tick spread is still applied
                       in tick mode because ask-bid is a market property, not a cost
                       toggle — matching MT5.)
    COSTS_REALISTIC -> keep the broker's spread, commission and swap from ``base``.
    MT5_PARITY      -> same as REALISTIC; kept distinct so callers can layer any
                       further MT5-only knobs (e.g. triple_swap_weekday) explicitly.
    """
    if mode not in COST_MODES:
        raise ValueError(f"mode must be one of {COST_MODES}, got {mode!r}")
    cfg = dict(base)
    if mode == "COSTS_OFF":
        cfg["use_spread"] = False
        for f in _COST_FIELDS:
            cfg[f] = 0.0
    else:  # COSTS_REALISTIC / MT5_PARITY keep the broker cost surface untouched
        cfg.setdefault("use_spread", True)
    return cfg


def apply_fixed_lot_audit(base: dict[str, Any], lots: float = 1.0) -> dict[str, Any]:
    """Return a copy of ``base`` configured for a fixed-lot audit.

    Disables %-risk sizing so every trade uses ``lots`` — removes position sizing as
    a source of divergence when auditing prices/timing. (The strategy may still emit a
    per-signal ``size``; with risk_per_trade_pct=0 the engine uses that or 1.0.)
    """
    cfg = dict(base)
    cfg["risk_per_trade_pct"] = 0.0
    cfg["fixed_lot"] = float(lots)
    return cfg


def build_exec_config(
    base: dict[str, Any],
    *,
    cost_mode: str = "COSTS_REALISTIC",
    fixed_lot: float | None = None,
) -> dict[str, Any]:
    """Convenience: apply a cost mode and (optionally) a fixed-lot audit in one call."""
    cfg = apply_cost_mode(base, cost_mode)
    if fixed_lot is not None:
        cfg = apply_fixed_lot_audit(cfg, fixed_lot)
    return cfg
