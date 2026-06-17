# MT5 Validation Track

Goal: prove, with small auditable cases, where **BacktestCore** matches or
diverges from the **MetaTrader 5 Strategy Tester**. This track does not change
the BacktestCore engine — it builds an independent MT5 reference and compares
results trade by trade.

## Pieces

| Piece | Path |
| --- | --- |
| Reference EA (MQL5) | `backtest_core/brokers/mt5/mql5/ReferenceEmaCrossEA.mq5` |
| Data/spec exporter (existing) | `backtest_core/brokers/mt5/mql5/ExportBacktestPackage.mq5` |
| Trade comparator | `scripts/compare_mt5_trades.py` |
| Validation cases | `validation_cases/<case>/` |

The reference EA reproduces `backtest_core/strategies/examples/ema_cross.py`.

## Why the EA recomputes EMA and ATR by hand

BacktestCore and MT5's built-in indicators are **not** numerically identical, so
the EA computes both manually to remove that as a source of divergence:

- **EMA** — BacktestCore uses `pandas.ewm(span=period, adjust=False)`:
  `alpha = 2/(period+1)`, seeded at the first bar with that bar's close. MT5's
  `iMA(MODE_EMA)` seeds with an SMA of the first `period` values, so it differs
  during warmup. The EA replicates the pandas recursion.
- **ATR** — BacktestCore uses `TR.rolling(period).mean()`, a **simple** mean of
  True Range. MT5's `iATR` uses Wilder/RMA smoothing, which would change SL/TP
  distances. The EA computes the simple mean of TR instead.

With those matched, the only expected differences are **execution** effects.

## Expected, documented divergences (not hidden)

1. **Fill timing.** BacktestCore fills at the **close of the signal bar**. The
   EA fills at **market on the open of the next bar**. For continuous FX these
   prices are close; the residual is the close→next-open gap plus spread.
2. **Spread / bid-ask.** BacktestCore treats OHLC as bid and adds spread on the
   buy side. MT5 fills at the real ask/bid. Use the same spread source.
3. **Intrabar SL/TP ordering.** When SL and TP both sit inside one bar,
   BacktestCore (candle mode) assumes **SL first**. MT5 with *Every tick based
   on real ticks* resolves the true path and may hit TP first. This is the main
   structural difference and the reason we run MT5 in real-tick mode.
4. **Commission.** MT5 scripts cannot read account commission reliably, so
   `symbol_spec.json` leaves it null. Set `commission_per_lot` on both sides to
   the same value, or keep both at 0 to isolate the other effects.

## Step 1 — Export the data package from MT5

In MetaTrader 5, run `ExportBacktestPackage.mq5` (Scripts) on the target chart.
It writes `candles.csv`, `ticks.csv`, `symbol_spec.json`, `account_spec.json`,
`export_manifest.json`. Copy that folder into:

```
data/broker_exports/<Broker>/<Symbol>/<Timeframe>/
```

(The exporter now shows live progress on the chart and in the MT5 Experts log,
including estimated percentage, elapsed time, candles done and ticks written.
If tick export is slow, those updates tell you whether it is still advancing or
has likely stalled.)

(An EURUSD H4 FTMO package is already present and used by the first case.)

## Step 2 — Run the reference EA in the Strategy Tester

1. Copy `ReferenceEmaCrossEA.mq5` to `MQL5/Experts/` and compile it in
   MetaEditor (must compile with **0 errors**).
2. Open the Strategy Tester and set, identically to the BacktestCore run:
   - **Symbol**: same symbol (e.g. EURUSD).
   - **Timeframe**: same TF (e.g. H4).
   - **Date range**: the same interval as the exported candles
     (`export_manifest.json` → `first_bar_time` / `last_bar_time`).
   - **Modelling**: `Every tick based on real ticks`.
   - **Deposit**: same initial capital as the BacktestCore run (e.g. 10000).
   - **Leverage**: same as `account_spec.json` (e.g. 1:30).
   - **Inputs**: `FastPeriod`, `SlowPeriod`, `AtrPeriod`, `StopAtr`, `TakeAtr`,
     `Lots`, `CloseOnOpposite` — matching the BacktestCore config.
3. Run. On completion the EA writes its trades CSV to the terminal's
   `MQL5/Files/` (or `Common/Files/` if `UseCommonFiles=true`):

   ```
   ticket,side,entry_time,entry_price,exit_time,exit_price,lots,pnl,commission,swap,reason
   ```
4. Copy that CSV into the case folder as `mt5_trades.csv`.

## Step 3 — Generate the BacktestCore side

Each case ships a small reproducible generator. For the first case:

```bash
.venv/bin/python validation_cases/eurusd_h4_ema_cross/generate_backtestcore_trades.py
```

It writes `backtestcore_trades.csv` (and `backtestcore_run.json` with the exact
engine settings used).

## Step 4 — Compare

```bash
python scripts/compare_mt5_trades.py \
  --mt5 validation_cases/eurusd_h4_ema_cross/mt5_trades.csv \
  --bt  validation_cases/eurusd_h4_ema_cross/backtestcore_trades.csv \
  --price-tol 0.00002 \
  --time-tol-seconds 5 \
  --out validation_cases/eurusd_h4_ema_cross/comparison.json
```

The comparator prints (and saves to `comparison.json`):

- total trades per side, paired count;
- trades missing in MT5 and missing in BacktestCore;
- mean/max absolute entry-price, exit-price and PnL differences;
- a `divergences.csv` with the per-pair detail.

## How to read the result

- **Paired ≈ total on both sides** and **mean|Δ| within a few points** →
  engines agree; remaining gaps are the documented execution effects.
- **Missing trades** usually mean a signal/timing mismatch (fill-timing or an
  SL/TP that one side hit and the other did not).
- **Large PnL gaps with matched prices** point at commission/swap settings.

Every divergence should be traceable to one of the four documented effects
above. If it is not, that is a finding worth filing — do not paper over it.

## Cases

1. **`eurusd_h4_ema_cross`** — EURUSD H4 EMA Cross. Start with `StopAtr=0`,
   `TakeAtr=0` (no SL/TP) to isolate entry/exit timing, then repeat with
   `StopAtr=1.5`, `TakeAtr=3.0` to test intrabar SL/TP ordering.
2. EURUSD M1 mean reversion — only once the EMA-cross case is clean.
