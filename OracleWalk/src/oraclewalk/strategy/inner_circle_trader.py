# file: oraclewalk/strategy/inner_circle_trader.py

import numpy as np
import pandas as pd
import time

from oraclewalk.strategy.base_strategy import StrategyBase
from oraclewalk.data.indicators import add_atr, detect_fvg


class InnerCircleTrader(StrategyBase):
    """
    Estratégia Inner Circle Trader (ICT / FVG) portada do Colab.

    Reproduz a lógica do `generate_signals(df)` do notebook:
    - EMA 50 como filtro de tendência
    - Detecção de FVG no estilo BigBeluga
    - Entrada no reteste dos 50% do FVG
    - Stop atrás do bloco
    - TP = 3R
    - Filtro de risco mínimo com ATR14 (opcional)
    """

    def __init__(self, cfg):
        self.cfg = cfg
        # se quiser depois, dá pra puxar RR, MAX_AGE, etc. do config
        self._last_fvg_calc = 0.0
        self._last_fvg_log = 0.0

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Mantém EXATAMENTE a mesma lógica do generate_signals(df) do framework original.
        Alinhado 100% com: Inner Cicle Trader /backtest_framework_btc (10).py

        - recebe df com colunas: datetime, open, high, low, close, volume
        - devolve um DataFrame com coluna 'signal' (+ metadata de entrada)
        """

        # EXATAMENTE como no original (linha 917-919)
        df = df.copy()
        
        # Garante que datetime seja uma coluna (não índice)
        # O HistoricalDataHandler retorna com datetime como índice
        if df.index.name == "datetime" or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            if "index" in df.columns:
                df = df.rename(columns={"index": "datetime"})
        
        # Se datetime não existe como coluna, cria a partir do índice
        if "datetime" not in df.columns:
            if isinstance(df.index, pd.DatetimeIndex):
                df["datetime"] = df.index
            else:
                raise ValueError("DataFrame deve ter coluna 'datetime' ou índice DatetimeIndex")
        
        df["datetime"] = pd.to_datetime(df["datetime"])

        # --- EMA 50 para filtro de tendência (igual ao original linha 921-923) ---
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        indicadores_usados = ["ema50"]

        # Garante ATR14 presente (no original é adicionado ANTES de chamar generate_signals)
        # Mas aqui verificamos para garantir compatibilidade
        if "atr14" not in df.columns:
            df = add_atr(df, 14, name="atr14")

        # 1) Detecta FVGs com o indicador oficial (EXATAMENTE como linha 926 do original)
        # IMPORTANTE: No original é chamado sem filter_percent, então usa o padrão 0.5
        fvg_df = detect_fvg(df, extend_bars=50)
        print("FVGs detectados (total):", len(fvg_df))


        # DataFrame de sinais no padrão do backtester original
        signals = pd.DataFrame({
            "datetime": df["datetime"],
            "signal": 0,
            "entry_price": np.nan,
            "stop_price": np.nan,
            "take_price": np.nan,
            "size": 1.0,
            "risk": np.nan,
        })

        RR           = 3.0    # TP = 3R
        MAX_AGE      = 100    # FVG expira depois de 100 candles
        MIN_ATR_FACT = 0.25   # risco mínimo = 0.25 * ATR14

        n      = len(df)
        highs  = df["high"].values
        lows   = df["low"].values
        vols   = df["volume"].values
        closes = df["close"].values
        atr14  = df["atr14"].values if "atr14" in df.columns else None
        ema50  = df["ema50"].values

        fvg_validos_volume  = 0
        fvg_validos_tamanho = 0

        # 2) Para cada FVG, achar o primeiro reteste do 50% e montar trade
        for _, row in fvg_df.iterrows():
            base_i   = int(row["index"])   # candle C2
            fvg_type = row["type"]
            top      = float(row["top"])
            bottom   = float(row["bottom"])
            mid      = float(row["mid"])

            # precisa ter espaço pra olhar candles atrás e pra frente
            if base_i >= n - 1 or base_i < 3:
                continue

            # ---------- FILTRO DE TENDÊNCIA COM EMA50 (no candle base) ----------
            ema_now   = ema50[base_i]
            price_ref = closes[base_i]  # close do C2
            if np.isnan(ema_now):
                continue

            # bullish: só em tendência de alta (preço acima da ema)
            if fvg_type == "bullish" and price_ref <= ema_now:
                continue

            # bearish: só em tendência de baixa (preço abaixo da ema)
            if fvg_type == "bearish" and price_ref >= ema_now:
                continue

            # ---------- FILTRO DE VOLUME FINANCEIRO ----------
            v0 = vols[base_i]       # volume do candle que gerou o FVG
            v1 = vols[base_i - 1]   # candle 1 atrás
            v2 = vols[base_i - 2]   # candle 2 atrás
            v3 = vols[base_i - 3]   # candle 3 atrás

            # No teu Colab esse filtro está comentado com """ ... """
            # então aqui mantemos o mesmo comportamento: NÃO filtra por volume,
            # só guarda a contagem se você reativar depois.
            # if not (v0 > v1 and v0 > v2 and v0 > v3):
            #     continue
            # fvg_validos_volume += 1

            # ---------- JANELA DE VIDA DO FVG ----------
            start_j = base_i + 1
            end_j   = min(n - 1, base_i + MAX_AGE)

            entry_bar = None
            # Pequena tolerância para capturar toques de meio-ponto com diferenças de arredondamento
            tol = mid * 1e-6
            for j in range(start_j, end_j + 1):
                lo_j = lows[j]
                hi_j = highs[j]
                # candle precisa tocar o 50% do FVG (com tolerância mínima)
                if (lo_j - tol) <= mid <= (hi_j + tol):
                    entry_bar = j
                    break

            if entry_bar is None:
                continue  # nunca retestou → FVG morto (exatamente como linha 1008 do original)

            # ---------- FILTRO DE TENDÊNCIA NA HORA DA ENTRADA ----------
            ema_entry   = ema50[entry_bar]
            price_entry = closes[entry_bar]
            if np.isnan(ema_entry):
                continue

            # EXATAMENTE como no original (linhas 1016-1022)
            if fvg_type == "bullish" and price_entry <= ema_entry:
                # entrada estaria "abaixo" da ema → descarta
                continue

            if fvg_type == "bearish" and price_entry >= ema_entry:
                # entrada estaria "acima" da ema → descarta
                continue

            # ---------- STOP ATRÁS DAS MÍNIMAS/MÁXIMAS DO BLOCO ----------
            idx0 = base_i - 2
            idx3 = base_i + 1

            block_lows  = lows[idx0:idx3+1]
            block_highs = highs[idx0:idx3+1]

            if fvg_type == "bullish":
                entry = mid
                sl    = block_lows.min()
                risk  = entry - sl
                if risk <= 0:
                    continue
                tp    = entry + RR * risk
                sig   = 1

            elif fvg_type == "bearish":
                entry = mid
                sl    = block_highs.max()
                risk  = sl - entry
                if risk <= 0:
                    continue
                tp    = entry - RR * risk
                sig   = -1

            else:
                continue

            # ---------- FILTRO DE RISCO MÍNIMO ----------
            if atr14 is not None and MIN_ATR_FACT > 0:
                min_risk = atr14[base_i] * MIN_ATR_FACT
                if risk < min_risk:
                    continue

            fvg_validos_tamanho += 1

            # evita sobrescrever se já tiver sinal nesse candle
            # EXATAMENTE como no original (linha 1061-1066): usa .loc, não .iloc
            if signals.loc[entry_bar, "signal"] == 0:
                signals.loc[entry_bar, "signal"]      = sig
                signals.loc[entry_bar, "entry_price"] = entry
                signals.loc[entry_bar, "stop_price"]  = sl
                signals.loc[entry_bar, "take_price"]  = tp
                signals.loc[entry_bar, "risk"]        = risk

        # 3) Calcula end_bar para cada FVG (para visualização)
        # end_bar = candle onde foi retestado OU 100 barras após index
        for idx, row in fvg_df.iterrows():
            start_idx = int(row["index"])
            mid = row["mid"]
            
            # Procura reteste nos próximos 100 candles
            end_idx = min(start_idx + 100, n - 1)
            retest_idx = None
            
            for j in range(start_idx + 1, end_idx + 1):
                if lows[j] <= mid <= highs[j]:
                    retest_idx = j
                    break
            
            # Define end_bar
            if retest_idx is not None:
                fvg_df.at[idx, 'end_bar'] = retest_idx
            else:
                fvg_df.at[idx, 'end_bar'] = end_idx

        # 4) Salva FVGs para o dashboard
        # Mapeia index -> datetime (timestamp em segundos para o front)
        # O front espera: start_time, end_time, top, bottom, mid, type
        if not fvg_df.empty:
            # Converte index para timestamp
            # O front espera timestamp em SEGUNDOS (inteiro) para garantir match com o candle.
            # AJUSTE VISUAL: O FVG é formado entre C0 e C2. Visualmente, ele começa após C0.
            # Mas para desenhar o retângulo cobrindo a região, usamos o tempo de C0 (idx-2) ou C1 (idx-1).
            # O padrão é usar C0 (início da formação).
            # "index" aqui é o índice de C2 (confirmação).
            fvg_df["start_time"] = fvg_df["index"].apply(
                lambda idx: int(df["datetime"].iloc[idx - 2].timestamp()) if (idx - 2) >= 0 and idx < len(df) else None
            )
            fvg_df["end_time"] = fvg_df["end_bar"].apply(
                lambda idx: int(df["datetime"].iloc[int(idx)].timestamp()) if idx < len(df) else None
            )
            self.last_fvgs = fvg_df
        else:
            self.last_fvgs = pd.DataFrame()


        print("FVGs com volume forte (filtro OFF, só contagem):", fvg_validos_volume)
        print("FVGs que passaram no filtro de tamanho:", fvg_validos_tamanho)
        print("Sinais de COMPRA gerados:", (signals["signal"] == 1).sum())
        print("Sinais de VENDA gerados :", (signals["signal"] == -1).sum())

        # 👉 Backtester do OracleWalk só precisa do DataFrame com 'signal'.
        # Ele vai ignorar as colunas extras se não estiver usando.
        return signals


    def process_live_candle(self, candle: dict) -> dict:
        """
        Modo LIVE: mantém um DataFrame interno e recalcula FVGs a cada candle novo.
        
        Args:
            candle: dict com keys: datetime, open, high, low, close, volume, is_closed
        
        Returns:
            dict: {'signal': int, 'sl': float, 'tp': float}
        """
        # Inicializa DataFrame interno se não existir
        if not hasattr(self, 'df') or self.df is None:
            self.df = pd.DataFrame()
        
        # Garante que datetime seja coluna (não index)
        if not self.df.empty and 'datetime' not in self.df.columns:
            self.df = self.df.reset_index()
            if 'index' in self.df.columns:
                self.df = self.df.rename(columns={'index': 'datetime'})
        
        # Converte candle em DataFrame row
        new_row = pd.DataFrame([{
            'datetime': candle['datetime'],
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume']
        }])
        
        # Append ou update robusto
        if self.df.empty:
            self.df = new_row
        else:
            # Verifica duplicatas de forma robusta
            current_dt = pd.to_datetime(candle['datetime'])
            
            # Se a coluna datetime não for datetime64, converte
            if not pd.api.types.is_datetime64_any_dtype(self.df['datetime']):
                self.df['datetime'] = pd.to_datetime(self.df['datetime'])
                
            # Procura se já existe esse timestamp
            # Comparação vetorial é mais rápida que iterrows
            mask = self.df['datetime'] == current_dt
            if mask.any():
                # Atualiza (intrabar)
                idx = self.df.index[mask][0]
                self.df.loc[idx, ['open', 'high', 'low', 'close', 'volume']] = \
                    new_row.iloc[0][['open', 'high', 'low', 'close', 'volume']]
            else:
                # Novo candle
                self.df = pd.concat([self.df, new_row], ignore_index=True)
        
        # Limita tamanho do buffer (últimos 1000 candles)
        if len(self.df) > 1000:
            self.df = self.df.iloc[-1000:].reset_index(drop=True)
        
        result = {'signal': 0, 'sl': 0.0, 'tp': 0.0, 'fvg_updated': False}
        
        # SÓ CALCULA SINAIS E FVG SE O CANDLE FECHOU
        # Isso evita recálculo frenético a cada tick e garante estabilidade dos FVGs.
        # Se 'is_closed' não vier no dict, assume False por segurança.
        is_closed = candle.get('is_closed', False)
        now = time.time()
        should_refresh_fvg = len(self.df) >= 100 and (is_closed or (now - self._last_fvg_calc) >= 5)
        signals = None

        if should_refresh_fvg:
            signals = self.generate_signals(self.df)
            self._last_fvg_calc = now
            result['fvg_updated'] = True
        
        if is_closed and signals is not None and not signals.empty:
            last_row = signals.iloc[-1]
            sig = last_row['signal']
            if pd.notna(sig) and sig != 0:
                result['signal'] = int(sig)
                result['sl'] = float(last_row['stop_price']) if pd.notna(last_row['stop_price']) else 0.0
                result['tp'] = float(last_row['take_price']) if pd.notna(last_row['take_price']) else 0.0
        
        # Mesmo sem sinal, garante que last_fvgs está atualizado para o dashboard
        # (generate_signals já preenche self.last_fvgs)
        if should_refresh_fvg and hasattr(self, "last_fvgs"):
            fvg_count = len(self.last_fvgs) if hasattr(self.last_fvgs, "__len__") else 0
            if is_closed or (now - self._last_fvg_log) >= 60:
                label = "fechamento" if is_closed else "live"
                print(f"[ICT] FVGs recalculados ({label}): {fvg_count}")
                self._last_fvg_log = now
        
        return result
