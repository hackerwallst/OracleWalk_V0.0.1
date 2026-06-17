//+------------------------------------------------------------------+
//| P1_ClockFlip.mq5  —  parity probe #1                             |
//| Port of backtest_core/strategies/parity_probes.py :: P1ClockFlip |
//|                                                                  |
//| Market flip on a fixed weekly clock. Validates: market entry at  |
//| the new bar's open, opposite-signal close, swap over multi-day   |
//| holds. Deterministic (datetime only) — any divergence vs the     |
//| Python export is the ENGINE.                                     |
//|                                                                  |
//| Logic: on each NEW bar, look at the just-closed bar (shift 1).   |
//|   weekday==long_weekday  & hour==entry_hour -> desired = +1      |
//|   weekday==short_weekday & hour==entry_hour -> desired = -1      |
//|   if desired!=0 and current dir!=desired: close & open market.   |
//|                                                                  |
//| Python engine config to match: entry_timing="next_bar_open".     |
//+------------------------------------------------------------------+
#property strict
#property description "BacktestCore parity probe P1 - ClockFlip"
#include "ParityProbeCommon.mqh"

input int    InpEntryHour    = 0;     // hour (broker time) the flip fires
input int    InpLongWeekday  = 1;     // MQL5: Sun=0,Mon=1..Sat=6  (Python Mon=0 -> here 1)
input int    InpShortWeekday = 3;     // Python Wed=2 -> here 3
input double InpFixedLots    = 0.10;
input long   InpMagicNumber  = 990401;
input string InpTradesCsv    = "P1_ClockFlip_trades.csv";
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

   // Just-closed bar = shift 1 (the "signal bar"); we act at this new bar's open.
   datetime bt = iTime(_Symbol, PERIOD_CURRENT, 1);
   MqlDateTime st; TimeToStruct(bt, st);

   int desired = 0;
   if(st.day_of_week == InpLongWeekday  && st.hour == InpEntryHour) desired = 1;
   if(st.day_of_week == InpShortWeekday && st.hour == InpEntryHour) desired = -1;
   if(desired == 0)
      return;

   int dir = GetPosDir();
   if(dir == desired)
      return;

   if(dir != 0)
      ClosePos();

   double lots = NormLots(InpFixedLots);
   if(desired > 0)
      g_trade.Buy(lots, _Symbol, 0, 0, 0, "P1 LONG");
   else
      g_trade.Sell(lots, _Symbol, 0, 0, 0, "P1 SHORT");
}
//+------------------------------------------------------------------+
