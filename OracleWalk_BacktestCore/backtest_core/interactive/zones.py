"""Causal store of support/resistance zones drawn during a replay.

Each zone carries the bar index at which it was created. The store keeps an
append-only log of mutations (create / update / delete), each stamped with the
bar index where it happened. ``active_zones(bar_index)`` reconstructs the zone
set as it existed at that bar, considering only events at or before it.

This is the anti-lookahead guarantee: a zone can never influence a bar earlier
than the bar where it was drawn, and edits/removals only take effect from their
own bar onward. The log also makes a full replay deterministic and re-runnable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_PRICE_FIELDS = ("price_low", "price_high")
_VALID_SIDES = ("support", "resistance")


@dataclass
class ZoneEvent:
    kind: str  # "create" | "update" | "delete"
    bar_index: int
    payload: dict[str, Any]


class ZoneStore:
    def __init__(self) -> None:
        self._events: list[ZoneEvent] = []
        self._counter = 0

    # ---- mutations (each stamped with the bar where it happened) ----
    def create(
        self,
        bar_index: int,
        price_low: float,
        price_high: float,
        side: str,
        timeframe: str = "",
    ) -> str:
        self._counter += 1
        zid = f"z{self._counter}"
        lo, hi = sorted((float(price_low), float(price_high)))
        self._events.append(
            ZoneEvent(
                "create",
                int(bar_index),
                {
                    "id": zid,
                    "price_low": lo,
                    "price_high": hi,
                    "side": _clean_side(side),
                    "timeframe": _clean_tf(timeframe),
                },
            )
        )
        return zid

    def update(self, zid: str, bar_index: int, fields: dict[str, Any]) -> None:
        payload: dict[str, Any] = {"id": zid}
        if "price_low" in fields and "price_high" in fields:
            lo, hi = sorted((float(fields["price_low"]), float(fields["price_high"])))
            payload["price_low"], payload["price_high"] = lo, hi
        else:
            for field in _PRICE_FIELDS:
                if field in fields and fields[field] is not None:
                    payload[field] = float(fields[field])
        if fields.get("side"):
            payload["side"] = _clean_side(fields["side"])
        if fields.get("timeframe"):
            payload["timeframe"] = _clean_tf(fields["timeframe"])
        self._events.append(ZoneEvent("update", int(bar_index), payload))

    def delete(self, zid: str, bar_index: int) -> None:
        self._events.append(ZoneEvent("delete", int(bar_index), {"id": zid}))

    # ---- causal read ----
    def active_zones(self, bar_index: int) -> list[dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for ev in self._events:
            if ev.bar_index > bar_index:
                continue
            zid = ev.payload["id"]
            if ev.kind == "create":
                states[zid] = {
                    "id": zid,
                    "price_low": ev.payload["price_low"],
                    "price_high": ev.payload["price_high"],
                    "side": ev.payload["side"],
                    "timeframe": ev.payload.get("timeframe", ""),
                    "created_at_bar": ev.bar_index,
                    "state": "active",
                }
                order.append(zid)
            elif ev.kind == "update" and zid in states:
                for key in ("price_low", "price_high", "side", "timeframe"):
                    if key in ev.payload:
                        states[zid][key] = ev.payload[key]
            elif ev.kind == "delete" and zid in states:
                states[zid]["state"] = "deleted"
        return [states[z] for z in order if states[z]["state"] != "deleted"]

    def get(self, zid: str, bar_index: int) -> dict[str, Any] | None:
        for zone in self.active_zones(bar_index):
            if zone["id"] == zid:
                return zone
        return None

    def all_zones(self, bar_index: int | None = None) -> list[dict[str, Any]]:
        """Every zone ever created up to ``bar_index`` (default: all), including
        deleted ones, with their resolved definition and final ``state``.

        Unlike :meth:`active_zones`, deleted zones are kept — a zone may have
        produced trades before it was erased, and per-zone edge analytics must
        still attribute them. ``state`` is ``"active"`` or ``"deleted"``.
        """
        cap = bar_index if bar_index is not None else max((e.bar_index for e in self._events), default=0)
        states: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for ev in self._events:
            if ev.bar_index > cap:
                continue
            zid = ev.payload["id"]
            if ev.kind == "create":
                states[zid] = {
                    "id": zid,
                    "price_low": ev.payload["price_low"],
                    "price_high": ev.payload["price_high"],
                    "side": ev.payload["side"],
                    "timeframe": ev.payload.get("timeframe", ""),
                    "created_at_bar": ev.bar_index,
                    "state": "active",
                }
                order.append(zid)
            elif ev.kind == "update" and zid in states:
                for key in ("price_low", "price_high", "side", "timeframe"):
                    if key in ev.payload:
                        states[zid][key] = ev.payload[key]
            elif ev.kind == "delete" and zid in states:
                states[zid]["state"] = "deleted"
        return [states[z] for z in order]


def _clean_side(side: str) -> str:
    value = str(side or "").strip().lower()
    return value if value in _VALID_SIDES else "support"


def _clean_tf(timeframe: str) -> str:
    return str(timeframe or "").strip().upper()
