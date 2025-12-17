# file: oraclewalk/execution/execution_price_model.py

class ExecutionPriceModel:
    """
    Modelo de execução realista:
    - Usa bid/ask
    - Aplica slippage
    - Aplica comissão maker/taker
    - Retorna preço final da execução real
    """

    def __init__(
        self,
        slippage_pct: float,
        commission_maker: float,
        commission_taker: float
    ):
        # porcentagens para fator multiplicador
        self.slippage = slippage_pct / 100
        self.com_maker = commission_maker / 100
        self.com_taker = commission_taker / 100

    # ===============================
    # EXECUÇÃO DE COMPRA (BUY / LONG)
    # ===============================

    def exec_buy(self, bid: float, ask: float, taker=True) -> float:
        """
        Compra ocorre no ASK + slippage + comissão.
        """
        price = ask

        # aplicar slippage (sempre prejudica quem compra)
        price *= (1 + self.slippage)

        # comissão (geralmente taker em mercado)
        if taker:
            price *= (1 + self.com_taker)
        else:
            price *= (1 + self.com_maker)

        return price

    # ===============================
    # EXECUÇÃO DE VENDA (SELL / SHORT)
    # ===============================

    def exec_sell(self, bid: float, ask: float, taker=True) -> float:
        """
        Venda ocorre no BID - slippage - comissão.
        """
        price = bid

        # aplicar slippage (sempre prejudica quem vende)
        price *= (1 - self.slippage)

        # comissão
        if taker:
            price *= (1 - self.com_taker)
        else:
            price *= (1 - self.com_maker)

        return price
