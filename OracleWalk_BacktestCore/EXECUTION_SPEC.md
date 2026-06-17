# EXECUTION_SPEC — BacktestCore ⇄ MT5 execution contract

This is the **canonical, strategy-agnostic** description of how the BacktestCore
engine turns *signals* into *trades*, and how each mode maps onto an MT5 Strategy
Tester execution model. It is an **execution** contract: nothing here is specific to
the FVG strategy. FVG is only the first homologation case. Any future strategy that
emits the same signal columns gets the same execution guarantees.

> Scope rule (non-negotiable): the engine may change *how/when/at-what-price an order
> is placed, filled, and closed* — alignment, rounding, candle vs tick, costs,
> pending-order carry, anti-lookahead. It must **not** change a strategy's entry/exit
> *logic* (which setups, filters, levels). Setup logic lives in the strategy; the
> engine only executes what the strategy emits.

---

## 1. The two execution worlds (and their parity twins)

| MT5 Strategy Tester model            | BacktestCore mode                          | Fills decided by |
|--------------------------------------|--------------------------------------------|------------------|
| **Every tick based on real ticks**   | `execution_mode="tick"` (+ real ticks)     | per-tick bid/ask |
| **1 minute OHLC** / open prices only | `execution_mode="candle"`                  | per-bar OHLC     |

The engine homologates **each pair independently**: the tick world is compared
against an EA running *Every tick based on real ticks*; the candle world against an
EA running closed-candle order placement.

---

## 2. Signal contract (what a strategy emits)

`signals`: `datetime`, `signal` (`1` long / `-1` short / `0` none). Optional columns:

| column             | meaning |
|--------------------|---------|
| `order_type`       | `market` (default), `limit`, or `stop` |
| `entry_price`      | for limit/stop: the **trigger** price |
| `stop_price`       | protective stop level |
| `take_price`       | take-profit level |
| `size`             | lots (used when % risk sizing is off) |
| `risk`             | money risk (informational / RR) |
| `trailing_distance`| trailing-stop distance |
| `expiry_bars`      | **pending-order validity** in bars (carry window) |
| `gate_column`      | name of a data column the fill price is gated on (e.g. `sma60`) |
| `gate_side`        | `above` / `below` — required relation of fill price to `gate_column` |
| `comment`          | label carried onto the trade |

Unknown columns are ignored. Missing optional columns mean "feature off".

---

## 3. Order types & the carried pending-order book

`pending_order_book` (config, default **off**) decides whether `limit`/`stop`
signals are *carried*:

- **off** — legacy behaviour: a `limit`/`stop` order is only fillable on its own
  signal bar (same-bar trigger). A `market` order under `execution_model="realistic"`
  is fast-rejected if it carries an intrabar `entry_price` on the signal candle
  (anti-lookahead guard) — use `next_bar_open`, a carried pending order, or
  `execution_model="idealized"` for research.
- **on** — a `limit`/`stop` signal is **not** filled on its signal bar. It is placed
  in a **pending-order book** at *signal-bar close* and becomes fillable from the
  **next** bar/tick onward, until it fills or its `expiry_bars` validity elapses.
  This is the only honest way to reproduce a live EA that places an order when a
  candle closes and waits for price to come to it.

### Causality (anti-lookahead), invariant in both modes
1. A pending order is registered **after** the signal bar's own bar/ticks are
   processed → it can never fill on the bar that created it.
2. During a forming bar `k`, the **last closed bar is `k-1`**. Any indicator the gate
   reads (e.g. an SMA) uses index `k-1` — never the still-forming bar's own values.
3. One pending order fills per tick (tick mode) / per bar (candle mode), in
   placement order (oldest first).
4. `single_position_mode`: a touch while a position is open **consumes** (drops) the
   order without trading — matching the EA that drops a zone it can't act on.

---

## 4. Tick-touch fill semantics (`execution_mode="tick"`, pending book on)

Mirrors *Every tick based on real ticks*:

- **Trigger detection** uses the **bid travel range** between consecutive ticks:
  `lo = min(prev_bid, bid)`, `hi = max(prev_bid, bid)`; touched if
  `lo ≤ trigger ≤ hi`. This catches a level the bid *jumped over* between ticks.
- The inter-tick baseline **resets at each bar boundary** (first tick of a bar has
  `prev_bid = bid`), matching the EA clearing its last-bid state on a new bar.
- **Gate** is evaluated at the firing tick: `bid (gate_side) data[gate_column][k-1]`
  — current bid vs the **last closed bar's** indicator value.
- **Fill price** = the trigger, then routed through the normal execution-price model:
  long fills at `trigger + tick_spread` (≈ ask), short at `trigger` (≈ bid). With a
  real tick spread this reproduces the EA's *market* fill at touch; with spread off
  it equals the mid.

## 5. Candle fill semantics (`execution_mode="candle"`, pending book on)

Mirrors closed-candle order placement:

- **Trigger detection**: the bar crosses the level — limit long `low ≤ trigger`,
  limit short `high ≥ trigger` (stop is the mirror).
- **Gate** uses the **fill bar's own** close vs the fill bar's `gate_column`
  (closed-candle semantics).
- At most one pending order fills per bar.

### Intrabar SL/TP ordering (`intrabar_mode`)

When both SL and TP sit inside the same candle and there are no ticks to
disambiguate, `intrabar_mode` decides which is hit first:

| mode            | rule |
|-----------------|------|
| `conservative`  | **SL first** (pessimistic) — the safe default |
| `optimistic`    | TP first |
| `mt5_like_ohlc` | infer from the candle body: bull `O→L→H→C`, bear `O→H→L→C`; SL-first iff `(close≥open) == is_long` |

`mt5_like_ohlc` truth table — long/bull→SL, long/bear→TP, short/bull→TP,
short/bear→SL. Tick mode never hits the both-inside branch (high==low), so this is a
candle-world knob only.

## 6. Stop-loss / take-profit

Checked every tick (tick mode) / every bar (candle mode), **SL before TP**
(conservative) when both are inside the same bar/tick range:

- **Long**: SL when `bid ≤ stop`, TP when `bid ≥ take`; exit recorded at the level.
- **Short**: SL when `ask (=bid+spread) ≥ stop`, TP when `ask ≤ take`.

This matches MT5 triggering a buy's SL/TP on bid and a sell's on ask.

---

## 7. Cost modes

Selected via engine config; orthogonal to execution mode:

| mode            | spread | commission | swap | use |
|-----------------|--------|------------|------|-----|
| **COSTS_OFF**       | off (`use_spread=False`, tick spread still applied as it is a market property) | 0 | 0 | isolate execution logic from costs |
| **COSTS_REALISTIC** | real | broker `commission_per_lot` | broker swaps | honest performance |
| **MT5_PARITY**      | real (tick ask−bid) | broker | broker, with `triple_swap_weekday` | bit-for-bit vs MT5 |

`fixed_lot_audit`: set `risk_per_trade_pct=0` and `fixed_lot=L` to remove
position-sizing as a source of divergence when auditing prices/timing.

These presets are first-class in `backtest_core/core/exec_modes.py`:
`apply_cost_mode(base, "COSTS_OFF"|"COSTS_REALISTIC"|"MT5_PARITY")`,
`apply_fixed_lot_audit(base, lots)`, and the one-shot
`build_exec_config(base, cost_mode=..., fixed_lot=...)`. They only touch the cost
surface / sizing — never strategy params or execution mode.

---

## 8. Homologation results (FVG SMA9 + body 0.6, EURUSD H1)

Via `scripts/parity_compare.py`, costs off, fixed lot.

**Tick world** — Python (`emit_pending_orders=True`, `pending_order_book=True`, tick
mode) vs the MT5 `FVG_SMA9_Body60_TickTouch` EA:

| window               | py trades | mt5 trades | paired within tol | max entry Δ | max exit Δ | max exit-time Δ |
|----------------------|-----------|------------|-------------------|-------------|------------|-----------------|
| 2026-05-01 .. 05-19  | 8         | 8          | **8/8**           | 0.00004     | 0.00002    | 9 s             |
| 2025-03-01 .. 03-20  | 7         | 7          | **7/7**           | 0.000035    | 0.0001     | 0 s             |

**Candle world** — Python (classic touch-bar signal, candle mode,
`entry_timing="next_bar_open"`, `intrabar_mode="mt5_like_ohlc"`) vs the MT5
`FVG_SMA9_BacktestCore` EA (next-bar-open market entry, tick-resolved exits):

| window               | py trades | mt5 trades | paired within tol | max entry Δ | max exit Δ | exit bar |
|----------------------|-----------|------------|-------------------|-------------|------------|----------|
| 2026-05-01 .. 05-19  | 7         | 7          | **7/7**           | 0.00001     | **0.0**    | same     |

In the candle world every entry lands on the **same next-bar open**, every exit
**price is identical**, and exits fall in the **same bar** (Python stamps the bar
time, MT5 the intrabar tick). Entry Δ is the spread (Python COSTS_OFF enters at the
open mid, MT5 at open+spread).

**Conclusion**: with the carried pending-order book (tick) and `mt5_like_ohlc`
intrabar ordering (candle), BacktestCore reproduces both MT5 EAs **trade-for-trade**
— same count, same entry timing, same directions, same exit reasons, same exit
prices. Residual deltas (≤ ~1 pip; a few seconds on some tick exits; bar-granularity
on candle exit timestamps) are explained entirely by MT5's 5-digit rounding and
tick-vs-bar stamping — not by any logic difference.

The originally reported gap (Python very positive vs MT5 near-zero on the "same"
strategy) was an **execution-model** mismatch (batch/candle/next-bar entry vs
live tick-touch limit placement), now resolved at the engine level.

---

## 9. Reproduce

```bash
# 1) generate Python tick trades for a window
python /tmp/homolog_tick.py                 # window + leadin set inside

# 2) compare against the MT5 export and emit artifacts
python scripts/parity_compare.py \
  --py  reports/parity/python_tick_trades.csv \
  --mt5 ".../Common/Files/FVG_SMA9_Body60_TickTouch_trades.csv" \
  --out reports/parity --start 2026-05-01 --end 2026-05-19 \
  --price-tol 0.00010 --time-tol 120
# -> reports/parity/comparison_report.csv, comparison_summary.md (first divergence)
```

The harness is strategy-agnostic: point it at any BacktestCore trade CSV and any MT5
trade CSV with the canonical schema.
