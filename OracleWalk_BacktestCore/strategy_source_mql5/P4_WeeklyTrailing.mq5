//+------------------------------------------------------------------+
//| P4_WeeklyTrailing.mq5  —  parity probe #4                        |
//| Port of parity_probes.py :: P4WeeklyTrailing                     |
//|                                                                  |
//| Weekly market long with a trailing stop that only arms after a   |
//| profit threshold — the exact mechanism behind the trailing bug   |
//| we fixed (the start threshold must survive entry-timing shift).  |
//|                                                                  |
//| Logic: on a NEW bar whose just-closed bar (shift 1) has          |
//|   weekday==entry_weekday & hour==entry_hour and we are flat:     |
//|     open market BUY; SL = signalClose - init_stop_pts.           |
//|   On every tick while long:                                      |
//|     if (Bid - entry) >= trailing_start_pts*Point:    // arm      |
//|        newSL = Bid - trailing_distance_pts*Point                 |
//|        if newSL > currentSL: modify (ratchet up only).           |
//|                                                                  |
//| Python engine config to match: entry_timing="next_bar_open".     |
//| SL/threshold use the signal-bar close as reference (= Python).   |
//+------------------------------------------------------------------+
#property strict
#property description "BacktestCore parity probe P4 - WeeklyTrailing"
#include "ParityProbeCommon.mqh"

input int    InpEntryWeekday   = 1;     // MQL5 Mon=1 (Python Mon=0)
input int    InpEntryHour      = 0;
input double InpInitStopPoints = 300.0;
input double InpTrailDistPoints = 150.0;
input double InpTrailStartPoints = 100.0;
input double InpFixedLots       = 0.10;
input long   InpMagicNumber     = 990404;
input string InpTradesCsv       = "P4_WeeklyTrailing_trades.csv";
input bool   InpUseCommonFiles  = true;

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

void ManageTrailing()
{
   ulong ticket = GetPosTicket();
   if(ticket == 0) return;
   if(!PositionSelectByTicket(ticket)) return;
   if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY) return;

   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double cur_sl = PositionGetDouble(POSITION_SL);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if((bid - entry) < InpTrailStartPoints * _Point)  // threshold not reached -> don't trail
      return;

   double new_sl = NP(bid - InpTrailDistPoints * _Point);
   if(new_sl > cur_sl)  // ratchet up only
      g_trade.PositionModify(ticket, new_sl, PositionGetDouble(POSITION_TP));
}

void OnTick()
{
   ManageTrailing();  // runs every tick, like Python's bar-by-bar trailing update

   if(!IsNewBar())
      return;

   datetime bt = iTime(_Symbol, PERIOD_CURRENT, 1);
   MqlDateTime st; TimeToStruct(bt, st);
   if(st.day_of_week != InpEntryWeekday || st.hour != InpEntryHour)
      return;
   if(GetPosDir() != 0)
      return;

   double sig_close = iClose(_Symbol, PERIOD_CURRENT, 1);   // reference = signal-bar close
   double sl = NP(sig_close - InpInitStopPoints * _Point);
   g_trade.Buy(NormLots(InpFixedLots), _Symbol, 0, sl, 0, "P4 LONG");
}
//+------------------------------------------------------------------+
