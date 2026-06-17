#property tester_file "ZonasManual_XAUUSDm_H1.csv"

#include <Trade\Trade.mqh>
#include <ChartObjects\ChartObjectsTxtControls.mqh>
#include <ChartObjects\ChartObjectsShapes.mqh>

struct ZonaManual
{
   datetime tempo_ini;
   datetime tempo_fim;
   double topo;
   double fundo;
   string tipo; // "S" = suporte, "R" = resistência
   bool valida; // true por padrão
   ENUM_TIMEFRAMES tf_origin; // TF de origem da zona; PERIOD_CURRENT = desconhecida (usa _Period)
};

ZonaManual zonas[];

CTrade trade;

// === INPUTS PRINCIPAIS ===

// Preset único de TF (Exaustão > Confirmação por média)
enum ENUM_TF_PRESET
{
    TF_D1_H1 = 0,   // D1 > H1
    TF_H4_M15 = 1,  // H4 > M15
    TF_H1_M5 = 2,   // H1 > M5
    TF_M15_M1 = 3   // M15 > M1
};
input ENUM_TF_PRESET TFPreset = TF_M15_M1;

// === Indicadores ===
#define RSI_Buy   27.0
#define RSI_Sell  72.0
#define RSI_Period 14

// === Risco e trade ===
input double TakeProfitFactor = 3.0;
input double Lote = 0.10;
input double PercentualRisco = 2.0;
input bool ExibirPainelSwap = true;
input int SwapPainelAtualizaSeg = 60;
input int SwapPainelProjecaoDias = 5;

// === Modo de operação ===
enum ENUM_MODO_OPERACAO
{
    MODO_COM_CONFIRMACAO = 0,
    MODO_SEM_CONFIRMACAO = 1,
    MODO_AMBOS = 2
};

input ENUM_MODO_OPERACAO ModoOperacao = MODO_COM_CONFIRMACAO;


// === Cooldown ===
input int CooldownHoras = 4;

// === S&R GPT — Configurações fixas do módulo AI Zones ===
#define GPT_TIMER_SEC       5
#define GPT_CANDLES         500
#define GPT_SUPPORT_COLOR   clrLimeGreen
#define GPT_RESIST_COLOR    clrRed
#define GPT_LOOKBACK_BARS   200
#define GPT_EXTEND_BARS     80
#define GPT_FONT_SIZE       8
#define GPT_EXPORT_EVERY    604800   // 7 dias; exportacao manual pelo botao quando precisar
#define GPT_ALERT_POPUP     true
#define GPT_ALERT_SOUND     true
#define GPT_ALERT_PUSH      true

// === Configurações fixas ===
#define MaxPorLado_Ambos 2
#define Magic 77777
#define SL_RECUO_ZONA_PCT 50.0

// Timeframes derivados do preset
ENUM_TIMEFRAMES TimeFrame = PERIOD_M15;
ENUM_TIMEFRAMES Execucao_TF = PERIOD_M1;

int deslocamento = 10;
datetime ultimaStopTime = 0;
bool bloqueado = false;
int CooldownSegundos = 0;

// === S&R GPT — Globals do módulo AI Zones ===
string         g_gpt_prefix    = "SRAI_";
string         g_gpt_lastJson  = "";
string         g_gpt_jsonFile  = "";
datetime       g_gpt_lastExport = 0;
bool           g_gpt_persistenceBusy = false;

// === Cooldown helpers ===
inline bool EmCooldown()
{
   return (bloqueado && (TimeCurrent() - ultimaStopTime) < CooldownSegundos);
}

inline bool EncerrarCooldownSePreciso()
{
   if (bloqueado && (TimeCurrent() - ultimaStopTime) >= CooldownSegundos)
   {
      bloqueado = false;
      Print("✅ Cooldown encerrado — reativando entradas.");
      return true;
   }
   return false;
}

inline void IniciarCooldown()
{
   bloqueado      = true;
   ultimaStopTime = TimeCurrent();
   PrintFormat("⏸️ Cooldown iniciado por %dh após SL. Até %s",
               CooldownHoras,
               TimeToString(ultimaStopTime + CooldownSegundos, TIME_MINUTES));
}


// === LOG CONTROLADO (sem flood por tipo) ===
void SafeLog(string msg, int minIntervalSec = 60, string key = "")
{
   static string keys[100];
   static datetime lastTimes[100];
   static int count = 0;

   datetime now = TimeCurrent();
   string id = (key == "") ? msg : key;

   for (int i = 0; i < count; i++)
   {
      if (keys[i] == id)
      {
         if ((now - lastTimes[i]) < minIntervalSec)
            return;

         lastTimes[i] = now;
         Print(msg);
         return;
      }
   }

   if (count < 100)
   {
      keys[count] = id;
      lastTimes[count] = now;
      count++;
   }

   Print(msg);
}

// === Controle de janela de espera ===
bool aguardandoCompra = false;
bool aguardandoVenda  = false;

// === Controle por janela (MODO_AMBOS) ===
bool compraSemFeita=false, compraComFeita=false;
bool vendaSemFeita=false, vendaComFeita=false;
bool manualBuySemFeita=false, manualBuyComFeita=false;
bool manualSellSemFeita=false, manualSellComFeita=false;

// Controle de logs de saída de zona
static bool foraZonaCompra = false;
static bool foraZonaVenda = false;

// === Controle de logs anti-flood ===
datetime ultimoLogCompraManual = 0;
datetime ultimoLogVendaManual  = 0;
datetime ultimoLogSaidaCompra  = 0;
datetime ultimoLogSaidaVenda   = 0;
int intervaloLogJanelaSegundos = 900;
int intervaloLogSaidaSegundos  = 900;

datetime tempoInicioAguardarCompra = 0;
datetime tempoInicioAguardarVenda  = 0;
double zonaCompraMin = 0.0, zonaCompraMax = 0.0;
double zonaVendaMin  = 0.0, zonaVendaMax  = 0.0;
datetime zonaCompraTempoIni = 0, zonaCompraTempoFim = 0;
datetime zonaVendaTempoIni  = 0, zonaVendaTempoFim  = 0;
string tipoZonaPendente = "";
bool aguardandoSegundoPontoZona = false;
datetime zonaTempoPonto1 = 0;
double zonaPrecoPonto1 = 0.0;

// === Limite de posições totais por ativo (BUY+SELL somadas) ===
input int MaxOrdensPorAtivo = 2;

// === Helpers de contagem ===
int CountOpenPositionsAny()
{
   int count = 0;
   for (int i = 0; i < PositionsTotal(); i++)
   {
      ulong tk = PositionGetTicket(i);
      if (!PositionSelectByTicket(tk)) continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      long magic     = (long)PositionGetInteger(POSITION_MAGIC);

      if (symbol == _Symbol && magic == Magic)
         count++;
   }
   return count;
}


bool ExisteSemConfirmacaoLado(ENUM_POSITION_TYPE side){
   for(int i=0;i<PositionsTotal();i++){
      ulong tk=PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=(long)Magic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE)!=side) continue;

      string c = PositionGetString(POSITION_COMMENT);
      if(StringFind(c,"|SEM|")>=0 || StringFind(c,"(SEM confirmação)")>=0)
         return true;
   }
   return false;
}

bool PodeAbrirNovaOrdem(ENUM_POSITION_TYPE side, bool semConfirmacao){
   if(CountOpenPositionsAny() >= MaxOrdensPorAtivo)
      return false;

   if(semConfirmacao && ExisteSemConfirmacaoLado(side))
      return false;

   return true;
}

double CalcularRecuoSLDaZona(const double zonaMin, const double zonaMax)
{
   double altura = MathAbs(zonaMax - zonaMin);
   double recuo = altura * (SL_RECUO_ZONA_PCT / 100.0);
   if (recuo < 0.0)
      recuo = 0.0;
   return recuo;
}

double CalcularSLCompraDaZona(const double zonaMin, const double zonaMax)
{
   return NormalizeDouble(zonaMin - CalcularRecuoSLDaZona(zonaMin, zonaMax), _Digits);
}

double CalcularSLVendaDaZona(const double zonaMin, const double zonaMax)
{
   return NormalizeDouble(zonaMax + CalcularRecuoSLDaZona(zonaMin, zonaMax), _Digits);
}

bool PrecoDentroDaZona(const double preco, const double zonaMin, const double zonaMax)
{
   return (preco >= zonaMin && preco <= zonaMax);
}

bool TempoDentroDaZona(const datetime agora, const datetime zonaIni, const datetime zonaFim)
{
   if (zonaIni <= 0 || zonaFim <= 0)
      return true;

   datetime ini = (zonaIni < zonaFim) ? zonaIni : zonaFim;
   datetime fim = (zonaIni > zonaFim) ? zonaIni : zonaFim;
   return (agora >= ini && agora <= fim);
}

bool AgoraDentroDaJanelaDoRetangulo(const string nome, const datetime agora)
{
   datetime t1 = (datetime)ObjectGetInteger(0, nome, OBJPROP_TIME, 0);
   datetime t2 = (datetime)ObjectGetInteger(0, nome, OBJPROP_TIME, 1);
   if (t1 <= 0 || t2 <= 0)
      return true;

   datetime ini = (t1 < t2) ? t1 : t2;
   datetime fim = (t1 > t2) ? t1 : t2;
   return (agora >= ini && agora <= fim);
}

long   janelaCompraId = 0, janelaVendaId = 0;
ulong  ticketBuySem   = 0, ticketBuyCom   = 0;
ulong  ticketSellSem  = 0, ticketSellCom  = 0;

int suporteIdxSel    = -1, resistenciaIdxSel = -1;
int janelaCompraZonaIdx = -1, janelaVendaZonaIdx = -1;
ENUM_TIMEFRAMES janelaCompraTF = PERIOD_CURRENT, janelaVendaTF = PERIOD_CURRENT;

void ResetJanelaCompra(){
   aguardandoCompra=false;
   compraSemFeita=false; compraComFeita=false;
   zonaCompraMin=0.0; zonaCompraMax=0.0;
   zonaCompraTempoIni=0; zonaCompraTempoFim=0;
   tempoInicioAguardarCompra=0;
   janelaCompraId=0; ticketBuySem=0; ticketBuyCom=0;
}

void ResetJanelaVenda(){
   aguardandoVenda=false;
   vendaSemFeita=false; vendaComFeita=false;
   zonaVendaMin=0.0; zonaVendaMax=0.0;
   zonaVendaTempoIni=0; zonaVendaTempoFim=0;
   tempoInicioAguardarVenda=0;
   janelaVendaId=0; ticketSellSem=0; ticketSellCom=0;
}

int CountOpenPositionsSide(ENUM_POSITION_TYPE side)
{
   int count = 0;
   for (int i = 0; i < PositionsTotal(); i++)
   {
      ulong tk = PositionGetTicket(i);
      if (!PositionSelectByTicket(tk)) continue;

      if (PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if ((long)PositionGetInteger(POSITION_MAGIC) != (long)Magic) continue;

      if ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == side)
         count++;
   }
   return count;
}

bool ExistePosicaoPorComentario(const string &comment){
   for(int i=0;i<PositionsTotal();i++){
      ulong tk=PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=(long)Magic) continue;
      string c = PositionGetString(POSITION_COMMENT);
      if(c==comment) return true;
   }
   return false;
}


int segundosJanela = 0;

bool usarUltOsc = true;
bool usarConfirmacaoMedia = true;
datetime ultimoUpdatePainelSwap = 0;

// === Confirmação ancorada na TF da zona ===
// Osciladores (exaustão) rodam na TF da zona; SMA60 (gatilho) na TF abaixo.

// Cache de handles de indicadores por timeframe (criados sob demanda).
struct TFHandles
{
   ENUM_TIMEFRAMES tf;
   int rsi;
   int stoch;
   int ultosc;
   int sma;
};
TFHandles g_tfCache[];

int GarantirCacheTF(ENUM_TIMEFRAMES tf)
{
   for(int i = 0; i < ArraySize(g_tfCache); i++)
      if(g_tfCache[i].tf == tf)
         return i;

   TFHandles h;
   h.tf     = tf;
   h.rsi    = iRSI(_Symbol, tf, RSI_Period, PRICE_CLOSE);
   h.stoch  = iStochastic(_Symbol, tf, 50, 3, 3, MODE_SMA, STO_LOWHIGH);
   h.ultosc = usarUltOsc ? iCustom(_Symbol, tf, "Ultimate_Oscillator") : INVALID_HANDLE;
   h.sma    = usarConfirmacaoMedia ? iMA(_Symbol, tf, 60, 0, MODE_SMA, PRICE_CLOSE) : INVALID_HANDLE;

   int n = ArraySize(g_tfCache);
   ArrayResize(g_tfCache, n + 1);
   g_tfCache[n] = h;
   return n;
}

int RSIHandle(ENUM_TIMEFRAMES tf)    { return g_tfCache[GarantirCacheTF(tf)].rsi; }
int StochHandle(ENUM_TIMEFRAMES tf)  { return g_tfCache[GarantirCacheTF(tf)].stoch; }
int UltOscHandle(ENUM_TIMEFRAMES tf) { return g_tfCache[GarantirCacheTF(tf)].ultosc; }
int SMAHandle(ENUM_TIMEFRAMES tf)    { return g_tfCache[GarantirCacheTF(tf)].sma; }

// Garante o cache da TF e valida que RSI/Estocástico (e SMA, se em uso) foram criados.
bool ValidarCacheTF(ENUM_TIMEFRAMES tf)
{
   int idx = GarantirCacheTF(tf);
   if (g_tfCache[idx].rsi == INVALID_HANDLE || g_tfCache[idx].stoch == INVALID_HANDLE)
   {
      PrintFormat("Erro ao criar handles de RSI/Estocástico para TF %s", EnumToString(tf));
      return false;
   }
   if (usarConfirmacaoMedia && g_tfCache[idx].sma == INVALID_HANDLE)
   {
      PrintFormat("Erro ao criar handle da SMA60 para TF %s", EnumToString(tf));
      return false;
   }
   return true;
}

// Texto de timeframe (W1/D1/H4/H1, sinônimos e "PERIOD_*") -> enum; desconhecido -> PERIOD_CURRENT.
ENUM_TIMEFRAMES TFFromText(string s)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   StringToUpper(s);
   StringReplace(s, " ", "");
   StringReplace(s, "PERIOD_", "");
   if(s == "W1" || s == "1W" || s == "WEEKLY" || s == "WEEK" || s == "W") return PERIOD_W1;
   if(s == "D1" || s == "1D" || s == "DAILY"  || s == "DAY"  || s == "D") return PERIOD_D1;
   if(s == "H4" || s == "4H" || s == "240")                               return PERIOD_H4;
   if(s == "H1" || s == "1H" || s == "60" || s == "HOURLY" || s == "H")   return PERIOD_H1;
   return PERIOD_CURRENT;
}

// TF efetiva da zona: desconhecida -> TF do gráfico.
ENUM_TIMEFRAMES TFZonaEfetiva(ENUM_TIMEFRAMES tfZona)
{
   return (tfZona == PERIOD_CURRENT) ? (ENUM_TIMEFRAMES)_Period : tfZona;
}

// TF do gatilho (cruzamento SMA60): uma escala abaixo, conforme esquemática original.
ENUM_TIMEFRAMES GatilhoTF(ENUM_TIMEFRAMES tfZona)
{
   switch(tfZona)
   {
      case PERIOD_W1: return PERIOD_D1;
      case PERIOD_D1: return PERIOD_H1;
      case PERIOD_H4: return PERIOD_M15;
      case PERIOD_H1: return PERIOD_M5;
      default:        return Execucao_TF; // zona desconhecida -> execução do preset
   }
}

// Lê osciladores na TF informada; false se algum buffer ainda não estiver pronto.
bool LerOsciladoresTF(ENUM_TIMEFRAMES tf, double &rsiOut, double &stochOut,
                      bool &ultoscBuyOk, bool &ultoscSellOk)
{
   ultoscBuyOk  = true;
   ultoscSellOk = true;
   rsiOut   = 50.0;
   stochOut = 50.0;

   double rsi[];
   ArraySetAsSeries(rsi, true);
   if(CopyBuffer(RSIHandle(tf), 0, 1, 1, rsi) <= 0)
      return false;
   rsiOut = rsi[0];

   double stoch_k[];
   ArraySetAsSeries(stoch_k, true);
   if(CopyBuffer(StochHandle(tf), 0, 1, 1, stoch_k) <= 0)
      return false;
   stochOut = stoch_k[0];

   if(usarUltOsc)
   {
      double ultosc[];
      ArraySetAsSeries(ultosc, true);
      if(CopyBuffer(UltOscHandle(tf), 0, 1, 1, ultosc) <= 0)
         return false;
      ultoscBuyOk  = (ultosc[0] < 30);
      ultoscSellOk = (ultosc[0] > 70);
   }
   return true;
}

// Casa a zona tocada (tipo + faixa de preço) com zonas[] e devolve a TF de origem.
ENUM_TIMEFRAMES TFDaZonaCasada(string tipo, double zMin, double zMax)
{
   ENUM_TIMEFRAMES best = PERIOD_CURRENT;
   double bestOverlap = 0.0;
   for(int i = 0; i < ArraySize(zonas); i++)
   {
      if(!zonas[i].valida) continue;
      if(zonas[i].tipo != tipo) continue;
      double zf = MathMin(zonas[i].topo, zonas[i].fundo);
      double zt = MathMax(zonas[i].topo, zonas[i].fundo);
      double overlap = MathMin(zMax, zt) - MathMax(zMin, zf);
      if(overlap > bestOverlap)
      {
         bestOverlap = overlap;
         best = zonas[i].tf_origin;
      }
   }
   return best;
}

#define SWAP_PANEL_PREFIX "PAINEL_SWAP_"

//+------------------------------------------------------------------+
//| S&R GPT — JSON parser helpers (manual, sem JAson.mqh)            |
//+------------------------------------------------------------------+
int GPT_FindMatchingBracket(const string text, const int open_pos,
                            const ushort open_char, const ushort close_char)
{
   int depth = 0;
   bool in_string = false;
   bool escaped = false;
   for(int i = open_pos; i < StringLen(text); i++)
   {
      ushort ch = StringGetCharacter(text, i);
      if(in_string)
      {
         if(escaped) { escaped = false; continue; }
         if(ch == '\\') { escaped = true; continue; }
         if(ch == '"') in_string = false;
         continue;
      }
      if(ch == '"') { in_string = true; continue; }
      if(ch == open_char) depth++;
      else if(ch == close_char)
      {
         depth--;
         if(depth == 0) return i;
      }
   }
   return -1;
}

string GPT_ExtractStringValue(const string text, const string key)
{
   string marker = "\"" + key + "\"";
   int kp = StringFind(text, marker);
   if(kp < 0) return "";

   int colon = StringFind(text, ":", kp + StringLen(marker));
   if(colon < 0) return "";

   int quote1 = StringFind(text, "\"", colon + 1);
   if(quote1 < 0) return "";
   quote1++;

   int quote2 = quote1;
   bool escaped = false;
   while(quote2 < StringLen(text))
   {
      ushort ch = StringGetCharacter(text, quote2);
      if(escaped) { escaped = false; quote2++; continue; }
      if(ch == '\\') { escaped = true; quote2++; continue; }
      if(ch == '"') break;
      quote2++;
   }
   return StringSubstr(text, quote1, quote2 - quote1);
}

bool GPT_ExtractNumber(const string text, const string key, double &value)
{
   string marker = "\"" + key + "\"";
   int kp = StringFind(text, marker);
   if(kp < 0) return false;

   int colon = StringFind(text, ":", kp + StringLen(marker));
   if(colon < 0) return false;

   int start = colon + 1;
   while(start < StringLen(text))
   {
      ushort ch = StringGetCharacter(text, start);
      if(ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n') break;
      start++;
   }

   int end = start;
   while(end < StringLen(text))
   {
      ushort ch = StringGetCharacter(text, end);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '+')
         { end++; continue; }
      break;
   }

   if(end == start) return false;
   value = StringToDouble(StringSubstr(text, start, end - start));
   return true;
}

string GPT_ExtractArray(const string text, const string key)
{
   string marker = "\"" + key + "\"";
   int kp = StringFind(text, marker);
   if(kp < 0) return "";

   int start = StringFind(text, "[", kp);
   if(start < 0) return "";

   int end = GPT_FindMatchingBracket(text, start, '[', ']');
   if(end < 0) return "";

   return StringSubstr(text, start, end - start + 1);
}

//+------------------------------------------------------------------+
//| S&R GPT — CSV Export (OHLCV para Python)                         |
//+------------------------------------------------------------------+
void GPT_ExportTimeframe(ENUM_TIMEFRAMES tf, string tfName)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, true);

   int copied = CopyRates(_Symbol, tf, 0, GPT_CANDLES, rates);
   if(copied <= 0) return;

   string filename = "sr_gpt_" + _Symbol + "_" + tfName + ".csv";
   int handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE) return;

   FileWrite(handle, "time", "open", "high", "low", "close", "tick_volume", "spread");

   for(int j = copied - 1; j >= 0; j--)
   {
      FileWrite(handle,
         TimeToString(rates[j].time, TIME_DATE | TIME_MINUTES),
         DoubleToString(rates[j].open, _Digits),
         DoubleToString(rates[j].high, _Digits),
         DoubleToString(rates[j].low, _Digits),
         DoubleToString(rates[j].close, _Digits),
         IntegerToString(rates[j].tick_volume),
         IntegerToString(rates[j].spread)
      );
   }

   FileClose(handle);
}

void GPT_ExportAllTimeframes()
{
   GPT_ExportTimeframe(PERIOD_W1, "W1");
   GPT_ExportTimeframe(PERIOD_D1, "D1");
   GPT_ExportTimeframe(PERIOD_H4, "H4");
   GPT_ExportTimeframe(PERIOD_H1, "H1");
   g_gpt_lastExport = TimeLocal();
   PrintFormat("S&R GPT: Exported CSVs for %s (W1/D1/H4/H1)", _Symbol);
}

datetime GPT_OldestCsvExportTime()
{
   string files[4];
   files[0] = "sr_gpt_" + _Symbol + "_W1.csv";
   files[1] = "sr_gpt_" + _Symbol + "_D1.csv";
   files[2] = "sr_gpt_" + _Symbol + "_H4.csv";
   files[3] = "sr_gpt_" + _Symbol + "_H1.csv";

   datetime oldest = 0;
   for(int i = 0; i < 4; i++)
   {
      if(!FileIsExist(files[i]))
         return 0;
      datetime modified = (datetime)FileGetInteger(files[i], FILE_MODIFY_DATE, false);
      if(modified <= 0)
         return 0;
      if(oldest == 0 || modified < oldest)
         oldest = modified;
   }

   return oldest;
}

bool GPT_CsvExportIsStale()
{
   datetime oldest = GPT_OldestCsvExportTime();
   if(oldest <= 0)
      return true;

   g_gpt_lastExport = oldest;
   return (TimeLocal() - oldest >= GPT_EXPORT_EVERY);
}

void GPT_ExportAllTimeframesIfNeeded(const bool force, const string reason)
{
   if(force || GPT_CsvExportIsStale())
   {
      GPT_ExportAllTimeframes();
      PrintFormat("S&R GPT: CSV export trigger: %s", reason);
   }
}

//+------------------------------------------------------------------+
//| S&R GPT — Symbol list management                                 |
//+------------------------------------------------------------------+
void GPT_UpdateSymbolList()
{
   string listFile = "sr_gpt_symbols.txt";
   string existing = "";

   if(FileIsExist(listFile))
   {
      int rh = FileOpen(listFile, FILE_READ | FILE_TXT | FILE_ANSI);
      if(rh != INVALID_HANDLE)
      {
         while(!FileIsEnding(rh))
            existing += FileReadString(rh) + "\n";
         FileClose(rh);
      }
   }

   if(StringFind(existing, _Symbol) >= 0)
      return;

   int wh = FileOpen(listFile, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(wh == INVALID_HANDLE) return;
   FileSeek(wh, 0, SEEK_END);
   FileWriteString(wh, _Symbol + "\n");
   FileClose(wh);
}

//+------------------------------------------------------------------+
//| S&R GPT — Read text file                                         |
//+------------------------------------------------------------------+
string GPT_ReadTextFile(const string filename)
{
   ResetLastError();
   int handle = FileOpen(filename, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE) return "";

   string text = "";
   while(!FileIsEnding(handle))
      text += FileReadString(handle);
   FileClose(handle);
   return text;
}

string GPT_ManualZonesFile()
{
   return "sr_zones_manual_" + _Symbol + ".csv";
}

datetime GPT_FileModifyTime(const string filename)
{
   if(!FileIsExist(filename))
      return 0;
   return (datetime)FileGetInteger(filename, FILE_MODIFY_DATE, false);
}

bool GPT_IsZoneObjectName(const string name)
{
   return (StringFind(name, "ZONA_SUPORTE") == 0 ||
           StringFind(name, "ZONA_RESISTENCIA") == 0);
}

bool GPT_SaveCurrentZones(const string reason)
{
   if(MQLInfoInteger(MQL_TESTER) || g_gpt_persistenceBusy)
      return false;

   string filename = GPT_ManualZonesFile();
   int handle = FileOpen(filename, FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("S&R GPT: falha ao salvar ajustes manuais em %s (erro %d)",
                  filename, GetLastError());
      return false;
   }

   FileWrite(handle, "SYMBOL", "TIMEFRAME", "TIPO", "TEMPO1", "TEMPO2", "TOPO", "FUNDO", "TIMEFRAME_ORIGIN");

   int saved = 0;
   int total = ObjectsTotal(0);
   string tfName = EnumToString((ENUM_TIMEFRAMES)_Period);

   for(int i = 0; i < total; i++)
   {
      string name = ObjectName(0, i);
      if(!GPT_IsZoneObjectName(name))
         continue;

      if(ObjectGetInteger(0, name, OBJPROP_TYPE) != OBJ_RECTANGLE)
         continue;

      double price1 = ObjectGetDouble(0, name, OBJPROP_PRICE, 0);
      double price2 = ObjectGetDouble(0, name, OBJPROP_PRICE, 1);
      datetime time1 = (datetime)ObjectGetInteger(0, name, OBJPROP_TIME, 0);
      datetime time2 = (datetime)ObjectGetInteger(0, name, OBJPROP_TIME, 1);

      if(time1 == 0 || time2 == 0 || price1 == price2)
         continue;

      string tipo = (StringFind(name, "ZONA_SUPORTE") == 0) ? "S" : "R";
      double topo = MathMax(price1, price2);
      double fundo = MathMin(price1, price2);

      ENUM_TIMEFRAMES tfZona = TFDaZonaCasada(tipo, fundo, topo);
      string tfOrigin = (tfZona == PERIOD_CURRENT) ? "" : EnumToString(tfZona);

      FileWrite(handle,
                _Symbol,
                tfName,
                tipo,
                TimeToString(time1, TIME_DATE | TIME_MINUTES),
                TimeToString(time2, TIME_DATE | TIME_MINUTES),
                DoubleToString(topo, _Digits),
                DoubleToString(fundo, _Digits),
                tfOrigin);
      saved++;
   }

   FileClose(handle);
   PrintFormat("S&R GPT: %d zona(s) salva(s) em %s (%s)", saved, filename, reason);
   return true;
}

//+------------------------------------------------------------------+
//| S&R GPT — Remove all GPT objects                                 |
//+------------------------------------------------------------------+
void GPT_RemoveAllObjects()
{
   for(int i = ObjectsTotal(0, 0, -1) - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, g_gpt_prefix) == 0)
         ObjectDelete(0, name);
   }
}

int GPT_CountObjects()
{
   int total = 0;
   for(int i = ObjectsTotal(0, 0, -1) - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, g_gpt_prefix) == 0) total++;
   }
   return total;
}

//+------------------------------------------------------------------+
//| S&R GPT — Draw zone rectangle + label                            |
//+------------------------------------------------------------------+
void GPT_DrawZoneRect(int index, string zoneType, double priceUpper, double priceLower,
                      int strength, string tfOrigin, int touches)
{
   string labelName = g_gpt_prefix + "LBL_"  + IntegerToString(index);

   bool isSupport = (zoneType == "support");
   color zoneColor = isSupport ? GPT_SUPPORT_COLOR : GPT_RESIST_COLOR;

   int bars = Bars(_Symbol, _Period);
   if(bars < 2) return;

   int startShift = MathMin(MathMax(GPT_LOOKBACK_BARS, 1), bars - 1);
   datetime time1 = iTime(_Symbol, _Period, startShift);
   datetime time2 = TimeCurrent() + (datetime)(PeriodSeconds(_Period) * GPT_EXTEND_BARS);

   double low  = MathMin(priceUpper, priceLower);
   double high = MathMax(priceUpper, priceLower);

   // Retângulo único: nome ZONA_* para trading + visual + editável
   string zoneName = isSupport
      ? "ZONA_SUPORTE_GPT_" + IntegerToString(index)
      : "ZONA_RESISTENCIA_GPT_" + IntegerToString(index);

   ObjectDelete(0, zoneName);
   if(ObjectCreate(0, zoneName, OBJ_RECTANGLE, 0, time1, high, time2, low))
   {
      ObjectSetInteger(0, zoneName, OBJPROP_COLOR, zoneColor);
      ObjectSetInteger(0, zoneName, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, zoneName, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, zoneName, OBJPROP_BACK, true);
      ObjectSetInteger(0, zoneName, OBJPROP_FILL, true);
      ObjectSetInteger(0, zoneName, OBJPROP_SELECTABLE, true);
      ObjectSetInteger(0, zoneName, OBJPROP_HIDDEN, false);

      string tip = isSupport ? "Suporte" : "Resistencia";
      tip += " | " + tfOrigin + " | Forca:" + IntegerToString(strength)
           + " | Toques:" + IntegerToString(touches);
      ObjectSetString(0, zoneName, OBJPROP_TOOLTIP, tip);
   }

   // Label
   double midPrice = (high + low) / 2.0;
   string typeStr = isSupport ? "S" : "R";
   string labelText = typeStr + " | " + tfOrigin + " | F:" + IntegerToString(strength)
                    + " | T:" + IntegerToString(touches);

   ObjectDelete(0, labelName);
   if(ObjectCreate(0, labelName, OBJ_TEXT, 0, TimeCurrent(), midPrice))
   {
      ObjectSetString(0, labelName, OBJPROP_TEXT, labelText);
      ObjectSetInteger(0, labelName, OBJPROP_COLOR, zoneColor);
      ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, GPT_FONT_SIZE);
      ObjectSetString(0, labelName, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, labelName, OBJPROP_ANCHOR, ANCHOR_LEFT);
      ObjectSetInteger(0, labelName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, labelName, OBJPROP_BACK, false);
   }
}

void GPT_DrawTrendLabel(string trend, string generatedAt)
{
   string name = g_gpt_prefix + "TREND";
   string text = "S&R GPT | Trend: " + trend + " | " + generatedAt;

   ObjectDelete(0, name);
   if(ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0))
   {
      ObjectSetString(0, name, OBJPROP_TEXT, text);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 20);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
      ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
   }
}


//+------------------------------------------------------------------+
//| S&R GPT — Parse JSON and draw zones + populate zonas[]           |
//+------------------------------------------------------------------+
void GPT_ParseAndDraw(const string json)
{
   g_gpt_persistenceBusy = true;
   GPT_RemoveAllObjects();

   string trend = GPT_ExtractStringValue(json, "trend");
   string genAt = GPT_ExtractStringValue(json, "generated_at");
   GPT_DrawTrendLabel(trend, genAt);

   string zonesArray = GPT_ExtractArray(json, "zones");
   if(zonesArray == "")
   {
      g_gpt_persistenceBusy = false;
      return;
   }

   // Limpar zonas anteriores do array e gráfico
   ResetDesenhoZonaPendente();
   ResetJanelaCompra();
   ResetJanelaVenda();
   LimparZonasDoGrafico();
   ArrayResize(zonas, 0);

   int pos = 0;
   int count = 0;

   int bars = Bars(_Symbol, _Period);
   int startShift = MathMin(MathMax(GPT_LOOKBACK_BARS, 1), (bars > 1 ? bars - 1 : 1));
   datetime syntheticTimeIni = iTime(_Symbol, _Period, startShift);
   datetime syntheticTimeFim = TimeCurrent() + (datetime)(PeriodSeconds(_Period) * GPT_EXTEND_BARS);

   while(pos < StringLen(zonesArray))
   {
      int start = StringFind(zonesArray, "{", pos);
      if(start < 0) break;

      int end = GPT_FindMatchingBracket(zonesArray, start, '{', '}');
      if(end < 0) break;

      string obj = StringSubstr(zonesArray, start, end - start + 1);

      string zType     = GPT_ExtractStringValue(obj, "type");
      string tfOrigin  = GPT_ExtractStringValue(obj, "timeframe_origin");
      double priceUp   = 0, priceLo = 0, str = 0, tch = 0;

      GPT_ExtractNumber(obj, "price_upper", priceUp);
      GPT_ExtractNumber(obj, "price_lower", priceLo);
      GPT_ExtractNumber(obj, "strength", str);
      GPT_ExtractNumber(obj, "touches", tch);

      if(priceUp > 0 && priceLo > 0 && priceUp > priceLo)
      {
         GPT_DrawZoneRect(count, zType, priceUp, priceLo, (int)str, tfOrigin, (int)tch);

         // Popula zonas[] para backtest
         ZonaManual z;
         z.tempo_ini = syntheticTimeIni;
         z.tempo_fim = syntheticTimeFim;
         z.topo = MathMax(priceUp, priceLo);
         z.fundo = MathMin(priceUp, priceLo);
         z.tipo = (zType == "support") ? "S" : "R";
         z.valida = true;
         z.tf_origin = TFFromText(tfOrigin);

         ArrayResize(zonas, ArraySize(zonas) + 1);
         zonas[ArraySize(zonas) - 1] = z;

         count++;
      }

      pos = end + 1;
   }

   PrintFormat("S&R GPT: %s — %d zones (trend: %s)", _Symbol, count, trend);
   ChartRedraw(0);

   // Notificações
   string msg = "S&R GPT | " + _Symbol + " | " + IntegerToString(count)
              + " zones updated (trend: " + trend + ")";
   if(GPT_ALERT_POPUP)
      Alert(msg);
   if(GPT_ALERT_SOUND)
      PlaySound("alert.wav");
   if(GPT_ALERT_PUSH)
      SendNotification(msg);

   g_gpt_persistenceBusy = false;
   GPT_SaveCurrentZones("json import");
}

//+------------------------------------------------------------------+
//| S&R GPT — Import zones from JSON (button handler)                |
//+------------------------------------------------------------------+
bool GPT_ImportarZonasJSON()
{
   string jsonFile = "sr_zones_" + _Symbol + ".json";
   string json = GPT_ReadTextFile(jsonFile);
   if(json == "")
   {
      PrintFormat("S&R GPT: JSON not found: %s", jsonFile);
      return false;
   }

   GPT_ParseAndDraw(json);
   g_gpt_lastJson = json;
   return true;
}

bool GPT_ImportarZonasSalvas()
{
   string manualFile = GPT_ManualZonesFile();
   if(!FileIsExist(manualFile))
      return false;

   bool imported = ImportarZonasDeArquivo(manualFile, false);
   if(!imported)
   {
      ResetDesenhoZonaPendente();
      ResetJanelaCompra();
      ResetJanelaVenda();
      LimparZonasDoGrafico();
      ArrayResize(zonas, 0);
      ChartRedraw();
      PrintFormat("S&R GPT: arquivo de ajustes existe mas nao contem zonas validas: %s", manualFile);
   }

   g_gpt_lastJson = GPT_ReadTextFile(g_gpt_jsonFile);
   PrintFormat("S&R GPT: ajustes manuais carregados de %s", manualFile);
   return true;
}

bool GPT_LoadInitialZones()
{
   datetime manualMod = GPT_FileModifyTime(GPT_ManualZonesFile());
   datetime jsonMod = GPT_FileModifyTime(g_gpt_jsonFile);

   if(manualMod > 0 && manualMod >= jsonMod)
      return GPT_ImportarZonasSalvas();

   return GPT_ImportarZonasJSON();
}

//+------------------------------------------------------------------+
//| S&R GPT — Refresh zones (timer callback)                         |
//+------------------------------------------------------------------+
void GPT_RefreshZones()
{
   string json = GPT_ReadTextFile(g_gpt_jsonFile);
   if(json == "") return;

   if(json == g_gpt_lastJson)
      return;

   GPT_ParseAndDraw(json);
   g_gpt_lastJson = json;
}

//+------------------------------------------------------------------+
//| Swap Panel functions                                              |
//+------------------------------------------------------------------+
string NomeDiaSemanaSwap(const int day)
{
   switch (day)
   {
      case 0: return "Domingo";
      case 1: return "Segunda";
      case 2: return "Terca";
      case 3: return "Quarta";
      case 4: return "Quinta";
      case 5: return "Sexta";
      case 6: return "Sabado";
   }
   return "N/A";
}

string DescreverSwapMode(const int mode)
{
   switch (mode)
   {
      case SYMBOL_SWAP_MODE_DISABLED:         return "Desativado";
      case SYMBOL_SWAP_MODE_POINTS:           return "Points";
      case SYMBOL_SWAP_MODE_CURRENCY_SYMBOL:  return "Moeda simbolo";
      case SYMBOL_SWAP_MODE_CURRENCY_MARGIN:  return "Moeda margem";
      case SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT: return "Moeda deposito";
      case SYMBOL_SWAP_MODE_INTEREST_CURRENT: return "Juros preco atual";
      case SYMBOL_SWAP_MODE_INTEREST_OPEN:    return "Juros preco abertura";
      case SYMBOL_SWAP_MODE_REOPEN_CURRENT:   return "Reabertura atual";
      case SYMBOL_SWAP_MODE_REOPEN_BID:       return "Reabertura bid";
   }
   return "Desconhecido";
}

string UnidadeSwapMode(const int mode)
{
   switch (mode)
   {
      case SYMBOL_SWAP_MODE_POINTS:           return "pts/lot/dia";
      case SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT: return AccountInfoString(ACCOUNT_CURRENCY) + "/lot/dia";
      case SYMBOL_SWAP_MODE_CURRENCY_SYMBOL:  return "ccy simbolo/lot/dia";
      case SYMBOL_SWAP_MODE_CURRENCY_MARGIN:  return "ccy margem/lot/dia";
      case SYMBOL_SWAP_MODE_INTEREST_CURRENT:
      case SYMBOL_SWAP_MODE_INTEREST_OPEN:    return "% a.a.";
      case SYMBOL_SWAP_MODE_REOPEN_CURRENT:
      case SYMBOL_SWAP_MODE_REOPEN_BID:       return "preco";
      case SYMBOL_SWAP_MODE_DISABLED:         return "-";
   }
   return "u";
}

color CorSwapValor(const double v)
{
   if (v > 0.0) return clrLimeGreen;
   if (v < 0.0) return clrTomato;
   return clrSilver;
}

string FormatarSwapValor(const double valor, const int mode)
{
   int casas = 2;
   if (mode == SYMBOL_SWAP_MODE_POINTS)
      casas = 1;
   else if (mode == SYMBOL_SWAP_MODE_INTEREST_CURRENT || mode == SYMBOL_SWAP_MODE_INTEREST_OPEN)
      casas = 3;

   string fmt = "%+." + IntegerToString(casas) + "f";
   return StringFormat(fmt, valor);
}

string NomeObjSwap(const string sufixo)
{
   return SWAP_PANEL_PREFIX + sufixo;
}

void UpsertLabelSwap(const string sufixo, const int y, const string texto, const color cor, const int fontSize = 9)
{
   string nome = NomeObjSwap(sufixo);
   if (ObjectFind(0, nome) < 0)
      ObjectCreate(0, nome, OBJ_LABEL, 0, 0, 0);

   ObjectSetInteger(0, nome, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
   ObjectSetInteger(0, nome, OBJPROP_ANCHOR, ANCHOR_RIGHT_UPPER);
   ObjectSetInteger(0, nome, OBJPROP_XDISTANCE, 12);
   ObjectSetInteger(0, nome, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, nome, OBJPROP_FONTSIZE, fontSize);
   ObjectSetInteger(0, nome, OBJPROP_COLOR, cor);
   ObjectSetInteger(0, nome, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, nome, OBJPROP_HIDDEN, true);
   ObjectSetString(0, nome, OBJPROP_FONT, "Consolas");
   ObjectSetString(0, nome, OBJPROP_TEXT, texto);
}

void RemoverPainelSwap()
{
   string ids[] = {"TITLE","MODE","BUY","SELL","PAYAVG","NETAVG","ROLL3","PROJBUY","PROJSELL","UPDATED"};
   for (int i = 0; i < ArraySize(ids); i++)
      ObjectDelete(0, NomeObjSwap(ids[i]));
}

void AtualizarPainelSwap(const bool force = false)
{
   if (!ExibirPainelSwap)
   {
      RemoverPainelSwap();
      return;
   }

   int intervalo = MathMax(1, SwapPainelAtualizaSeg);
   if (!force && ultimoUpdatePainelSwap > 0 && (TimeCurrent() - ultimoUpdatePainelSwap) < intervalo)
      return;

   int modo = (int)SymbolInfoInteger(_Symbol, SYMBOL_SWAP_MODE);
   double swapBuy = SymbolInfoDouble(_Symbol, SYMBOL_SWAP_LONG);
   double swapSell = SymbolInfoDouble(_Symbol, SYMBOL_SWAP_SHORT);
   int day3 = (int)SymbolInfoInteger(_Symbol, SYMBOL_SWAP_ROLLOVER3DAYS);
   int diasProj = MathMax(1, SwapPainelProjecaoDias);

   double somaPag = 0.0;
   int qtdPag = 0;
   if (swapBuy < 0.0) { somaPag += swapBuy; qtdPag++; }
   if (swapSell < 0.0) { somaPag += swapSell; qtdPag++; }

   double custoMedioPagamento = (qtdPag > 0) ? (somaPag / qtdPag) : 0.0;
   double custoLiquidoMedio = (swapBuy + swapSell) / 2.0;
   double projBuy = swapBuy * diasProj;
   double projSell = swapSell * diasProj;

   UpsertLabelSwap("TITLE", 24, "SWAP | " + _Symbol, clrWhite, 10);
   UpsertLabelSwap("MODE", 42, "Modo: " + DescreverSwapMode(modo) + " (" + UnidadeSwapMode(modo) + ")", clrSilver, 9);
   UpsertLabelSwap("BUY", 60, "BUY  (1 lote/dia):   " + FormatarSwapValor(swapBuy, modo), CorSwapValor(swapBuy), 9);
   UpsertLabelSwap("SELL", 78, "SELL (1 lote/dia):   " + FormatarSwapValor(swapSell, modo), CorSwapValor(swapSell), 9);
   UpsertLabelSwap("PAYAVG", 96, "Custo medio pagamento: " + FormatarSwapValor(custoMedioPagamento, modo), CorSwapValor(custoMedioPagamento), 9);
   UpsertLabelSwap("NETAVG", 114, "Custo liquido medio:    " + FormatarSwapValor(custoLiquidoMedio, modo), CorSwapValor(custoLiquidoMedio), 9);
   UpsertLabelSwap("ROLL3", 132, "Rollover triplo: " + NomeDiaSemanaSwap(day3), clrKhaki, 9);
   UpsertLabelSwap("PROJBUY", 150, "Projecao " + IntegerToString(diasProj) + "d BUY:  " + FormatarSwapValor(projBuy, modo), CorSwapValor(projBuy), 9);
   UpsertLabelSwap("PROJSELL", 168, "Projecao " + IntegerToString(diasProj) + "d SELL: " + FormatarSwapValor(projSell, modo), CorSwapValor(projSell), 9);
   UpsertLabelSwap("UPDATED", 186, "Atualizado: " + TimeToString(TimeCurrent(), TIME_SECONDS), clrGray, 8);

   ultimoUpdatePainelSwap = TimeCurrent();
}

// === ONINIT ===
int OnInit()
{
   Print("🟡 OnInit começou — S&R 0.2.0");
   Print("EA iniciado: S&R Quant + GPT AI Zones");
   g_gpt_jsonFile = "sr_zones_" + _Symbol + ".json";

   // === Aplicar preset de TF ===
   switch(TFPreset)
   {
      case TF_D1_H1:
         TimeFrame = PERIOD_D1;
         Execucao_TF = PERIOD_H1;
         break;
      case TF_H4_M15:
         TimeFrame = PERIOD_H4;
         Execucao_TF = PERIOD_M15;
         break;
      case TF_H1_M5:
         TimeFrame = PERIOD_H1;
         Execucao_TF = PERIOD_M5;
         break;
      case TF_M15_M1:
      default:
         TimeFrame = PERIOD_M15;
         Execucao_TF = PERIOD_M1;
         break;
   }

   usarConfirmacaoMedia = (ModoOperacao == MODO_COM_CONFIRMACAO || ModoOperacao == MODO_AMBOS);
   if (!usarConfirmacaoMedia)
      Print("ℹ️ Modo SEM confirmação: desativando gatilho por SMA/TF menor para compatibilidade com backtest em abertura de preços.");

   segundosJanela = 3 * PeriodSeconds(TimeFrame);
   trade.SetExpertMagicNumber((ulong)Magic);
   CooldownSegundos = CooldownHoras * 3600;

   // === Se estiver em modo de teste, tentar carregar zonas ===
   if (MQLInfoInteger(MQL_TESTER))
   {
      Print("✅ Entrou no MQL_TESTER");
      if(GPT_LoadInitialZones())
      {
         Print("📥 Backtest: zonas carregadas do GPT/ajustes salvos...");
      }
      else
      {
         // Fallback para CSV tradicional
         Print("🔍 Backtest: buscando CSV de zonas para ", _Symbol,
               " (todos os TFs; prioridade: MQL5\\Files; fallback: Common\\Files)");
         if (!ImportarZonasMaisRecente())
            return INIT_FAILED;
      }
   }

   // === Indicadores por TF (cache) ===
   // Disponibilidade do Ultimate Oscillator (probe no TF do gráfico).
   int ultProbe = iCustom(_Symbol, _Period, "Ultimate_Oscillator");
   if (ultProbe == INVALID_HANDLE)
   {
      usarUltOsc = false;
      PrintFormat("⚠️ Ultimate_Oscillator indisponível (erro %d). EA seguirá sem esse filtro.",
                  GetLastError());
   }
   else
   {
      IndicatorRelease(ultProbe);
   }

   // Pré-cria os handles: TFs de zona (osciladores) + TFs de gatilho (SMA) + fallbacks.
   ENUM_TIMEFRAMES tfsFixas[6] = { PERIOD_W1, PERIOD_D1, PERIOD_H4, PERIOD_H1, PERIOD_M15, PERIOD_M5 };
   bool okHandles = true;
   for (int t = 0; t < ArraySize(tfsFixas); t++)
      if (!ValidarCacheTF(tfsFixas[t])) okHandles = false;
   if (!ValidarCacheTF((ENUM_TIMEFRAMES)_Period)) okHandles = false;
   if (!ValidarCacheTF(Execucao_TF))              okHandles = false;
   if (!okHandles)
      return INIT_FAILED;

   // Criar botões
   CriarBotoes();

   // Garantir modo candle
   ChartSetInteger(0, CHART_MODE, CHART_CANDLES);

   // Fundo e elementos visuais
   ChartSetInteger(0, CHART_COLOR_BACKGROUND, clrBlack);
   ChartSetInteger(0, CHART_COLOR_FOREGROUND, clrWhite);
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_SHOW_VOLUMES, false);
   ChartSetInteger(0, 36, false);

   ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, clrDeepSkyBlue);
   ChartSetInteger(0, CHART_COLOR_CHART_UP, clrDeepSkyBlue);
   ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, clrRed);
   ChartSetInteger(0, CHART_COLOR_CHART_DOWN, clrRed);

   ChartSetInteger(0, CHART_COLOR_CHART_LINE, clrBlack);
   ChartSetInteger(0, CHART_COLOR_BID, clrWhite);
   ChartSetInteger(0, CHART_COLOR_ASK, clrWhite);
   ChartSetInteger(0, CHART_COLOR_LAST, clrBlack);

   ChartRedraw();
   AtualizarPainelSwap(true);

   // === S&R GPT — Inicializar módulo AI Zones ===
   if(!MQLInfoInteger(MQL_TESTER))
   {
      EventSetTimer(GPT_TIMER_SEC);
      GPT_ExportAllTimeframesIfNeeded(false, "startup weekly check");
      GPT_UpdateSymbolList();
      GPT_LoadInitialZones();
   }

   return INIT_SUCCEEDED;
}

void CriarBotoes()
{
   long chart_id = ChartID();

   // Botão Suporte
   string nomeBotaoSuporte = "BotaoSuporte";
   ObjectDelete(chart_id, nomeBotaoSuporte);
   ObjectCreate(chart_id, nomeBotaoSuporte, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(chart_id, nomeBotaoSuporte, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(chart_id, nomeBotaoSuporte, OBJPROP_XDISTANCE, 20);
   ObjectSetInteger(chart_id, nomeBotaoSuporte, OBJPROP_YDISTANCE, 40);
   ObjectSetInteger(chart_id, nomeBotaoSuporte, OBJPROP_XSIZE, 120);
   ObjectSetInteger(chart_id, nomeBotaoSuporte, OBJPROP_YSIZE, 20);
   ObjectSetString(chart_id, nomeBotaoSuporte, OBJPROP_TEXT, "Desenhar Suporte");

   // Botão Resistência
   string nomeBotaoResistencia = "BotaoResistencia";
   ObjectDelete(chart_id, nomeBotaoResistencia);
   ObjectCreate(chart_id, nomeBotaoResistencia, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(chart_id, nomeBotaoResistencia, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(chart_id, nomeBotaoResistencia, OBJPROP_XDISTANCE, 160);
   ObjectSetInteger(chart_id, nomeBotaoResistencia, OBJPROP_YDISTANCE, 40);
   ObjectSetInteger(chart_id, nomeBotaoResistencia, OBJPROP_XSIZE, 140);
   ObjectSetInteger(chart_id, nomeBotaoResistencia, OBJPROP_YSIZE, 20);
   ObjectSetString(chart_id, nomeBotaoResistencia, OBJPROP_TEXT, "Desenhar Resistência");

   // Botão Importar Zonas (agora importa JSON do GPT)
   string nomeBotaoImportar = "BotaoImportarZonas";
   ObjectDelete(chart_id, nomeBotaoImportar);
   ObjectCreate(chart_id, nomeBotaoImportar, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(chart_id, nomeBotaoImportar, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(chart_id, nomeBotaoImportar, OBJPROP_XDISTANCE, 320);
   ObjectSetInteger(chart_id, nomeBotaoImportar, OBJPROP_YDISTANCE, 40);
   ObjectSetInteger(chart_id, nomeBotaoImportar, OBJPROP_XSIZE, 130);
   ObjectSetInteger(chart_id, nomeBotaoImportar, OBJPROP_YSIZE, 20);
   ObjectSetString(chart_id, nomeBotaoImportar, OBJPROP_TEXT, "Importar Zonas GPT");

   // Botão Exportar CSVs do GPT
   string nomeBotaoExportarCsv = "BotaoExportarCsvGPT";
   ObjectDelete(chart_id, nomeBotaoExportarCsv);
   ObjectCreate(chart_id, nomeBotaoExportarCsv, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(chart_id, nomeBotaoExportarCsv, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(chart_id, nomeBotaoExportarCsv, OBJPROP_XDISTANCE, 470);
   ObjectSetInteger(chart_id, nomeBotaoExportarCsv, OBJPROP_YDISTANCE, 40);
   ObjectSetInteger(chart_id, nomeBotaoExportarCsv, OBJPROP_XSIZE, 120);
   ObjectSetInteger(chart_id, nomeBotaoExportarCsv, OBJPROP_YSIZE, 20);
   ObjectSetString(chart_id, nomeBotaoExportarCsv, OBJPROP_TEXT, "Exportar CSV");

}


void ResetDesenhoZonaPendente()
{
   tipoZonaPendente = "";
   aguardandoSegundoPontoZona = false;
   zonaTempoPonto1 = 0;
   zonaPrecoPonto1 = 0.0;
}

void IniciarDesenhoZona(string tipo)
{
   tipoZonaPendente = tipo;
   aguardandoSegundoPontoZona = false;
   zonaTempoPonto1 = 0;
   zonaPrecoPonto1 = 0.0;
   Print("🖱️ Modo desenho ", tipo, " ativado. Clique no 1º ponto da zona no gráfico.");
}

void ProcessarCliqueDesenhoZona(const int x, const int y)
{
   if (tipoZonaPendente == "")
      return;

   int subwindow = -1;
   datetime tempo = 0;
   double preco = 0.0;
   if (!ChartXYToTimePrice(0, x, y, subwindow, tempo, preco))
   {
      Print("❌ Erro ao capturar ponto do mouse: ", GetLastError());
      return;
   }

   if (subwindow != 0)
   {
      Print("⚠️ Clique na janela principal do gráfico para desenhar a zona.");
      return;
   }

   if (!aguardandoSegundoPontoZona)
   {
      zonaTempoPonto1 = tempo;
      zonaPrecoPonto1 = preco;
      aguardandoSegundoPontoZona = true;
      Print("📍 1º ponto da zona ", tipoZonaPendente, " marcado. Clique no 2º ponto.");
      return;
   }

   if (tempo == zonaTempoPonto1 || MathAbs(preco - zonaPrecoPonto1) < (_Point * 0.1))
   {
      Print("⚠️ 2º ponto inválido. Clique em outro local para formar o retângulo.");
      return;
   }

   string nomeZona = "ZONA_" + tipoZonaPendente + "_" + IntegerToString((int)TimeLocal()) + "_" + IntegerToString((int)GetTickCount());
   bool ok = ObjectCreate(0, nomeZona, OBJ_RECTANGLE, 0, zonaTempoPonto1, zonaPrecoPonto1, tempo, preco);
   if (!ok)
   {
      Print("❌ Erro ao criar zona manual: ", GetLastError());
      return;
   }

   color cor = (tipoZonaPendente == "SUPORTE") ? clrGreen : clrRed;
   ObjectSetInteger(0, nomeZona, OBJPROP_COLOR, cor);
   ObjectSetInteger(0, nomeZona, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, nomeZona, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, nomeZona, OBJPROP_BACK, true);
   ObjectSetInteger(0, nomeZona, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, nomeZona, OBJPROP_SELECTED, true);

   Print("✅ Zona ", tipoZonaPendente, " criada manualmente: ", nomeZona);
   ResetDesenhoZonaPendente();
   GPT_SaveCurrentZones("manual create");
}

void LimparZonasDoGrafico()
{
   int total = ObjectsTotal(0);
   for (int i = total - 1; i >= 0; i--)
   {
      string nome = ObjectName(0, i);
      if (StringFind(nome, "ZONA_SUPORTE") == 0 ||
          StringFind(nome, "ZONA_RESISTENCIA") == 0 ||
          StringFind(nome, "ZONA_CSV_") == 0)
      {
         ObjectDelete(0, nome);
      }
   }
}

bool ExisteArquivoCsv(const string arquivo, const bool usarCommon, datetime &dataMod)
{
   dataMod = 0;
   int flags = FILE_READ | FILE_CSV | (usarCommon ? FILE_COMMON : 0);

   ResetLastError();
   int handle = FileOpen(arquivo, flags | FILE_ANSI, ';');
   if (handle == INVALID_HANDLE)
   {
      ResetLastError();
      handle = FileOpen(arquivo, flags, ';');
      if (handle == INVALID_HANDLE)
         return false;
   }

   FileClose(handle);
   long mod = FileGetInteger(arquivo, FILE_MODIFY_DATE, usarCommon);
   if (mod > 0)
      dataMod = (datetime)mod;

   return true;
}

bool AbrirArquivoCsv(const string arquivo, const bool usarCommon, int &handleOut, const bool silencioso=false)
{
   handleOut = INVALID_HANDLE;
   int flags = FILE_READ | FILE_CSV | (usarCommon ? FILE_COMMON : 0);

   ResetLastError();
   handleOut = FileOpen(arquivo, flags | FILE_ANSI, ';');
   if (handleOut != INVALID_HANDLE)
      return true;

   int erroAnsi = GetLastError();
   ResetLastError();
   handleOut = FileOpen(arquivo, flags, ';');
   if (handleOut != INVALID_HANDLE)
      return true;

   if (!silencioso)
      PrintFormat("❌ Falha ao abrir CSV '%s' (ANSI erro=%d, fallback erro=%d).",
                  arquivo, erroAnsi, GetLastError());
   return false;
}

string NormalizarTokenBusca(string valor)
{
   StringToUpper(valor);
   StringTrimLeft(valor);
   StringTrimRight(valor);
   StringReplace(valor, ".", "");
   StringReplace(valor, "_", "");
   StringReplace(valor, "-", "");
   StringReplace(valor, "/", "");
   StringReplace(valor, " ", "");
   return valor;
}

bool SimbolosSaoCompativeis(const string simboloA, const string simboloB)
{
   string a = NormalizarTokenBusca(simboloA);
   string b = NormalizarTokenBusca(simboloB);

   if (a == "" || b == "")
      return false;

   if (a == b)
      return true;

   return (StringFind(a, b) >= 0 || StringFind(b, a) >= 0);
}

bool NomeCsvCompativelComSimbolo(const string nomeArquivo, const string simboloAlvo)
{
   if (StringFind(nomeArquivo, "ZonasManual_") != 0)
      return false;

   int len = StringLen(nomeArquivo);
   if (len <= 16)
      return false;

   if (StringCompare(StringSubstr(nomeArquivo, len - 4), ".csv", false) != 0)
      return false;

   string raiz = StringSubstr(nomeArquivo, StringLen("ZonasManual_"), len - StringLen("ZonasManual_") - 4);
   int posSeparador = StringFind(raiz, "_");
   string simboloNoNome = (posSeparador > 0) ? StringSubstr(raiz, 0, posSeparador) : raiz;

   return SimbolosSaoCompativeis(simboloNoNome, simboloAlvo);
}

void ConsiderarCsvCandidato(const string candidato,
                            const bool candidatoCommon,
                            const string simboloAlvo,
                            string &arquivoEscolhido,
                            bool &usarCommon,
                            datetime &dataEscolhida)
{
   if (!NomeCsvCompativelComSimbolo(candidato, simboloAlvo))
      return;

   datetime dataMod = 0;
   if (!ExisteArquivoCsv(candidato, candidatoCommon, dataMod))
      return;

   if (arquivoEscolhido == "" || dataMod >= dataEscolhida)
   {
      arquivoEscolhido = candidato;
      usarCommon = candidatoCommon;
      dataEscolhida = dataMod;
   }
}

void EscanearCsvsPorPadrao(const bool escanearCommon,
                           const string simboloAlvo,
                           string &arquivoEscolhido,
                           bool &usarCommon,
                           datetime &dataEscolhida)
{
   string arquivoEncontrado = "";
   long buscaHandle = FileFindFirst("ZonasManual_*.csv", arquivoEncontrado, escanearCommon ? FILE_COMMON : 0);
   if (buscaHandle == INVALID_HANDLE)
      return;

   while (true)
   {
      ConsiderarCsvCandidato(arquivoEncontrado, escanearCommon, simboloAlvo,
                             arquivoEscolhido, usarCommon, dataEscolhida);
      if (!FileFindNext(buscaHandle, arquivoEncontrado))
         break;
   }

   FileFindClose(buscaHandle);
}

bool EncontrarCsvMaisRecenteDoSimbolo(const string simbolo, string &arquivoEscolhido, bool &usarCommon)
{
   string tfs[] = {
      "M1","M2","M3","M4","M5","M6","M10","M12","M15","M20","M30",
      "H1","H2","H3","H4","H6","H8","H12","D1","W1","MN1"
   };

   arquivoEscolhido = "";
   usarCommon = false;
   datetime dataEscolhida = 0;

   for (int i = 0; i < ArraySize(tfs); i++)
   {
      string candidato = "ZonasManual_" + simbolo + "_" + tfs[i] + ".csv";
      ConsiderarCsvCandidato(candidato, false, simbolo, arquivoEscolhido, usarCommon, dataEscolhida);
      ConsiderarCsvCandidato(candidato, true, simbolo, arquivoEscolhido, usarCommon, dataEscolhida);
   }

   string candidatoSemTf = "ZonasManual_" + simbolo + ".csv";
   ConsiderarCsvCandidato(candidatoSemTf, false, simbolo, arquivoEscolhido, usarCommon, dataEscolhida);
   ConsiderarCsvCandidato(candidatoSemTf, true, simbolo, arquivoEscolhido, usarCommon, dataEscolhida);

   EscanearCsvsPorPadrao(false, simbolo, arquivoEscolhido, usarCommon, dataEscolhida);
   EscanearCsvsPorPadrao(true, simbolo, arquivoEscolhido, usarCommon, dataEscolhida);

   return (arquivoEscolhido != "");
}

bool ImportarZonasDeArquivo(const string arquivo, const bool usarCommon)
{
   int handle = INVALID_HANDLE;
   if (!AbrirArquivoCsv(arquivo, usarCommon, handle))
      return false;

   g_gpt_persistenceBusy = true;
   ResetDesenhoZonaPendente();
   ResetJanelaCompra();
   ResetJanelaVenda();
   LimparZonasDoGrafico();
   ArrayResize(zonas, 0);

   string pastaBase = usarCommon
      ? (TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\")
      : (TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\");
   Print("📂 Importando zonas de: ", pastaBase, arquivo);

   int linhasLidas = 0;
   int zonasImportadas = 0;
   int zonasIgnoradas = 0;
   bool primeiraLinha = true;

   while (!FileIsEnding(handle))
   {
      string symbolStr = FileReadString(handle);
      string timeframeStr = FileReadString(handle);
      string tipo = FileReadString(handle);
      string tempo1 = FileReadString(handle);
      string tempo2 = FileReadString(handle);
      string topoStr = FileReadString(handle);
      string fundoStr = FileReadString(handle);

      // Coluna opcional TIMEFRAME_ORIGIN (CSV antigo de 7 colunas não a possui).
      string tfOriginStr = "";
      if (!FileIsLineEnding(handle))
         tfOriginStr = FileReadString(handle);

      if (symbolStr == "" && timeframeStr == "" && tipo == "" &&
          tempo1 == "" && tempo2 == "" && topoStr == "" && fundoStr == "")
      {
         break;
      }

      if (primeiraLinha)
      {
         bool headerSymbol = (StringCompare(symbolStr, "SYMBOL", false) == 0);
         bool headerTf     = (StringCompare(timeframeStr, "TIMEFRAME", false) == 0 ||
                              StringCompare(timeframeStr, "TF", false) == 0);
         if (headerSymbol && headerTf)
         {
            primeiraLinha = false;
            continue;
         }
         primeiraLinha = false;
      }

      linhasLidas++;

      if (!SimbolosSaoCompativeis(symbolStr, _Symbol))
      {
         zonasIgnoradas++;
         continue;
      }

      if (tipo != "S" && tipo != "R")
      {
         zonasIgnoradas++;
         continue;
      }

      datetime t1 = StringToTime(tempo1);
      datetime t2 = StringToTime(tempo2);
      double topo = StringToDouble(topoStr);
      double fundo = StringToDouble(fundoStr);

      if (t1 == 0 || t2 == 0 || t1 == t2 || topo == fundo)
      {
         zonasIgnoradas++;
         continue;
      }

      ZonaManual z;
      z.tempo_ini = (t1 < t2) ? t1 : t2;
      z.tempo_fim = (t1 > t2) ? t1 : t2;
      z.topo = MathMax(topo, fundo);
      z.fundo = MathMin(topo, fundo);
      z.tipo = tipo;
      z.valida = true;
      z.tf_origin = TFFromText(tfOriginStr);

      string nome = (tipo == "S")
         ? "ZONA_SUPORTE_CSV_" + IntegerToString(zonasImportadas)
         : "ZONA_RESISTENCIA_CSV_" + IntegerToString(zonasImportadas);
      color cor = (tipo == "S") ? clrLime : clrRed;

      if (ObjectFind(0, nome) >= 0)
         ObjectDelete(0, nome);

      if (!ObjectCreate(0, nome, OBJ_RECTANGLE, 0, z.tempo_ini, z.topo, z.tempo_fim, z.fundo))
      {
         Print("❌ Erro ao criar zona importada: ", nome, " | Erro: ", GetLastError());
         zonasIgnoradas++;
         continue;
      }

      ObjectSetInteger(0, nome, OBJPROP_COLOR, cor);
      ObjectSetInteger(0, nome, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, nome, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, nome, OBJPROP_BACK, true);
      ObjectSetInteger(0, nome, OBJPROP_SELECTABLE, true);
      ObjectSetInteger(0, nome, OBJPROP_SELECTED, false);

      ArrayResize(zonas, ArraySize(zonas) + 1);
      zonas[ArraySize(zonas) - 1] = z;
      zonasImportadas++;
   }

   FileClose(handle);
   ChartRedraw();

   PrintFormat("✅ Importação concluída | Arquivo=%s%s | Linhas=%d | Importadas=%d | Ignoradas=%d",
               pastaBase, arquivo, linhasLidas, zonasImportadas, zonasIgnoradas);

   if (zonasImportadas == 0)
      Print("⚠️ Nenhuma zona válida importada para este símbolo.");

   g_gpt_persistenceBusy = false;
   GPT_SaveCurrentZones("csv import");

   return (zonasImportadas > 0);
}

bool ImportarZonasMaisRecente()
{
   // Tenta primeiro JSON do GPT
   if(GPT_ImportarZonasJSON())
      return true;

   // Fallback para CSV
   string arquivo = "";
   bool usarCommon = false;
   if (!EncontrarCsvMaisRecenteDoSimbolo(_Symbol, arquivo, usarCommon))
   {
      string pastaLocal = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
      string pastaCommon = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\";
      Print("❌ Nenhum JSON/CSV encontrado para ", _Symbol,
            ". Pastas verificadas: ", pastaLocal, " e ", pastaCommon);
      return false;
   }

   return ImportarZonasDeArquivo(arquivo, usarCommon);
}

double CalcularLote(double precoEntrada, double precoSL)
{
    double saldo = AccountInfoDouble(ACCOUNT_BALANCE);
    double riscoMonetario = saldo * (PercentualRisco / 100.0);

    if (ModoOperacao == MODO_AMBOS)
        riscoMonetario /= 2.0;

    double valorPorPonto = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
    double tamanhoTick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
    double distancia = MathAbs(precoEntrada - precoSL);
    double distanciaPontos = distancia / tamanhoTick;

    if (distanciaPontos == 0 || valorPorPonto == 0)
        return 0.0;

    double loteBruto = riscoMonetario / (distanciaPontos * valorPorPonto);
    double minLote = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    double stepLote = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
    double maxLote = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

    double loteNormalizado = NormalizeDouble(MathRound(loteBruto / stepLote) * stepLote, 2);
    if (loteNormalizado < minLote && loteBruto > 0) loteNormalizado = minLote;
    if (loteNormalizado > maxLote) loteNormalizado = maxLote;

    return loteNormalizado;
}

string TimeframeToStr(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D1";
      case PERIOD_W1:  return "W1";
      case PERIOD_MN1: return "MN1";
      default:         return "UNK";
   }
}

bool LerZonasDeArquivo(string symbol, string tf_str)
{
   string nome_arquivo = "ZonasManual_" + symbol + "_" + tf_str + ".csv";
   string pathLocal = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\" + nome_arquivo;
   string pathCommon = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + nome_arquivo;

   int handle = INVALID_HANDLE;
   bool usouCommon = false;

   if (AbrirArquivoCsv(nome_arquivo, false, handle, true))
   {
      usouCommon = false;
   }
   else if (AbrirArquivoCsv(nome_arquivo, true, handle, true))
   {
      usouCommon = true;
   }
   else
   {
      Print("❌ Erro ao abrir arquivo de zonas: ", nome_arquivo,
            " | Tentado local: ", pathLocal,
            " | Fallback common: ", pathCommon,
            " | Erro final: ", GetLastError());
      return false;
   }

   Print("✅ Arquivo de zonas encontrado em: ", (usouCommon ? pathCommon : pathLocal));

   ArrayResize(zonas, 0);

   int linhas = 0;
   int importadas = 0;
   int ignoradas = 0;
   bool primeiraLinha = true;

   while (!FileIsEnding(handle) && linhas < 5000)
   {
      string symbolStr = FileReadString(handle);
      string timeframeStr = FileReadString(handle);
      string tipo = FileReadString(handle);
      string tempo1 = FileReadString(handle);
      string tempo2 = FileReadString(handle);
      string topoStr = FileReadString(handle);
      string fundoStr = FileReadString(handle);

      // Coluna opcional TIMEFRAME_ORIGIN (CSV antigo de 7 colunas não a possui).
      string tfOriginStr = "";
      if (!FileIsLineEnding(handle))
         tfOriginStr = FileReadString(handle);

      if (symbolStr == "" && timeframeStr == "" && tipo == "" &&
          tempo1 == "" && tempo2 == "" && topoStr == "" && fundoStr == "")
      {
         break;
      }

      if (primeiraLinha)
      {
         bool headerSymbol = (StringCompare(symbolStr, "SYMBOL", false) == 0);
         bool headerTf     = (StringCompare(timeframeStr, "TIMEFRAME", false) == 0 ||
                              StringCompare(timeframeStr, "TF", false) == 0);
         if (headerSymbol && headerTf)
         {
            primeiraLinha = false;
            continue;
         }
         primeiraLinha = false;
      }

      linhas++;

      if (!SimbolosSaoCompativeis(symbolStr, symbol))
      {
         ignoradas++;
         continue;
      }

      if (tipo != "S" && tipo != "R")
      {
         ignoradas++;
         continue;
      }

      datetime t1 = StringToTime(tempo1);
      datetime t2 = StringToTime(tempo2);
      double topo = StringToDouble(topoStr);
      double fundo = StringToDouble(fundoStr);
      if (t1 == 0 || t2 == 0 || t1 == t2 || topo == fundo)
      {
         ignoradas++;
         continue;
      }

      ZonaManual z;
      z.tempo_ini = (t1 < t2) ? t1 : t2;
      z.tempo_fim = (t1 > t2) ? t1 : t2;
      z.topo = MathMax(topo, fundo);
      z.fundo = MathMin(topo, fundo);
      z.tipo = tipo;
      z.valida = true;
      z.tf_origin = TFFromText(tfOriginStr);

      ArrayResize(zonas, ArraySize(zonas) + 1);
      zonas[ArraySize(zonas) - 1] = z;
      importadas++;
   }

   FileClose(handle);
   PrintFormat("📥 Leitura de zonas concluída | Arquivo=%s | Linhas=%d | Importadas=%d | Ignoradas=%d",
               nome_arquivo, linhas, importadas, ignoradas);

   return (importadas > 0);
}

void DesenharZonasNoGrafico()
{
   for (int i = 0; i < ArraySize(zonas); i++)
   {
      if (!zonas[i].valida) continue;

      string nome = "ZONA_CSV_" + IntegerToString(i);
      color cor = (zonas[i].tipo == "S") ? clrLime : clrRed;
      if (zonas[i].tempo_ini == zonas[i].tempo_fim || zonas[i].topo == zonas[i].fundo)
      {
         Print("⚠️ Zona ignorada por dados inválidos: ", i);
         continue;
      }

      ObjectCreate(0, nome, OBJ_RECTANGLE, 0, zonas[i].tempo_ini, zonas[i].topo,
                  zonas[i].tempo_fim, zonas[i].fundo);

      ObjectSetInteger(0, nome, OBJPROP_COLOR, cor);
      ObjectSetInteger(0, nome, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, nome, OBJPROP_BACK, true);
      ObjectSetInteger(0, nome, OBJPROP_SELECTABLE, false);
   }
}

void KillWindowsAfterSL(const bool wasBuy){
   if(wasBuy){
      if(aguardandoCompra) Print("🧹 Fechando janela de COMPRA após SL.");
      ResetJanelaCompra();
   }else{
      if(aguardandoVenda)  Print("🧹 Fechando janela de VENDA após SL.");
      ResetJanelaVenda();
   }
}

// === ONDEINIT ===
void OnDeinit(const int reason)
{
   for (int i = 0; i < ArraySize(g_tfCache); i++)
   {
      if (g_tfCache[i].rsi    != INVALID_HANDLE) IndicatorRelease(g_tfCache[i].rsi);
      if (g_tfCache[i].stoch  != INVALID_HANDLE) IndicatorRelease(g_tfCache[i].stoch);
      if (g_tfCache[i].ultosc != INVALID_HANDLE) IndicatorRelease(g_tfCache[i].ultosc);
      if (g_tfCache[i].sma    != INVALID_HANDLE) IndicatorRelease(g_tfCache[i].sma);
   }
   ArrayResize(g_tfCache, 0);
   RemoverPainelSwap();
   GPT_SaveCurrentZones("deinit");
   GPT_RemoveAllObjects();
   EventKillTimer();
   Print("EA finalizado — S&R 0.2.0");
}

// === ONTIMER (S&R GPT) ===
void OnTimer()
{
   // Re-export CSVs weekly only; use the chart button for manual refresh.
   if(GPT_EXPORT_EVERY > 0)
      GPT_ExportAllTimeframesIfNeeded(false, "weekly schedule");

   GPT_RefreshZones();
}

// === ONTICK ===
void OnTick()
{
   AtualizarPainelSwap();

   // ----- COOLDOWN GLOBAL PÓS-SL -----
   if (EmCooldown())
      return;

   EncerrarCooldownSePreciso();


   if (ModoOperacao != MODO_AMBOS && PositionSelect(_Symbol))
       return;


   // === Osciladores (exaustão) ===
   // Lidos por zona tocada, na TF de origem da zona (ver LerOsciladoresTF / sites abaixo).
   double rsiValue = 50.0;
   double stochValue = 50.0;
   bool ultoscCompraOk = false;
   bool ultoscVendaOk = false;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   ENUM_TIMEFRAMES tfBarControle = usarConfirmacaoMedia ? Execucao_TF : TimeFrame;
   datetime currBar = iTime(_Symbol, tfBarControle, 0);
   static datetime lastBarTime = 0;
   static bool logCompraFeitoNaBarra = false;
   static bool logVendaFeitoNaBarra  = false;
   if (currBar != lastBarTime){
       lastBarTime = currBar;
       logCompraFeitoNaBarra = false;
       logVendaFeitoNaBarra  = false;
   }

   bool permitirSemConfirmacao = (ModoOperacao == MODO_SEM_CONFIRMACAO || ModoOperacao == MODO_AMBOS);
   bool permitirComConfirmacao = usarConfirmacaoMedia &&
                                 (ModoOperacao == MODO_COM_CONFIRMACAO || ModoOperacao == MODO_AMBOS);

   // === MODO BACKTEST: usar zonas do CSV/JSON ===
   if (MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_VISUAL_MODE))
   {
      double melhorDistanciaSuporte = DBL_MAX;
      double suporteMin = 0, suporteMax = 0;
      bool suporteEncontrado = false;

      double melhorDistanciaResistencia = DBL_MAX;
      double resistenciaMin = 0, resistenciaMax = 0;
      bool resistenciaEncontrada = false;

      for (int i = 0; i < ArraySize(zonas); i++)
      {

      if (!zonas[i].valida) continue;
      if (TimeCurrent() < zonas[i].tempo_ini || TimeCurrent() > zonas[i].tempo_fim)
         continue;

      double zonaMin = MathMin(zonas[i].topo, zonas[i].fundo);
      double zonaMax = MathMax(zonas[i].topo, zonas[i].fundo);
      double centro = (zonaMin + zonaMax) / 2;

         if (zonas[i].tipo == "S" && ask >= zonaMin && ask <= zonaMax)
         {
            double dist = MathAbs(ask - centro);
            if (dist < melhorDistanciaSuporte)
            {
               melhorDistanciaSuporte = dist;
               suporteMin = zonaMin;
               suporteMax = zonaMax;
               suporteEncontrado = true;
               suporteIdxSel = i;
            }
         }

         if (zonas[i].tipo == "R" && bid >= zonaMin && bid <= zonaMax)
         {
            double dist = MathAbs(bid - centro);
            if (dist < melhorDistanciaResistencia)
            {
               melhorDistanciaResistencia = dist;
               resistenciaMin = zonaMin;
               resistenciaMax = zonaMax;
               resistenciaEncontrada = true;
               resistenciaIdxSel = i;
            }
         }
      }

      // === COMPRA CSV ===
      if (aguardandoCompra)
      {
         if (!TempoDentroDaZona(TimeCurrent(), zonaCompraTempoIni, zonaCompraTempoFim))
         {
             SafeLog(StringFormat("⏰ Janela COMPRA cancelada: zona fora do tempo | Agora=%s | Zona=[%s ~ %s]",
                                  TimeToString(TimeCurrent(), TIME_MINUTES),
                                  TimeToString(zonaCompraTempoIni, TIME_MINUTES),
                                  TimeToString(zonaCompraTempoFim, TIME_MINUTES)), 60, "tempoBuyCsv");
             ResetJanelaCompra();
             return;
         }

         if ( (ModoOperacao == MODO_AMBOS && CountOpenPositionsSide(POSITION_TYPE_BUY) >= MaxPorLado_Ambos) ||
              (ModoOperacao != MODO_AMBOS && PositionSelect(_Symbol)) )
         {
             Print("⛔ Capacidade de BUY atingida — cancelando janela de COMPRA.");
             ResetJanelaCompra();
             return;
         }

          if (ask < zonaCompraMin || ask > zonaCompraMax)
          {
              if (!foraZonaCompra)
              {
                  foraZonaCompra = true;
                  SafeLog(StringFormat("🚫 Preço saiu da zona de COMPRA (CSV) | Ask=%.5f | Zona=[%.5f ~ %.5f]",
                                       ask, zonaCompraMin, zonaCompraMax), 600, "saidaBuy");
              }
              ResetJanelaCompra();
              return;
          }
          else
          {
              foraZonaCompra = false;
          }

          if (TimeCurrent() > tempoInicioAguardarCompra + segundosJanela){
              PrintFormat("⏳ Tempo excedido COMPRA (CSV) | Agora=%s | Fim=%s",
                          TimeToString(TimeCurrent(), TIME_MINUTES),
                          TimeToString(tempoInicioAguardarCompra + segundosJanela, TIME_MINUTES));
              ResetJanelaCompra();
              return;
          }

          bool cruzouCompra=false;
          if (permitirComConfirmacao)
              cruzouCompra = VerificarCruzamentoMedia(true, GatilhoTF(janelaCompraTF));

          bool ordemExecutada=false;

          bool capBuyOkAmbos = (ModoOperacao != MODO_AMBOS)
                               ? true
                               : (CountOpenPositionsSide(POSITION_TYPE_BUY) < MaxPorLado_Ambos);

          string cmtSem = StringFormat("CSV|BUY|SEM|zona=%d|win=%ld", janelaCompraZonaIdx, janelaCompraId);
          string cmtCom = StringFormat("CSV|BUY|COM|zona=%d|win=%ld", janelaCompraZonaIdx, janelaCompraId);

          if (permitirComConfirmacao && cruzouCompra && !compraComFeita && capBuyOkAmbos
              && ticketBuyCom==0 && !ExistePosicaoPorComentario(cmtCom))
          {
              if(!PodeAbrirNovaOrdem(POSITION_TYPE_BUY,false)){
                SafeLog("⛔ Bloqueado por regra (limite total ou duplicação).", 300);
                 ResetJanelaCompra();
                 return;
              }

              double askExec = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
              if (!PrecoDentroDaZona(askExec, zonaCompraMin, zonaCompraMax))
              {
                 SafeLog(StringFormat("🚫 Bloqueio final BUY (CSV COM): preço fora da zona | Ask=%.5f | Zona=[%.5f ~ %.5f]",
                                      askExec, zonaCompraMin, zonaCompraMax), 60, "bloqBuyCsvCom");
                 ResetJanelaCompra();
                 return;
              }
              double sl = CalcularSLCompraDaZona(zonaCompraMin, zonaCompraMax);
              double risco = askExec - sl;
              double tp = askExec + risco * TakeProfitFactor;

              PrintFormat("✅ COMPRA (CSV) COM confirmação | Ask=%.5f | Zona=[%.5f ~ %.5f]",
                          askExec, zonaCompraMin, zonaCompraMax);

              double loteCalculado = CalcularLote(askExec, sl);

              if (loteCalculado > 0 && trade.Buy(loteCalculado, _Symbol, askExec, sl, tp, cmtCom))
              {
                  string arrowName = "SetaBuyCSV_" + TimeToString(TimeCurrent(), TIME_SECONDS);
                  ObjectCreate(0, arrowName, OBJ_ARROW_BUY, 0, TimeCurrent(), askExec);
                  ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clrBlue);

                  compraComFeita = true;
                  ticketBuyCom   = trade.ResultOrder();

                  if (ModoOperacao == MODO_AMBOS && !compraSemFeita){
                  } else {
                      ResetJanelaCompra();
                  }
                  ordemExecutada = true;
              } else {
                  Print("Erro Buy CSV (COM conf): ", trade.ResultRetcode(), " - ", trade.ResultRetcodeDescription());
              }
          }

         if (permitirSemConfirmacao && !ordemExecutada && !compraSemFeita && capBuyOkAmbos
             && ticketBuySem==0 && !ExistePosicaoPorComentario(cmtSem))
         {
             if(!PodeAbrirNovaOrdem(POSITION_TYPE_BUY,true)){
                SafeLog("⛔ Bloqueado por regra (limite total ou duplicação).", 300);
                ResetJanelaCompra();
                return;
             }

             compraSemFeita = true;
             static datetime ultimaCompraSem = 0;
             if (TimeCurrent() == ultimaCompraSem) return;
             ultimaCompraSem = TimeCurrent();

             double askExec = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
             if (!PrecoDentroDaZona(askExec, zonaCompraMin, zonaCompraMax))
             {
                 SafeLog(StringFormat("🚫 Bloqueio final BUY (CSV SEM): preço fora da zona | Ask=%.5f | Zona=[%.5f ~ %.5f]",
                                      askExec, zonaCompraMin, zonaCompraMax), 60, "bloqBuyCsvSem");
                 compraSemFeita = false;
                 ResetJanelaCompra();
                 return;
             }
             double sl = CalcularSLCompraDaZona(zonaCompraMin, zonaCompraMax);
             double risco = askExec - sl;
             double tp = askExec + risco * TakeProfitFactor;

             PrintFormat("✅ COMPRA (CSV) SEM confirmação | Ask=%.5f | Zona=[%.5f ~ %.5f]",
                         askExec, zonaCompraMin, zonaCompraMax);

             double loteCalculado = CalcularLote(askExec, sl);
             if (loteCalculado <= 0) {
                 Print("❌ Lote calculado inválido: ", loteCalculado, " — abortando.");
                 compraSemFeita = false;
                 return;
             }

             bool ok = trade.Buy(loteCalculado, _Symbol, askExec, sl, tp, cmtSem);
             uint retcode = trade.ResultRetcode();

             if (ok && (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED || retcode == TRADE_RETCODE_DONE_PARTIAL)) {
                 string arrowName = "SetaBuyCSV_" + TimeToString(TimeCurrent(), TIME_SECONDS);
                 ObjectCreate(0, arrowName, OBJ_ARROW_BUY, 0, TimeCurrent(), askExec);
                 ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clrAqua);
                 ticketBuySem = trade.ResultOrder();

                 if (ModoOperacao == MODO_AMBOS && !compraComFeita) {
                 } else {
                     ResetJanelaCompra();
                 }
             } else {
                 compraSemFeita = false;
             }
         }
          if (!ordemExecutada && !(permitirSemConfirmacao && !permitirComConfirmacao) && !logCompraFeitoNaBarra){
              logCompraFeitoNaBarra = true;
          }
      }


      // === ABRIR NOVA JANELA DE COMPRA ===
      {
         int buysAbertas = CountOpenPositionsSide(POSITION_TYPE_BUY);
         bool capJanelaBuy = (ModoOperacao == MODO_AMBOS) ? (buysAbertas < MaxPorLado_Ambos)
                                                 : (buysAbertas < 1);

         // Exaustão na TF da zona tocada.
         ENUM_TIMEFRAMES tfZonaCompra = (suporteIdxSel >= 0 && suporteIdxSel < ArraySize(zonas))
                                        ? zonas[suporteIdxSel].tf_origin : PERIOD_CURRENT;
         bool exaustaoCompra = false;
         if (suporteEncontrado &&
             LerOsciladoresTF(TFZonaEfetiva(tfZonaCompra), rsiValue, stochValue, ultoscCompraOk, ultoscVendaOk))
            exaustaoCompra = (rsiValue < RSI_Buy && stochValue < 20 && ultoscCompraOk);

         if (capJanelaBuy && CountOpenPositionsAny() < MaxOrdensPorAtivo
             && suporteEncontrado && exaustaoCompra
             && !aguardandoCompra)
         {
             tempoInicioAguardarCompra = TimeCurrent();
             aguardandoCompra = true;
             zonaCompraMin = suporteMin;
             zonaCompraMax = suporteMax;
             janelaCompraZonaIdx = suporteIdxSel;
             janelaCompraTF = tfZonaCompra;
             if (suporteIdxSel >= 0 && suporteIdxSel < ArraySize(zonas))
             {
                zonaCompraTempoIni = zonas[suporteIdxSel].tempo_ini;
                zonaCompraTempoFim = zonas[suporteIdxSel].tempo_fim;
             }
             else
             {
                zonaCompraTempoIni = 0;
                zonaCompraTempoFim = 0;
             }


             compraSemFeita = false;
             compraComFeita = false;
             if (janelaCompraId == 0)
             janelaCompraId = (long)TimeCurrent();
             ticketBuySem = 0;
             ticketBuyCom = 0;
         }
      }

      // === VENDA CSV ===
      if (aguardandoVenda)
      {
          if (!TempoDentroDaZona(TimeCurrent(), zonaVendaTempoIni, zonaVendaTempoFim))
          {
              SafeLog(StringFormat("⏰ Janela VENDA cancelada: zona fora do tempo | Agora=%s | Zona=[%s ~ %s]",
                                   TimeToString(TimeCurrent(), TIME_MINUTES),
                                   TimeToString(zonaVendaTempoIni, TIME_MINUTES),
                                   TimeToString(zonaVendaTempoFim, TIME_MINUTES)), 60, "tempoSellCsv");
              ResetJanelaVenda();
              return;
          }

          if ( (ModoOperacao == MODO_AMBOS && CountOpenPositionsSide(POSITION_TYPE_SELL) >= MaxPorLado_Ambos) ||
               (ModoOperacao != MODO_AMBOS && PositionSelect(_Symbol)) )
          {
              Print("⛔ Capacidade de SELL atingida — cancelando janela de VENDA.");
              ResetJanelaVenda();
              return;
          }
          if (bid < zonaVendaMin || bid > zonaVendaMax)
          {
              if (!foraZonaVenda)
              {
                  foraZonaVenda = true;
                  SafeLog(StringFormat("🚫 Preço saiu da zona de VENDA (CSV) | Bid=%.5f | Zona=[%.5f ~ %.5f]",
                                       bid, zonaVendaMin, zonaVendaMax), 600, "saidaSell");
              }
              ResetJanelaVenda();
              return;
          }
          else
          {
              foraZonaVenda = false;
          }

          if (TimeCurrent() > tempoInicioAguardarVenda + segundosJanela){
              PrintFormat("⏳ Tempo excedido VENDA (CSV) | Agora=%s | Fim=%s",
                          TimeToString(TimeCurrent(), TIME_MINUTES),
                          TimeToString(tempoInicioAguardarVenda + segundosJanela, TIME_MINUTES));
              ResetJanelaVenda();
              return;
          }

          bool cruzouVenda=false;
          if (permitirComConfirmacao)
              cruzouVenda = VerificarCruzamentoMedia(false, GatilhoTF(janelaVendaTF));

          bool ordemExecutada=false;

          bool capSellOkAmbos = (ModoOperacao != MODO_AMBOS)
                                ? true
                                : (CountOpenPositionsSide(POSITION_TYPE_SELL) < MaxPorLado_Ambos);

          string cmtSem = StringFormat("CSV|SELL|SEM|zona=%d|win=%ld", janelaVendaZonaIdx, janelaVendaId);
          string cmtCom = StringFormat("CSV|SELL|COM|zona=%d|win=%ld", janelaVendaZonaIdx, janelaVendaId);

          if (permitirComConfirmacao && cruzouVenda && !vendaComFeita && capSellOkAmbos
              && ticketSellCom==0 && !ExistePosicaoPorComentario(cmtCom))
          {
              if(!PodeAbrirNovaOrdem(POSITION_TYPE_SELL,false)){
                 SafeLog("⛔ Bloqueado por regra (limite total ou duplicação).", 300);
                 ResetJanelaVenda();
                 return;
              }
              double bidExec = SymbolInfoDouble(_Symbol, SYMBOL_BID);
              if (!PrecoDentroDaZona(bidExec, zonaVendaMin, zonaVendaMax))
              {
                 SafeLog(StringFormat("🚫 Bloqueio final SELL (CSV COM): preço fora da zona | Bid=%.5f | Zona=[%.5f ~ %.5f]",
                                      bidExec, zonaVendaMin, zonaVendaMax), 60, "bloqSellCsvCom");
                 ResetJanelaVenda();
                 return;
              }
              double sl = CalcularSLVendaDaZona(zonaVendaMin, zonaVendaMax);
              double risco = sl - bidExec;
              double tp = bidExec - risco * TakeProfitFactor;

              PrintFormat("✅ VENDA (CSV) COM confirmação | Bid=%.5f | Zona=[%.5f ~ %.5f]",
                          bidExec, zonaVendaMin, zonaVendaMax);

              double loteCalculado = CalcularLote(bidExec, sl);
              if (loteCalculado <= 0) {
                  Print("❌ Lote calculado inválido: ", loteCalculado, " — abortando.");
                  return;
              }

              trade.Sell(loteCalculado, _Symbol, bidExec, sl, tp, cmtCom);

              uint retcode = trade.ResultRetcode();
              if (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED || retcode == TRADE_RETCODE_DONE_PARTIAL) {

                  string arrowName = "SetaSellCSV_" + TimeToString(TimeCurrent(), TIME_SECONDS);
                  ObjectCreate(0, arrowName, OBJ_ARROW_SELL, 0, TimeCurrent(), bidExec);
                  ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clrRed);

                  vendaComFeita = true;
                  ticketSellCom = trade.ResultOrder();

                  if (ModoOperacao == MODO_AMBOS && !vendaSemFeita){
                  } else {
                      ResetJanelaVenda();
                  }
                  ordemExecutada = true;
              } else {
                  PrintFormat("❌ Erro real SELL CSV (COM conf): %u - %s | Preço tentado=%.5f",
                              retcode, trade.ResultRetcodeDescription(), bidExec);
              }
          }

         if (permitirSemConfirmacao && !ordemExecutada && !vendaSemFeita && capSellOkAmbos
             && ticketSellSem==0 && !ExistePosicaoPorComentario(cmtSem))
         {
             if(!PodeAbrirNovaOrdem(POSITION_TYPE_SELL,true)){
                SafeLog("⛔ Bloqueado por regra (limite total ou duplicação).", 300);
                ResetJanelaVenda();
                return;
             }

             vendaSemFeita = true;
             static datetime ultimaVendaSem = 0;
             if (TimeCurrent() == ultimaVendaSem) return;
             ultimaVendaSem = TimeCurrent();

             double bidExec = SymbolInfoDouble(_Symbol, SYMBOL_BID);
             if (!PrecoDentroDaZona(bidExec, zonaVendaMin, zonaVendaMax))
             {
                 SafeLog(StringFormat("🚫 Bloqueio final SELL (CSV SEM): preço fora da zona | Bid=%.5f | Zona=[%.5f ~ %.5f]",
                                      bidExec, zonaVendaMin, zonaVendaMax), 60, "bloqSellCsvSem");
                 vendaSemFeita = false;
                 ResetJanelaVenda();
                 return;
             }
             double sl = CalcularSLVendaDaZona(zonaVendaMin, zonaVendaMax);
             double risco = sl - bidExec;
             double tp = bidExec - risco * TakeProfitFactor;

             PrintFormat("✅ VENDA (CSV) SEM confirmação | Bid=%.5f | Zona=[%.5f ~ %.5f]",
                         bidExec, zonaVendaMin, zonaVendaMax);

             double loteCalculado = CalcularLote(bidExec, sl);
             if (loteCalculado <= 0) {
                 Print("❌ Lote calculado inválido: ", loteCalculado, " — abortando.");
                 vendaSemFeita = false;
                 return;
             }

             bool ok = trade.Sell(loteCalculado, _Symbol, bidExec, sl, tp, cmtSem);
             uint retcode = trade.ResultRetcode();

             if (ok && (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED || retcode == TRADE_RETCODE_DONE_PARTIAL)) {
                 string arrowName = "SetaSellCSV_" + TimeToString(TimeCurrent(), TIME_SECONDS);
                 ObjectCreate(0, arrowName, OBJ_ARROW_SELL, 0, TimeCurrent(), bidExec);
                 ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clrOrangeRed);
                 ticketSellSem = trade.ResultOrder();

                 if (ModoOperacao == MODO_AMBOS && !vendaComFeita) {
                 } else {
                     ResetJanelaVenda();
                 }
             } else {
                 vendaSemFeita = false;
             }
         }


          if (!ordemExecutada && !(permitirSemConfirmacao && !permitirComConfirmacao) && !logVendaFeitoNaBarra){
              SafeLog(StringFormat("🔄 Aguardando condição para VENDA (CSV) | Modo=%d", ModoOperacao), 900, "aguardaSell");
              logVendaFeitoNaBarra = true;
          }
      }

      // === ABRIR NOVA JANELA DE VENDA ===
      {
         int sellsAbertas = CountOpenPositionsSide(POSITION_TYPE_SELL);
         bool capJanelaSell = (ModoOperacao == MODO_AMBOS) ? (sellsAbertas < MaxPorLado_Ambos)
                                                  : (sellsAbertas < 1);

         // Exaustão na TF da zona tocada.
         ENUM_TIMEFRAMES tfZonaVenda = (resistenciaIdxSel >= 0 && resistenciaIdxSel < ArraySize(zonas))
                                       ? zonas[resistenciaIdxSel].tf_origin : PERIOD_CURRENT;
         bool exaustaoVenda = false;
         if (resistenciaEncontrada &&
             LerOsciladoresTF(TFZonaEfetiva(tfZonaVenda), rsiValue, stochValue, ultoscCompraOk, ultoscVendaOk))
            exaustaoVenda = (rsiValue > RSI_Sell && stochValue > 80 && ultoscVendaOk);

         if (capJanelaSell && CountOpenPositionsAny() < MaxOrdensPorAtivo
             && resistenciaEncontrada && exaustaoVenda
             && !aguardandoVenda)
         {
             tempoInicioAguardarVenda = TimeCurrent();
             aguardandoVenda = true;
             zonaVendaMin = resistenciaMin;
             zonaVendaMax = resistenciaMax;
             janelaVendaZonaIdx = resistenciaIdxSel;
             janelaVendaTF = tfZonaVenda;
             if (resistenciaIdxSel >= 0 && resistenciaIdxSel < ArraySize(zonas))
             {
                zonaVendaTempoIni = zonas[resistenciaIdxSel].tempo_ini;
                zonaVendaTempoFim = zonas[resistenciaIdxSel].tempo_fim;
             }
             else
             {
                zonaVendaTempoIni = 0;
                zonaVendaTempoFim = 0;
             }


             vendaSemFeita = false;
             vendaComFeita = false;
             if (janelaVendaId == 0)
             janelaVendaId = (long)TimeCurrent();
             ticketSellSem = 0;
             ticketSellCom = 0;

             SafeLog(StringFormat("🕒 Janela VENDA até %s | Zona=[%.5f~%.5f]",
                                  TimeToString(tempoInicioAguardarVenda + segundosJanela, TIME_MINUTES),
                                  zonaVendaMin, zonaVendaMax), 30);
         }
      }

      return;
   }

   // === Procurar zonas (LIVE MODE — scan chart objects) ===
   datetime tempo = TimeCurrent();
   double melhorDistanciaSuporte = DBL_MAX;
   double suporteMin = 0, suporteMax = 0;
   string zonaSuporteSelecionada = "";
   datetime suporteTempoIni = 0, suporteTempoFim = 0;

   double melhorDistanciaResistencia = DBL_MAX;
   double resistenciaMin = 0, resistenciaMax = 0;
   string zonaResistenciaSelecionada = "";
   datetime resistenciaTempoIni = 0, resistenciaTempoFim = 0;

   int total_objs = ObjectsTotal(0);

   for (int i = 0; i < total_objs; i++)
   {
      string nome = ObjectName(0, i);
      if (ObjectGetInteger(0, nome, OBJPROP_TYPE) != OBJ_RECTANGLE)
         continue;

      double price1 = ObjectGetDouble(0, nome, OBJPROP_PRICE, 0);
      double price2 = ObjectGetDouble(0, nome, OBJPROP_PRICE, 1);
      datetime t1 = (datetime)ObjectGetInteger(0, nome, OBJPROP_TIME, 0);
      datetime t2 = (datetime)ObjectGetInteger(0, nome, OBJPROP_TIME, 1);

      double zonaMin = MathMin(price1, price2);
      double zonaMax = MathMax(price1, price2);
      double centro = (zonaMin + zonaMax) / 2;
      datetime zonaTempoIni = (t1 < t2) ? t1 : t2;
      datetime zonaTempoFim = (t1 > t2) ? t1 : t2;

      if (!TempoDentroDaZona(tempo, zonaTempoIni, zonaTempoFim))
         continue;

      // SUPORTE
      if (StringFind(nome, "ZONA_SUPORTE") == 0 && ask >= zonaMin && ask <= zonaMax)
      {
         double distancia = MathAbs(ask - centro);
         if (distancia < melhorDistanciaSuporte)
         {
            melhorDistanciaSuporte = distancia;
            suporteMin = zonaMin;
            suporteMax = zonaMax;
            zonaSuporteSelecionada = nome;
            suporteTempoIni = zonaTempoIni;
            suporteTempoFim = zonaTempoFim;
         }
      }

      // RESISTÊNCIA
      if (StringFind(nome, "ZONA_RESISTENCIA") == 0 && bid >= zonaMin && bid <= zonaMax)
      {
         double distancia = MathAbs(bid - centro);
         if (distancia < melhorDistanciaResistencia)
         {
            melhorDistanciaResistencia = distancia;
            resistenciaMin = zonaMin;
            resistenciaMax = zonaMax;
            zonaResistenciaSelecionada = nome;
            resistenciaTempoIni = zonaTempoIni;
            resistenciaTempoFim = zonaTempoFim;
         }
      }
   }

   // === COMPRA MANUAL ===
   // Exaustão na TF da zona tocada (recuperada de zonas[] por preço/tipo).
   ENUM_TIMEFRAMES tfZonaCompraLive = (zonaSuporteSelecionada != "")
                                      ? TFDaZonaCasada("S", suporteMin, suporteMax) : PERIOD_CURRENT;
   bool exaustaoCompraLive = false;
   if (zonaSuporteSelecionada != "" &&
       LerOsciladoresTF(TFZonaEfetiva(tfZonaCompraLive), rsiValue, stochValue, ultoscCompraOk, ultoscVendaOk))
      exaustaoCompraLive = (rsiValue < RSI_Buy && stochValue < 20 && ultoscCompraOk);

   if (!aguardandoCompra && zonaSuporteSelecionada != "" && exaustaoCompraLive)
   {
       if (TimeCurrent() - ultimoLogCompraManual > intervaloLogJanelaSegundos)
       {
           ultimoLogCompraManual = TimeCurrent();
           SafeLog(StringFormat("🕒 Janela COMPRA até %s | Zona=[%.5f~%.5f]",
                                TimeToString(TimeCurrent() + segundosJanela, TIME_MINUTES),
                                suporteMin, suporteMax), 30);
       }
       aguardandoCompra = true;
       tempoInicioAguardarCompra = TimeCurrent();
       zonaCompraMin = suporteMin;
       zonaCompraMax = suporteMax;
       zonaCompraTempoIni = suporteTempoIni;
       zonaCompraTempoFim = suporteTempoFim;
       janelaCompraTF = tfZonaCompraLive;
   }

   if (aguardandoCompra)
   {
       if (!TempoDentroDaZona(TimeCurrent(), zonaCompraTempoIni, zonaCompraTempoFim))
       {
           ResetJanelaCompra();
           return;
       }

       if (ask < zonaCompraMin || ask > zonaCompraMax)
       {
           if (TimeCurrent() - ultimoLogSaidaCompra > intervaloLogSaidaSegundos)
           {
               ultimoLogSaidaCompra = TimeCurrent();
               SafeLog(StringFormat("🚫 Preço saiu da zona de COMPRA | Ask=%.5f | Zona=[%.5f ~ %.5f]",
                                    ask, zonaCompraMin, zonaCompraMax), 0);
           }
           ResetJanelaCompra();
           return;
       }


       if (TimeCurrent() > tempoInicioAguardarCompra + segundosJanela)
       {
           PrintFormat("⏳ Tempo excedido COMPRA MANUAL | Agora=%s | Fim=%s",
                       TimeToString(TimeCurrent(), TIME_MINUTES),
                       TimeToString(tempoInicioAguardarCompra + segundosJanela, TIME_MINUTES));
           ResetJanelaCompra();
           return;
       }


       bool cruzouCompra = permitirComConfirmacao && VerificarCruzamentoMedia(true, GatilhoTF(janelaCompraTF));

       bool capBuyOkAmbos = (ModoOperacao != MODO_AMBOS)
                            ? true
                            : (CountOpenPositionsSide(POSITION_TYPE_BUY) < MaxPorLado_Ambos);

       double askExec = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
       if (!PrecoDentroDaZona(askExec, zonaCompraMin, zonaCompraMax))
       {
           ResetJanelaCompra();
           return;
       }
       double sl = CalcularSLCompraDaZona(zonaCompraMin, zonaCompraMax);
       double risco = askExec - sl;
       double tp = askExec + risco * TakeProfitFactor;

       if (permitirComConfirmacao && cruzouCompra && !compraComFeita && capBuyOkAmbos)
       {
           if (!PodeAbrirNovaOrdem(POSITION_TYPE_BUY,false)) return;
           double lote = CalcularLote(askExec, sl);
           string cmtManualCom = StringFormat("Manual|BUY|COM|zona=%d|win=%ld", janelaCompraZonaIdx, janelaCompraId);
           if (lote > 0 && trade.Buy(lote, _Symbol, askExec, sl, tp, cmtManualCom))

           {
               compraComFeita = true;
               ObjectCreate(0, "SetaBuyManualCom_" + TimeToString(TimeCurrent(), TIME_SECONDS),
                            OBJ_ARROW_BUY, 0, TimeCurrent(), askExec);
               ObjectSetInteger(0, "SetaBuyManualCom_" + TimeToString(TimeCurrent(), TIME_SECONDS),
                                OBJPROP_COLOR, clrBlue);
               if (ModoOperacao != MODO_AMBOS || compraSemFeita) ResetJanelaCompra();
           }
       }

      if (permitirSemConfirmacao && !compraSemFeita && capBuyOkAmbos)
      {
          if (!PodeAbrirNovaOrdem(POSITION_TYPE_BUY,true))
              return;

          string cmtManualSem = StringFormat("Manual|BUY|SEM|zona=%d|win=%ld", janelaCompraZonaIdx, janelaCompraId);

          double lote = CalcularLote(askExec, sl);
          if (lote > 0 && trade.Buy(lote, _Symbol, askExec, sl, tp, cmtManualSem))
          {
              compraSemFeita = true;
              string arrowName = "SetaBuyManualSem_" + TimeToString(TimeCurrent(), TIME_SECONDS);
              ObjectCreate(0, arrowName, OBJ_ARROW_BUY, 0, TimeCurrent(), askExec);
              ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clrAqua);

              if (ModoOperacao != MODO_AMBOS || compraComFeita)
                  ResetJanelaCompra();
          }
      }

   }


   // === VENDA MANUAL ===
   // Exaustão na TF da zona tocada (recuperada de zonas[] por preço/tipo).
   ENUM_TIMEFRAMES tfZonaVendaLive = (zonaResistenciaSelecionada != "")
                                     ? TFDaZonaCasada("R", resistenciaMin, resistenciaMax) : PERIOD_CURRENT;
   bool exaustaoVendaLive = false;
   if (zonaResistenciaSelecionada != "" &&
       LerOsciladoresTF(TFZonaEfetiva(tfZonaVendaLive), rsiValue, stochValue, ultoscCompraOk, ultoscVendaOk))
      exaustaoVendaLive = (rsiValue > RSI_Sell && stochValue > 80 && ultoscVendaOk);

   if (!aguardandoVenda && zonaResistenciaSelecionada != "" && exaustaoVendaLive)
   {
       if (TimeCurrent() - ultimoLogVendaManual > intervaloLogJanelaSegundos)
       {
           ultimoLogVendaManual = TimeCurrent();
           SafeLog(StringFormat("🕒 Janela VENDA até %s | Zona=[%.5f~%.5f]",
                                TimeToString(TimeCurrent() + segundosJanela, TIME_MINUTES),
                                resistenciaMin, resistenciaMax), 30);
       }
       aguardandoVenda = true;
       tempoInicioAguardarVenda = TimeCurrent();
       zonaVendaMin = resistenciaMin;
       zonaVendaMax = resistenciaMax;
       zonaVendaTempoIni = resistenciaTempoIni;
       zonaVendaTempoFim = resistenciaTempoFim;
       janelaVendaTF = tfZonaVendaLive;
   }

   if (aguardandoVenda)
   {
       if (!TempoDentroDaZona(TimeCurrent(), zonaVendaTempoIni, zonaVendaTempoFim))
       {
           ResetJanelaVenda();
           return;
       }

       if (bid < zonaVendaMin || bid > zonaVendaMax)
       {
           if (TimeCurrent() - ultimoLogSaidaVenda > intervaloLogSaidaSegundos)
           {
               ultimoLogSaidaVenda = TimeCurrent();
               SafeLog(StringFormat("🚫 Preço saiu da zona de VENDA | Bid=%.5f | Zona=[%.5f ~ %.5f]",
                                    bid, zonaVendaMin, zonaVendaMax), 0);
           }
           ResetJanelaVenda();
           return;
       }

       if (TimeCurrent() > tempoInicioAguardarVenda + segundosJanela)
       {
           PrintFormat("⏳ Tempo excedido VENDA MANUAL | Agora=%s | Fim=%s",
                       TimeToString(TimeCurrent(), TIME_MINUTES),
                       TimeToString(tempoInicioAguardarVenda + segundosJanela, TIME_MINUTES));
           ResetJanelaVenda();
           return;
       }

       bool cruzouVenda = permitirComConfirmacao && VerificarCruzamentoMedia(false, GatilhoTF(janelaVendaTF));

       bool capSellOkAmbos = (ModoOperacao != MODO_AMBOS)
                             ? true
                             : (CountOpenPositionsSide(POSITION_TYPE_SELL) < MaxPorLado_Ambos);

       double bidExec = SymbolInfoDouble(_Symbol, SYMBOL_BID);
       if (!PrecoDentroDaZona(bidExec, zonaVendaMin, zonaVendaMax))
       {
           ResetJanelaVenda();
           return;
       }
       double sl = CalcularSLVendaDaZona(zonaVendaMin, zonaVendaMax);
       double risco = sl - bidExec;
       double tp = bidExec - risco * TakeProfitFactor;

       if (permitirComConfirmacao && cruzouVenda && !vendaComFeita && capSellOkAmbos)
       {
           if (!PodeAbrirNovaOrdem(POSITION_TYPE_SELL,false)) return;
           double lote = CalcularLote(bidExec, sl);
           string cmtManualCom = StringFormat("Manual|SELL|COM|zona=%d|win=%ld", janelaVendaZonaIdx, janelaVendaId);
           if (lote > 0 && trade.Sell(lote, _Symbol, bidExec, sl, tp, cmtManualCom))
           {
               vendaComFeita = true;
               ObjectCreate(0, "SetaSellManualCom_" + TimeToString(TimeCurrent(), TIME_SECONDS),
                            OBJ_ARROW_SELL, 0, TimeCurrent(), bidExec);
               ObjectSetInteger(0, "SetaSellManualCom_" + TimeToString(TimeCurrent(), TIME_SECONDS),
                                OBJPROP_COLOR, clrRed);
               if (ModoOperacao != MODO_AMBOS || vendaSemFeita) ResetJanelaVenda();
           }
       }

      if (permitirSemConfirmacao && !vendaSemFeita && capSellOkAmbos)
      {
          if (!PodeAbrirNovaOrdem(POSITION_TYPE_SELL,true))
              return;

          string cmtManualSem = StringFormat("Manual|SELL|SEM|zona=%d|win=%ld", janelaVendaZonaIdx, janelaVendaId);

          double lote = CalcularLote(bidExec, sl);
          if (lote > 0 && trade.Sell(lote, _Symbol, bidExec, sl, tp, cmtManualSem))
          {
              vendaSemFeita = true;
              string arrowName = "SetaSellManualSem_" + TimeToString(TimeCurrent(), TIME_SECONDS);
              ObjectCreate(0, arrowName, OBJ_ARROW_SELL, 0, TimeCurrent(), bidExec);
              ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clrOrangeRed);

              if (ModoOperacao != MODO_AMBOS || vendaComFeita)
                  ResetJanelaVenda();
          }
      }
   }
}

void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& req,
                        const MqlTradeResult& res)
{
   if (trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   ulong deal = trans.deal;
   if (!HistoryDealSelect(deal))
      return;

   long magic   = (long)HistoryDealGetInteger(deal, DEAL_MAGIC);
   long entry   = HistoryDealGetInteger(deal, DEAL_ENTRY);
   long reason  = HistoryDealGetInteger(deal, DEAL_REASON);
   long dtype   = HistoryDealGetInteger(deal, DEAL_TYPE);
   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT);
   double price  = HistoryDealGetDouble(deal, DEAL_PRICE);
   datetime dtime = (datetime)HistoryDealGetInteger(deal, DEAL_TIME);
   string comment = HistoryDealGetString(deal, DEAL_COMMENT);

   if (magic != Magic || entry != DEAL_ENTRY_OUT || reason != DEAL_REASON_SL)
      return;

   bool wasBuy = (dtype == DEAL_TYPE_SELL);

   IniciarCooldown();
   KillWindowsAfterSL(wasBuy);
}



bool VerificarCruzamentoMedia(bool compra, ENUM_TIMEFRAMES triggerTF)
{
    if (!usarConfirmacaoMedia)
        return false;

    int sma = SMAHandle(triggerTF);
    if (sma == INVALID_HANDLE)
        return false;

    double smaBuffer[];
    ArraySetAsSeries(smaBuffer, true);

    if (CopyBuffer(sma, 0, 2, 2, smaBuffer) <= 0)
    {
        Print("Erro ao copiar dados da SMA60");
        return false;
    }

    double closeBuffer[];
    ArraySetAsSeries(closeBuffer, true);

    if (CopyClose(_Symbol, triggerTF, 2, 2, closeBuffer) <= 0)
    {
        Print("Erro ao copiar preços de fechamento");
        return false;
    }

    if (compra)
    {
        if (closeBuffer[1] > smaBuffer[1] && closeBuffer[0] > smaBuffer[0])
            return true;
    }
    else
    {
        if (closeBuffer[1] < smaBuffer[1] && closeBuffer[0] < smaBuffer[0])
            return true;
    }

    return false;
}

void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   if (id == CHARTEVENT_OBJECT_CLICK)
   {
      if (sparam == "BotaoSuporte")
      {
         IniciarDesenhoZona("SUPORTE");
         return;
      }

      else if (sparam == "BotaoResistencia")
      {
         IniciarDesenhoZona("RESISTENCIA");
         return;
      }

      else if (sparam == "BotaoImportarZonas")
      {
         ImportarZonasMaisRecente();
         return;
      }

      else if (sparam == "BotaoExportarCsvGPT")
      {
         GPT_ExportAllTimeframesIfNeeded(true, "manual button");
         Alert("S&R GPT: CSVs exportados para " + _Symbol);
         return;
      }
   }

   if (id == CHARTEVENT_CLICK && tipoZonaPendente != "")
   {
      ProcessarCliqueDesenhoZona((int)lparam, (int)dparam);
      return;
   }

   if ((id == CHARTEVENT_OBJECT_DRAG ||
        id == CHARTEVENT_OBJECT_CHANGE ||
        id == CHARTEVENT_OBJECT_DELETE) &&
       GPT_IsZoneObjectName(sparam))
   {
      GPT_SaveCurrentZones("chart edit");
      return;
   }
}
