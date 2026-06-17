//+------------------------------------------------------------------+
//| CrossTendency_V1_BacktestCore.mq5                                |
//| MT5 EA generated from backtest_core CrossTendencyV1Strategy.     |
//|                                                                  |
//| Fidelity target: reproduce the Python strategy exactly so that   |
//| trades can be compared 1:1 between BacktestCore and MT5.         |
//|                                                                  |
//| Python rules mirrored here:                                      |
//|  - Entry: EMA fast crosses EMA slow on CLOSED bar.               |
//|  - ATR filter: ATR(14) >= floor in points AND (optionally)       |
//|    ATR >= ATR_SMA(20) * multiplier.                              |
//|  - ADX filter: ADX(14) >= threshold.                             |
//|  - Stop: most recent confirmed DAILY pivot low/high.             |
//|    Daily pivots use left/right/search window on D1 bars.         |
//|  - No take profit. Exit by trailing or opposite signal.          |
//|  - Trailing: percentage of entry price, activates only after     |
//|    the trade reaches a minimum profit threshold.                 |
//|  - Opposite signal closes current position and opens new one.    |
//+------------------------------------------------------------------+
#property strict
#property description "CrossTendency V1 - BacktestCore conversion"
#property version "1.00"

#include <Trade/Trade.mqh>

//--- Inputs matching Python __init__ defaults exactly
input int    InpFastMaPeriod             = 20;      // EMA fast period
input int    InpSlowMaPeriod             = 50;      // EMA slow period
input int    InpAtrPeriod                = 14;      // ATR period
input bool   InpUseDynamicAtrFilter      = true;    // Use ATR > ATR_MA * mult filter
input int    InpAtrFilterMaPeriod        = 20;      // ATR SMA period for filter
input double InpAtrHighMultiplier        = 1.1;     // ATR must exceed MA * this
input double InpMinAtrPoints             = 100.0;   // Minimum ATR floor in points
input bool   InpUseAdxFilter             = true;    // Use ADX filter
input int    InpAdxPeriod                = 14;      // ADX period
input double InpAdxMinValue              = 25.0;    // ADX minimum threshold
input int    InpPivotLeftBars            = 20;      // Pivot detection: left bars (D1)
input int    InpPivotRightBars           = 20;      // Pivot detection: right bars (D1)
input int    InpPivotSearchBars          = 400;     // Pivot search lookback (D1 bars)
input double InpPivotBufferPoints        = 0.0;     // Buffer added to pivot stop
input bool   InpUseTrailing              = true;    // Enable trailing stop
input double InpTrailingStopPercent      = 0.5;     // Trailing distance as % of entry
input double InpTrailingStartProfitPct   = 1.0;     // Min profit % to activate trailing
input int    InpTrailingStepPoints       = 10;      // Min step to move trailing (points)
input double InpFixedLots                = 0.10;    // Fixed lot size
input bool   InpUseRiskPercent           = false;   // Use risk-based sizing
input double InpRiskPercent              = 1.0;     // Risk % of balance
input double InpContractSize             = 100000.0;// Contract size
input long   InpMagicNumber              = 990301;  // Magic number
input string InpTradesCsvName            = "CrossTendency_V1_trades.csv";
input bool   InpUseCommonFiles           = true;    // Save CSV to common files

CTrade g_trade;

//--- Indicator handles
int g_ema_fast_handle;
int g_ema_slow_handle;
int g_atr_handle;
int g_adx_handle;

//--- State
datetime g_last_bar_time = 0;
int      g_prev_trend    = 0;  // +1 bullish, -1 bearish, 0 flat
bool     g_initialized   = false;

//--- Trailing state (per-position)
double   g_trailing_distance  = 0.0;
double   g_trailing_entry     = 0.0;
bool     g_trailing_active    = false;
double   g_trailing_best_stop = 0.0;

//+------------------------------------------------------------------+
int OnInit()
{
   if(InpFastMaPeriod < 1 || InpSlowMaPeriod < 1 || InpFastMaPeriod >= InpSlowMaPeriod)
   {
      Print("Invalid MA periods: fast=", InpFastMaPeriod, " slow=", InpSlowMaPeriod);
      return(INIT_PARAMETERS_INCORRECT);
   }

   g_ema_fast_handle = iMA(_Symbol, PERIOD_CURRENT, InpFastMaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_ema_slow_handle = iMA(_Symbol, PERIOD_CURRENT, InpSlowMaPeriod, 0, MODE_EMA, PRICE_CLOSE);
   g_atr_handle      = iATR(_Symbol, PERIOD_CURRENT, InpAtrPeriod);
   g_adx_handle      = iADX(_Symbol, PERIOD_CURRENT, InpAdxPeriod);

   if(g_ema_fast_handle == INVALID_HANDLE || g_ema_slow_handle == INVALID_HANDLE ||
      g_atr_handle == INVALID_HANDLE || g_adx_handle == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles.");
      return(INIT_FAILED);
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   g_last_bar_time = 0;
   g_prev_trend = 0;
   g_initialized = false;
   g_trailing_active = false;

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_ema_fast_handle != INVALID_HANDLE) IndicatorRelease(g_ema_fast_handle);
   if(g_ema_slow_handle != INVALID_HANDLE) IndicatorRelease(g_ema_slow_handle);
   if(g_atr_handle != INVALID_HANDLE)      IndicatorRelease(g_atr_handle);
   if(g_adx_handle != INVALID_HANDLE)      IndicatorRelease(g_adx_handle);
}

//+------------------------------------------------------------------+
double NormalizePrice(double price)
{
   return NormalizeDouble(price, _Digits);
}

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
double NormalizeLots(double lots)
{
   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0) step = 0.01;
   lots = MathMax(min_lot, MathMin(max_lot, lots));
   lots = MathFloor(lots / step) * step;
   lots = MathMax(min_lot, lots);
   return NormalizeDouble(lots, VolumeDigits(step));
}

//+------------------------------------------------------------------+
double LotsFromRisk(double entry_price, double stop_price)
{
   if(!InpUseRiskPercent || InpRiskPercent <= 0.0)
      return NormalizeLots(InpFixedLots);

   double per_unit_risk = MathAbs(entry_price - stop_price);
   double money_risk    = AccountInfoDouble(ACCOUNT_BALANCE) * (InpRiskPercent / 100.0);
   double per_lot_risk  = per_unit_risk * InpContractSize;
   if(per_lot_risk <= 0.0 || money_risk <= 0.0)
      return NormalizeLots(InpFixedLots);

   return NormalizeLots(money_risk / per_lot_risk);
}

//+------------------------------------------------------------------+
// Get current position direction: +1 long, -1 short, 0 none
//+------------------------------------------------------------------+
int GetPositionDirection()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      return (type == POSITION_TYPE_BUY) ? 1 : -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
ulong GetPositionTicket()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      return ticket;
   }
   return 0;
}

//+------------------------------------------------------------------+
void ClosePosition()
{
   ulong ticket = GetPositionTicket();
   if(ticket > 0)
   {
      g_trade.PositionClose(ticket);
      g_trailing_active = false;
   }
}

//+------------------------------------------------------------------+
// Daily pivot detection — mirrors Python _build_daily_pivots exactly.
// Scans D1 bars to find the most recent confirmed pivot low/high.
//+------------------------------------------------------------------+
bool FindDailyPivotLow(double &pivot_price)
{
   pivot_price = 0.0;
   int total_needed = InpPivotSearchBars + InpPivotRightBars + 1;
   double d_low[];
   ArraySetAsSeries(d_low, false);
   int copied = CopyLow(_Symbol, PERIOD_D1, 1, total_needed, d_low);
   if(copied < InpPivotLeftBars + InpPivotRightBars + 1)
      return false;

   // Walk backwards from the most recent confirmed bar (index = copied - 1 - InpPivotRightBars)
   // A pivot at day j is confirmed after j + right bars have passed.
   // We're looking at D1 bars shifted by 1 (skip current incomplete day).
   // The most recent confirmed pivot: j such that j + right <= copied - 1
   int confirmed_end = copied - 1 - InpPivotRightBars;
   int search_start  = MathMax(InpPivotLeftBars, confirmed_end - InpPivotSearchBars);

   for(int j = confirmed_end; j >= search_start; j--)
   {
      int win_start = MathMax(0, j - InpPivotLeftBars);
      int win_end   = j + InpPivotRightBars;
      if(win_end >= copied) continue;

      bool is_pivot = true;
      for(int k = win_start; k <= win_end; k++)
      {
         if(d_low[k] < d_low[j])
         {
            is_pivot = false;
            break;
         }
      }
      if(is_pivot)
      {
         pivot_price = d_low[j];
         return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
bool FindDailyPivotHigh(double &pivot_price)
{
   pivot_price = 0.0;
   int total_needed = InpPivotSearchBars + InpPivotRightBars + 1;
   double d_high[];
   ArraySetAsSeries(d_high, false);
   int copied = CopyHigh(_Symbol, PERIOD_D1, 1, total_needed, d_high);
   if(copied < InpPivotLeftBars + InpPivotRightBars + 1)
      return false;

   int confirmed_end = copied - 1 - InpPivotRightBars;
   int search_start  = MathMax(InpPivotLeftBars, confirmed_end - InpPivotSearchBars);

   for(int j = confirmed_end; j >= search_start; j--)
   {
      int win_start = MathMax(0, j - InpPivotLeftBars);
      int win_end   = j + InpPivotRightBars;
      if(win_end >= copied) continue;

      bool is_pivot = true;
      for(int k = win_start; k <= win_end; k++)
      {
         if(d_high[k] > d_high[j])
         {
            is_pivot = false;
            break;
         }
      }
      if(is_pivot)
      {
         pivot_price = d_high[j];
         return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
// ATR filter — mirrors Python exactly:
//   atr[i] >= min_atr_points * point
//   if dynamic: atr[i] >= atr_ma[i] * multiplier
//+------------------------------------------------------------------+
bool AtrFilterPass()
{
   double atr_buf[];
   ArraySetAsSeries(atr_buf, true);
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr_buf) < 1)
      return false;
   double atr_val = atr_buf[0];

   double min_atr_price = InpMinAtrPoints * _Point;
   if(atr_val < min_atr_price)
      return false;

   if(InpUseDynamicAtrFilter)
   {
      // ATR SMA: average of last N ATR values
      double atr_series[];
      ArraySetAsSeries(atr_series, true);
      if(CopyBuffer(g_atr_handle, 0, 1, InpAtrFilterMaPeriod, atr_series) < InpAtrFilterMaPeriod)
         return false;

      double atr_sum = 0.0;
      for(int i = 0; i < InpAtrFilterMaPeriod; i++)
         atr_sum += atr_series[i];
      double atr_ma = atr_sum / InpAtrFilterMaPeriod;

      if(atr_val < atr_ma * InpAtrHighMultiplier)
         return false;
   }
   return true;
}

//+------------------------------------------------------------------+
// ADX filter — mirrors Python: adx[i] >= adx_min_value
//+------------------------------------------------------------------+
bool AdxFilterPass()
{
   if(!InpUseAdxFilter)
      return true;

   double adx_buf[];
   ArraySetAsSeries(adx_buf, true);
   // ADX main line is buffer 0
   if(CopyBuffer(g_adx_handle, 0, 1, 1, adx_buf) < 1)
      return false;

   return (adx_buf[0] >= InpAdxMinValue);
}

//+------------------------------------------------------------------+
// EMA cross detection on closed bar (shift=1)
// Returns: +1 bullish cross, -1 bearish cross, 0 no cross
//+------------------------------------------------------------------+
int DetectCross()
{
   double fast_buf[], slow_buf[];
   ArraySetAsSeries(fast_buf, true);
   ArraySetAsSeries(slow_buf, true);

   // Need current closed bar (shift=1) and previous (shift=2) to detect cross
   if(CopyBuffer(g_ema_fast_handle, 0, 1, 2, fast_buf) < 2) return 0;
   if(CopyBuffer(g_ema_slow_handle, 0, 1, 2, slow_buf) < 2) return 0;

   // fast_buf[0] = shift 1 (just closed), fast_buf[1] = shift 2 (previous)
   int trend_now  = (fast_buf[0] > slow_buf[0]) ? 1 : ((fast_buf[0] < slow_buf[0]) ? -1 : 0);
   int trend_prev = (fast_buf[1] > slow_buf[1]) ? 1 : ((fast_buf[1] < slow_buf[1]) ? -1 : 0);

   if(!g_initialized)
   {
      g_prev_trend = trend_now;
      g_initialized = true;
      return 0;
   }

   int cross = trend_now - g_prev_trend;
   g_prev_trend = trend_now;

   if(cross > 0) return 1;   // bullish cross
   if(cross < 0) return -1;  // bearish cross
   return 0;
}

//+------------------------------------------------------------------+
// Trailing stop management — mirrors Python engine exactly:
//   1. Only activates after profit >= trailing_start_profit_percent
//   2. Distance = entry_price * trailing_stop_percent / 100
//   3. Stop only moves in favorable direction (ratchets)
//   4. Minimum step = trailing_step_points * _Point
//+------------------------------------------------------------------+
void ManageTrailingStop()
{
   if(!InpUseTrailing || !g_trailing_active)
      return;

   ulong ticket = GetPositionTicket();
   if(ticket == 0)
   {
      g_trailing_active = false;
      return;
   }

   if(!PositionSelectByTicket(ticket))
      return;

   long pos_type = PositionGetInteger(POSITION_TYPE);
   double current_sl = PositionGetDouble(POSITION_SL);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double trailing_step = InpTrailingStepPoints * _Point;

   if(pos_type == POSITION_TYPE_BUY)
   {
      // Check profit threshold before activating trailing
      double profit_pct = (bid - g_trailing_entry) / g_trailing_entry;
      if(profit_pct < InpTrailingStartProfitPct / 100.0)
         return;

      double new_sl = NormalizePrice(bid - g_trailing_distance);
      if(new_sl > current_sl + trailing_step)
      {
         g_trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP));
      }
   }
   else // SELL
   {
      double profit_pct = (g_trailing_entry - ask) / g_trailing_entry;
      if(profit_pct < InpTrailingStartProfitPct / 100.0)
         return;

      double new_sl = NormalizePrice(ask + g_trailing_distance);
      if(current_sl == 0.0 || new_sl < current_sl - trailing_step)
      {
         g_trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP));
      }
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   // Trailing runs on every tick (matches Python bar-by-bar trailing update)
   ManageTrailingStop();

   // Signal logic only on new closed bar
   datetime current_bar_time = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(current_bar_time == g_last_bar_time)
      return;
   g_last_bar_time = current_bar_time;

   //--- Detect EMA cross on the just-closed bar
   int cross = DetectCross();
   if(cross == 0)
      return;

   //--- ATR filter
   if(!AtrFilterPass())
      return;

   //--- ADX filter
   if(!AdxFilterPass())
      return;

   //--- Daily pivot stop
   double pivot_price = 0.0;
   double stop_price  = 0.0;
   double buffer = InpPivotBufferPoints * _Point;

   if(cross == 1) // BUY signal
   {
      if(!FindDailyPivotLow(pivot_price))
         return;
      stop_price = NormalizePrice(pivot_price - buffer);
   }
   else // SELL signal
   {
      if(!FindDailyPivotHigh(pivot_price))
         return;
      stop_price = NormalizePrice(pivot_price + buffer);
   }

   //--- Close opposite position (matches Python close_on_signal="opposite")
   int pos_dir = GetPositionDirection();
   if(pos_dir != 0 && pos_dir != cross)
   {
      ClosePosition();
      Sleep(100);
   }
   // If same direction position exists, skip (no stacking)
   if(GetPositionDirection() == cross)
      return;

   //--- Entry at close of the just-completed bar
   double entry_price = iClose(_Symbol, PERIOD_CURRENT, 1);
   double lots = LotsFromRisk(entry_price, stop_price);

   string comment = "CrossTendency V1 " + (cross == 1 ? "BUY" : "SELL");

   bool ok = false;
   if(cross == 1)
      ok = g_trade.Buy(lots, _Symbol, 0, stop_price, 0, comment);
   else
      ok = g_trade.Sell(lots, _Symbol, 0, stop_price, 0, comment);

   if(ok)
   {
      Print(comment, " | entry=", entry_price, " stop=", stop_price,
            " pivot=", pivot_price, " lots=", lots);

      //--- Setup trailing
      if(InpUseTrailing)
      {
         g_trailing_entry    = entry_price;
         g_trailing_distance = entry_price * (InpTrailingStopPercent / 100.0);
         g_trailing_active   = true;
      }
   }
   else
   {
      Print("Order failed: ", g_trade.ResultRetcode(), " ", g_trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
