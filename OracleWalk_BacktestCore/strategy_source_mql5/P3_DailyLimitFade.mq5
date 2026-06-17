//+------------------------------------------------------------------+
//| P3_DailyLimitFade.mq5  —  parity probe #3                        |
//| Port of parity_probes.py :: P3DailyLimitFade                     |
//|                                                                  |
//| Daily mean-revert via a LIMIT pending order — the carried order  |
//| book / tick-touch path, the one most sensitive to parity.        |
//| Validates: limit order fill, intrabar SL/TP, expiry.             |
//|                                                                  |
//| Logic: on the new bar whose just-closed bar (shift 1) has        |
//|   hour==place_hour, place a BUY LIMIT at iClose(D1,1)-offset     |
//|   with SL=trigger-sl_pts, TP=trigger+tp_pts, expiry = signal bar |
//|   time + expiry_bars*PeriodSeconds. Skip while a position open.  |
//|                                                                  |
//| Python engine config to match: entry_timing="signal_close".      |
//+------------------------------------------------------------------+
#property strict
#property description "BacktestCore parity probe P3 - DailyLimitFade (limit)"
#include "ParityProbeCommon.mqh"

input int    InpPlaceHour    = 0;
input double InpOffsetPoints = 150.0;  // trigger = prevday close - offset
input double InpSlPoints     = 200.0;
input double InpTpPoints     = 300.0;
input int    InpExpiryBars   = 23;
input double InpFixedLots    = 0.10;
input long   InpMagicNumber  = 990403;
input string InpTradesCsv    = "P3_DailyLimitFade_trades.csv";
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

   datetime bt = iTime(_Symbol, PERIOD_CURRENT, 1);
   MqlDateTime st; TimeToStruct(bt, st);
   if(st.hour != InpPlaceHour)
      return;

   if(GetPosDir() != 0)
      return;

   double prev_day_close = iClose(_Symbol, PERIOD_D1, 1);
   if(prev_day_close <= 0.0)
      return;

   double trigger = NP(prev_day_close - InpOffsetPoints * _Point);
   double sl      = NP(trigger - InpSlPoints * _Point);
   double tp      = NP(trigger + InpTpPoints * _Point);
   datetime expiry = bt + (datetime)(InpExpiryBars * PeriodSeconds(PERIOD_CURRENT));

   DeletePendingMagic();
   g_trade.BuyLimit(NormLots(InpFixedLots), trigger, _Symbol, sl, tp,
                    ORDER_TIME_SPECIFIED, expiry, "P3 BUYLIMIT");
}
//+------------------------------------------------------------------+
