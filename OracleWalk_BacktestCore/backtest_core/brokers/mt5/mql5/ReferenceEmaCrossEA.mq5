//+------------------------------------------------------------------+
//| ReferenceEmaCrossEA.mq5                                          |
//| MT5 reference EA for validating BacktestCore's EMA Crossover.    |
//|                                                                  |
//| Goal: reproduce, as faithfully as possible, the logic of        |
//|   backtest_core/strategies/examples/ema_cross.py                |
//| so the MT5 Strategy Tester result can be compared trade-by-trade |
//| against BacktestCore (see scripts/compare_mt5_trades.py).        |
//|                                                                  |
//| Faithfulness notes (READ THIS):                                 |
//|  - EMA is computed manually with alpha = 2/(period+1), seeded    |
//|    at the OLDEST available bar with that bar's close. This       |
//|    matches pandas ewm(span=period, adjust=False). It does NOT    |
//|    use iMA, whose EMA is seeded with an SMA and would diverge    |
//|    during warmup.                                                |
//|  - ATR is computed as a SIMPLE moving average of True Range      |
//|    (TR.rolling(period).mean()). It does NOT use iATR, which      |
//|    applies Wilder/RMA smoothing and would place SL/TP at         |
//|    different distances.                                          |
//|  - The signal is evaluated on the just-closed bar (shift 1).     |
//|    A bullish cross = fast[1] > slow[1] AND fast[2] <= slow[2].   |
//|  - SL/TP levels are derived from the signal bar's close[1] and   |
//|    atr[1], exactly like ema_cross.py, NOT from the actual fill.  |
//|                                                                  |
//| Known, expected divergence vs BacktestCore (documented, not     |
//| hidden): BacktestCore fills at the CLOSE of the signal bar,      |
//| while this EA fills at MARKET on the OPEN of the next bar. For   |
//| continuous FX these prices are very close; the residual gap is   |
//| explained in docs/mt5_validation.md.                            |
//|                                                                  |
//| Install: MQL5/Experts/ReferenceEmaCrossEA.mq5 -> compile -> run  |
//| in the Strategy Tester. A trades CSV is written on test end to   |
//| <Files>/ (or Common/Files) with the schema expected by the      |
//| comparator.                                                      |
//+------------------------------------------------------------------+
#property strict
#property description "BacktestCore EMA Crossover reference EA for MT5 validation"

#include <Trade/Trade.mqh>

input int    FastPeriod      = 12;        // EMA fast period
input int    SlowPeriod      = 36;        // EMA slow period
input int    AtrPeriod       = 14;        // ATR period (simple mean of TR)
input double StopAtr         = 1.5;       // SL distance in ATR units (0 = no SL)
input double TakeAtr         = 3.0;       // TP distance in ATR units (0 = no TP)
input double Lots            = 0.10;      // Fixed lot size
input bool   CloseOnOpposite = true;      // Close (and reverse) on opposite cross
input long   MagicNumber     = 990011;    // EA magic number
input string TradesCsvName   = "ReferenceEmaCrossEA_trades.csv"; // Output CSV
input bool   UseCommonFiles  = true;      // true = Common/Files (visible after a tester run)

CTrade   trade;
int      g_warmup = 0;          // bars needed before signals are valid
datetime g_last_bar_time = 0;   // new-bar detector

// Diagnostic: log EVERY detected crossover, whether or not it became a trade.
datetime g_sig_time[];          // signal bar time (the just-closed bar)
int      g_sig_dir[];           // +1 bullish, -1 bearish
int      g_sig_action[];        // 0=none(same dir), 1=open, 2=reverse, 3=blocked
int      g_sig_retcode[];       // order retcode (0 if no order sent)

void LogSignal(datetime t, int dir, int action, int retcode)
{
   int n = ArraySize(g_sig_time);
   ArrayResize(g_sig_time, n + 1);
   ArrayResize(g_sig_dir, n + 1);
   ArrayResize(g_sig_action, n + 1);
   ArrayResize(g_sig_retcode, n + 1);
   g_sig_time[n] = t; g_sig_dir[n] = dir; g_sig_action[n] = action; g_sig_retcode[n] = retcode;
}

// Pending order kept alive across ticks when the broker rejects at the daily
// rollover (retcode 10018, market closed). The market reopens seconds later, so
// a real EA simply retries — matching reality and converging with BacktestCore.
int    g_pending_dir = 0;        // 0 = none, +1/-1 = target side to (re)try
double g_pending_sl  = 0.0;
double g_pending_tp  = 0.0;

//+------------------------------------------------------------------+
int OnInit()
{
   if(FastPeriod < 1 || SlowPeriod < 1 || AtrPeriod < 1)
   {
      Print("Invalid period inputs.");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(FastPeriod >= SlowPeriod)
      Print("WARNING: FastPeriod >= SlowPeriod; crossovers may be unusual.");

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetTypeFillingBySymbol(_Symbol);

   // Need enough bars for the slowest EMA to stabilise plus ATR/2-bar lookback.
   g_warmup = MathMax(SlowPeriod, AtrPeriod) + 2;
   g_last_bar_time = 0;
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Compute EMA at a given shift, matching pandas adjust=False.      |
//| shift 0 = current forming bar, 1 = last closed bar, ...          |
//| Seeds at the oldest available bar with its close.               |
//+------------------------------------------------------------------+
double EmaAtShift(const double &close_series[], int total, int period, int shift)
{
   // close_series is as-series: index 0 = current bar, 'shift' = target bar,
   // total-1 = oldest bar. Build the EMA from the oldest bar forward to 'shift'.
   double alpha = 2.0 / (period + 1.0);
   int oldest = total - 1;            // as-series index of the oldest bar
   double ema = close_series[oldest]; // seed with the oldest close (adjust=False)
   for(int idx = oldest - 1; idx >= shift; idx--)
   {
      double price = close_series[idx];
      ema = alpha * price + (1.0 - alpha) * ema;
   }
   return ema;
}

//+------------------------------------------------------------------+
//| ATR as a simple mean of True Range over 'period' bars ending at  |
//| 'shift'. Matches TR.rolling(period).mean() in BacktestCore.      |
//+------------------------------------------------------------------+
double AtrSmaAtShift(const double &high[], const double &low[], const double &close[],
                     int total, int period, int shift)
{
   // Need bars shift .. shift+period-1, and one prior close for TR.
   if(shift + period >= total)
      return 0.0;
   double sum = 0.0;
   for(int k = 0; k < period; k++)
   {
      int i = shift + k;             // as-series index
      double tr1 = high[i] - low[i];
      double tr2 = MathAbs(high[i] - close[i + 1]);
      double tr3 = MathAbs(low[i]  - close[i + 1]);
      double tr  = MathMax(tr1, MathMax(tr2, tr3));
      sum += tr;
   }
   return sum / period;
}

//+------------------------------------------------------------------+
bool HasOpenPosition(int &dir_out)
{
   dir_out = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      long ptype = PositionGetInteger(POSITION_TYPE);
      dir_out = (ptype == POSITION_TYPE_BUY) ? 1 : -1;
      return true;
   }
   return false;
}

void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      trade.PositionClose(ticket);
   }
}

//+------------------------------------------------------------------+
//| Make the net position equal 'dir': close any opposite first, then |
//| open 'dir'. Returns true only when the target is achieved.        |
//+------------------------------------------------------------------+
bool EnsureTarget(int dir, double sl, double tp)
{
   int cur = 0;
   bool has = HasOpenPosition(cur);
   if(has && cur == dir)
      return true;                  // already in the target direction
   if(has)
   {
      CloseAllPositions();
      if(HasOpenPosition(cur))
         return false;              // close rejected (e.g. market closed): retry later
   }
   bool ok = (dir > 0)
             ? trade.Buy(Lots, _Symbol, 0.0, sl, tp, "ema_cross")
             : trade.Sell(Lots, _Symbol, 0.0, sl, tp, "ema_cross");
   return ok && trade.ResultRetcode() == TRADE_RETCODE_DONE;
}

//+------------------------------------------------------------------+
void OnTick()
{
   // Retry a reversal that the broker rejected at the rollover instant.
   if(g_pending_dir != 0)
   {
      if(EnsureTarget(g_pending_dir, g_pending_sl, g_pending_tp))
         g_pending_dir = 0;         // filled on a later tick — converged
   }

   // Act once per newly closed bar.
   datetime current_bar = (datetime)iTime(_Symbol, _Period, 0);
   if(current_bar == g_last_bar_time)
      return;
   g_last_bar_time = current_bar;

   int total = Bars(_Symbol, _Period);
   if(total < g_warmup + 2)
      return;

   // Pull as-series buffers.
   double close[], high[], low[];
   ArraySetAsSeries(close, true);
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   int want = total;
   if(CopyClose(_Symbol, _Period, 0, want, close) <= 0) return;
   if(CopyHigh(_Symbol, _Period, 0, want, high) <= 0) return;
   if(CopyLow(_Symbol, _Period, 0, want, low) <= 0) return;
   int got = ArraySize(close);

   double fast1 = EmaAtShift(close, got, FastPeriod, 1);
   double slow1 = EmaAtShift(close, got, SlowPeriod, 1);
   double fast2 = EmaAtShift(close, got, FastPeriod, 2);
   double slow2 = EmaAtShift(close, got, SlowPeriod, 2);
   double atr1  = AtrSmaAtShift(high, low, close, got, AtrPeriod, 1);

   bool bullish_cross = (fast2 <= slow2) && (fast1 > slow1);
   bool bearish_cross = (fast2 >= slow2) && (fast1 < slow1);
   if(!bullish_cross && !bearish_cross)
      return;

   int new_dir = bullish_cross ? 1 : -1;
   double signal_close = close[1]; // close of the just-closed signal bar

   int open_dir = 0;
   bool has_pos = HasOpenPosition(open_dir);
   int action = has_pos ? 2 : 1;        // 2=reverse, 1=open

   // Same direction: nothing to do.
   if(has_pos && open_dir == new_dir)
   {
      g_pending_dir = 0;
      LogSignal(current_bar, new_dir, 0, 0);      // 0 = same dir, no action
      return;
   }
   // Opposite signal but reversing is disabled.
   if(has_pos && !CloseOnOpposite)
   {
      LogSignal(current_bar, new_dir, 3, 0);      // 3 = blocked (no reverse)
      return;
   }

   // Compute SL/TP from the signal bar's close and ATR (like ema_cross.py).
   double sl = 0.0, tp = 0.0;
   if(StopAtr > 0.0 && atr1 > 0.0)
      sl = (new_dir > 0) ? signal_close - StopAtr * atr1
                         : signal_close + StopAtr * atr1;
   if(TakeAtr > 0.0 && atr1 > 0.0)
      tp = (new_dir > 0) ? signal_close + TakeAtr * atr1
                         : signal_close - TakeAtr * atr1;

   bool ok = EnsureTarget(new_dir, sl, tp);
   int retcode = (int)trade.ResultRetcode();
   LogSignal(current_bar, new_dir, action, retcode);
   if(ok)
   {
      g_pending_dir = 0;
   }
   else
   {
      // Rejected (typically rollover, retcode 10018): keep it and retry on the
      // next tick when the market reopens.
      g_pending_dir = new_dir;
      g_pending_sl  = sl;
      g_pending_tp  = tp;
      PrintFormat("Order deferred dir=%d retcode=%d (%s) — will retry",
                  new_dir, retcode, trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| On test/EA end: dump closed round-trip trades from history.      |
//| One row per position id (works for hedging accounts).            |
//| Schema: ticket,side,entry_time,entry_price,exit_time,exit_price, |
//|         lots,pnl,commission,swap,reason                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(!HistorySelect(0, TimeCurrent()))
   {
      Print("HistorySelect failed; no trades CSV written.");
      return;
   }

   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI;
   if(UseCommonFiles) flags |= FILE_COMMON;
   int h = FileOpen(TradesCsvName, flags, ',');
   if(h == INVALID_HANDLE)
   {
      Print("Failed to open trades CSV: ", TradesCsvName, " err=", GetLastError());
      return;
   }
   FileWrite(h, "ticket", "side", "entry_time", "entry_price",
             "exit_time", "exit_price", "lots", "pnl", "commission", "swap", "reason");

   // Collect unique position ids in chronological order of their entry deal.
   int total_deals = HistoryDealsTotal();
   long pos_ids[];
   ArrayResize(pos_ids, 0);

   for(int i = 0; i < total_deals; i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != MagicNumber) continue;
      long entry_type = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry_type != DEAL_ENTRY_IN) continue;
      long pid = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      int n = ArraySize(pos_ids);
      ArrayResize(pos_ids, n + 1);
      pos_ids[n] = pid;
   }

   int rows = 0;
   for(int p = 0; p < ArraySize(pos_ids); p++)
   {
      long pid = pos_ids[p];
      datetime entry_time = 0, exit_time = 0;
      double entry_price = 0.0, exit_price = 0.0, lots = 0.0;
      double pnl = 0.0, commission = 0.0, swap = 0.0;
      int side = 0;
      string reason = "signal";
      bool has_exit = false;

      for(int i = 0; i < total_deals; i++)
      {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0) continue;
         if(HistoryDealGetInteger(deal, DEAL_POSITION_ID) != pid) continue;
         if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;

         long entry_type = HistoryDealGetInteger(deal, DEAL_ENTRY);
         double d_price  = HistoryDealGetDouble(deal, DEAL_PRICE);
         double d_vol    = HistoryDealGetDouble(deal, DEAL_VOLUME);
         double d_profit = HistoryDealGetDouble(deal, DEAL_PROFIT);
         double d_comm   = HistoryDealGetDouble(deal, DEAL_COMMISSION);
         double d_swap   = HistoryDealGetDouble(deal, DEAL_SWAP);
         datetime d_time = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
         long d_type     = HistoryDealGetInteger(deal, DEAL_TYPE);

         commission += d_comm;
         swap       += d_swap;
         pnl        += d_profit;

         if(entry_type == DEAL_ENTRY_IN)
         {
            entry_time  = d_time;
            entry_price = d_price;
            lots        = d_vol;
            side        = (d_type == DEAL_TYPE_BUY) ? 1 : -1;
         }
         else // DEAL_ENTRY_OUT or OUT_BY
         {
            exit_time  = d_time;
            exit_price = d_price;
            has_exit   = true;
            long dr = HistoryDealGetInteger(deal, DEAL_REASON);
            if(dr == DEAL_REASON_SL)      reason = "sl";
            else if(dr == DEAL_REASON_TP) reason = "tp";
            else if(dr == DEAL_REASON_SO) reason = "stop_out";
            else                          reason = "signal";
         }
      }

      // Include swap/commission in the comparable net pnl.
      double net_pnl = pnl + swap + commission;

      FileWrite(h,
         IntegerToString(pid),
         (side > 0 ? "long" : "short"),
         TimeToString(entry_time, TIME_DATE | TIME_SECONDS),
         DoubleToString(entry_price, _Digits),
         (has_exit ? TimeToString(exit_time, TIME_DATE | TIME_SECONDS) : ""),
         (has_exit ? DoubleToString(exit_price, _Digits) : ""),
         DoubleToString(lots, 2),
         DoubleToString(net_pnl, 2),
         DoubleToString(commission, 2),
         DoubleToString(swap, 2),
         reason);
      rows++;
   }

   FileClose(h);
   string base = UseCommonFiles
                 ? TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\"
                 : TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   PrintFormat("ReferenceEmaCrossEA: wrote %d trades to:", rows);
   Print("  ", base, TradesCsvName);

   // Diagnostic signals log: every detected crossover and what happened to it.
   string sig_name = "ReferenceEmaCrossEA_signals.csv";
   int sh = FileOpen(sig_name, flags, ',');
   if(sh != INVALID_HANDLE)
   {
      FileWrite(sh, "signal_bar_time", "dir", "action", "retcode");
      int ns = ArraySize(g_sig_time);
      for(int i = 0; i < ns; i++)
      {
         string act = (g_sig_action[i] == 0) ? "same_dir"
                    : (g_sig_action[i] == 1) ? "open"
                    : (g_sig_action[i] == 2) ? "reverse" : "blocked";
         FileWrite(sh,
            TimeToString(g_sig_time[i], TIME_DATE | TIME_SECONDS),
            (g_sig_dir[i] > 0 ? "long" : "short"),
            act,
            IntegerToString(g_sig_retcode[i]));
      }
      FileClose(sh);
      PrintFormat("ReferenceEmaCrossEA: logged %d detected crossovers to %s%s",
                  ns, base, sig_name);
   }
}
//+------------------------------------------------------------------+
