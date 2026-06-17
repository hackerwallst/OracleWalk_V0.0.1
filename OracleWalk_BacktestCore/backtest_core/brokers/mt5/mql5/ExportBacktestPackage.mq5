//+------------------------------------------------------------------+
//| ExportBacktestPackage.mq5                                        |
//| Exports candles + ticks + symbol/account specs for BacktestCore. |
//|                                                                  |
//| Put this file in:                                                |
//|   MQL5/Scripts/ExportBacktestPackage.mq5                         |
//| Then compile and run it from MetaTrader 5.                       |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs

input string          InpSymbol          = "";          // Empty = current chart symbol
input ENUM_TIMEFRAMES InpTimeframe       = PERIOD_CURRENT; // Current = chart timeframe
input int             InpBars            = 0;           // 0 = all available candles
input bool            InpExportTicks     = true;        // Export real ticks for intrabar replay
input int             InpMaxTicks        = 0;           // 0 = no tick cap
input int             InpTickChunkHours  = 24;          // CopyTicksRange chunk size
input int             InpTickLookbackDays = 365;        // 0 = full candle range; safer for broker tick history
input bool            InpAbortOnTickError = false;      // true = stop package when a tick chunk fails
input int             InpMaxTickErrorChunks = 5;        // Stop tick export after N failed chunks; 0 = no limit
input int             InpMaxEmptyTickChunks = 30;       // Stop after N consecutive EMPTY chunks (broker has no ticks); 0 = no limit
input int             InpTickWarmupRetries = 3;         // CopyTicks sync attempts before CopyTicksRange
input int             InpTickWarmupSeconds = 5;         // Wait per tick sync attempt
input int             InpTickFallbackCount = 200000;    // CopyTicks fallback count per failed range chunk
input int             InpProgressLogSeconds = 2;        // Seconds between progress logs/comments
input string          InpOutputRoot      = "";          // Empty = Files/<Broker>/<Symbol>/<TF>
input bool            InpUseCommonFiles  = false;       // true = Terminal/Common/Files

long     g_tick_error_chunks = 0;
long     g_tick_empty_chunks = 0;
int      g_tick_last_error = 0;
bool     g_tick_range_limited = false;
datetime g_tick_export_from = 0;
datetime g_tick_export_to = 0;
string   g_tick_note = "";

string JsonEscape(string text)
{
   StringReplace(text, "\\", "\\\\");
   StringReplace(text, "\"", "\\\"");
   StringReplace(text, "\r", "\\r");
   StringReplace(text, "\n", "\\n");
   return text;
}

string BoolToJson(bool value)
{
   return value ? "true" : "false";
}

string TimeframeToString(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M2:  return "M2";
      case PERIOD_M3:  return "M3";
      case PERIOD_M4:  return "M4";
      case PERIOD_M5:  return "M5";
      case PERIOD_M6:  return "M6";
      case PERIOD_M10: return "M10";
      case PERIOD_M12: return "M12";
      case PERIOD_M15: return "M15";
      case PERIOD_M20: return "M20";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H2:  return "H2";
      case PERIOD_H3:  return "H3";
      case PERIOD_H4:  return "H4";
      case PERIOD_H6:  return "H6";
      case PERIOD_H8:  return "H8";
      case PERIOD_H12: return "H12";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
      default:         return IntegerToString((int)tf);
   }
}

int PeriodSecondsSafe(ENUM_TIMEFRAMES tf)
{
   int seconds = PeriodSeconds(tf);
   return seconds > 0 ? seconds : 0;
}

string JoinPath(string a, string b)
{
   if(StringLen(a) == 0)
      return b;
   if(StringSubstr(a, StringLen(a) - 1, 1) == "\\")
      return a + b;
   return a + "\\" + b;
}

bool EnsureFolder(string path, int flags)
{
   string parts[];
   int count = StringSplit(path, '\\', parts);
   if(count <= 0)
      return false;

   string current = "";
   for(int i = 0; i < count; i++)
   {
      if(parts[i] == "")
         continue;
      current = (current == "") ? parts[i] : current + "\\" + parts[i];
      if(!FolderCreate(current, flags) && GetLastError() != 5016)
      {
         // 5016 normally means folder already exists in many terminal builds.
         ResetLastError();
      }
   }
   return true;
}

string D(double value, int digits = 10)
{
   return DoubleToString(value, digits);
}

string FormatDuration(const int total_seconds)
{
   int seconds = total_seconds;
   if(seconds < 0)
      seconds = 0;
   int hours = seconds / 3600;
   int minutes = (seconds % 3600) / 60;
   int secs = seconds % 60;
   return StringFormat("%02d:%02d:%02d", hours, minutes, secs);
}

string TickFlagName(const uint flags)
{
   if(flags == COPY_TICKS_INFO)
      return "COPY_TICKS_INFO";
   if(flags == COPY_TICKS_TRADE)
      return "COPY_TICKS_TRADE";
   return "COPY_TICKS_ALL";
}

double ClampProgress(const double value)
{
   if(value < 0.0)
      return 0.0;
   if(value > 100.0)
      return 100.0;
   return value;
}

void LogTickProbe(const string label, const string symbol, const MqlTick &ticks[], const int copied, const int error_code)
{
   if(copied > 0)
   {
      Print("[BacktestCore Export] Tick probe ",
            label,
            " ok | symbol=", symbol,
            " copied=", copied,
            " first=", TimeToString(ticks[0].time, TIME_DATE | TIME_SECONDS),
            " first_msc=", ticks[0].time_msc,
            " last=", TimeToString(ticks[copied - 1].time, TIME_DATE | TIME_SECONDS),
            " last_msc=", ticks[copied - 1].time_msc,
            " bid=", DoubleToString(ticks[copied - 1].bid, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
            " ask=", DoubleToString(ticks[copied - 1].ask, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
            " flags=", ticks[copied - 1].flags);
      return;
   }

   Print("[BacktestCore Export] Tick probe ",
         label,
         " failed/empty | symbol=", symbol,
         " copied=", copied,
         " error=", error_code);
}

void ProbeTickAccess(const string symbol, const ulong from_msc, const ulong to_msc)
{
   bool selected = SymbolSelect(symbol, true);
   bool synchronized = SymbolIsSynchronized(symbol);
   MqlTick last_tick;
   bool has_last = SymbolInfoTick(symbol, last_tick);
   Print("[BacktestCore Export] Tick diagnostics | symbol=", symbol,
         " selected=", BoolToJson(selected),
         " synchronized=", BoolToJson(synchronized));
   if(has_last)
   {
      Print("[BacktestCore Export] SymbolInfoTick | time=",
            TimeToString(last_tick.time, TIME_DATE | TIME_SECONDS),
            " time_msc=", last_tick.time_msc,
            " bid=", DoubleToString(last_tick.bid, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
            " ask=", DoubleToString(last_tick.ask, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
            " last=", DoubleToString(last_tick.last, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
            " flags=", last_tick.flags);
   }
   else
   {
      Print("[BacktestCore Export] SymbolInfoTick failed | error=", GetLastError());
      ResetLastError();
   }

   MqlTick recent[];
   ArraySetAsSeries(recent, false);
   ResetLastError();
   int copied_recent = CopyTicks(symbol, recent, COPY_TICKS_ALL, 0, 2000);
   int recent_error = GetLastError();
   LogTickProbe("CopyTicks recent", symbol, recent, copied_recent, recent_error);
   ResetLastError();

   MqlTick from_probe[];
   ArraySetAsSeries(from_probe, false);
   ResetLastError();
   int copied_from = CopyTicks(symbol, from_probe, COPY_TICKS_ALL, from_msc, 10);
   int from_error = GetLastError();
   LogTickProbe("CopyTicks from requested start", symbol, from_probe, copied_from, from_error);
   ResetLastError();

   MqlTick range_probe[];
   ArraySetAsSeries(range_probe, false);
   ResetLastError();
   int copied_range = CopyTicksRange(symbol, range_probe, COPY_TICKS_ALL, from_msc, to_msc);
   int range_error = GetLastError();
   LogTickProbe("CopyTicksRange full requested window probe", symbol, range_probe, copied_range, range_error);
   ResetLastError();
}

bool WarmupTickHistory(const string symbol, const ulong from_msc)
{
   int retries = InpTickWarmupRetries > 0 ? InpTickWarmupRetries : 0;
   int sleep_ms = (InpTickWarmupSeconds > 0 ? InpTickWarmupSeconds : 1) * 1000;
   for(int attempt = 0; attempt <= retries; attempt++)
   {
      MqlTick warm[];
      ArraySetAsSeries(warm, false);
      ResetLastError();
      int copied = CopyTicks(symbol, warm, COPY_TICKS_ALL, from_msc, 1);
      int err = GetLastError();
      if(copied >= 0)
      {
         Print("[BacktestCore Export] Tick warmup ok | attempt=", attempt + 1,
               " copied=", copied,
               " error=", err,
               " from_msc=", from_msc);
         ResetLastError();
         return true;
      }

      Print("[BacktestCore Export] Tick warmup failed | attempt=", attempt + 1,
            " copied=", copied,
            " error=", err,
            " from_msc=", from_msc);
      ResetLastError();
      if(attempt < retries)
         Sleep(sleep_ms);
   }
   return false;
}

void ReportProgress(
   const string stage,
   const string symbol,
   const string timeframe_text,
   const double progress_pct,
   const long bars_done,
   const long bars_total,
   const long ticks_done,
   const long ticks_target,
   const ulong range_done_msc,
   const ulong range_total_msc,
   const datetime started_at,
   const bool force_log = false
)
{
   static datetime s_last_log = 0;
   datetime now = TimeCurrent();
   int interval = InpProgressLogSeconds > 0 ? InpProgressLogSeconds : 1;
   bool should_log = force_log || s_last_log == 0 || (now - s_last_log) >= interval;
   if(!should_log)
      return;

   int elapsed = (int)(now - started_at);
   double pct = ClampProgress(progress_pct);
   string bars_text = bars_total > 0
      ? StringFormat("%d/%d", (int)bars_done, (int)bars_total)
      : IntegerToString((int)bars_done);
   string ticks_text = ticks_target > 0
      ? StringFormat("%I64d/%I64d", ticks_done, ticks_target)
      : StringFormat("%I64d", ticks_done);
   string range_text = range_total_msc > 0
      ? StringFormat("%.1f%%", ClampProgress((double)range_done_msc * 100.0 / (double)range_total_msc))
      : "0.0%";

   string message = StringFormat(
      "BacktestCore export\\n%s %s\\nEtapa: %s\\nProgresso: %.1f%%%s\\nCandles: %s\\nTicks: %s\\nFaixa temporal: %s\\nTempo: %s",
      symbol,
      timeframe_text,
      stage,
      pct,
      ticks_target > 0 ? " (estimado)" : "",
      bars_text,
      ticks_text,
      range_text,
      FormatDuration(elapsed)
   );

   Comment(message);
   Print("[BacktestCore Export] ", stage,
         " | symbol=", symbol,
         " tf=", timeframe_text,
         " progress=", DoubleToString(pct, 1), "%",
         " bars=", bars_text,
         " ticks=", ticks_text,
         " range=", range_text,
         " elapsed=", FormatDuration(elapsed));
   s_last_log = now;
}

void WriteSymbolSpec(const string path, const string symbol, const ENUM_TIMEFRAMES timeframe, const int flags)
{
   int handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | flags);
   if(handle == INVALID_HANDLE)
   {
      Print("Failed to open symbol spec: ", path, " error=", GetLastError());
      return;
   }

   double contract_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double volume_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double volume_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double volume_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double swap_long = SymbolInfoDouble(symbol, SYMBOL_SWAP_LONG);
   double swap_short = SymbolInfoDouble(symbol, SYMBOL_SWAP_SHORT);
   int swap_mode = (int)SymbolInfoInteger(symbol, SYMBOL_SWAP_MODE);
   int calc_mode = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_CALC_MODE);
   int stops_level = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int freeze_level = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   string currency_base = SymbolInfoString(symbol, SYMBOL_CURRENCY_BASE);
   string currency_profit = SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT);
   string currency_margin = SymbolInfoString(symbol, SYMBOL_CURRENCY_MARGIN);
   // --- extra cost / sizing fields so the backtester inherits the FULL spec ---
   int    triple_swap_day = (int)SymbolInfoInteger(symbol, SYMBOL_SWAP_ROLLOVER3DAYS);
   double tick_value_profit = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   double tick_value_loss = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   double margin_initial = SymbolInfoDouble(symbol, SYMBOL_MARGIN_INITIAL);
   double margin_maintenance = SymbolInfoDouble(symbol, SYMBOL_MARGIN_MAINTENANCE);
   double margin_hedged = SymbolInfoDouble(symbol, SYMBOL_MARGIN_HEDGED);
   double volume_limit = SymbolInfoDouble(symbol, SYMBOL_VOLUME_LIMIT);
   int    spread_points = (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   bool   spread_float = (bool)SymbolInfoInteger(symbol, SYMBOL_SPREAD_FLOAT);
   int    exec_mode = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_EXEMODE);
   string description = SymbolInfoString(symbol, SYMBOL_DESCRIPTION);

   FileWriteString(handle, "{\n");
   FileWriteString(handle, "  \"symbol\": \"" + JsonEscape(symbol) + "\",\n");
   FileWriteString(handle, "  \"timeframe\": \"" + TimeframeToString(timeframe) + "\",\n");
   FileWriteString(handle, "  \"period_seconds\": " + IntegerToString(PeriodSecondsSafe(timeframe)) + ",\n");
   FileWriteString(handle, "  \"contract_size\": " + D(contract_size) + ",\n");
   FileWriteString(handle, "  \"point\": " + D(point, digits + 2) + ",\n");
   FileWriteString(handle, "  \"digits\": " + IntegerToString(digits) + ",\n");
   FileWriteString(handle, "  \"tick_size\": " + D(tick_size, digits + 2) + ",\n");
   FileWriteString(handle, "  \"tick_value\": " + D(tick_value) + ",\n");
   FileWriteString(handle, "  \"volume_min\": " + D(volume_min, 4) + ",\n");
   FileWriteString(handle, "  \"volume_max\": " + D(volume_max, 4) + ",\n");
   FileWriteString(handle, "  \"volume_step\": " + D(volume_step, 4) + ",\n");
   FileWriteString(handle, "  \"tick_value_profit\": " + D(tick_value_profit) + ",\n");
   FileWriteString(handle, "  \"tick_value_loss\": " + D(tick_value_loss) + ",\n");
   FileWriteString(handle, "  \"volume_limit\": " + D(volume_limit, 4) + ",\n");
   FileWriteString(handle, "  \"swap_long_per_lot\": " + D(swap_long) + ",\n");
   FileWriteString(handle, "  \"swap_short_per_lot\": " + D(swap_short) + ",\n");
   FileWriteString(handle, "  \"swap_mode\": " + IntegerToString(swap_mode) + ",\n");
   FileWriteString(handle, "  \"triple_swap_weekday\": " + IntegerToString(triple_swap_day) + ",\n");
   FileWriteString(handle, "  \"margin_initial\": " + D(margin_initial) + ",\n");
   FileWriteString(handle, "  \"margin_maintenance\": " + D(margin_maintenance) + ",\n");
   FileWriteString(handle, "  \"margin_hedged\": " + D(margin_hedged) + ",\n");
   FileWriteString(handle, "  \"spread_current_points\": " + IntegerToString(spread_points) + ",\n");
   FileWriteString(handle, "  \"spread_float\": " + (spread_float ? "true" : "false") + ",\n");
   FileWriteString(handle, "  \"trade_exemode\": " + IntegerToString(exec_mode) + ",\n");
   FileWriteString(handle, "  \"trade_calc_mode\": " + IntegerToString(calc_mode) + ",\n");
   FileWriteString(handle, "  \"stops_level_points\": " + IntegerToString(stops_level) + ",\n");
   FileWriteString(handle, "  \"freeze_level_points\": " + IntegerToString(freeze_level) + ",\n");
   FileWriteString(handle, "  \"currency_base\": \"" + JsonEscape(currency_base) + "\",\n");
   FileWriteString(handle, "  \"currency_profit\": \"" + JsonEscape(currency_profit) + "\",\n");
   FileWriteString(handle, "  \"currency_margin\": \"" + JsonEscape(currency_margin) + "\",\n");
   FileWriteString(handle, "  \"description\": \"" + JsonEscape(description) + "\",\n");
   FileWriteString(handle, "  \"commission_per_lot\": null,\n");
   FileWriteString(handle, "  \"commission_note\": \"MT5 nao expoe a comissao da conta de forma confiavel a scripts. Preencha manualmente (a FTMO publica ~3/lote por lado). O backtester herda tudo o resto automaticamente.\",\n");
   FileWriteString(handle, "  \"slippage_note\": \"Slippage nao e propriedade do simbolo no MT5; e modelado no motor (default 0) ou capturado REALsticamente rodando em modo TICK (fills no bid/ask real).\"\n");
   FileWriteString(handle, "}\n");
   FileClose(handle);
}

void WriteAccountSpec(const string path, const int flags)
{
   int handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | flags);
   if(handle == INVALID_HANDLE)
   {
      Print("Failed to open account spec: ", path, " error=", GetLastError());
      return;
   }

   FileWriteString(handle, "{\n");
   FileWriteString(handle, "  \"login\": " + IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN)) + ",\n");
   FileWriteString(handle, "  \"server\": \"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\",\n");
   FileWriteString(handle, "  \"company\": \"" + JsonEscape(AccountInfoString(ACCOUNT_COMPANY)) + "\",\n");
   FileWriteString(handle, "  \"currency\": \"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\",\n");
   FileWriteString(handle, "  \"leverage\": " + IntegerToString((int)AccountInfoInteger(ACCOUNT_LEVERAGE)) + ",\n");
   FileWriteString(handle, "  \"margin_mode\": " + IntegerToString((int)AccountInfoInteger(ACCOUNT_MARGIN_MODE)) + ",\n");
   FileWriteString(handle, "  \"trade_mode\": " + IntegerToString((int)AccountInfoInteger(ACCOUNT_TRADE_MODE)) + ",\n");
   FileWriteString(handle, "  \"balance_at_export\": " + D(AccountInfoDouble(ACCOUNT_BALANCE)) + ",\n");
   FileWriteString(handle, "  \"equity_at_export\": " + D(AccountInfoDouble(ACCOUNT_EQUITY)) + "\n");
   FileWriteString(handle, "}\n");
   FileClose(handle);
}

void WriteManifest(
   const string path,
   const string broker_folder,
   const string symbol,
   const ENUM_TIMEFRAMES timeframe,
   const int bars_exported,
   const long ticks_exported,
   const datetime first_time,
   const datetime last_time,
   const bool common_files,
   const int flags
)
{
   int handle = FileOpen(path, FILE_WRITE | FILE_TXT | FILE_ANSI | flags);
   if(handle == INVALID_HANDLE)
   {
      Print("Failed to open manifest: ", path, " error=", GetLastError());
      return;
   }

   FileWriteString(handle, "{\n");
   FileWriteString(handle, "  \"format\": \"BacktestCore MT5 Broker Package\",\n");
   FileWriteString(handle, "  \"version\": 1,\n");
   FileWriteString(handle, "  \"exported_at\": \"" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\",\n");
   FileWriteString(handle, "  \"broker_folder\": \"" + JsonEscape(broker_folder) + "\",\n");
   FileWriteString(handle, "  \"symbol\": \"" + JsonEscape(symbol) + "\",\n");
   FileWriteString(handle, "  \"timeframe\": \"" + TimeframeToString(timeframe) + "\",\n");
   FileWriteString(handle, "  \"bars_requested\": " + IntegerToString(InpBars) + ",\n");
   FileWriteString(handle, "  \"bars_exported\": " + IntegerToString(bars_exported) + ",\n");
   FileWriteString(handle, "  \"ticks_requested\": " + BoolToJson(InpExportTicks) + ",\n");
   FileWriteString(handle, "  \"ticks_exported\": " + IntegerToString(ticks_exported) + ",\n");
   FileWriteString(handle, "  \"tick_source\": \"CopyTicksRange(COPY_TICKS_ALL)\",\n");
   FileWriteString(handle, "  \"tick_cap\": " + IntegerToString(InpMaxTicks) + ",\n");
   FileWriteString(handle, "  \"tick_lookback_days\": " + IntegerToString(InpTickLookbackDays) + ",\n");
   FileWriteString(handle, "  \"tick_range_limited\": " + BoolToJson(g_tick_range_limited) + ",\n");
   FileWriteString(handle, "  \"tick_first_time\": \"" + (g_tick_export_from > 0 ? TimeToString(g_tick_export_from, TIME_DATE | TIME_MINUTES) : "") + "\",\n");
   FileWriteString(handle, "  \"tick_last_time\": \"" + (g_tick_export_to > 0 ? TimeToString(g_tick_export_to, TIME_DATE | TIME_MINUTES) : "") + "\",\n");
   FileWriteString(handle, "  \"tick_error_chunks\": " + IntegerToString((int)g_tick_error_chunks) + ",\n");
   FileWriteString(handle, "  \"tick_empty_chunks\": " + IntegerToString((int)g_tick_empty_chunks) + ",\n");
   FileWriteString(handle, "  \"tick_last_error\": " + IntegerToString(g_tick_last_error) + ",\n");
   FileWriteString(handle, "  \"tick_note\": \"" + JsonEscape(g_tick_note) + "\",\n");
   FileWriteString(handle, "  \"first_bar_time\": \"" + TimeToString(first_time, TIME_DATE | TIME_MINUTES) + "\",\n");
   FileWriteString(handle, "  \"last_bar_time\": \"" + TimeToString(last_time, TIME_DATE | TIME_MINUTES) + "\",\n");
   FileWriteString(handle, "  \"common_files\": " + BoolToJson(common_files) + ",\n");
   FileWriteString(handle, "  \"files\": {\n");
   FileWriteString(handle, "    \"candles\": \"candles.csv\",\n");
   if(InpExportTicks)
      FileWriteString(handle, "    \"ticks\": \"ticks.csv\",\n");
   FileWriteString(handle, "    \"symbol_spec\": \"symbol_spec.json\",\n");
   FileWriteString(handle, "    \"account_spec\": \"account_spec.json\"\n");
   FileWriteString(handle, "  }\n");
   FileWriteString(handle, "}\n");
   FileClose(handle);
}

long WriteTicksCsv(
   const string path,
   const string symbol,
   const datetime first_bar_time,
   const datetime last_bar_time,
   const ENUM_TIMEFRAMES timeframe,
   const int bars_exported,
   const int flags
)
{
   if(!InpExportTicks)
      return 0;

   g_tick_error_chunks = 0;
   g_tick_empty_chunks = 0;
   g_tick_last_error = 0;
   g_tick_range_limited = false;
   g_tick_export_from = 0;
   g_tick_export_to = 0;
   g_tick_note = "";

   int handle = FileOpen(path, FILE_WRITE | FILE_CSV | FILE_ANSI | flags, ',');
   if(handle == INVALID_HANDLE)
   {
      Print("Failed to open ticks CSV: ", path, " error=", GetLastError());
      return -1;
   }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   int period_seconds = PeriodSecondsSafe(timeframe);
   if(period_seconds <= 0)
      period_seconds = 60;

   int chunk_seconds = InpTickChunkHours > 0 ? InpTickChunkHours * 3600 : 86400;
   datetime tick_from_time = first_bar_time;
   if(InpTickLookbackDays > 0)
   {
      datetime lookback_from = (datetime)((long)last_bar_time - (long)InpTickLookbackDays * 86400);
      if(tick_from_time < lookback_from)
      {
         tick_from_time = lookback_from;
         g_tick_range_limited = true;
      }
   }

   if(tick_from_time > last_bar_time)
      tick_from_time = first_bar_time;

   g_tick_export_from = tick_from_time;
   g_tick_export_to = last_bar_time;
   if(g_tick_range_limited)
      g_tick_note = StringFormat("Tick export was limited to the last %d day(s). Candles remain fully exported.", InpTickLookbackDays);

   ulong from_msc = (ulong)tick_from_time * 1000;
   ulong to_msc = ((ulong)last_bar_time + (ulong)period_seconds) * 1000 - 1;
   ulong chunk_msc = (ulong)chunk_seconds * 1000;
   ulong total_range_msc = to_msc >= from_msc ? (to_msc - from_msc + 1) : 0;
   long total = 0;
   long consecutive_errors = 0;
   long consecutive_empty = 0;
   datetime started_at = TimeCurrent();
   string timeframe_text = TimeframeToString(timeframe);

   FileWrite(handle, "time", "time_msc", "bid", "ask", "last", "volume", "volume_real", "flags");
   ReportProgress("Preparando export de ticks", symbol, timeframe_text, 0.0, bars_exported, bars_exported, 0, InpMaxTicks, 0, total_range_msc, started_at, true);
   if(g_tick_range_limited)
   {
      Print("[BacktestCore Export] Tick range limited by InpTickLookbackDays=",
            InpTickLookbackDays,
            " | candle_start=", TimeToString(first_bar_time, TIME_DATE | TIME_MINUTES),
            " tick_start=", TimeToString(tick_from_time, TIME_DATE | TIME_MINUTES),
            " tick_end=", TimeToString(last_bar_time, TIME_DATE | TIME_MINUTES));
   }

   ulong first_probe_to = from_msc + chunk_msc - 1;
   if(first_probe_to > to_msc || first_probe_to < from_msc)
      first_probe_to = to_msc;
   ProbeTickAccess(symbol, from_msc, first_probe_to);
   WarmupTickHistory(symbol, from_msc);

   for(ulong chunk_from = from_msc; chunk_from <= to_msc;)
   {
      ulong chunk_to = chunk_from + chunk_msc - 1;
      if(chunk_to > to_msc || chunk_to < chunk_from)
         chunk_to = to_msc;

      MqlTick ticks[];
      ArraySetAsSeries(ticks, false);
      ResetLastError();
      int copied = CopyTicksRange(symbol, ticks, COPY_TICKS_ALL, chunk_from, chunk_to);
      if(copied < 0)
      {
         int err = GetLastError();
         g_tick_error_chunks++;
         consecutive_errors++;
         g_tick_last_error = err;
         ulong failed_done_msc = chunk_from > from_msc ? (chunk_from - from_msc) : 0;
         double failed_pct = total_range_msc > 0 ? (double)failed_done_msc * 100.0 / (double)total_range_msc : 0.0;
         ReportProgress("Erro ao copiar ticks", symbol, timeframe_text, failed_pct, bars_exported, bars_exported, total, InpMaxTicks, failed_done_msc, total_range_msc, started_at, true);
         Print("CopyTicksRange failed for ", symbol, " error=", err, " from=", chunk_from, " to=", chunk_to);
         if(InpTickFallbackCount > 0)
         {
            MqlTick fallback_ticks[];
            ArraySetAsSeries(fallback_ticks, false);
            ResetLastError();
            int fallback_copied = CopyTicks(symbol, fallback_ticks, COPY_TICKS_ALL, chunk_from, (uint)InpTickFallbackCount);
            int fallback_error = GetLastError();
            Print("[BacktestCore Export] CopyTicks fallback | copied=",
                  fallback_copied,
                  " error=", fallback_error,
                  " from=", chunk_from,
                  " max_count=", InpTickFallbackCount);
            if(fallback_copied > 0)
            {
               int fallback_written = 0;
               for(int j = 0; j < fallback_copied; j++)
               {
                  if(fallback_ticks[j].time_msc > chunk_to)
                     break;
                  if(fallback_ticks[j].time_msc < chunk_from)
                     continue;
                  if(InpMaxTicks > 0 && total >= InpMaxTicks)
                     break;

                  FileWrite(
                     handle,
                     TimeToString(fallback_ticks[j].time, TIME_DATE | TIME_SECONDS),
                     IntegerToString(fallback_ticks[j].time_msc),
                     DoubleToString(fallback_ticks[j].bid, digits),
                     DoubleToString(fallback_ticks[j].ask, digits),
                     DoubleToString(fallback_ticks[j].last, digits),
                     IntegerToString((long)fallback_ticks[j].volume),
                     D(fallback_ticks[j].volume_real),
                     IntegerToString((int)fallback_ticks[j].flags)
                  );
                  total++;
                  fallback_written++;
               }
               FileFlush(handle);
               if(fallback_written > 0)
               {
                  consecutive_errors = 0;
                  Print("[BacktestCore Export] CopyTicks fallback wrote ",
                        fallback_written,
                        " tick(s) for failed range chunk.");
                  if(chunk_to >= to_msc)
                     break;
                  chunk_from = chunk_to + 1;
                  continue;
               }
            }
            ResetLastError();
         }
         if(InpAbortOnTickError)
         {
            FileClose(handle);
            Comment("");
            return -1;
         }
         if(InpMaxTickErrorChunks > 0 && consecutive_errors >= InpMaxTickErrorChunks)
         {
            if(g_tick_note != "")
               g_tick_note += " ";
            g_tick_note += StringFormat("Tick export stopped after %d consecutive failed CopyTicksRange chunk(s).", (int)consecutive_errors);
            Print("[BacktestCore Export] Stopping tick export after ",
                  consecutive_errors,
                  " consecutive failed chunks. Candles/spec files will still be exported.");
            break;
         }
         ResetLastError();
         if(chunk_to >= to_msc)
            break;
         chunk_from = chunk_to + 1;
         continue;
      }

      consecutive_errors = 0;
      if(copied == 0)
      {
         g_tick_empty_chunks++;
         consecutive_empty++;
         // Broker has no tick history for this window: bail out instead of grinding
         // through thousands of empty chunks, so the package STILL FINALIZES with
         // candles + spec (just no ticks.csv content). Only triggers while we've
         // gathered no ticks yet, so a gap inside otherwise-good data won't stop it.
         if(InpMaxEmptyTickChunks > 0 && total == 0 && consecutive_empty >= InpMaxEmptyTickChunks)
         {
            if(g_tick_note != "")
               g_tick_note += " ";
            g_tick_note += StringFormat("No ticks from broker after %d consecutive empty chunk(s) — exported candles + spec only.", (int)consecutive_empty);
            Print("[BacktestCore Export] No ticks from broker after ", consecutive_empty,
                  " empty chunks. Finalizing package WITHOUT ticks (candles/spec are fine).");
            break;
         }
      }
      else
         consecutive_empty = 0;

      for(int i = 0; i < copied; i++)
      {
         if(InpMaxTicks > 0 && total >= InpMaxTicks)
         {
            FileClose(handle);
            ulong capped_done_msc = chunk_to >= from_msc ? (chunk_to - from_msc + 1) : 0;
            double capped_pct = total_range_msc > 0 ? (double)capped_done_msc * 100.0 / (double)total_range_msc : 100.0;
            ReportProgress("Cap de ticks atingido", symbol, timeframe_text, capped_pct, bars_exported, bars_exported, total, InpMaxTicks, capped_done_msc, total_range_msc, started_at, true);
            Print("Tick export reached InpMaxTicks=", InpMaxTicks, ". Increase the cap if you need the full range.");
            Comment("");
            return total;
         }

         FileWrite(
            handle,
            TimeToString(ticks[i].time, TIME_DATE | TIME_SECONDS),
            IntegerToString(ticks[i].time_msc),
            DoubleToString(ticks[i].bid, digits),
            DoubleToString(ticks[i].ask, digits),
            DoubleToString(ticks[i].last, digits),
            IntegerToString((long)ticks[i].volume),
            D(ticks[i].volume_real),
            IntegerToString((int)ticks[i].flags)
         );
         total++;
      }

      FileFlush(handle);
      ulong done_msc = chunk_to >= from_msc ? (chunk_to - from_msc + 1) : 0;
      double progress_pct = total_range_msc > 0 ? (double)done_msc * 100.0 / (double)total_range_msc : 100.0;
      ReportProgress("Exportando ticks", symbol, timeframe_text, progress_pct, bars_exported, bars_exported, total, InpMaxTicks, done_msc, total_range_msc, started_at);

      if(chunk_to >= to_msc)
         break;
      chunk_from = chunk_to + 1;
   }

   FileClose(handle);
   if(total == 0)
   {
      if(g_tick_note != "")
         g_tick_note += " ";
      g_tick_note += "No real ticks were returned by the terminal/broker for the requested tick window.";
      Print("[BacktestCore Export] Warning: ticks.csv has 0 ticks. Try lowering the date range, increasing broker history, or setting InpTickLookbackDays=0 only if the terminal has the full tick history.");
   }
   else if(g_tick_error_chunks > 0)
   {
      if(g_tick_note != "")
         g_tick_note += " ";
      g_tick_note += StringFormat("%d tick chunk(s) failed and were skipped.", (int)g_tick_error_chunks);
   }
   ReportProgress("Ticks concluídos", symbol, timeframe_text, 100.0, bars_exported, bars_exported, total, InpMaxTicks, total_range_msc, total_range_msc, started_at, true);
   Comment("");
   return total;
}

void OnStart()
{
   string symbol = InpSymbol == "" ? _Symbol : InpSymbol;
   ENUM_TIMEFRAMES timeframe = InpTimeframe == PERIOD_CURRENT ? (ENUM_TIMEFRAMES)_Period : InpTimeframe;
   string timeframe_text = TimeframeToString(timeframe);
   int flags = InpUseCommonFiles ? FILE_COMMON : 0;
   datetime started_at = TimeCurrent();

   if(!SymbolSelect(symbol, true))
   {
      Print("Could not select symbol: ", symbol);
      return;
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int bars_to_copy = InpBars > 0 ? InpBars : Bars(symbol, timeframe);
   if(bars_to_copy <= 0)
   {
      Print("No bars available for ", symbol, " ", TimeframeToString(timeframe), " error=", GetLastError());
      return;
   }

   int copied = CopyRates(symbol, timeframe, 0, bars_to_copy, rates);
   if(copied <= 0)
   {
      Print("CopyRates failed for ", symbol, " ", TimeframeToString(timeframe), " error=", GetLastError());
      return;
   }

   ReportProgress("Preparando candles", symbol, timeframe_text, 5.0, 0, copied, 0, InpMaxTicks, 0, 0, started_at, true);

   string broker = AccountInfoString(ACCOUNT_COMPANY);
   if(broker == "")
      broker = AccountInfoString(ACCOUNT_SERVER);
   if(broker == "")
      broker = "UnknownBroker";

   StringReplace(broker, "\\", "-");
   StringReplace(broker, "/", "-");
   StringReplace(broker, ":", "-");

   string tf = TimeframeToString(timeframe);
   string folder = JoinPath(JoinPath(JoinPath(InpOutputRoot, broker), symbol), tf);
   EnsureFolder(folder, flags);

   string candles_path = JoinPath(folder, "candles.csv");
   int csv = FileOpen(candles_path, FILE_WRITE | FILE_CSV | FILE_ANSI | flags, ',');
   if(csv == INVALID_HANDLE)
   {
      Print("Failed to open candles CSV: ", candles_path, " error=", GetLastError());
      return;
   }

   FileWrite(csv, "time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume");

   // CopyRates can be terminal-dependent in orientation. Export sorted oldest -> newest.
   bool ascending = rates[0].time <= rates[copied - 1].time;
   for(int n = 0; n < copied; n++)
   {
      int i = ascending ? n : copied - 1 - n;
      FileWrite(
         csv,
         TimeToString(rates[i].time, TIME_DATE | TIME_MINUTES),
         DoubleToString(rates[i].open, _Digits),
         DoubleToString(rates[i].high, _Digits),
         DoubleToString(rates[i].low, _Digits),
         DoubleToString(rates[i].close, _Digits),
         (long)rates[i].tick_volume,
         (int)rates[i].spread,
         (long)rates[i].real_volume
      );

      if((n + 1) == copied || ((n + 1) % 5000) == 0)
      {
         double candles_pct = 5.0 + ((double)(n + 1) * 15.0 / (double)copied);
         ReportProgress("Exportando candles", symbol, timeframe_text, candles_pct, n + 1, copied, 0, InpMaxTicks, 0, 0, started_at, (n + 1) == copied);
      }
   }
   FileClose(csv);

   datetime first_time = ascending ? rates[0].time : rates[copied - 1].time;
   datetime last_time = ascending ? rates[copied - 1].time : rates[0].time;
   ReportProgress("Candles concluídos", symbol, timeframe_text, InpExportTicks ? 20.0 : 85.0, copied, copied, 0, InpMaxTicks, 0, 0, started_at, true);
   long ticks_exported = WriteTicksCsv(JoinPath(folder, "ticks.csv"), symbol, first_time, last_time, timeframe, copied, flags);
   if(ticks_exported < 0)
      ticks_exported = 0;

   ReportProgress("Gravando manifesto", symbol, timeframe_text, 95.0, copied, copied, ticks_exported, InpMaxTicks, 0, 0, started_at, true);
   WriteSymbolSpec(JoinPath(folder, "symbol_spec.json"), symbol, timeframe, flags);
   WriteAccountSpec(JoinPath(folder, "account_spec.json"), flags);
   WriteManifest(JoinPath(folder, "export_manifest.json"), folder, symbol, timeframe, copied, ticks_exported, first_time, last_time, InpUseCommonFiles, flags);
   ReportProgress("Export concluído", symbol, timeframe_text, 100.0, copied, copied, ticks_exported, InpMaxTicks, 0, 0, started_at, true);
   Comment("");

   Print("BacktestCore package exported:");
   Print("  ", folder);
   Print("Copy/import this whole folder. It contains the full package for this broker/symbol/timeframe.");
   Print("Files:");
   Print("  candles.csv");
   if(InpExportTicks)
      Print("  ticks.csv (", ticks_exported, " ticks)");
   Print("  symbol_spec.json");
   Print("  account_spec.json");
   Print("  export_manifest.json");
}
