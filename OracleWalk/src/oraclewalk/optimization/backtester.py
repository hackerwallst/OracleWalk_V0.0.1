# file: oraclewalk/optimization/backtester.py

import pandas as pd
from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class Backtester:
    """
    Backtester simples baseado em sinais da estratégia.
    """

    def __init__(self, risk_manager):
        self.risk_manager = risk_manager

    def run(self, df: pd.DataFrame, strategy) -> dict:
        """
        Executa backtest básico:
        - calcula sinais
        - simula entradas/saídas
        - atualiza equity usando RiskManager
        """

        logger.info("Iniciando backtest...")

        # Normaliza o DataFrame de entrada preservando datetime
        if "datetime" in df.columns:
            df_iter = df.reset_index(drop=True)
        elif isinstance(df.index, pd.DatetimeIndex):
            df_iter = df.reset_index().rename(columns={"index": "datetime"})
        else:
            raise ValueError("DataFrame de entrada para backtest precisa da coluna 'datetime' ou índice DatetimeIndex.")

        signals = strategy.generate_signals(df_iter)

        if len(signals) != len(df_iter):
            raise ValueError("Strategy.generate_signals deve retornar mesmo número de linhas que o DataFrame de entrada.")

        for col in ("close", "datetime"):
            if col not in df_iter.columns:
                raise ValueError(f"DataFrame de entrada para backtest precisa da coluna '{col}'.")

        equity = self.risk_manager.initial_balance
        balance = equity
        wins = 0
        losses = 0

        position = None
        entry_price = None

        for i in range(len(signals)):
            sig = signals["signal"].iloc[i]
            price = df_iter["close"].iloc[i]

            # entrar comprado
            if sig == 1 and position is None:
                position = "long"
                entry_price = price

            # entrar vendido
            elif sig == -1 and position is None:
                position = "short"
                entry_price = price

            # sair (quando sinal oposto surge)
            elif sig != 0 and position is not None:
                if position == "long":
                    pnl = price - entry_price
                else:
                    pnl = entry_price - price

                if pnl > 0:
                    wins += 1
                else:
                    losses += 1

                balance += pnl
                position = None
                entry_price = None

        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0.0
        pnl_total = balance - self.risk_manager.initial_balance

        logger.info("Backtest finalizado.")

        return {
            "equity_final": balance,
            "pnl": pnl_total,
            "win_rate": win_rate
        }
