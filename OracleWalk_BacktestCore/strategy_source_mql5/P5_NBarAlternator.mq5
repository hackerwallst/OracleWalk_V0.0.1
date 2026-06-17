//+------------------------------------------------------------------+
//| P5_NBarAlternator.mq5  —  parity probe #5                        |
//| Port of parity_probes.py :: P5NBarAlternator                     |
//|                                                                  |
//| Dense market reversals on a timestamp-anchored clock. Validates: |
//| many opposite-signal reversals and per-trade cost accrual. The   |
//| schedule is anchored to absolute UNIX time (NOT a bar counter)   |
//| so Python and MT5 compute the same block for the same bar with   |
//| no warm-start drift.                                             |
//|                                                                  |
//| Logic: bar_seconds = PeriodSeconds(PERIOD_CURRENT). On each NEW  |
//|   bar, for the just-closed bar t1 (shift 1):                     |
//|     block1 = t1 / (period_bars*bar_seconds)                      |
//|     block2 = iTime(shift 2) / (period_bars*bar_seconds)          |
//|     if block1 != block2 (first bar of a new block):              |
//|        desired = (block1 % 2 == 0) ? +1 : -1                     |
//|        if pos dir != desired: close & open market `desired`.     |
//|                                                                  |
//| Python engine config to match: entry_timing="next_bar_open".     |
//+------------------------------------------------------------------+
#property strict
#property description "BacktestCore parity probe P5 - NBarAlternator"
#include "ParityProbeCommon.mqh"

input int    InpPeriodBars   = 20;
input double InpFixedLots     = 0.10;
input long   InpMagicNumber   = 990405;
input string InpTradesCsv     = "P5_NBarAlternator_trades.csv";
input bool   InpUseCommonFiles = true;

long g_block_seconds = 0;

int OnInit()
{
   g_magic = InpMagicNumber;
   g_trades_csv = InpTradesCsv;
   g_use_common = InpUseCommonFiles;
   g_trade.SetExpertMagicNumber(g_magic);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_last_bar = 0;
   g_block_seconds = (long)InpPeriodBars * (long)PeriodSeconds(PERIOD_CURRENT);
   if(g_block_seconds <= 0) g_block_seconds = (long)InpPeriodBars * 3600;
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { CommonDeinit(); }

void OnTick()
{
   if(!IsNewBar())
      return;

   datetime t1 = iTime(_Symbol, PERIOD_CURRENT, 1);  // just-closed bar
   datetime t2 = iTime(_Symbol, PERIOD_CURRENT, 2);  // bar before it
   if(t1 == 0 || t2 == 0)
      return;

   long block1 = (long)t1 / g_block_seconds;
   long block2 = (long)t2 / g_block_seconds;
   if(block1 == block2)        // not the first bar of a new block
      return;

   int desired = (block1 % 2 == 0) ? 1 : -1;
   int dir = GetPosDir();
   if(dir == desired)
      return;

   if(dir != 0)
      ClosePos();

   double lots = NormLots(InpFixedLots);
   if(desired > 0)
      g_trade.Buy(lots, _Symbol, 0, 0, 0, "P5 LONG");
   else
      g_trade.Sell(lots, _Symbol, 0, 0, 0, "P5 SHORT");
}
//+------------------------------------------------------------------+
