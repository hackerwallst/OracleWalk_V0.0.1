#property script_show_inputs

// Cores padrao das zonas (ajuste conforme necessario)
#define COR_SUPORTE clrLime
#define COR_RESISTENCIA clrRed

input string ArquivoCSV = "";          // Nome do arquivo CSV (vazio = padrao ZonasManual_SYMBOL_TF.csv)
input bool FiltrarSymbol = true;       // Ignora linhas com Symbol diferente do grafico atual (Timeframe ignorado)
input bool LimparAntes = true;         // Remove zonas importadas anteriormente (prefixo _CSV_)
input bool PularCabecalho = true;      // CSV possui cabecalho?

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

void LimparZonasImportadas()
{
   int total = ObjectsTotal(0);
   for (int i = total - 1; i >= 0; i--)
   {
      string nome = ObjectName(0, i);
      if (StringFind(nome, "ZONA_SUPORTE_CSV_") == 0 ||
          StringFind(nome, "ZONA_RESISTENCIA_CSV_") == 0)
      {
         ObjectDelete(0, nome);
      }
   }
}

void OnStart()
{
   string arquivo = ArquivoCSV;
   if (arquivo == "")
   {
      arquivo = EncontrarArquivoMaisRecente(_Symbol);
      if (arquivo == "")
         arquivo = "ZonasManual_" + _Symbol + "_" + TimeframeToStr(_Period) + ".csv";
   }

   ImportarZonas(arquivo);
}

string EncontrarArquivoMaisRecente(string simbolo)
{
   string mask = "ZonasManual_" + simbolo + "_*.csv";
   string nome = "";
   datetime dt = 0;
   long size = 0;

   long h = FileFindFirst(mask, nome, dt, size);
   if (h == INVALID_HANDLE)
      return "";

   string escolhido = nome;
   datetime dt_escolhido = dt;

   while (FileFindNext(h, nome, dt, size))
   {
      if (dt > dt_escolhido)
      {
         dt_escolhido = dt;
         escolhido = nome;
      }
   }

   FileFindClose(h);
   return escolhido;
}

void ImportarZonas(string arquivo)
{
   if (LimparAntes)
      LimparZonasImportadas();

   ResetLastError();
   int handle = FileOpen(arquivo, FILE_READ | FILE_CSV | FILE_ANSI, ';');
   if (handle == INVALID_HANDLE)
   {
      Print("Erro ao abrir arquivo CSV: ", arquivo, " | Erro: ", GetLastError());
      return;
   }

   // Pula cabecalho
   if (PularCabecalho)
   {
      for (int i = 0; i < 7 && !FileIsEnding(handle); i++)
         FileReadString(handle);
   }

   int linhas_lidas = 0;
   int zonas_importadas = 0;
   int zonas_ignoradas = 0;
   while (!FileIsEnding(handle))
   {
      string symbolStr    = FileReadString(handle);
      string timeframeStr = FileReadString(handle);
      string tipo         = FileReadString(handle);
      string tempo1       = FileReadString(handle);
      string tempo2       = FileReadString(handle);
      string topoStr      = FileReadString(handle);
      string fundoStr     = FileReadString(handle);

      if (symbolStr == "" && timeframeStr == "" && tipo == "" &&
          tempo1 == "" && tempo2 == "" && topoStr == "" && fundoStr == "")
      {
         break;
      }

      linhas_lidas++;

      if (FiltrarSymbol)
      {
         if (symbolStr != _Symbol)
         {
            zonas_ignoradas++;
            continue;
         }
      }

      if (tipo != "S" && tipo != "R")
      {
         zonas_ignoradas++;
         continue;
      }

      datetime t1 = StringToTime(tempo1);
      datetime t2 = StringToTime(tempo2);
      double topo = StringToDouble(topoStr);
      double fundo = StringToDouble(fundoStr);

      if (t1 == 0 || t2 == 0 || t1 == t2 || topo == fundo)
      {
         zonas_ignoradas++;
         continue;
      }

      datetime tempo_ini = (t1 < t2) ? t1 : t2;
      datetime tempo_fim = (t1 > t2) ? t1 : t2;
      double preco_topo = MathMax(topo, fundo);
      double preco_fundo = MathMin(topo, fundo);

      string nome = (tipo == "S")
         ? "ZONA_SUPORTE_CSV_" + IntegerToString(zonas_importadas)
         : "ZONA_RESISTENCIA_CSV_" + IntegerToString(zonas_importadas);
      color cor = (tipo == "S") ? COR_SUPORTE : COR_RESISTENCIA;

      if (ObjectFind(0, nome) >= 0)
         ObjectDelete(0, nome);

      if (!ObjectCreate(0, nome, OBJ_RECTANGLE, 0, tempo_ini, preco_topo, tempo_fim, preco_fundo))
      {
         Print("Erro ao criar zona: ", nome, " | Erro: ", GetLastError());
         zonas_ignoradas++;
         continue;
      }

      ObjectSetInteger(0, nome, OBJPROP_COLOR, cor);
      ObjectSetInteger(0, nome, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, nome, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, nome, OBJPROP_BACK, true);
      ObjectSetInteger(0, nome, OBJPROP_SELECTABLE, true);
      ObjectSetInteger(0, nome, OBJPROP_SELECTED, false);

      zonas_importadas++;
   }

   FileClose(handle);
   Print("Importacao concluida. Linhas lidas: ", linhas_lidas,
         " | Zonas importadas: ", zonas_importadas,
         " | Zonas ignoradas: ", zonas_ignoradas,
         " | Arquivo: ", arquivo);
}
