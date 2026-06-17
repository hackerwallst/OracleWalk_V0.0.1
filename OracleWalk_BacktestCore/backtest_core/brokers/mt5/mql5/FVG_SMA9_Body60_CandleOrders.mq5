//+------------------------------------------------------------------+
//| FVG_SMA9_Body60_CandleOrders.mq5                                 |
//| MT5 EA converted from backtest_core/strategies/fvg_imbalance.py. |
//|                                                                  |
//| Fidelity target: reproduce the Python FVG signal engine exactly, |
//| with only one intentional change requested by the owner: SMA=9.  |
//|                                                                  |
//| Python rules mirrored here:                                      |
//|  - Process closed candles chronologically from the test start.   |
//|  - First try to fill active FVGs at the 50% midpoint.            |
//|  - Then detect a new 3-candle FVG ending on the same bar.        |
//|  - Volume filter: displacement volume > mean of 5 prior candles. |
//|  - Body filter: displacement body must be large vs candle range. |
//|  - Trend filter at entry bar: BUY close>SMA9, SELL close<SMA9.   |
//|  - Stop behind the whole 3-candle structure.                     |
//|  - TP = entry midpoint +/- RR * risk.                            |
//|  - Expire unfilled FVGs after ExpiryBars candles.                |
//|                                                                  |
//| Execution: candle-close signals open market orders in MT5.        |
//+------------------------------------------------------------------+
#property strict
#property description "FVG SMA9 Body60 CandleOrders - BacktestCore signal execution"

#include <Trade/Trade.mqh>

enum ENUM_FVG_EXECUTION_MODE
{
   FVG_SIGNALS_ONLY = 0,
   FVG_MARKET_NEXT_BAR = 1,
   FVG_TICK_TOUCH = 2
};

input int                     InpSmaPeriod          = 9;       // Requested winning SMA period
input int                     InpVolLookback        = 5;       // Python default
input int                     InpExpiryBars         = 20;      // Python default
input double                  InpRiskReward         = 3.0;     // Python default
input double                  InpStopBufferPoints   = 0.0;     // Python default
input double                  InpPoint              = 0.00001; // Python default point
input double                  InpMinBodyRatio       = 0.6;     // New FVG filter: full body, little wick
input ENUM_FVG_EXECUTION_MODE InpExecutionMode      = FVG_MARKET_NEXT_BAR;
input bool                    InpTickTrendUsesPrice = true;    // true = current Bid vs SMA9 on tick touch
input bool                    InpSinglePositionMode = true;    // Matches config close_on_signal=never
input bool                    InpUseRiskPercent     = true;    // Match BacktestCore risk sizing when possible
input double                  InpRiskPercent        = 1.0;     // BacktestCore default/config
input double                  InpFixedLots          = 0.10;    // Used when risk sizing is disabled
input double                  InpContractSize       = 100000.0;// BacktestCore config
input long                    InpMagicNumber        = 990261;
input string                  InpSignalsCsvName     = "FVG_SMA9_Body60_CandleOrders_signals.csv";
input string                  InpTradesCsvName      = "FVG_SMA9_Body60_CandleOrders_trades.csv";
input bool                    InpUseCommonFiles     = true;

CTrade trade;

struct FvgZone
{
   int    direction;
   double mid;
   double stop;
   int    created_bar;
   int    expiry_bar;
};

datetime g_last_current_bar = 0;
bool     g_started = false;
double   g_last_bid = 0.0;
bool     g_have_last_bid = false;

datetime g_time[];
double   g_open[];
double   g_high[];
double   g_low[];
double   g_close[];
double   g_volume[];

FvgZone g_active[];

datetime g_sig_time[];
int      g_sig_bar[];
int      g_sig_dir[];
double   g_sig_entry[];
double   g_sig_stop[];
double   g_sig_take[];
double   g_sig_sma[];
int      g_sig_zone_bar[];
string   g_sig_comment[];
string   g_sig_action[];
int      g_sig_retcode[];

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpSmaPeriod < 1 || InpVolLookback < 1 || InpExpiryBars < 1 || InpRiskReward <= 0.0)
   {
      Print("Invalid FVG inputs.");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(InpContractSize <= 0.0)
   {
      Print("Invalid contract size.");
      return(INIT_PARAMETERS_INCORRECT);
   }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetTypeFillingBySymbol(_Symbol);

   g_last_current_bar = 0;
   g_started = false;
   g_last_bid = 0.0;
   g_have_last_bid = false;
   ArrayResize(g_time, 0);
   ArrayResize(g_open, 0);
   ArrayResize(g_high, 0);
   ArrayResize(g_low, 0);
   ArrayResize(g_close, 0);
   ArrayResize(g_volume, 0);
   ArrayResize(g_active, 0);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
double NormalizePrice(double price)
{
   return NormalizeDouble(price, _Digits);
}

bool BodyOk(double o, double h, double l, double c)
{
   if(InpMinBodyRatio <= 0.0)
      return true;
   double range = h - l;
   if(range <= 0.0)
      return false;
   return (MathAbs(c - o) / range) >= InpMinBodyRatio;
}

bool SmaAtIndex(int index, double &out)
{
   out = 0.0;
   if(index + 1 < InpSmaPeriod)
      return false;

   double sum = 0.0;
   for(int i = index - InpSmaPeriod + 1; i <= index; i++)
      sum += g_close[i];
   out = sum / InpSmaPeriod;
   return true;
}

bool VolumeAverageBefore(int index, double &out)
{
   out = 0.0;
   if(index - InpVolLookback < 0)
      return false;

   double sum = 0.0;
   for(int i = index - InpVolLookback; i < index; i++)
      sum += g_volume[i];
   out = sum / InpVolLookback;
   return true;
}

void AppendClosedBar(const MqlRates &bar)
{
   int n = ArraySize(g_time);
   ArrayResize(g_time, n + 1);
   ArrayResize(g_open, n + 1);
   ArrayResize(g_high, n + 1);
   ArrayResize(g_low, n + 1);
   ArrayResize(g_close, n + 1);
   ArrayResize(g_volume, n + 1);

   g_time[n] = bar.time;
   g_open[n] = bar.open;
   g_high[n] = bar.high;
   g_low[n] = bar.low;
   g_close[n] = bar.close;
   g_volume[n] = (double)bar.tick_volume;
}

void AddZone(int direction, double mid, double stop, int created_bar, int expiry_bar)
{
   int n = ArraySize(g_active);
   ArrayResize(g_active, n + 1);
   g_active[n].direction = direction;
   g_active[n].mid = mid;
   g_active[n].stop = stop;
   g_active[n].created_bar = created_bar;
   g_active[n].expiry_bar = expiry_bar;
}

bool HasOpenPosition(int &dir_out)
{
   dir_out = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      dir_out = (type == POSITION_TYPE_BUY) ? 1 : -1;
      return true;
   }
   return false;
}

int VolumeDigits(double step)
{
   int digits = 0;
   double scaled = step;
   while(digits < 8 && MathAbs(scaled - MathRound(scaled)) > 0.00000001)
   {
      scaled *= 10.0;
      digits++;
   }
   return digits;
}

double NormalizeLots(double lots)
{
   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = 0.01;

   lots = MathMax(min_lot, MathMin(max_lot, lots));
   lots = MathFloor(lots / step) * step;
   lots = MathMax(min_lot, lots);
   return NormalizeDouble(lots, VolumeDigits(step));
}

double LotsFromRisk(double entry_mid, double stop_price)
{
   if(!InpUseRiskPercent || InpRiskPercent <= 0.0)
      return NormalizeLots(InpFixedLots);

   double per_unit_risk = MathAbs(entry_mid - stop_price);
   double money_risk = AccountInfoDouble(ACCOUNT_BALANCE) * (InpRiskPercent / 100.0);
   double per_lot_risk = per_unit_risk * InpContractSize;
   if(per_lot_risk <= 0.0 || money_risk <= 0.0)
      return NormalizeLots(InpFixedLots);

   return NormalizeLots(money_risk / per_lot_risk);
}

void LogSignal(
   datetime signal_time,
   int bar_index,
   int direction,
   double entry_mid,
   double stop_price,
   double take_price,
   double sma_value,
   int zone_created_bar,
   string comment,
   string action,
   int retcode
)
{
   int n = ArraySize(g_sig_time);
   ArrayResize(g_sig_time, n + 1);
   ArrayResize(g_sig_bar, n + 1);
   ArrayResize(g_sig_dir, n + 1);
   ArrayResize(g_sig_entry, n + 1);
   ArrayResize(g_sig_stop, n + 1);
   ArrayResize(g_sig_take, n + 1);
   ArrayResize(g_sig_sma, n + 1);
   ArrayResize(g_sig_zone_bar, n + 1);
   ArrayResize(g_sig_comment, n + 1);
   ArrayResize(g_sig_action, n + 1);
   ArrayResize(g_sig_retcode, n + 1);

   g_sig_time[n] = signal_time;
   g_sig_bar[n] = bar_index;
   g_sig_dir[n] = direction;
   g_sig_entry[n] = entry_mid;
   g_sig_stop[n] = stop_price;
   g_sig_take[n] = take_price;
   g_sig_sma[n] = sma_value;
   g_sig_zone_bar[n] = zone_created_bar;
   g_sig_comment[n] = comment;
   g_sig_action[n] = action;
   g_sig_retcode[n] = retcode;
}

string ExecuteSignal(int direction, double entry_mid, double stop_price, double take_price, int &retcode)
{
   retcode = 0;
   if(InpExecutionMode == FVG_SIGNALS_ONLY)
      return "signal_only";

   int open_dir = 0;
   if(InpSinglePositionMode && HasOpenPosition(open_dir))
      return "blocked_position";

   double lots = LotsFromRisk(entry_mid, stop_price);
   double sl = NormalizePrice(stop_price);
   double tp = NormalizePrice(take_price);
   string comment = (direction > 0) ? "FVG BUY" : "FVG SELL";

   bool ok = false;
   if(direction > 0)
      ok = trade.Buy(lots, _Symbol, 0.0, sl, tp, comment);
   else
      ok = trade.Sell(lots, _Symbol, 0.0, sl, tp, comment);

   retcode = (int)trade.ResultRetcode();
   if(ok && retcode == TRADE_RETCODE_DONE)
      return (InpExecutionMode == FVG_TICK_TOUCH) ? "open_tick_touch" : "open_market_next_bar";

   PrintFormat("FVG order failed dir=%d lots=%s entry_mid=%s sl=%s tp=%s retcode=%d (%s)",
               direction,
               DoubleToString(lots, 2),
               DoubleToString(entry_mid, _Digits),
               DoubleToString(sl, _Digits),
               DoubleToString(tp, _Digits),
               retcode,
               trade.ResultRetcodeDescription());
   return "order_failed";
}

void FireSignalAt(datetime signal_time, int i, const FvgZone &zone, double sma_value)
{
   double risk = MathAbs(zone.mid - zone.stop);
   if(risk <= 0.0)
      return;

   double take = zone.mid + zone.direction * InpRiskReward * risk;
   string comment = (zone.direction > 0) ? "FVG BUY" : "FVG SELL";
   int retcode = 0;
   string action = ExecuteSignal(zone.direction, zone.mid, zone.stop, take, retcode);

   LogSignal(
      signal_time,
      i,
      zone.direction,
      zone.mid,
      zone.stop,
      take,
      sma_value,
      zone.created_bar,
      comment,
      action,
      retcode
   );
}

void FireSignal(int i, const FvgZone &zone, double sma_value)
{
   FireSignalAt(g_time[i], i, zone, sma_value);
}

void PruneExpiredZones(int bar_index)
{
   FvgZone still[];
   int keep = 0;
   ArrayResize(still, ArraySize(g_active));

   for(int z = 0; z < ArraySize(g_active); z++)
   {
      if(bar_index <= g_active[z].expiry_bar)
      {
         still[keep] = g_active[z];
         keep++;
      }
   }

   ArrayResize(g_active, keep);
   for(int k = 0; k < keep; k++)
      g_active[k] = still[k];
}

void ProcessCandleCloseFills(int i)
{
   double sma_value = 0.0;
   bool has_sma = SmaAtIndex(i, sma_value);

   FvgZone still[];
   int keep = 0;
   ArrayResize(still, ArraySize(g_active));
   bool fired = false;

   for(int z = 0; z < ArraySize(g_active); z++)
   {
      FvgZone zone = g_active[z];
      if(i > zone.expiry_bar)
         continue;

      bool touched = (g_low[i] <= zone.mid && zone.mid <= g_high[i]);
      bool trend_ok = has_sma && (
         (zone.direction > 0 && g_close[i] > sma_value) ||
         (zone.direction < 0 && g_close[i] < sma_value)
      );

      if(!fired && touched && trend_ok)
      {
         double risk = MathAbs(zone.mid - zone.stop);
         if(risk <= 0.0)
            continue;

         FireSignal(i, zone, sma_value);
         fired = true;
         continue;
      }

      still[keep] = zone;
      keep++;
   }

   ArrayResize(g_active, keep);
   for(int k = 0; k < keep; k++)
      g_active[k] = still[k];
}

void ProcessBar(int i)
{
   if(InpExecutionMode == FVG_TICK_TOUCH)
      PruneExpiredZones(i);
   else
      ProcessCandleCloseFills(i);

   if(i < 2)
      return;

   int displacement = i - 1;
   double vol_avg = 0.0;
   if(!VolumeAverageBefore(displacement, vol_avg))
      return;

   bool strong_vol = g_volume[displacement] > vol_avg;
   if(!strong_vol)
      return;

   if(!BodyOk(g_open[displacement], g_high[displacement], g_low[displacement], g_close[displacement]))
      return;

   if(g_high[i - 2] < g_low[i])
   {
      double gap_lo = g_high[i - 2];
      double gap_hi = g_low[i];
      double structure_low = MathMin(g_low[i - 2], MathMin(g_low[i - 1], g_low[i]));
      double stop = structure_low - InpStopBufferPoints * InpPoint;
      AddZone(+1, (gap_lo + gap_hi) / 2.0, stop, i, i + InpExpiryBars);
   }
   else if(g_low[i - 2] > g_high[i])
   {
      double gap_lo = g_high[i];
      double gap_hi = g_low[i - 2];
      double structure_high = MathMax(g_high[i - 2], MathMax(g_high[i - 1], g_high[i]));
      double stop = structure_high + InpStopBufferPoints * InpPoint;
      AddZone(-1, (gap_lo + gap_hi) / 2.0, stop, i, i + InpExpiryBars);
   }
}

void MonitorTickTouch()
{
   if(InpExecutionMode != FVG_TICK_TOUCH)
      return;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   double bid = tick.bid;
   if(bid <= 0.0)
      bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(bid <= 0.0)
      return;

   if(ArraySize(g_active) <= 0 || ArraySize(g_time) <= 0)
   {
      g_last_bid = bid;
      g_have_last_bid = true;
      return;
   }

   int i = ArraySize(g_time) - 1;
   double sma_value = 0.0;
   if(!SmaAtIndex(i, sma_value))
   {
      g_last_bid = bid;
      g_have_last_bid = true;
      return;
   }

   double from_bid = g_have_last_bid ? g_last_bid : bid;
   double lo = MathMin(from_bid, bid);
   double hi = MathMax(from_bid, bid);
   double trend_price = InpTickTrendUsesPrice ? bid : g_close[i];

   FvgZone still[];
   int keep = 0;
   bool fired = false;
   ArrayResize(still, ArraySize(g_active));

   for(int z = 0; z < ArraySize(g_active); z++)
   {
      FvgZone zone = g_active[z];
      if(i > zone.expiry_bar)
         continue;

      bool touched = (lo <= zone.mid && zone.mid <= hi);
      bool trend_ok = (
         (zone.direction > 0 && trend_price > sma_value) ||
         (zone.direction < 0 && trend_price < sma_value)
      );

      if(!fired && touched && trend_ok)
      {
         double risk = MathAbs(zone.mid - zone.stop);
         if(risk <= 0.0)
            continue;

         datetime signal_time = (datetime)tick.time;
         if(signal_time <= 0)
            signal_time = TimeCurrent();
         FireSignalAt(signal_time, i, zone, sma_value);
         fired = true;
         continue;
      }

      still[keep] = zone;
      keep++;
   }

   ArrayResize(g_active, keep);
   for(int k = 0; k < keep; k++)
      g_active[k] = still[k];

   g_last_bid = bid;
   g_have_last_bid = true;
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime current_bar = (datetime)iTime(_Symbol, _Period, 0);
   if(current_bar <= 0)
      return;

   // First tester/live bar is only the start marker. The first processed
   // closed candle is the one that closes after this EA has started, matching
   // a Python dataframe that begins at the selected backtest start.
   if(!g_started)
   {
      g_started = true;
      g_last_current_bar = current_bar;
      MonitorTickTouch();
      return;
   }

   if(current_bar != g_last_current_bar)
   {
      g_last_current_bar = current_bar;

      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int copied = CopyRates(_Symbol, _Period, 1, 1, rates);
      if(copied != 1)
         return;

      AppendClosedBar(rates[0]);
      int i = ArraySize(g_time) - 1;
      ProcessBar(i);
      g_have_last_bid = false;
   }

   MonitorTickTouch();
}

//+------------------------------------------------------------------+
void WriteSignalsCsv(int flags)
{
   int h = FileOpen(InpSignalsCsvName, flags, ',');
   if(h == INVALID_HANDLE)
   {
      Print("Failed to open signals CSV: ", InpSignalsCsvName, " err=", GetLastError());
      return;
   }

   FileWrite(h, "signal_time", "bar_index", "direction", "entry_mid", "stop_price",
             "take_price", "sma9", "zone_created_bar", "comment", "action", "retcode");

   for(int i = 0; i < ArraySize(g_sig_time); i++)
   {
      FileWrite(h,
         TimeToString(g_sig_time[i], TIME_DATE | TIME_SECONDS),
         IntegerToString(g_sig_bar[i]),
         (g_sig_dir[i] > 0 ? "long" : "short"),
         DoubleToString(g_sig_entry[i], _Digits),
         DoubleToString(g_sig_stop[i], _Digits),
         DoubleToString(g_sig_take[i], _Digits),
         DoubleToString(g_sig_sma[i], _Digits),
         IntegerToString(g_sig_zone_bar[i]),
         g_sig_comment[i],
         g_sig_action[i],
         IntegerToString(g_sig_retcode[i])
      );
   }

   FileClose(h);
}

void WriteTradesCsv(int flags)
{
   if(!HistorySelect(0, TimeCurrent()))
   {
      Print("HistorySelect failed; no trades CSV written.");
      return;
   }

   int h = FileOpen(InpTradesCsvName, flags, ',');
   if(h == INVALID_HANDLE)
   {
      Print("Failed to open trades CSV: ", InpTradesCsvName, " err=", GetLastError());
      return;
   }

   FileWrite(h, "ticket", "side", "entry_time", "entry_price",
             "exit_time", "exit_price", "lots", "pnl", "commission", "swap", "reason");

   int total_deals = HistoryDealsTotal();
   long pos_ids[];
   ArrayResize(pos_ids, 0);

   for(int i = 0; i < total_deals; i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
         continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;

      long pid = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      int n = ArraySize(pos_ids);
      ArrayResize(pos_ids, n + 1);
      pos_ids[n] = pid;
   }

   for(int p = 0; p < ArraySize(pos_ids); p++)
   {
      long pid = pos_ids[p];
      datetime entry_time = 0;
      datetime exit_time = 0;
      double entry_price = 0.0;
      double exit_price = 0.0;
      double lots = 0.0;
      double pnl = 0.0;
      double commission = 0.0;
      double swap = 0.0;
      int side = 0;
      bool has_exit = false;
      string reason = "signal";

      for(int i = 0; i < total_deals; i++)
      {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0)
            continue;
         if(HistoryDealGetInteger(deal, DEAL_POSITION_ID) != pid)
            continue;
         if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
            continue;
         if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber)
            continue;

         long entry_type = HistoryDealGetInteger(deal, DEAL_ENTRY);
         long deal_type = HistoryDealGetInteger(deal, DEAL_TYPE);
         double deal_price = HistoryDealGetDouble(deal, DEAL_PRICE);
         double deal_volume = HistoryDealGetDouble(deal, DEAL_VOLUME);
         datetime deal_time = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);

         pnl += HistoryDealGetDouble(deal, DEAL_PROFIT);
         commission += HistoryDealGetDouble(deal, DEAL_COMMISSION);
         swap += HistoryDealGetDouble(deal, DEAL_SWAP);

         if(entry_type == DEAL_ENTRY_IN)
         {
            entry_time = deal_time;
            entry_price = deal_price;
            lots = deal_volume;
            side = (deal_type == DEAL_TYPE_BUY) ? 1 : -1;
         }
         else
         {
            exit_time = deal_time;
            exit_price = deal_price;
            has_exit = true;
            long dr = HistoryDealGetInteger(deal, DEAL_REASON);
            if(dr == DEAL_REASON_SL)
               reason = "sl";
            else if(dr == DEAL_REASON_TP)
               reason = "tp";
            else if(dr == DEAL_REASON_SO)
               reason = "stop_out";
            else
               reason = "signal";
         }
      }

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
         reason
      );
   }

   FileClose(h);
}

void OnDeinit(const int reason)
{
   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;

   WriteSignalsCsv(flags);
   WriteTradesCsv(flags);

   string base = InpUseCommonFiles
                 ? TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\"
                 : TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   PrintFormat("FVG_SMA9_Body60_CandleOrders: wrote %d signals to:", ArraySize(g_sig_time));
   Print("  ", base, InpSignalsCsvName);
   Print("  ", base, InpTradesCsvName);
}
