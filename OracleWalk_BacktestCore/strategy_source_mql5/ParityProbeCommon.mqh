//+------------------------------------------------------------------+
//| ParityProbeCommon.mqh                                            |
//| Shared helpers for the BacktestCore parity probes (P1..P5).      |
//|                                                                  |
//| Keep this file in the SAME folder as the probe EAs (MQL5/Experts)|
//| so #include "ParityProbeCommon.mqh" resolves.                    |
//|                                                                  |
//| Each EA sets g_magic / g_trades_csv / g_use_common in OnInit,    |
//| drives its own OnTick logic, and calls CommonDeinit() in         |
//| OnDeinit to dump a canonical trades CSV that scripts/            |
//| parity_compare.py can diff against the Python export.            |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>

CTrade   g_trade;
long     g_magic       = 0;
string   g_trades_csv  = "probe_trades.csv";
bool     g_use_common  = true;
datetime g_last_bar    = 0;

//--- New-bar detection on the chart timeframe.
bool IsNewBar()
{
   datetime t = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(t == g_last_bar)
      return false;
   g_last_bar = t;
   return true;
}

//--- Current position direction for this magic: +1 long, -1 short, 0 none.
int GetPosDir()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic) continue;
      return (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
   }
   return 0;
}

ulong GetPosTicket()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_magic) continue;
      return ticket;
   }
   return 0;
}

void ClosePos()
{
   ulong ticket = GetPosTicket();
   if(ticket > 0)
      g_trade.PositionClose(ticket);
}

//--- Delete any resting pending orders for this magic (one-order-at-a-time probes).
void DeletePendingMagic()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != g_magic) continue;
      g_trade.OrderDelete(ticket);
   }
}

bool HasPendingMagic()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != g_magic) continue;
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

double NormLots(double lots)
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

double NP(double price) { return NormalizeDouble(price, _Digits); }

//--- Canonical trades CSV: one row per closed position, schema compatible with
//--- scripts/parity_compare.py (entry_time, side, entry_price, exit_time,
//--- exit_price, reason).
void WriteTradesCsv()
{
   if(!HistorySelect(0, TimeCurrent()))
   {
      Print("HistorySelect failed; no trades CSV written.");
      return;
   }
   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI;
   if(g_use_common) flags |= FILE_COMMON;

   // Qualify the filename with the symbol so runs on different instruments do NOT
   // overwrite each other: "P1_ClockFlip_trades.csv" -> "P1_ClockFlip_EURUSD_trades.csv".
   string fname = g_trades_csv;
   if(StringFind(fname, "_trades.csv") >= 0)
      StringReplace(fname, "_trades.csv", "_" + _Symbol + "_trades.csv");
   else
      fname = _Symbol + "_" + fname;

   int h = FileOpen(fname, flags, ',');
   if(h == INVALID_HANDLE)
   {
      Print("Failed to open trades CSV: ", fname, " err=", GetLastError());
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
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != g_magic) continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      long pid = HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      int n = ArraySize(pos_ids);
      ArrayResize(pos_ids, n + 1);
      pos_ids[n] = pid;
   }

   for(int p = 0; p < ArraySize(pos_ids); p++)
   {
      long pid = pos_ids[p];
      datetime entry_time = 0, exit_time = 0;
      double entry_price = 0.0, exit_price = 0.0, lots = 0.0;
      double pnl = 0.0, commission = 0.0, swap = 0.0;
      int side = 0;
      bool has_exit = false;
      string reason = "signal";

      for(int i = 0; i < total_deals; i++)
      {
         ulong deal = HistoryDealGetTicket(i);
         if(deal == 0) continue;
         if(HistoryDealGetInteger(deal, DEAL_POSITION_ID) != pid) continue;
         if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
         if(HistoryDealGetInteger(deal, DEAL_MAGIC) != g_magic) continue;

         long entry_type = HistoryDealGetInteger(deal, DEAL_ENTRY);
         long deal_type  = HistoryDealGetInteger(deal, DEAL_TYPE);
         double deal_price = HistoryDealGetDouble(deal, DEAL_PRICE);
         double deal_vol   = HistoryDealGetDouble(deal, DEAL_VOLUME);
         datetime deal_time = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);

         pnl        += HistoryDealGetDouble(deal, DEAL_PROFIT);
         commission += HistoryDealGetDouble(deal, DEAL_COMMISSION);
         swap       += HistoryDealGetDouble(deal, DEAL_SWAP);

         if(entry_type == DEAL_ENTRY_IN)
         {
            entry_time = deal_time;
            entry_price = deal_price;
            lots = deal_vol;
            side = (deal_type == DEAL_TYPE_BUY) ? 1 : -1;
         }
         else
         {
            exit_time = deal_time;
            exit_price = deal_price;
            has_exit = true;
            long dr = HistoryDealGetInteger(deal, DEAL_REASON);
            if(dr == DEAL_REASON_SL)      reason = "sl";
            else if(dr == DEAL_REASON_TP) reason = "tp";
            else if(dr == DEAL_REASON_SO) reason = "stop_out";
            else                          reason = "signal";
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
         reason);
   }
   FileClose(h);
   Print("Wrote trades CSV: ", fname, " (", ArraySize(pos_ids), " positions)");
}

void CommonDeinit()
{
   WriteTradesCsv();
}
//+------------------------------------------------------------------+
