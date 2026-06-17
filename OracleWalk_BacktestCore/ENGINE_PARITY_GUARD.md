# Engine Parity Guard — keep the execution engine untouchable

The execution engine (`backtest_core/core/engine.py`) is validated against MT5
trade-for-trade (see `EXECUTION_SPEC.md` and the parity-probe work). It must not
regress. Two layers protect it.

## 1. Fast armor (run on EVERY engine change)

```
python tests/test_engine_parity_armor.py        # no pytest needed; ~1s
```
Self-contained synthetic locks (9 tests). They guard, with teeth:
- `trailing_start_profit` survives the next-bar-open shift, and trailing only arms
  after the profit threshold (the CrossTendency trailing bug).
- `reject_invalid_pending` drops wrong-side resting orders (no phantom fills) but
  keeps valid ones.
- PnL scales with `contract_size`/`point` (multi-asset: US30/BTC/XAU).
- market entry = next bar open; opposite signal closes+reverses; SL/TP resolve at level.
- safety-critical config defaults are pinned.

Must print `9/9 passed`. A failure means you broke a proven behaviour.

## 2. Heavy gate (run before AND after any tick-fill / pending / entry-timing change)

```
python scripts/homolog_fvg_tick.py                                   # expect 8/8
python scripts/homolog_fvg_tick.py --start 2025-03-01 --end 2025-03-20 --leadin 2025-02-01   # expect 7/7
```
The gold-standard FVG tick parity vs the MT5 `FVG_SMA9_Body60_TickTouch` export.
Needs the EURUSD broker tick package; takes minutes. Must report `PARITY OK`.

## Hard-won rules (do NOT relearn these the hard way)

- **Never** change the pending-order tick trigger to test ask-for-buys / bid-for-sells.
  It looks correct but regresses FVG parity 8/8 → 7/8. Bid-for-all is empirically right.
- Order-validity rejection must use the **next bar's first tick / bar open** as the
  market reference, NOT the signal bar's close (close over-rejects valid orders).
- Pending-order probes/strategies need `entry_timing="signal_close"`; market ones use
  `next_bar_open`. Wrong timing silently drops the order's trigger.
- A "missing trade" is usually **data**, not the engine: check the dataset's date
  coverage and the asset's session hours (US30/XAU have no 00:00 bar — they open 01:00;
  probes keyed to hour 0 produce zero signals there, faithfully matching MT5).

## Multi-asset note

`scripts/run_parity_probes.py` auto-reads `symbol_spec.json` (point/contract). Verified
faithful on EURUSD (FX), US30 (index), BTCUSD (crypto), XAUUSD (metal) — including the
no-trade case. Use `--place-hour` (FX=0; index/metal=1) and `--dist-mult` per asset; the
MT5 EA inputs must match.
