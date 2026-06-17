from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .engine import BacktestConfig, Backtester


@dataclass(frozen=True)
class PortfolioSymbolInput:
    symbol: str
    data: pd.DataFrame
    signals: pd.DataFrame
    config: dict[str, Any] | None = None
    symbol_spec: dict[str, Any] | None = None
    ticks: pd.DataFrame | None = None


@dataclass
class PortfolioConfig:
    initial_capital: float = 1000.0
    account_currency: str = "USD"
    leverage: float = 1.0
    stop_out_level_pct: float | None = None
    max_positions: int | None = None
    max_positions_per_symbol: int | None = None
    max_exposure_by_symbol: dict[str, float] = field(default_factory=dict)
    max_exposure_by_currency: dict[str, float] = field(default_factory=dict)
    currency_rates: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    per_symbol: dict[str, dict[str, Any]]
    account: dict[str, Any]


@dataclass
class _SymbolState:
    symbol: str
    engine: Backtester
    data: pd.DataFrame
    ticks_by_bar: dict[int, pd.DataFrame]
    profit_currency: str
    margin_currency: str
    base_currency: str | None
    has_stop: bool
    has_take: bool
    has_size: bool
    has_risk: bool
    has_trail: bool
    has_entry: bool


class PortfolioBacktester:
    """
    Candle-based multi-symbol backtester with one shared account ledger.

    The trade schema follows Backtester and adds `symbol` in portfolio mode.
    Monetary trade fields are expressed in account currency after conversion.
    """

    def __init__(
        self,
        symbols: Mapping[str, PortfolioSymbolInput | dict[str, Any]],
        config: dict[str, Any] | None = None,
    ):
        raw_config = dict(config or {})
        portfolio_fields = {field.name for field in fields(PortfolioConfig)}
        self.config = PortfolioConfig(
            **{key: value for key, value in raw_config.items() if key in portfolio_fields}
        )
        self.account_currency = self.config.account_currency.upper()
        self.converter = _CurrencyConverter(self.config.currency_rates)

        engine_fields = {field.name for field in fields(BacktestConfig)}
        common_engine_config = {
            key: value for key, value in raw_config.items() if key in engine_fields
        }
        common_engine_config.setdefault("initial_capital", self.config.initial_capital)
        common_engine_config.setdefault("leverage", self.config.leverage)
        common_engine_config["stop_out_level_pct"] = None

        self.states = {
            symbol: self._prepare_symbol(symbol, item, common_engine_config)
            for symbol, item in symbols.items()
        }

    def run(self) -> PortfolioResult:
        balance = float(self.config.initial_capital)
        open_trades: list[dict[str, Any]] = []
        closed_trades: list[dict[str, Any]] = []
        trade_id = 0
        snapshots: dict[str, dict[str, Any]] = {}
        equity_rows: list[dict[str, Any]] = []

        timeline = self._timeline()
        rows_by_symbol = self._rows_by_datetime()
        for dt in timeline:
            for state in self.states.values():
                row = rows_by_symbol.get(state.symbol, {}).get(dt)
                if row is None:
                    continue
                spread_price = state.engine._row_spread_price(row)
                close = float(row["close"])
                snapshots[state.symbol] = {
                    "price": close,
                    "spread_price": spread_price,
                    "datetime": row["datetime"],
                    "bar_index": int(row["_bar_index"]),
                }

                bar_ticks = state.ticks_by_bar.get(int(row["_bar_index"]))
                if bar_ticks is not None and not bar_ticks.empty:
                    balance = self._process_ticks_for_symbol(
                        state=state,
                        bar_ticks=bar_ticks,
                        bar_index=int(row["_bar_index"]),
                        balance=balance,
                        open_trades=open_trades,
                        closed_trades=closed_trades,
                        snapshots=snapshots,
                    )

                balance = self._process_exits_for_symbol(
                    state=state,
                    row=row,
                    spread_price=spread_price,
                    balance=balance,
                    open_trades=open_trades,
                    closed_trades=closed_trades,
                    snapshots=snapshots,
                    check_stop_take=bar_ticks is None or bar_ticks.empty,
                )

                if self._is_stop_out(balance, open_trades, snapshots):
                    balance = self._close_all(
                        open_trades=open_trades,
                        closed_trades=closed_trades,
                        snapshots=snapshots,
                        balance=balance,
                        reason="stop_out",
                    )
                    continue

                trade = self._maybe_open_trade(
                    state=state,
                    row=row,
                    spread_price=spread_price,
                    balance=balance,
                    open_trades=open_trades,
                    snapshots=snapshots,
                    trade_id=trade_id,
                )
                if trade is not None:
                    open_trades.append(trade)
                    trade_id += 1

            equity_rows.append(self._account_row(dt, balance, open_trades, snapshots))

        if open_trades:
            balance = self._close_all(
                open_trades=open_trades,
                closed_trades=closed_trades,
                snapshots=snapshots,
                balance=balance,
                reason="eod",
            )
            if len(timeline) > 0:
                equity_rows.append(self._account_row(timeline[-1], balance, open_trades, snapshots))

        trades = self._finalize_trades(closed_trades)
        equity = pd.DataFrame(equity_rows)
        per_symbol = self._per_symbol(trades, equity)
        return PortfolioResult(
            trades=trades,
            equity=equity,
            per_symbol=per_symbol,
            account={
                "currency": self.account_currency,
                "initial_capital": float(self.config.initial_capital),
                "final_balance": float(balance),
                "leverage": float(self.config.leverage),
                "symbols": {
                    symbol: {
                        "profit_currency": state.profit_currency,
                        "margin_currency": state.margin_currency,
                        "base_currency": state.base_currency,
                    }
                    for symbol, state in self.states.items()
                },
            },
        )

    def _prepare_symbol(
        self,
        symbol: str,
        item: PortfolioSymbolInput | dict[str, Any],
        common_engine_config: dict[str, Any],
    ) -> _SymbolState:
        symbol_input = self._coerce_symbol_input(symbol, item)
        symbol_spec = dict(symbol_input.symbol_spec or {})
        engine_config = dict(common_engine_config)
        engine_config.update(_engine_config_from_symbol_spec(symbol_spec, self.config.leverage))
        engine_config.update(symbol_input.config or {})
        engine_config["stop_out_level_pct"] = None

        engine = Backtester(symbol_input.data, engine_config)
        data = self._merge_signals(engine, symbol_input.signals)
        data["_bar_index"] = np.arange(len(data), dtype=int)

        return _SymbolState(
            symbol=symbol_input.symbol,
            engine=engine,
            data=data,
            ticks_by_bar=self._ticks_by_bar(engine, data, symbol_input.ticks),
            profit_currency=str(symbol_spec.get("currency_profit") or self.account_currency).upper(),
            margin_currency=str(symbol_spec.get("currency_margin") or symbol_spec.get("currency_profit") or self.account_currency).upper(),
            base_currency=(
                str(symbol_spec.get("currency_base")).upper()
                if symbol_spec.get("currency_base")
                else None
            ),
            has_stop="stop_price" in data.columns,
            has_take="take_price" in data.columns,
            has_size="size" in data.columns,
            has_risk="risk" in data.columns,
            has_trail="trailing_distance" in data.columns,
            has_entry="entry_price" in data.columns,
        )

    def _coerce_symbol_input(
        self,
        symbol: str,
        item: PortfolioSymbolInput | dict[str, Any],
    ) -> PortfolioSymbolInput:
        if isinstance(item, PortfolioSymbolInput):
            return item
        return PortfolioSymbolInput(
            symbol=str(item.get("symbol") or symbol),
            data=item["data"],
            signals=item["signals"],
            config=item.get("config"),
            symbol_spec=item.get("symbol_spec"),
            ticks=item.get("ticks"),
        )

    def _merge_signals(self, engine: Backtester, signals: pd.DataFrame) -> pd.DataFrame:
        if signals is None or signals.empty:
            sig = pd.DataFrame({"datetime": engine.data["datetime"], "signal": 0})
        else:
            sig = signals.copy()
        if "datetime" not in sig.columns or "signal" not in sig.columns:
            raise ValueError("signals must contain 'datetime' and 'signal' columns")

        sig["datetime"] = pd.to_datetime(sig["datetime"])
        sig = sig.sort_values("datetime").reset_index(drop=True)
        data = pd.merge(engine.data, sig, on="datetime", how="left", suffixes=("", "_sig"))
        data["signal"] = data["signal"].fillna(0).astype(int)
        data = engine._apply_entry_timing(data)
        data = engine._apply_execution_latency(data)
        data = engine._apply_session_policy(data)
        return data.reset_index(drop=True)

    def _ticks_by_bar(
        self,
        engine: Backtester,
        data: pd.DataFrame,
        ticks: pd.DataFrame | None,
    ) -> dict[int, pd.DataFrame]:
        if engine.config.execution_mode != "tick" or ticks is None or ticks.empty:
            return {}
        return engine._ticks_by_bar(data, engine._prepare_ticks(ticks))

    def _timeline(self) -> pd.DatetimeIndex:
        parts = [state.data["datetime"] for state in self.states.values() if not state.data.empty]
        if not parts:
            return pd.DatetimeIndex([])
        return pd.DatetimeIndex(pd.concat(parts, ignore_index=True).drop_duplicates()).sort_values()

    def _rows_by_datetime(self) -> dict[str, dict[pd.Timestamp, pd.Series]]:
        out: dict[str, dict[pd.Timestamp, pd.Series]] = {}
        for state in self.states.values():
            if state.data.empty:
                out[state.symbol] = {}
                continue
            rows: dict[pd.Timestamp, pd.Series] = {}
            for _, row in state.data.drop_duplicates("datetime", keep="first").iterrows():
                rows[row["datetime"]] = row
            out[state.symbol] = rows
        return out

    def _process_exits_for_symbol(
        self,
        state: _SymbolState,
        row: pd.Series,
        spread_price: float,
        balance: float,
        open_trades: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
        check_stop_take: bool = True,
    ) -> float:
        symbol_open = [trade for trade in open_trades if trade["symbol"] == state.symbol]
        if not symbol_open:
            return balance

        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        sigv = int(row["signal"])
        dt = row["datetime"]
        bar_index = int(row["_bar_index"])
        can_execute = state.engine._can_execute(dt)

        for trade in list(symbol_open):
            state.engine._update_excursions(trade, high, low, spread_price)
            state.engine._update_trailing_stop(trade, close)
            exit_price, exit_reason = (
                state.engine._check_stop_take(trade, high, low, spread_price)
                if can_execute and check_stop_take
                else (None, None)
            )
            if exit_reason is None and can_execute and state.engine._should_close_on_signal(trade, sigv):
                exit_price, exit_reason = close, "signal"
            if exit_reason is None:
                continue

            self._close_trade(
                state=state,
                trade=trade,
                exit_price=float(exit_price),
                exit_time=dt,
                exit_bar_index=bar_index,
                exit_reason=exit_reason,
                spread_price=spread_price,
                execution_source=row,
            )
            open_trades.remove(trade)
            closed_trades.append(trade)
            balance += float(trade["pnl"])
            snapshots[state.symbol] = {
                "price": float(exit_price),
                "spread_price": spread_price,
                "datetime": dt,
                "bar_index": bar_index,
            }
        return balance

    def _process_ticks_for_symbol(
        self,
        state: _SymbolState,
        bar_ticks: pd.DataFrame,
        bar_index: int,
        balance: float,
        open_trades: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
    ) -> float:
        for tick in bar_ticks.itertuples(index=False):
            bid = float(tick.bid)
            ask = float(tick.ask)
            spread_price = max(ask - bid, 0.0)
            tick_time = tick.datetime
            snapshots[state.symbol] = {
                "price": bid,
                "spread_price": spread_price,
                "datetime": tick_time,
                "bar_index": bar_index,
            }
            can_execute = state.engine._can_execute(tick_time)

            for trade in list(open_trades):
                if trade["symbol"] != state.symbol:
                    continue
                state.engine._update_excursions(trade, bid, bid, spread_price)
                state.engine._update_trailing_stop(
                    trade,
                    ask if trade["direction"] == "short" else bid,
                )
                exit_price, exit_reason = (
                    state.engine._check_stop_take(trade, bid, bid, spread_price)
                    if can_execute
                    else (None, None)
                )
                if exit_reason is None:
                    continue

                self._close_trade(
                    state=state,
                    trade=trade,
                    exit_price=float(exit_price),
                    exit_time=tick_time,
                    exit_bar_index=bar_index,
                    exit_reason=exit_reason,
                    spread_price=spread_price,
                    execution_source=tick,
                )
                open_trades.remove(trade)
                closed_trades.append(trade)
                balance += float(trade["pnl"])

            if self._is_stop_out(balance, open_trades, snapshots):
                balance = self._close_all(
                    open_trades=open_trades,
                    closed_trades=closed_trades,
                    snapshots=snapshots,
                    balance=balance,
                    reason="stop_out",
                )
        return balance

    def _maybe_open_trade(
        self,
        state: _SymbolState,
        row: pd.Series,
        spread_price: float,
        balance: float,
        open_trades: list[dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
        trade_id: int,
    ) -> dict[str, Any] | None:
        sigv = int(row["signal"])
        if sigv == 0:
            return None
        if not state.engine._can_execute(row["datetime"]):
            return None

        symbol_open = [trade for trade in open_trades if trade["symbol"] == state.symbol]
        if state.engine.config.single_position_mode and symbol_open:
            return None
        if self.config.max_positions is not None and len(open_trades) >= self.config.max_positions:
            return None
        if (
            self.config.max_positions_per_symbol is not None
            and len(symbol_open) >= self.config.max_positions_per_symbol
        ):
            return None

        free_margin = self._account_row(row["datetime"], balance, open_trades, snapshots)["free_margin"]
        market_price = float(row["open"]) if state.engine.config.entry_timing == "next_bar_open" else float(row["close"])
        entry_price = state.engine._resolve_entry_price(row, int(row["signal"]), market_price, state.has_entry)
        if entry_price is None:
            return None
        trade = state.engine._open_trade_from_row(
            trade_id=trade_id,
            dt=row["datetime"],
            price=entry_price,
            volume=float(row["volume"]),
            spread_price=spread_price,
            bar_index=int(row["_bar_index"]),
            sig_row=row,
            has_stop=state.has_stop,
            has_take=state.has_take,
            has_size=state.has_size,
            has_risk=state.has_risk,
            has_trail=state.has_trail,
            capital_now=balance,
            free_margin=np.inf,
        )
        if trade is None:
            return None

        self._attach_portfolio_fields(state, trade, row["datetime"], entry_price)
        if float(trade["margin_required"]) > free_margin:
            return None
        if not self._passes_exposure_limits(state, trade, open_trades):
            return None
        trade["free_margin_at_entry"] = free_margin
        return trade

    def _attach_portfolio_fields(self, state: _SymbolState, trade: dict[str, Any], dt, price: float) -> None:
        raw_margin = float(trade.get("margin_required", 0.0))
        raw_notional = float(trade.get("notional_value", 0.0))
        raw_risk = trade.get("risk")
        raw_commission_open = float(trade.get("commission_open", 0.0))

        trade["symbol"] = state.symbol
        trade["account_currency"] = self.account_currency
        trade["profit_currency"] = state.profit_currency
        trade["margin_currency"] = state.margin_currency
        trade["base_currency"] = state.base_currency
        trade["gross_pnl_profit_currency"] = np.nan
        trade["pnl_profit_currency"] = np.nan
        trade["margin_required_raw"] = raw_margin
        trade["notional_value_raw"] = raw_notional
        trade["commission_open_raw"] = raw_commission_open
        trade["risk_raw"] = raw_risk
        trade["margin_required"] = self._convert(raw_margin, state.margin_currency, self.account_currency, dt, state, price)
        trade["notional_value"] = self._convert(raw_notional, state.margin_currency, self.account_currency, dt, state, price)
        trade["commission_open"] = self._convert(raw_commission_open, state.profit_currency, self.account_currency, dt, state, price)
        if raw_risk is not None and not pd.isna(raw_risk):
            trade["risk"] = self._convert(float(raw_risk), state.profit_currency, self.account_currency, dt, state, price)

    def _convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
        dt,
        state: _SymbolState | None = None,
        price: float | None = None,
    ) -> float:
        try:
            return self.converter.convert(amount, from_currency, to_currency, dt)
        except ValueError:
            rate = self._derived_currency_rate(state, from_currency, to_currency, price)
            if rate is None:
                raise
            return float(amount) * rate

    def _derived_currency_rate(
        self,
        state: _SymbolState | None,
        from_currency: str,
        to_currency: str,
        price: float | None,
    ) -> float | None:
        if state is None or price is None:
            return None
        try:
            price_value = float(price)
        except Exception:
            return None
        if not np.isfinite(price_value) or price_value == 0.0:
            return None
        from_ccy = str(from_currency or "").upper()
        to_ccy = str(to_currency or "").upper()
        base_ccy = str(state.base_currency or "").upper()
        profit_ccy = str(state.profit_currency or "").upper()
        if from_ccy == base_ccy and to_ccy == profit_ccy:
            return price_value
        if from_ccy == profit_ccy and to_ccy == base_ccy:
            return 1.0 / price_value
        return None

    def _passes_exposure_limits(
        self,
        state: _SymbolState,
        candidate: dict[str, Any],
        open_trades: list[dict[str, Any]],
    ) -> bool:
        symbol_limit = self.config.max_exposure_by_symbol.get(state.symbol)
        if symbol_limit is not None:
            current = sum(
                float(trade.get("notional_value", 0.0))
                for trade in open_trades
                if trade["symbol"] == state.symbol
            )
            if current + float(candidate.get("notional_value", 0.0)) > float(symbol_limit):
                return False

        if not self.config.max_exposure_by_currency:
            return True
        currency = state.base_currency or state.profit_currency
        limit = self.config.max_exposure_by_currency.get(currency)
        if limit is None:
            return True
        current = sum(
            float(trade.get("notional_value", 0.0))
            for trade in open_trades
            if trade.get("base_currency") == currency or trade.get("profit_currency") == currency
        )
        return current + float(candidate.get("notional_value", 0.0)) <= float(limit)

    def _is_stop_out(
        self,
        balance: float,
        open_trades: list[dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
    ) -> bool:
        if self.config.stop_out_level_pct is None or not open_trades:
            return False
        account = self._account_row(None, balance, open_trades, snapshots)
        used_margin = float(account["margin_used"])
        if used_margin <= 0:
            return False
        return float(account["margin_level_pct"]) <= float(self.config.stop_out_level_pct)

    def _close_all(
        self,
        open_trades: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
        balance: float,
        reason: str,
    ) -> float:
        for trade in list(open_trades):
            state = self.states[trade["symbol"]]
            snap = snapshots.get(trade["symbol"])
            if snap is None:
                continue
            self._close_trade(
                state=state,
                trade=trade,
                exit_price=float(snap["price"]),
                exit_time=snap["datetime"],
                exit_bar_index=int(snap["bar_index"]),
                exit_reason=reason,
                spread_price=float(snap["spread_price"]),
            )
            open_trades.remove(trade)
            closed_trades.append(trade)
            balance += float(trade["pnl"])
        return balance

    def _close_trade(
        self,
        state: _SymbolState,
        trade: dict[str, Any],
        exit_price: float,
        exit_time,
        exit_bar_index: int,
        exit_reason: str,
        spread_price: float,
        execution_source=None,
    ) -> None:
        trade["commission_open"] = float(trade.get("commission_open_raw", trade.get("commission_open", 0.0)))
        state.engine._close_trade(
            trade,
            exit_price,
            exit_time,
            exit_bar_index,
            exit_reason,
            spread_price,
            execution_source,
        )
        raw_gross = float(trade.get("gross_pnl", 0.0))
        raw_pnl = float(trade.get("pnl", 0.0))
        raw_swap = float(trade.get("swap", 0.0))
        raw_commission_open = float(trade.get("commission_open", 0.0))
        raw_commission_close = float(trade.get("commission_close", 0.0))

        gross = self._convert(raw_gross, state.profit_currency, self.account_currency, exit_time, state, exit_price)
        swap = self._convert(raw_swap, state.profit_currency, self.account_currency, exit_time, state, exit_price)
        commission_open = self._convert(raw_commission_open, state.profit_currency, self.account_currency, exit_time, state, exit_price)
        commission_close = self._convert(raw_commission_close, state.profit_currency, self.account_currency, exit_time, state, exit_price)

        trade["gross_pnl_profit_currency"] = raw_gross
        trade["pnl_profit_currency"] = raw_pnl
        trade["swap_raw"] = raw_swap
        trade["commission_close_raw"] = raw_commission_close
        trade["gross_pnl"] = gross
        trade["swap"] = swap
        trade["commission_open"] = commission_open
        trade["commission_close"] = commission_close
        trade["pnl"] = gross + swap - commission_open - commission_close

    def _account_row(
        self,
        dt,
        balance: float,
        open_trades: list[dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        open_pnl = 0.0
        for trade in open_trades:
            snap = snapshots.get(trade["symbol"])
            if snap is None:
                continue
            state = self.states[trade["symbol"]]
            raw = state.engine._unrealized_pnl(
                trade,
                float(snap["price"]),
                float(snap["spread_price"]),
            )
            open_pnl += self._convert(
                raw,
                state.profit_currency,
                self.account_currency,
                snap["datetime"],
                state,
                float(snap["price"]),
            )

        margin_used = sum(float(trade.get("margin_required", 0.0)) for trade in open_trades)
        equity = float(balance) + open_pnl
        free_margin = equity - margin_used
        margin_level = equity / margin_used * 100.0 if margin_used > 0 else np.inf
        return {
            "datetime": dt,
            "balance": float(balance),
            "equity": equity,
            "open_pnl": open_pnl,
            "margin_used": margin_used,
            "free_margin": free_margin,
            "margin_level_pct": margin_level,
            "open_positions": len(open_trades),
        }

    def _finalize_trades(self, closed_trades: list[dict[str, Any]]) -> pd.DataFrame:
        if not closed_trades:
            return pd.DataFrame()
        trades = pd.DataFrame(closed_trades)
        trades["duration"] = pd.to_datetime(trades["exit_time"]) - pd.to_datetime(trades["entry_time"])
        trades["bars_in_trade"] = trades["exit_bar_index"] - trades["entry_bar_index"]
        trades["result"] = np.where(
            trades["pnl"] > 0,
            "win",
            np.where(trades["pnl"] < 0, "loss", "be"),
        )
        if "risk" not in trades.columns:
            trades["risk"] = np.nan
        trades["risk"] = pd.to_numeric(trades["risk"], errors="coerce")
        trades["risk_reward"] = np.where(
            trades["risk"].notna() & (trades["risk"] != 0),
            trades["pnl"] / trades["risk"],
            np.nan,
        )
        return trades

    def _per_symbol(self, trades: pd.DataFrame, equity: pd.DataFrame) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for symbol in self.states:
            symbol_trades = (
                trades[trades["symbol"] == symbol].reset_index(drop=True)
                if not trades.empty and "symbol" in trades.columns
                else pd.DataFrame()
            )
            contribution = float(symbol_trades["pnl"].sum()) if "pnl" in symbol_trades else 0.0
            out[symbol] = {
                "trades": symbol_trades,
                "equity": equity.copy(),
                "contribution": contribution,
            }
        return out


class _CurrencyConverter:
    def __init__(self, rates: Mapping[str, Any] | None):
        self.rates = dict(rates or {})

    def convert(self, amount: float, from_currency: str, to_currency: str, dt) -> float:
        from_ccy = str(from_currency or "").upper()
        to_ccy = str(to_currency or "").upper()
        if from_ccy == to_ccy or float(amount) == 0.0:
            return float(amount)
        return float(amount) * self.rate(from_ccy, to_ccy, dt)

    def rate(self, from_currency: str, to_currency: str, dt) -> float:
        direct_keys = (
            f"{from_currency}{to_currency}",
            f"{from_currency}/{to_currency}",
            f"{from_currency}_{to_currency}",
        )
        inverse_keys = (
            f"{to_currency}{from_currency}",
            f"{to_currency}/{from_currency}",
            f"{to_currency}_{from_currency}",
        )
        for key in direct_keys:
            if key in self.rates:
                return self._rate_value(self.rates[key], dt)
        for key in inverse_keys:
            if key in self.rates:
                rate = self._rate_value(self.rates[key], dt)
                if rate == 0:
                    raise ValueError(f"Currency rate {key} is zero")
                return 1.0 / rate
        raise ValueError(f"Missing currency conversion rate {from_currency}->{to_currency}")

    def _rate_value(self, value: Any, dt) -> float:
        if isinstance(value, (int, float, np.integer, np.floating)):
            return float(value)
        if isinstance(value, pd.Series):
            series = value.sort_index()
            if not isinstance(series.index, pd.DatetimeIndex):
                return float(series.iloc[-1])
            loc = series.index.searchsorted(pd.to_datetime(dt), side="right") - 1
            if loc < 0:
                raise ValueError("No currency rate available at or before requested time")
            return float(series.iloc[loc])
        if isinstance(value, pd.DataFrame):
            if "rate" not in value.columns:
                raise ValueError("Currency rate DataFrame must contain a 'rate' column")
            if "datetime" in value.columns:
                series = value.assign(datetime=pd.to_datetime(value["datetime"])).set_index("datetime")["rate"]
            else:
                series = value["rate"]
            return self._rate_value(series, dt)
        raise TypeError(f"Unsupported currency rate type: {type(value)!r}")


def _engine_config_from_symbol_spec(symbol_spec: dict[str, Any], leverage: float) -> dict[str, Any]:
    if not symbol_spec:
        return {}
    point = float(symbol_spec.get("point") or 0.00001)
    contract_size = float(symbol_spec.get("contract_size") or 1.0)
    return {
        "contract_size": contract_size,
        "point": point,
        "leverage": float(leverage or 1.0),
        "margin_rate": symbol_spec.get("margin_rate"),
        "fixed_spread_points": None,
        "use_spread": True,
        "spread_column": "spread",
        "swap_long_per_lot": _swap_to_money(
            float(symbol_spec.get("swap_long_per_lot") or 0.0),
            symbol_spec.get("swap_mode"),
            point,
            contract_size,
        ),
        "swap_short_per_lot": _swap_to_money(
            float(symbol_spec.get("swap_short_per_lot") or 0.0),
            symbol_spec.get("swap_mode"),
            point,
            contract_size,
        ),
        "triple_swap_weekday": _mt5_weekday_to_python(symbol_spec.get("triple_swap_weekday", 3)),
        "commission_per_lot": float(symbol_spec.get("commission_per_lot") or 0.0),
        "commission_perc": 0.0,
    }


def _swap_to_money(raw_swap: float, swap_mode, point: float, contract_size: float) -> float:
    try:
        mode = int(swap_mode)
    except Exception:
        mode = None
    if mode == 1:
        return raw_swap * point * contract_size
    return raw_swap


def _mt5_weekday_to_python(raw_day) -> int | None:
    if raw_day is None or raw_day == "":
        return None
    try:
        day = int(raw_day)
    except Exception:
        return None
    if day < 0 or day > 6:
        return None
    return (day + 6) % 7
