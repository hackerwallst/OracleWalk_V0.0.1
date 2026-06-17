"""Prop-firm evaluation — can a strategy pass a proprietary trading-firm challenge?

Reads the engine's per-bar equity track (datetime, equity, equity_low) plus the
trades, and judges the strategy against prop-firm rules (FTMO by default). All rules
are percentage-based and therefore scale-invariant, so the evaluation works on the
normalized equity (equity / initial_capital) and only uses `account_size` to render
money figures.

Two views:
  * single   — treat the whole backtest as ONE challenge attempt (pass/fail per rule
               + how close to each limit). One path = one (lucky/unlucky) sample.
  * rolling  — start a virtual challenge on EVERY trading day and report the % of
               starts that pass Phase 1, Phase 2, and both chained. This is the honest
               answer to "is the strategy capable of passing the firm", not a single path.

The daily-loss rule is checked on intrabar equity (`equity_low`), so an intraday dip
that a real desk would fail is not hidden by a green close.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


@dataclass
class PropRules:
    name: str
    profit_target_pct: float | None   # None = no target (funded phase)
    max_daily_loss_pct: float          # drop from the day's starting equity
    max_total_loss_pct: float          # static: drop from the challenge's initial balance
    min_trading_days: int
    max_days: int | None = None        # calendar/trading-day limit (None = unlimited)
    # --- account-busting extras (off by default; FTMO Normal doesn't use them) ---
    trailing_dd_pct: float | None = None        # trailing max drawdown (replaces/augments static)
    trailing_mode: str = "equity"               # "equity" (intraday high) or "balance" (daily close)
    trailing_basis: str = "peak"                 # "peak" = dd% of the running high-water (recalculated as
                                                 #   balance grows; the common forex-prop model);
                                                 # "initial" = dd% of the starting balance (fixed $, futures style)
    trailing_locks_at_initial: bool = False     # floor stops rising once it reaches the initial balance
    max_best_day_pct: float | None = None        # consistency: best day <= X% of total profit
    forbid_weekend_holding: bool = False         # no position may be held across a weekend
    require_stop_loss: bool = False              # every trade must carry a stop


# FTMO "Normal" rules (the project's broker). Targets/limits as fractions of balance.
FTMO_CHALLENGE = PropRules("FTMO Challenge", 0.10, 0.05, 0.10, 4)
FTMO_VERIFICATION = PropRules("FTMO Verification", 0.05, 0.05, 0.10, 4)
FTMO_FUNDED = PropRules("FTMO Funded", None, 0.05, 0.10, 0)
# A trailing-drawdown style desk (think FundedNext Stellar / many futures props): no
# static loss, a 6% equity trailing drawdown that locks at the initial balance, plus a
# 40%-of-profit consistency rule.
TRAILING_DESK = PropRules("Trailing-DD desk", 0.08, 0.05, 0.99, 3,
                          trailing_dd_pct=0.06, trailing_mode="equity",
                          trailing_basis="peak", trailing_locks_at_initial=False,
                          max_best_day_pct=0.40)

PRESETS = {
    "ftmo_challenge": FTMO_CHALLENGE,
    "ftmo_verification": FTMO_VERIFICATION,
    "ftmo_funded": FTMO_FUNDED,
    "trailing_desk": TRAILING_DESK,
}


# --------------------------------------------------------------------------- #
def daily_frame(equity_curve: pd.DataFrame, initial_capital: float,
                trades: pd.DataFrame | None = None) -> pd.DataFrame:
    """Collapse the per-bar equity track to one row per calendar day.

    Columns (normalized so initial_capital -> 1.0): r_open, r_close, r_min, r_max,
    plus `traded` (a position opened or closed that day -> counts as a trading day).
    """
    if equity_curve is None or equity_curve.empty:
        return pd.DataFrame(columns=["date", "r_open", "r_close", "r_min", "r_max", "traded"])
    ec = equity_curve.copy()
    ec["date"] = pd.to_datetime(ec["datetime"]).dt.date
    r = ec["equity"] / initial_capital
    r_low = ec["equity_low"] / initial_capital
    g = ec.assign(r=r, r_low=r_low).groupby("date")
    out = pd.DataFrame({
        "r_open": g["r"].first(),
        "r_close": g["r"].last(),
        "r_min": g["r_low"].min(),
        "r_max": g["r"].max(),
    }).reset_index()

    traded_dates: set = set()
    if trades is not None and not trades.empty:
        for col in ("entry_time", "exit_time"):
            if col in trades.columns:
                traded_dates |= set(pd.to_datetime(trades[col], errors="coerce").dt.date.dropna())
    out["traded"] = out["date"].isin(traded_dates)
    return out


# --------------------------------------------------------------------------- #
def _simulate(daily: pd.DataFrame, start: int, rules: PropRules) -> dict:
    """Run one challenge from row `start`. Returns outcome + day index of pass.

    outcome in {pass, fail_daily, fail_total, incomplete}.
    """
    base = daily["r_open"].iloc[start]
    if base <= 0:
        return {"outcome": "incomplete", "end": start, "trading_days": 0}
    target = None if rules.profit_target_pct is None else rules.profit_target_pct
    dd = rules.trailing_dd_pct
    peak = base  # running high-water for the trailing drawdown floor
    elapsed_trading = 0
    for i in range(start, len(daily)):
        row = daily.iloc[i]
        if rules.max_days is not None and (i - start) >= rules.max_days:
            return {"outcome": "incomplete", "end": i, "trading_days": elapsed_trading}
        day_open = row["r_open"]
        # Breaches first (a desk fails you the instant a limit is hit).
        daily_dd = (row["r_min"] - day_open) / base
        if daily_dd <= -rules.max_daily_loss_pct:
            return {"outcome": "fail_daily", "end": i, "trading_days": elapsed_trading}
        total_dd = (row["r_min"] - base) / base
        if total_dd <= -rules.max_total_loss_pct:
            return {"outcome": "fail_total", "end": i, "trading_days": elapsed_trading}
        # Trailing drawdown: floor trails the running high-water (intraday for "equity",
        # daily close for "balance"), optionally locking once it reaches the initial.
        if dd is not None:
            peak = max(peak, row["r_max"] if rules.trailing_mode == "equity" else row["r_close"])
            # Allowance recalculated on the running high-water ("peak") or fixed off the
            # initial balance ("initial"); the floor only ratchets up with the peak.
            floor = peak - dd * (peak if rules.trailing_basis == "peak" else base)
            if rules.trailing_locks_at_initial:
                floor = min(floor, base)
            if row["r_min"] < floor:
                return {"outcome": "fail_trailing", "end": i, "trading_days": elapsed_trading}
        if row["traded"]:
            elapsed_trading += 1
        # Profit target (on the day's close), only valid once min trading days are met.
        if target is not None:
            gain = (row["r_close"] - base) / base
            if gain >= target and elapsed_trading >= rules.min_trading_days:
                return {"outcome": "pass", "end": i, "trading_days": elapsed_trading,
                        "days": i - start + 1}
    # No target (funded) and no breach over the whole span = survived.
    if target is None:
        return {"outcome": "pass", "end": len(daily) - 1, "trading_days": elapsed_trading,
                "days": len(daily) - start}
    return {"outcome": "incomplete", "end": len(daily) - 1, "trading_days": elapsed_trading}


def evaluate_single(daily: pd.DataFrame, rules: PropRules) -> dict:
    """Whole backtest as one challenge: per-rule status + verdict + margins."""
    if daily.empty:
        return {"verdict": "no_data"}
    base = daily["r_open"].iloc[0]
    # Worst intraday daily drawdown across all days (% of initial).
    daily_dd_series = (daily["r_min"] - daily["r_open"]) / base
    total_dd_series = (daily["r_min"] - base) / base
    daily_dd = daily_dd_series.min()
    total_dd = total_dd_series.min()
    peak_gain = ((daily["r_close"] - base) / base).max()
    trading_days = int(daily["traded"].sum())
    worst_daily_date = str(daily["date"].iloc[int(daily_dd_series.idxmin())]) if len(daily) else None
    worst_total_date = str(daily["date"].iloc[int(total_dd_series.idxmin())]) if len(daily) else None
    # Consistency: largest single-day gain as a share of total profit (some firms cap
    # this; FTMO doesn't, but it flags "one lucky day carries the result").
    day_gain = (daily["r_close"] - daily["r_open"])
    total_profit = float(daily["r_close"].iloc[-1] - base)
    best_day_gain = float(day_gain.max())
    consistency_pct = (best_day_gain / total_profit * 100.0) if total_profit > 0 else None
    net_return_pct = total_profit / base * 100.0

    # Worst trailing-drawdown excursion across the whole curve (% of initial), if used.
    worst_trailing_dd = None
    if rules.trailing_dd_pct is not None:
        peak = base
        worst = 0.0
        peak_src = daily["r_max"] if rules.trailing_mode == "equity" else daily["r_close"]
        rmins = daily["r_min"].to_numpy()
        psrc = peak_src.to_numpy()
        for j in range(len(daily)):
            peak = max(peak, float(psrc[j]))
            floor = peak - rules.trailing_dd_pct * (peak if rules.trailing_basis == "peak" else base)
            if rules.trailing_locks_at_initial:
                floor = min(floor, base)
            worst = min(worst, (float(rmins[j]) - floor) / base)
        worst_trailing_dd = worst

    daily_ok = daily_dd > -rules.max_daily_loss_pct
    total_ok = total_dd > -rules.max_total_loss_pct
    target_ok = rules.profit_target_pct is None or peak_gain >= rules.profit_target_pct
    days_ok = trading_days >= rules.min_trading_days
    trailing_ok = worst_trailing_dd is None or worst_trailing_dd > 0  # floor never crossed
    consistency_ok = (rules.max_best_day_pct is None or total_profit <= 0
                      or (best_day_gain / total_profit) <= rules.max_best_day_pct)

    passed = daily_ok and total_ok and target_ok and days_ok and trailing_ok and consistency_ok
    binding = None
    if not daily_ok:
        binding = "max_daily_loss"
    elif not trailing_ok:
        binding = "trailing_dd"
    elif not total_ok:
        binding = "max_total_loss"
    elif not target_ok:
        binding = "profit_target"
    elif not days_ok:
        binding = "min_trading_days"
    elif not consistency_ok:
        binding = "consistency"
    return {
        "passed": bool(passed),
        "binding_rule": binding,
        "worst_daily_dd_pct": float(daily_dd * 100),
        "worst_daily_dd_date": worst_daily_date,
        "worst_total_dd_pct": float(total_dd * 100),
        "worst_total_dd_date": worst_total_date,
        "max_gain_pct": float(peak_gain * 100),
        "net_return_pct": float(net_return_pct),
        "trading_days": trading_days,
        "best_day_gain_pct": float(best_day_gain * 100),
        "consistency_pct": consistency_pct,
        "worst_trailing_dd_pct": None if worst_trailing_dd is None else float(worst_trailing_dd * 100),
        "checks": {
            "profit_target": bool(target_ok), "max_daily_loss": bool(daily_ok),
            "max_total_loss": bool(total_ok), "min_trading_days": bool(days_ok),
            "trailing_dd": bool(trailing_ok), "consistency": bool(consistency_ok),
        },
    }


def rolling_pass_rate(daily: pd.DataFrame, rules: PropRules) -> dict:
    """Start a challenge on every trading day; report the pass-rate + failure mix."""
    if daily.empty:
        return {"n_starts": 0, "pass_rate": None}
    starts = [i for i in range(len(daily)) if daily["traded"].iloc[i]] or list(range(len(daily)))
    outcomes = [_simulate(daily, i, rules) for i in starts]
    n = len(outcomes)
    counts = {k: 0 for k in ("pass", "fail_daily", "fail_total", "fail_trailing", "incomplete")}
    days_to_pass = []
    for o in outcomes:
        counts[o["outcome"]] += 1
        if o["outcome"] == "pass" and "days" in o:
            days_to_pass.append(o["days"])
    fail_keys = ("fail_daily", "fail_total", "fail_trailing")
    binding = max(fail_keys, key=lambda k: counts[k]) if any(counts[k] for k in fail_keys) else None
    rate = counts["pass"] / n if n else None
    return {
        "n_starts": n,
        "pass_count": counts["pass"],
        "pass_rate": rate,
        "breakdown_pct": {k: (v / n * 100 if n else 0.0) for k, v in counts.items()},
        "breakdown_counts": dict(counts),
        "median_days_to_pass": float(np.median(days_to_pass)) if days_to_pass else None,
        "min_days_to_pass": int(np.min(days_to_pass)) if days_to_pass else None,
        "max_days_to_pass": int(np.max(days_to_pass)) if days_to_pass else None,
        "expected_attempts": (1.0 / rate) if rate else None,
        "dominant_failure": binding,
    }


def evaluate_funded(daily: pd.DataFrame, rules: PropRules, account_size: float) -> dict:
    """Funded phase: there is no target — you keep the account until a loss/trailing
    limit blows it up. Start a funded account on every trading day and measure how
    often it gets blown, why, and how long it survives. Also the highest balance peak
    reached over the whole history (the withdrawal ceiling)."""
    if daily.empty:
        return {"n_starts": 0}
    fr = replace(rules, profit_target_pct=None)  # survive, no target
    starts = [i for i in range(len(daily)) if daily["traded"].iloc[i]] or list(range(len(daily)))
    n = len(starts)
    reasons = Counter()
    blowup_days = []
    blowups = 0
    for i in starts:
        o = _simulate(daily, i, fr)
        if o["outcome"] == "pass":          # survived the whole remaining span
            continue
        blowups += 1
        reasons[o["outcome"]] += 1
        blowup_days.append(o["end"] - i + 1)
    base0 = daily["r_open"].iloc[0]
    peak_r = float(daily["r_max"].max() / base0) if base0 else 1.0
    return {
        "n_starts": n,
        "blowup_count": blowups,
        "blowup_rate": (blowups / n) if n else None,
        "survive_rate": (1 - blowups / n) if n else None,
        "blowup_reasons_pct": {k: (reasons.get(k, 0) / n * 100 if n else 0.0)
                               for k in ("fail_daily", "fail_total", "fail_trailing")},
        "median_days_to_blowup": float(np.median(blowup_days)) if blowup_days else None,
        "peak_balance": account_size * peak_r,
        "peak_profit": account_size * (peak_r - 1.0),
        "peak_pct": (peak_r - 1.0) * 100.0,
    }


def _chained_pass_rate(daily, p1: PropRules, p2: PropRules) -> float | None:
    """Combined: pass Phase 1 by some day, then pass Phase 2 starting the next day."""
    if daily.empty:
        return None
    starts = [i for i in range(len(daily)) if daily["traded"].iloc[i]] or list(range(len(daily)))
    n = len(starts)
    if not n:
        return None
    combined = 0
    for i in starts:
        r1 = _simulate(daily, i, p1)
        if r1["outcome"] != "pass":
            continue
        nxt = r1["end"] + 1
        if nxt >= len(daily):
            continue
        if _simulate(daily, nxt, p2)["outcome"] == "pass":
            combined += 1
    return combined / n


# --------------------------------------------------------------------------- #
def trade_rule_violations(trades: pd.DataFrame, rules: PropRules) -> dict:
    """Per-trade rule checks an equity curve can't see: weekend holding and a missing
    stop. Returns counts + ok flags (only meaningful when the rule is enabled)."""
    out = {
        "weekend_holds": 0, "no_stop": 0,
        "weekend_ok": True, "stop_ok": True,
        "total_trades": int(0 if trades is None else len(trades)),
    }
    if trades is None or trades.empty:
        return out
    if rules.forbid_weekend_holding and {"entry_time", "exit_time"}.issubset(trades.columns):
        ent = pd.to_datetime(trades["entry_time"], errors="coerce")
        ext = pd.to_datetime(trades["exit_time"], errors="coerce")
        # A hold spans a weekend if a Saturday falls in (entry, exit]: floor days and
        # compare ISO weeks, or simply check the span covers >= one Sat/Sun.
        span_days = (ext - ent).dt.total_seconds() / 86400.0
        crosses = ((ent.dt.weekday + span_days) >= (5 - ent.dt.weekday).where(ent.dt.weekday <= 4, 0)) & (span_days >= 1)
        # Robust check: any Saturday between entry and exit.
        wk = ((ext.dt.isocalendar().week != ent.dt.isocalendar().week) | (ext.dt.year != ent.dt.year)) & ext.notna() & ent.notna()
        out["weekend_holds"] = int((wk | (crosses.fillna(False))).sum())
        out["weekend_ok"] = out["weekend_holds"] == 0
    if rules.require_stop_loss and "stop_price" in trades.columns:
        sp = pd.to_numeric(trades["stop_price"], errors="coerce")
        out["no_stop"] = int(sp.isna().sum())
        out["stop_ok"] = out["no_stop"] == 0
    return out


def _apply_overrides(rules: PropRules, ov: dict | None) -> PropRules:
    """Return a copy of `rules` with any non-None override fields applied (custom desk)."""
    if not ov:
        return rules
    g = lambda k, d: ov[k] if ov.get(k) is not None else d
    return PropRules(
        name=ov.get("name") or rules.name,
        profit_target_pct=g("profit_target_pct", rules.profit_target_pct),
        max_daily_loss_pct=g("max_daily_loss_pct", rules.max_daily_loss_pct),
        max_total_loss_pct=g("max_total_loss_pct", rules.max_total_loss_pct),
        min_trading_days=g("min_trading_days", rules.min_trading_days),
        max_days=g("max_days", rules.max_days),
        trailing_dd_pct=g("trailing_dd_pct", rules.trailing_dd_pct),
        trailing_mode=g("trailing_mode", rules.trailing_mode),
        trailing_basis=g("trailing_basis", rules.trailing_basis),
        trailing_locks_at_initial=g("trailing_locks_at_initial", rules.trailing_locks_at_initial),
        max_best_day_pct=g("max_best_day_pct", rules.max_best_day_pct),
        forbid_weekend_holding=g("forbid_weekend_holding", rules.forbid_weekend_holding),
        require_stop_loss=g("require_stop_loss", rules.require_stop_loss),
    )


def evaluate(equity_curve: pd.DataFrame, trades: pd.DataFrame, initial_capital: float,
             preset: str = "ftmo_challenge", account_size: float = 100_000.0,
             rules_override: dict | None = None) -> dict:
    """Full prop-firm scorecard for one backtest. `preset` keys: PRESETS.
    `rules_override` (any subset of PropRules fields) overrides the preset for a
    custom desk — e.g. {"profit_target_pct": 0.08, "max_daily_loss_pct": 0.04}."""
    p1 = _apply_overrides(PRESETS.get(preset, FTMO_CHALLENGE), rules_override)
    # Phase 2 keeps the Verification target (5%) but inherits the account-wide loss
    # overrides (daily/total/max_days), which apply across phases.
    p2_base = FTMO_VERIFICATION if preset.startswith("ftmo") else p1
    loss_ov = ({k: rules_override[k] for k in ("max_daily_loss_pct", "max_total_loss_pct", "max_days")
                if k in rules_override} if rules_override else None)
    p2 = _apply_overrides(p2_base, loss_ov)
    daily = daily_frame(equity_curve, initial_capital, trades)

    single = evaluate_single(daily, p1)
    trade_rules = trade_rule_violations(trades, p1)
    # Fold the per-trade rule breaches into the single-pass checks/verdict.
    single.setdefault("checks", {})
    if p1.forbid_weekend_holding:
        single["checks"]["weekend_holding"] = bool(trade_rules["weekend_ok"])
        if not trade_rules["weekend_ok"] and single.get("binding_rule") is None:
            single["binding_rule"] = "weekend_holding"
        single["passed"] = bool(single.get("passed")) and trade_rules["weekend_ok"]
    if p1.require_stop_loss:
        single["checks"]["stop_loss"] = bool(trade_rules["stop_ok"])
        if not trade_rules["stop_ok"] and single.get("binding_rule") is None:
            single["binding_rule"] = "stop_loss"
        single["passed"] = bool(single.get("passed")) and trade_rules["stop_ok"]

    phase1 = rolling_pass_rate(daily, p1)
    phase2 = rolling_pass_rate(daily, p2)
    combined = _chained_pass_rate(daily, p1, p2)
    funded = evaluate_funded(daily, p1, account_size)

    rate = phase1.get("pass_rate")
    # Hard per-trade breaches cap the verdict (a real desk fails you regardless of rate).
    hard_breach = (p1.forbid_weekend_holding and not trade_rules["weekend_ok"]) or \
                  (p1.require_stop_loss and not trade_rules["stop_ok"])
    verdict = ("FAILS" if hard_breach else
               "APPROVES" if rate is not None and rate >= 0.5 else
               "RISKY" if rate is not None and rate >= 0.2 else
               "FAILS" if rate is not None else "no_data")
    tgt = p1.profit_target_pct or 0.0
    dollars = {
        "account_size": account_size,
        "profit_target": account_size * tgt,
        "daily_loss_limit": account_size * p1.max_daily_loss_pct,
        "total_loss_limit": account_size * p1.max_total_loss_pct,
        "worst_daily_dd": account_size * (single.get("worst_daily_dd_pct", 0.0) / 100.0),
        "worst_total_dd": account_size * (single.get("worst_total_dd_pct", 0.0) / 100.0),
    }
    return {
        "preset": p1.name,
        "preset_key": preset,
        "custom": bool(rules_override),
        "account_size": account_size,
        "rules": {
            "profit_target_pct": p1.profit_target_pct, "max_daily_loss_pct": p1.max_daily_loss_pct,
            "max_total_loss_pct": p1.max_total_loss_pct, "min_trading_days": p1.min_trading_days,
            "max_days": p1.max_days, "trailing_dd_pct": p1.trailing_dd_pct,
            "trailing_mode": p1.trailing_mode, "trailing_basis": p1.trailing_basis,
            "trailing_locks_at_initial": p1.trailing_locks_at_initial,
            "max_best_day_pct": p1.max_best_day_pct, "forbid_weekend_holding": p1.forbid_weekend_holding,
            "require_stop_loss": p1.require_stop_loss,
        },
        "phase2_rules": {
            "profit_target_pct": p2.profit_target_pct, "max_daily_loss_pct": p2.max_daily_loss_pct,
            "max_total_loss_pct": p2.max_total_loss_pct, "min_trading_days": p2.min_trading_days,
        },
        "dollars": dollars,
        "trade_rules": trade_rules,
        "days_evaluated": int(len(daily)),
        "single": single,
        "phase1": phase1,
        "phase2": phase2,
        "funded": funded,
        "combined_pass_rate": combined,
        "verdict": verdict,
    }
