//+------------------------------------------------------------------+
//| P2_DailyBreakout.mq5  —  parity probe #2                         |
//| Port of parity_probes.py :: P2DailyBreakout                      |
//|                                                                  |
//| Daily breakout via a STOP pending order. Validates: carried stop |
//| order book, intrabar SL/TP first-touch, order expiry. One order  |
//| per day -> one resting order at a time.                          |
//|                                                                  |
//| Logic: on the new bar whose just-closed bar (shift 1) has        |
//|   hour==place_hour, place a BUY STOP at iHigh(D1,1)+buffer with  |
//|   SL=trigger-sl_pts, TP=trigger+tp_pts, expiry = signal bar time |
//|   + expiry_bars*PeriodSeconds. Skip while a position is open.    |
//|                                                                  |
//| Python engine config to match: entry_timing="signal_close".      |
//+------------------------------------------------------------------+
#property strict
#property description "BacktestCore parity probe P2 - DailyBreakout (stop)"
#include "ParityProbeCommon.mqh"

input int    InpPlaceHour    = 0;      // hour the order is placed
input double InpBufferPoints = 10.0;   // trigger = prevday high + buffer
input double InpSlPoints     = 200.0;
input double InpTpPoints     = 400.0;
input int    InpExpiryBars   = 23;     // validity in chart bars
input double InpFixedLots    = 0.10;
input long   InpMagicNumber  = 990402;
input string InpTradesCsv    = "P2_DailyBreakout_trades.csv";
input bool   InpUseCommonFiles = true;

int OnInit()
{
   g_magic = InpMagicNumber;
   g_trades_csv = InpTradesCsv;
   g_use_common = InpUseCommonFiles;
   g_trade.SetExpertMagicNumber(g_magic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_last_bar = 0;
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { CommonDeinit(); }

void OnTick()
{
   if(!IsNewBar())
      return;

   datetime bt = iTime(_Symbol, PERIOD_CURRENT, 1);  // just-closed signal bar
   MqlDateTime st; TimeToStruct(bt, st);
   if(st.hour != InpPlaceHour)
      return;

   // single-position semantics: don't place while a position is open
   if(GetPosDir() != 0)
      return;

   double prev_day_high = iHigh(_Symbol, PERIOD_D1, 1);
   if(prev_day_high <= 0.0)
      return;

   double trigger = NP(prev_day_high + InpBufferPoints * _Point);
   double sl      = NP(trigger - InpSlPoints * _Point);
   double tp      = NP(trigger + InpTpPoints * _Point);
   datetime expiry = bt + (datetime)(InpExpiryBars * PeriodSeconds(PERIOD_CURRENT));

   DeletePendingMagic();  // at most one resting order
   g_trade.BuyStop(NormLots(InpFixedLots), trigger, _Symbol, sl, tp,
                   ORDER_TIME_SPECIFIED, expiry, "P2 BUYSTOP");
}
//+------------------------------------------------------------------+
