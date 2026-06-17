# Parity Probes — Python ↔ MT5 engine validation

Five deterministic EAs that mirror `backtest_core/strategies/parity_probes.py`
trade-for-trade. They trigger only on exact, feed-robust quantities (datetime,
exact daily H/L/C, absolute time blocks) — never smoothed indicators — so any
divergence between MT5 and the Python backtester is **the engine**, not indicator
math or sub-pip data noise.

| Probe | Mechanism under test | Order type | Magic |
|-------|----------------------|-----------|-------|
| P1 ClockFlip      | market entry, timing, opposite close, swap | market | 990401 |
| P2 DailyBreakout  | STOP pending order, intrabar SL/TP, expiry | stop   | 990402 |
| P3 DailyLimitFade | LIMIT pending order (tick-touch), expiry    | limit  | 990403 |
| P4 WeeklyTrailing | trailing stop + profit-activation threshold | market | 990404 |
| P5 NBarAlternator | dense reversals, cost accrual               | market | 990405 |

## Files
- `ParityProbeCommon.mqh` — shared helpers + trades-CSV writer. **Must sit in the
  same folder as the EAs** (`MQL5/Experts/`).
- `P1_ClockFlip.mq5` … `P5_NBarAlternator.mq5`

## How to run (per probe)
1. Copy all 6 files into `MQL5/Experts/` and compile each `.mq5` in MetaEditor.
2. Strategy Tester → EURUSD, **H1**, "Every tick" (or "Every tick based on real
   ticks" for the most honest fill), same date window you ran in Python.
3. Run. On finish the EA writes its trades CSV (e.g. `P2_DailyBreakout_trades.csv`)
   to the **common files** folder (`AppData/Roaming/MetaQuotes/Terminal/Common/Files/`).

## Python side (already generated)
```
python scripts/run_parity_probes.py \
  --data "data/broker_exports/FTMO Global Markets Ltd/EURUSD/H1/candles.csv" \
  --start 2025-01-01 --end 2026-01-01 --out reports/parity_probes
# add --costs to also test spread/commission/swap (phase 2)
```
Outputs `reports/parity_probes/<probe>_py_trades.csv`.

## Compare trade-by-trade
```
python scripts/parity_compare.py \
  --py  reports/parity_probes/p2_daily_breakout_py_trades.csv \
  --mt5 "<Common>/Files/P2_DailyBreakout_trades.csv" \
  --out reports/parity_probes/p2 \
  --price-tol 0.00010 --time-tol 3600
```
Reads `comparison_summary.md` for the headline + the FIRST divergence.

## Parity rules baked in (must hold on both sides)
- **entry_timing**: market probes (P1/P4/P5) = `next_bar_open`; pending probes
  (P2/P3) = `signal_close`. The Python runner already sets these per probe.
- **leverage 100** so a 0.10 lot fits margin.
- Costs OFF for the first pass (prove mechanics), then re-run with `--costs` and a
  matching MT5 symbol spec.
- Weekday inputs use MQL5's Sun=0..Sat=6 (Python Mon=0 → EA input 1). Defaults
  already converted.

## Multi-asset (beyond EURUSD)

The engine is asset-agnostic: it reads point/contract_size from the broker
`symbol_spec.json` and computes PnL at any scale (verified on US30.cash:
point=0.01, contract=1.0, price ~42000 — SL/TP/trailing/PnL all exact). To run a
new asset:

```
python scripts/run_parity_probes.py \
  --data "data/broker_exports/<broker>/<SYMBOL>/H1/candles.csv" \
  --place-hour <first session hour>  --dist-mult <scale> \
  --start ... --end ... --out reports/parity_probes_<symbol>
# US30.cash example: --place-hour 1 --dist-mult 50   (index opens 01:00; point=0.01)
```

`--place-hour` must be an hour that EXISTS in the asset's session (US30 has no
00:00 bar). `--dist-mult` scales the point-based SL/TP/offset so they stay
meaningful at the asset's scale; the **MT5 EA inputs must use the same values**:
multiply InpSlPoints/InpTpPoints/InpBufferPoints/InpOffsetPoints/trailing inputs
by the same dist_mult and set InpPlaceHour/InpEntryHour to --place-hour. The EAs
already adapt point/lot via `_Point`/symbol info, so no recompile per asset.

For a trade-for-trade tick comparison the asset needs a `ticks.csv` export
(US30 currently has candles only — export its ticks via ExportBacktestPackage.mq5
to enable the apples-to-apples tick run).

## Known tuning points (expected, not bugs)
- Pending-order **expiry edge**: Python expires N bars after the signal bar; the
  EA sets `expiration = signalBarTime + N*PeriodSeconds`. A fill landing exactly on
  the expiry bar may differ by one bar — tune `InpExpiryBars` if the comparison
  flags it.
- P4 trailing/SL reference uses the **signal-bar close** on both sides; the entry
  itself is the next bar's open, so a sub-pip threshold offset (<0.001 pip) is
  expected and harmless.
