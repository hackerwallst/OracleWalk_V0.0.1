# file: oraclewalk/strategy/base_strategy.py

from abc import ABC, abstractmethod
import pandas as pd


class StrategyBase(ABC):
    """
    Classe base para todas as estratégias do OracleWalk.
    """

    # Se True -> processa durante o candle (intrabar)
    # Se False -> só processa quando o candle fechar
    use_intrabar: bool = False

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Modo backtest:
        Recebe um DataFrame OHLCV completo e retorna um DF com coluna 'signal'
        (1 = compra, -1 = venda, 0 = nada).
        """
        ...

    def process_live_candle(self, candle: dict) -> int:
        """
        Modo live:
        Recebe 1 candle (dict) e retorna um sinal:
            1  -> compra
           -1  -> venda
            0  -> nada

        Estratégias concretas podem sobrescrever.
        Implementação padrão: não faz nada.
        """
        return 0
