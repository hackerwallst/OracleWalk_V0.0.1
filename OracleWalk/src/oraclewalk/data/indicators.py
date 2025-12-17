# file: oraclewalk/data/indicators.py

import pandas as pd
import numpy as np


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Cálculo simples do RSI."""
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    gain = pd.Series(gain, index=series.index)
    loss = pd.Series(loss, index=series.index)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)

# 1) ATR
def add_atr(df, period=14, name="atr"):
    df = df.copy()
    high = df["high"]
    low  = df["low"]
    close_prev = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low  - close_prev).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["tr"] = tr
    df[name] = tr.rolling(period).mean()
    return df


# 2) ADX
def add_adx(df, period=14, name="adx"):
    df = df.copy()
    high = df["high"]
    low  = df["low"]
    close_prev = df["close"].shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low  - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # +DM / -DM
    plus_dm  = (high - high.shift(1)).where(
        (high - high.shift(1)) > (low.shift(1) - low), 0.0
    )
    plus_dm  = plus_dm.where(plus_dm > 0, 0.0)

    minus_dm = (low.shift(1) - low).where(
        (low.shift(1) - low) > (high - high.shift(1)), 0.0
    )
    minus_dm = minus_dm.where(minus_dm > 0, 0.0)

    # DI+
    tr_n     = tr.rolling(period).sum()
    plus_di  = 100 * (plus_dm.rolling(period).sum()  / tr_n)
    minus_di = 100 * (minus_dm.rolling(period).sum() / tr_n)

    dx = ((plus_di - minus_di).abs()
          / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.rolling(period).mean()

    df["plus_di"]  = plus_di
    df["minus_di"] = minus_di
    df[name] = adx
    return df


# 3) MACD
def add_macd(df, fast=12, slow=26, signal=9,
             col="close",
             name_macd="macd",
             name_signal="macd_signal",
             name_hist="macd_hist"):
    df = df.copy()
    ema_fast = df[col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[col].ewm(span=slow, adjust=False).mean()

    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal

    df[name_macd]   = macd
    df[name_signal] = macd_signal
    df[name_hist]   = macd_hist
    return df


# 4) Bollinger Bands
def add_bbands(df, period=20, std_mult=2,
               col="close",
               name_mid="bb_mid",
               name_up="bb_up",
               name_low="bb_low"):
    df = df.copy()
    ma = df[col].rolling(period).mean()
    std = df[col].rolling(period).std()

    df[name_mid] = ma
    df[name_up]  = ma + std_mult * std
    df[name_low] = ma - std_mult * std
    return df

def detect_fvg(
    df: pd.DataFrame,
    extend_bars: int = 50,      # mantido só pra compatibilidade com o resto do código
    lookback: int = 2000,       # mesmo "loockback" do Pine
    filter_percent: float = 0.5 # mesmo "Filter Gaps by %" do Pine
    ) -> pd.DataFrame:
    """
    FAIR VALUE GAP LOGIC (3-candle model) - Updated to match user request.
    
    We detect gaps using candles:
    * C0 = i-2
    * C1 = i-1
    * C2 = i
    """

    highs = df["high"].to_numpy()
    lows  = df["low"].to_numpy()
    n     = len(df)

    if n < 3:
        return pd.DataFrame(columns=["index", "type", "top", "bottom", "mid", "gap_pct"])

    # índice inicial pra respeitar o lookback (últimos N candles)
    start_i = 2

    rows = []

    for i in range(start_i, n):
        # candles usados:
        # i-2 = candle "C0"
        # i-1 = candle "C1"
        # i   = candle "C2" (confirmação)
        h0 = highs[i-2]
        h1 = highs[i-1]
        h2 = highs[i]
        l0 = lows[i-2]
        l1 = lows[i-1]
        l2 = lows[i]

        # ---------------- BULLISH FVG (imbalance up) ----------------
        # Conditions:
        # high[C0] < low[C2]
        # high[C0] < high[C1]
        # low[C0]  < low[C2]
        # ((low[C2] - high[C0]) / low[C2]) * 100 > filter_percent
        
        filt_up = 0.0
        if l2 != 0:
            filt_up = (l2 - h0) / l2 * 100.0

        is_bull_gap = (
            h0 < l2 and
            h0 < h1 and
            l0 < l2 and
            filt_up > filter_percent
        )

        if is_bull_gap:
            # Returned gap:
            # top    = low[C2]
            # bottom = high[C0]
            # mid    = (top + bottom) / 2
            top    = float(l2)
            bottom = float(h0)
            mid    = (top + bottom) / 2.0
            
            rows.append({
                "index":  i,
                "type":   "bullish",
                "top":    top,
                "bottom": bottom,
                "mid":    mid,
                "gap_pct": float(filt_up),
            })

        # ---------------- BEARISH FVG (imbalance down) ----------------
        # Conditions:
        # low[C0]  > high[C2]
        # low[C0]  > low[C1]
        # high[C0] > high[C2]
        # ((low[C0] - high[C2]) / low[C0]) * 100 > filter_percent

        filt_dn = 0.0
        if l0 != 0:
            filt_dn = (l0 - h2) / l0 * 100.0

        is_bear_gap = (
            l0 > h2 and
            l0 > l1 and
            h0 > h2 and
            filt_dn > filter_percent
        )

        if is_bear_gap:
            # Returned gap:
            # top    = low[C0]
            # bottom = high[C2]
            # mid    = (top + bottom) / 2
            top    = float(l0)
            bottom = float(h2)
            mid    = (top + bottom) / 2.0

            rows.append({
                "index":  i,
                "type":   "bearish",
                "top":    top,
                "bottom": bottom,
                "mid":    mid,
                "gap_pct": float(filt_dn),
            })

    fvg_df = pd.DataFrame(rows, columns=["index", "type", "top", "bottom", "mid", "gap_pct"])
    return fvg_df

    # ------------------------------------
# 2. VOLUME FINANCEIRO
# ------------------------------------
def volume_indicator(df: pd.DataFrame, length=20, spike_multiplier=1.5):
    """
    Volume simples para o framework.
    - volume médio
    - volume spike
    - volume acima/abaixo da média
    - cor do candle pelo volume

    df precisa conter colunas: ["open", "high", "low", "close", "volume"]
    """

    # Volume normal
    df["vol"] = df["volume"]

    # Média de volume
    df["vol_ma"] = df["volume"].rolling(length).mean()

    # Volume spike (cuando o volume está muito acima da média)
    df["vol_spike"] = df["vol"] > (df["vol_ma"] * spike_multiplier)

    # Volume acima/abaixo da média
    df["vol_high"] = df["vol"] > df["vol_ma"]
    df["vol_low"] = df["vol"] < df["vol_ma"]

    # Cor do candle por volume
    df["vol_color"] = df.apply(
        lambda row: "green" if row["close"] > row["open"] else "red",
        axis=1
    )

    return df

# ------------------------------------
# 2. ORDERBLOCK
# ------------------------------------

def detect_orderblocks(df: pd.DataFrame, lookback=5, extend_bars=50):
    """
    Detecta Order Blocks ICT reais:
    - OB de compra = último candle de baixa antes do BOS de alta
    - OB de venda = último candle de alta antes do BOS de baixa
    - Verifica ruptura real dos swings
    - Exporta coordenadas para desenho (retângulos)
    """

    orderblocks = []

    # 1 — Criar colunas auxiliares de swing high/low
    df["swing_high"] = df["high"].rolling(lookback).max()
    df["swing_low"] = df["low"].rolling(lookback).min()

    for i in range(lookback, len(df)):

        curr_close = df["close"].iloc[i]

        prev_swing_high = df["swing_high"].iloc[i-1]
        prev_swing_low  = df["swing_low"].iloc[i-1]

        # ===========================
        # BOS DE ALTA → OB BULLISH
        # ===========================
        if curr_close > prev_swing_high:

            # procurar o último candle bearish antes do BOS
            for j in range(i-1, i-1-lookback, -1):
                if df["close"].iloc[j] < df["open"].iloc[j]:  # candle vermelho
                    ob_open = df["open"].iloc[j]
                    ob_close = df["close"].iloc[j]
                    ob_high = df["high"].iloc[j]
                    ob_low = df["low"].iloc[j]

                    ob_top = max(ob_open, ob_close)
                    ob_bottom = min(ob_open, ob_close)
                    ob_mid = (ob_top + ob_bottom) / 2

                    orderblocks.append({
                        "index": j,
                        "type": "bullish",
                        "top": float(ob_top),
                        "bottom": float(ob_bottom),
                        "mid": float(ob_mid),
                        "project_right": extend_bars,
                        "color": "green"
                    })

                    break  # só o último válido

        # ===========================
        # BOS DE BAIXA → OB BEARISH
        # ===========================
        if curr_close < prev_swing_low:

            # procurar o último candle bullish antes do BOS
            for j in range(i-1, i-1-lookback, -1):
                if df["close"].iloc[j] > df["open"].iloc[j]:  # candle verde
                    ob_open = df["open"].iloc[j]
                    ob_close = df["close"].iloc[j]
                    ob_high = df["high"].iloc[j]
                    ob_low = df["low"].iloc[j]

                    ob_top = max(ob_open, ob_close)
                    ob_bottom = min(ob_open, ob_close)
                    ob_mid = (ob_top + ob_bottom) / 2

                    orderblocks.append({
                        "index": j,
                        "type": "bearish",
                        "top": float(ob_top),
                        "bottom": float(ob_bottom),
                        "mid": float(ob_mid),
                        "project_right": extend_bars,
                        "color": "red"
                    })

                    break

    return pd.DataFrame(orderblocks)