"""Per-zone edge analytics (Pillar 2) — the product's differentiator.

Because zones are hand-drawn *live and causally* (no lookahead), we can finally
answer the question a normal backtester can't: **which of my zones actually had
edge?** This aggregates the finished trades by the zone that triggered them, and
measures each zone's *respect rate* (touches that bounced vs broke through) from
the price action that came after it was drawn.

Reads finished results + the causal ``ZoneStore``. No engine dependency.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def build_zone_analytics(
    trades: pd.DataFrame,
    zone_store,
    data: pd.DataFrame,
    n_bars: int | None = None,
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """Edge by zone / TF / side / mode + per-zone respect rate.

    ``zone_store`` is the session's ``ZoneStore``; ``data`` the engine's prepared
    OHLC frame; ``n_bars`` the bar count actually replayed (causal cap).
    """
    cap = (n_bars - 1) if n_bars else None
    zones = list(zone_store.all_zones(cap)) if zone_store is not None else []
    has_trades = trades is not None and not trades.empty
    tdf = trades.copy() if has_trades else pd.DataFrame()

    if has_trades and "zone_id" not in tdf.columns:
        tdf["zone_id"] = None

    # --- per-zone respect rate from price action after the zone was drawn ------
    respect = _respect_rates(zones, data, cap)

    by_zone: list[dict[str, Any]] = []
    zones_with_trades = 0
    for z in zones:
        zid = z["id"]
        z_trades = tdf[tdf["zone_id"] == zid] if has_trades else pd.DataFrame()
        agg = _edge_stats(z_trades)
        if agg["trades"] > 0:
            zones_with_trades += 1
        r = respect.get(zid, {"touches": 0, "bounces": 0, "breaks": 0, "respect_rate": None})
        by_zone.append({
            "zone_id": zid,
            "side": z.get("side"),
            "timeframe": z.get("timeframe") or "",
            "price_low": z.get("price_low"),
            "price_high": z.get("price_high"),
            "created_at_bar": z.get("created_at_bar"),
            "state": z.get("state"),
            **agg,
            **r,
        })

    by_tf = _group_edge(tdf, "zone_tf", label="timeframe") if has_trades else []
    by_side = _group_edge(tdf, "zone_side", label="side") if has_trades else []
    by_mode = _mode_edge(tdf, mode) if has_trades else []

    return {
        "totals": {
            "zones_drawn": len(zones),
            "zones_with_trades": zones_with_trades,
            "unused_zones": len(zones) - zones_with_trades,
        },
        "by_zone": by_zone,
        "by_tf": by_tf,
        "by_side": by_side,
        "by_mode": by_mode,
    }


# --------------------------------------------------------------------------- #
def _edge_stats(t: pd.DataFrame) -> dict[str, Any]:
    if t is None or t.empty:
        return {"trades": 0, "wins": 0, "win_rate": None, "net_pnl": 0.0,
                "avg_r": None, "profit_factor": None}
    pnl = pd.to_numeric(t["pnl"], errors="coerce").fillna(0.0)
    wins = int((pnl > 0).sum())
    n = int(len(pnl))
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(pnl[pnl < 0].sum())
    r = pd.to_numeric(t["risk_reward"], errors="coerce").dropna() if "risk_reward" in t.columns else pd.Series(dtype=float)
    return {
        "trades": n,
        "wins": wins,
        "win_rate": round(wins / n * 100.0, 2) if n else None,
        "net_pnl": float(pnl.sum()),
        "avg_r": float(r.mean()) if not r.empty else None,
        "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
    }


def _group_edge(tdf: pd.DataFrame, col: str, *, label: str) -> list[dict[str, Any]]:
    if tdf is None or tdf.empty or col not in tdf.columns:
        return []
    out: list[dict[str, Any]] = []
    keyed = tdf.copy()
    keyed[col] = keyed[col].fillna("(base)").replace("", "(base)")
    for key, grp in keyed.groupby(col):
        out.append({label: key, **_edge_stats(grp)})
    out.sort(key=lambda d: d.get("net_pnl", 0.0), reverse=True)
    return out


def _mode_edge(tdf: pd.DataFrame, mode: str | None) -> list[dict[str, Any]]:
    """Split by the SEM/COM tag carried in the trade comment (e.g. 'BUY|COM')."""
    if tdf is None or tdf.empty or "comment" not in tdf.columns:
        return []
    keyed = tdf.copy()
    keyed["_mode"] = keyed["comment"].astype(str).str.split("|").str[-1].str.upper()
    keyed.loc[~keyed["_mode"].isin(["SEM", "COM"]), "_mode"] = mode or "?"
    out = []
    for key, grp in keyed.groupby("_mode"):
        stats = _edge_stats(grp)
        out.append({"mode": key, "trades": stats["trades"], "win_rate": stats["win_rate"],
                    "net_pnl": stats["net_pnl"], "avg_r": stats["avg_r"]})
    out.sort(key=lambda d: d.get("net_pnl", 0.0), reverse=True)
    return out


def _respect_rates(zones: list[dict], data: pd.DataFrame, cap: int | None) -> dict[str, dict]:
    """For each zone, count touch episodes after creation and how many broke through.

    A *touch* episode = a contiguous run of bars whose [low,high] intersects the
    zone band. A *break* = the price closes beyond the far side of the zone during
    that episode (below a support / above a resistance). respect_rate = bounces /
    touches, where bounces = touches that did not break.
    """
    out: dict[str, dict] = {}
    if data is None or len(data) == 0 or not {"high", "low", "close"}.issubset(data.columns):
        return {z["id"]: {"touches": 0, "bounces": 0, "breaks": 0, "respect_rate": None} for z in zones}
    high = pd.to_numeric(data["high"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(data["low"], errors="coerce").to_numpy(dtype=float)
    close = pd.to_numeric(data["close"], errors="coerce").to_numpy(dtype=float)
    end = min(cap + 1, len(data)) if cap is not None else len(data)

    for z in zones:
        lo, hi = float(z["price_low"]), float(z["price_high"])
        side = z.get("side")
        start = int(z.get("created_at_bar", 0)) + 1  # only bars AFTER the draw
        touches = breaks = 0
        inside = False
        broke_this_episode = False
        for i in range(max(start, 0), end):
            intersects = (low[i] <= hi) and (high[i] >= lo)
            if intersects and not inside:
                inside = True
                broke_this_episode = False
                touches += 1
            if inside:
                broke = (close[i] < lo) if side == "support" else (close[i] > hi)
                if broke and not broke_this_episode:
                    breaks += 1
                    broke_this_episode = True
            if not intersects and inside:
                inside = False
        bounces = max(touches - breaks, 0)
        out[z["id"]] = {
            "touches": touches,
            "bounces": bounces,
            "breaks": breaks,
            "respect_rate": round(bounces / touches * 100.0, 1) if touches else None,
        }
    return out
