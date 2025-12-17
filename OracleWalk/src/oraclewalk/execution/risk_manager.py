# file: oraclewalk/execution/risk_manager.py

from oraclewalk.utils.logger import setup_logger

logger = setup_logger(__name__)


class RiskManager:
    """
    Controla risco, tamanho de posição e equity.
    Funciona tanto no backtest quanto no modo live.
    """

    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db

        # balance inicial / equity inicial
        self.initial_balance = cfg.initial_balance
        self.current_balance = cfg.initial_balance

        # porcentagem de risco por trade (ex: 1%)
        self.risk_per_trade = cfg.risk_per_trade

    def get_position_size(self, price: float) -> float:
        """
        Define o tamanho da posição baseado no risco percentual.
        """
        risk_amount = self.current_balance * (self.risk_per_trade / 100)
        size = risk_amount / price

        logger.debug(f"Position size calculado: {size}")
        return size

    def update_balance(self, pnl: float):
        """
        Atualiza o saldo após um trade.
        """
        self.current_balance += pnl
        logger.info(f"Equity atualizada: {self.current_balance:.2f}")
        return self.current_balance
