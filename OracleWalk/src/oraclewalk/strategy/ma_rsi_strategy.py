import pandas as pd
from oraclewalk.strategy.base_strategy import StrategyBase
from oraclewalk.data.indicators import calc_rsi


class MaRsiStrategy(StrategyBase):
    """
    Estratégia MA + RSI.
    Funciona em:
    - Backtest (generate_signals)
    - Live (process_live_candle), com suporte a:
        • intrabar  -> opera durante o candle
        • candle close -> opera só quando fecha
    """

    def __init__(
        self,
        ma_short: int,
        ma_long: int,
        rsi_period: int,
        rsi_buy_threshold: float,
        rsi_sell_threshold: float,
        use_intrabar: bool = False,
    ):
        self.ma_short = ma_short
        self.ma_long = ma_long
        self.rsi_period = rsi_period
        self.rsi_buy_threshold = rsi_buy_threshold
        self.rsi_sell_threshold = rsi_sell_threshold

        # Controla se opera intrabar ou apenas em candle fechado
        self.use_intrabar = use_intrabar

        # DF interno para dados ao vivo (datetime como índice!)
        self.df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )
        self.df.index.name = "datetime"

    # -----------------------------------------------------------
    # INDICADORES
    # -----------------------------------------------------------
    def generate_indicators(self):
        """Atualiza medias móveis e RSI."""
        self.df["ma_short"] = self.df["close"].rolling(self.ma_short).mean()
        self.df["ma_long"] = self.df["close"].rolling(self.ma_long).mean()
        self.df["rsi"] = calc_rsi(self.df["close"], period=self.rsi_period)

    # -----------------------------------------------------------
    # BACKTEST OFFLINE
    # -----------------------------------------------------------
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["ma_short"] = df["close"].rolling(self.ma_short).mean()
        df["ma_long"] = df["close"].rolling(self.ma_long).mean()
        df["rsi"] = calc_rsi(df["close"], period=self.rsi_period)

        df["signal"] = 0

        buy_cond = (
            (df["ma_short"] > df["ma_long"]) &
            (df["rsi"] > self.rsi_buy_threshold)
        )

        sell_cond = (
            (df["ma_short"] < df["ma_long"]) &
            (df["rsi"] < self.rsi_sell_threshold)
        )

        df.loc[buy_cond, "signal"] = 1
        df.loc[sell_cond, "signal"] = -1

        return df

    # -----------------------------------------------------------
    # LIVE MODE (INTRABAR OU CANDLE CLOSE)
    # -----------------------------------------------------------
    def process_live_candle(self, candle: dict) -> int:
        """
        Processa um candle ao vivo e retorna:
            1 -> compra
           -1 -> venda
            0 -> nada
        """

        # Se não for intrabar, só processa quando o candle fechar
        if not self.use_intrabar and not candle.get("is_closed", False):
            return 0

        dt = candle["datetime"]

        # Adiciona / atualiza o candle no DF
        self.df.loc[dt] = {
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": candle["volume"],
        }

        # Se temos poucos candles ainda → não opera
        if len(self.df) < max(self.ma_long, self.rsi_period) + 2:
            return 0

        # Atualiza indicadores
        self.generate_indicators()

        last = self.df.iloc[-1]

        # Lógica de compra
        if (
            last["ma_short"] > last["ma_long"]
            and last["rsi"] > self.rsi_buy_threshold
        ):
            return 1

        # Lógica de venda
        if (
            last["ma_short"] < last["ma_long"]
            and last["rsi"] < self.rsi_sell_threshold
        ):
            return -1

        return 0
