from __future__ import annotations

import argparse
from datetime import datetime
import inspect
import json
import math
import mimetypes
import tempfile
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
import pandas as pd

from ..analytics.metrics import compute_metrics
from ..analytics.risk import compute_risk_metrics
from ..analytics.benchmark import buy_and_hold_metrics
from ..brokers.mt5 import load_mt5_broker_package
from ..brokers.mt5.loader import engine_config_from_symbol_spec
from ..cli import STRATEGIES, build_strategy, load_config
from ..core import PortfolioBacktester, PortfolioSymbolInput, run_strategy_backtest
from ..data import load_mt5_csv, load_mt5_ticks_csv, load_ohlcv_csv, market_data_path, validate_ohlcv
from ..report.exporters import generate_report_bundle
from ..report.robustness_charts import ROBUSTNESS_CHART_TITLES, generate_robustness_charts
from ..analytics.robustness import date_slice, run_battery
from ..analytics import prop_firm
from ..core.engine import Backtester
from ..interactive import routes as interactive_routes


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
PROJECT_ROOT = ROOT.parent.parent

# Default config / broker package used when starting the server.
SESSION_STATE = {
    "session": None,
    "config_path": None,
    "broker_package": None,
    "replay_mode": "candle",
    "output_dir": None,
    "lock": threading.Lock(),
}

# Background backtest jobs: a heavy tick run (minutes) cannot finish inside one HTTP
# request without the browser aborting it and the request holding the session lock
# for the whole time. Such runs execute on a worker thread; the client polls
# /api/session/job for coarse progress and picks up the session when it is done.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

MAX_TICK_REPLAY_FRAMES = 40_000
MIN_BACKTEST_BARS = 5

# Friendly labels for the PNG files emitted by the report bundle.
REPORT_LABELS = {
    "equity_total.png": "Equity total",
    "drawdown_curve.png": "Drawdown",
    "drawdown_monthly.png": "Drawdown mensal",
    "monthly_profit.png": "Lucro mensal",
    "yearly_profit.png": "Lucro anual",
    "profit_factor_month.png": "Profit Factor por mês",
    "heatmap.png": "Heatmap (hora x dia)",
    "boxplot_hour.png": "Boxplot por hora",
    "boxplot_weekday.png": "Boxplot por dia da semana",
    "histograms.png": "Histogramas",
    "r_multiples.png": "R-multiples",
    "scatter.png": "Scatter (duração x PnL)",
    "best_worst.png": "Melhores x piores trades",
    "atr_volume_price.png": "ATR / Volume / Preço",
    "volatility_vs_pnl.png": "Volatilidade x PnL",
    "monte_carlo_shuffle.png": "Monte Carlo · Shuffle",
    "monte_carlo_bootstrap.png": "Monte Carlo · Bootstrap",
    "monte_carlo_block_bootstrap.png": "Monte Carlo · Block Bootstrap",
    "monte_carlo_distribution.png": "Monte Carlo · Distribuição",
}
REPORT_ORDER = list(REPORT_LABELS.keys())


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Run the interactive BacktestCore web UI.")
    parser.add_argument("--config", default="configs/mt5_eurusd_h1.json")
    parser.add_argument("--broker-package", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-reuse-report", action="store_true")
    args = parser.parse_args(argv)

    session = build_session(args.config, args.broker_package, reuse_report=not args.no_reuse_report)
    SESSION_STATE["session"] = session
    SESSION_STATE["config_path"] = str(args.config)
    SESSION_STATE["broker_package"] = str(args.broker_package) if args.broker_package else None
    SESSION_STATE["replay_mode"] = "candle"
    SESSION_STATE["output_dir"] = session["metadata"].get("output_dir")

    handler = make_handler()
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"BacktestCore UI: http://{args.host}:{args.port}", flush=True)
    print(f"Config: {args.config}", flush=True)
    if args.broker_package:
        print(f"Broker package: {args.broker_package}", flush=True)
    server.serve_forever()


def _should_stream_ticks(start_date: str | None, end_date: str | None) -> bool:
    """Tick runs spanning more than a few months (or the full history) stream the
    ticks month-by-month so memory stays bounded. Short windows load fully."""
    if not (start_date and end_date):
        return True  # open-ended / full history
    try:
        return (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days > 120
    except Exception:
        return True


def build_session(
    config_path: str | Path,
    broker_package: str | Path | None = None,
    broker_packages: list[str] | None = None,
    reuse_report: bool = True,
    config_override: dict | None = None,
    replay_mode: str = "candle",
    progress_cb=None,
) -> dict:
    _p = progress_cb if callable(progress_cb) else (lambda *a, **k: None)
    tick_loader = None
    stream_ticks = False
    cfg = load_config(config_path) if config_path else (config_override or {})
    if config_override:
        cfg = {**cfg, **config_override}
    engine = dict(cfg.get("engine", {}) or {})
    if replay_mode != "tick":
        # "Candle fechado" must stay candle-only. Some configs/UI fields can
        # carry execution_mode=tick; honoring that here loads huge ticks.csv
        # files even when the user selected candle mode.
        engine["execution_mode"] = "candle"
    output_dir = Path(cfg.get("output_dir", "reports/ui_preview"))
    _ds = cfg.get("dataset", {}) or {}
    start_date = _ds.get("start_date") or cfg.get("start_date")
    end_date = _ds.get("end_date") or cfg.get("end_date")

    if broker_packages:
        package_list = [str(pkg) for pkg in broker_packages if pkg]
        if len(package_list) < 2:
            broker_packages = None
        else:
            return _build_portfolio_session(
                cfg=cfg,
                package_list=package_list,
                output_dir=output_dir,
                reuse_report=reuse_report,
                replay_mode=replay_mode,
            )

    if broker_package:
        want_ticks = replay_mode == "tick"
        # Large tick spans (or the full history) stream ONE month at a time so memory
        # stays bounded; short windows load fully (keeps tick-level chart replay).
        stream_ticks = want_ticks and _should_stream_ticks(start_date, end_date)
        load_ticks = want_ticks and not stream_ticks
        _p(12, "Carregando candles…" if not load_ticks else "Carregando ticks…")
        package = load_mt5_broker_package(
            broker_package,
            engine_overrides=engine,
            load_ticks=load_ticks,
            tick_start=start_date,
            tick_end=end_date,
        )
        data = package["data"]
        ticks = package.get("ticks")
        engine = package["engine_config"] | engine
        symbol = package["symbol_spec"].get("symbol", "UNKNOWN")
        timeframe = package["symbol_spec"].get("timeframe", "TF")
        account = package.get("account_spec", {})
        broker = account.get("company") or package["symbol_spec"].get("broker") or "MT5"
        ticks_count = 0 if ticks is None else len(ticks)
        if stream_ticks:
            ticks_csv = str(Path(broker_package) / "ticks.csv")
            win_s = pd.Timestamp(start_date) if start_date else None
            win_e = pd.Timestamp(end_date) if end_date else None

            def tick_loader(cs, ce, _csv=ticks_csv, _ws=win_s, _we=win_e):
                s = pd.Timestamp(cs) if _ws is None else max(pd.Timestamp(cs), _ws)
                e = pd.Timestamp(ce) if _we is None else min(pd.Timestamp(ce), _we)
                if s > e:
                    return None
                return load_mt5_ticks_csv(_csv, start=s, end=e)

            engine = engine | {"execution_mode": "tick"}
        elif want_ticks and ticks is not None and not ticks.empty:
            engine = engine | {"execution_mode": "tick"}
        else:
            engine = engine | {"execution_mode": "candle"}
    else:
        ticks = None
        ticks_count = 0
        dataset = cfg["dataset"]
        if "path" in dataset:
            data_path = Path(dataset["path"])
        else:
            data_path = market_data_path(
                symbol=dataset["symbol"],
                timeframe=dataset["timeframe"],
                filename=dataset.get("filename"),
                root=dataset.get("root", "data/raw"),
            )
        data = load_mt5_csv(data_path) if dataset.get("source") == "mt5" else load_ohlcv_csv(data_path)
        symbol = dataset.get("symbol", data_path.stem)
        timeframe = dataset.get("timeframe", "")
        broker = dataset.get("broker") or dataset.get("source", "csv")

    # Execution model is always realistic (idealized was research-only, optimistic,
    # and removed from the UI). Everything else is the strategy's decision (order
    # type, SL/TP/trailing) executed generically by the engine.
    engine["execution_model"] = "realistic"

    # Date filter: restrict the backtest to a specific period if the config asks.
    date_range = None
    if (start_date or end_date) and data is not None and not data.empty:
        before = len(data)
        data = date_slice(data, start_date, end_date)
        if data.empty:
            raise ValueError(
                f"Nenhuma barra encontrada no período selecionado ({start_date or 'início'} até {end_date or 'fim'})."
            )
        if len(data) < MIN_BACKTEST_BARS:
            raise ValueError(
                f"Período selecionado tem só {len(data)} barra(s). Escolha uma janela maior para rodar o backtest."
            )
        if ticks is not None and not ticks.empty:
            ticks = _slice_ticks_to_bars(ticks, data)
        date_range = {"start": start_date, "end": end_date, "bars": int(len(data)), "bars_full": before}
        reuse_report = False  # a cached report is for the full range, not this slice

    quality = validate_ohlcv(data, expected_freq=None)
    strategy = build_strategy(cfg)
    initial_capital = float(engine.get("initial_capital", 1000.0))
    trades_path = output_dir / "trades.csv"
    metrics_path = output_dir / "metrics.json"

    if reuse_report and trades_path.exists():
        prepared = strategy.prepare_indicators(data).reset_index(drop=True)
        trades = pd.read_csv(trades_path)
        for col in ["entry_time", "exit_time"]:
            if col in trades.columns:
                trades[col] = pd.to_datetime(trades[col], errors="coerce")
        metrics = _read_metrics(metrics_path, trades, initial_capital)
        source = f"report cache: {trades_path}"
    else:
        _p(55, "Rodando backtest…")
        result = run_strategy_backtest(
            data=data,
            strategy=strategy,
            config=engine | {"strategy_name": strategy.name},
            ticks=ticks,
            output_dir=output_dir,
            export_report=False,
            tick_loader=tick_loader,
        )
        _p(90, "Montando métricas e gráficos…")
        prepared = result["data"].reset_index(drop=True)
        trades = result["trades"].copy() if result["trades"] is not None else pd.DataFrame()
        metrics = compute_metrics(trades, initial_capital)
        source = "fresh backtest"

    # Tick was requested but this asset has no ticks (e.g. a data/raw CSV) -> it ran
    # in candle mode. Surface a clear warning instead of silently downgrading.
    tick_warning = None
    if replay_mode == "tick" and ticks_count == 0 and not stream_ticks:
        tick_warning = (
            "Modo tick pedido, mas este ativo nao tem ticks (CSV de data/raw). "
            "Rodou em CANDLE. Para tick, selecione um PACOTE MT5 (com ticks.csv) e um periodo curto."
        )
    elif stream_ticks:
        tick_warning = (
            "Histórico grande: backtest em TICK real (streaming por mês, memória limitada). "
            "O gráfico usa candles; os trades são fiéis a tick."
        )

    return serialize_session(
        prepared=prepared,
        trades=trades,
        ticks=ticks,
        config=engine,
        metrics=metrics,
        metadata={
            "symbol": symbol,
            "timeframe": timeframe,
            "broker": broker,
            "strategy": strategy.name,
            "strategy_id": cfg.get("strategy", {}).get("name", ""),
            "config_path": str(config_path) if config_path else "",
            "broker_package": str(broker_package or ""),
            "output_dir": str(output_dir),
            "source": source,
            "quality_ok": quality.ok,
            "quality_message": str(quality),
            "ticks": ticks_count,
            "date_range": date_range,
            "tick_warning": tick_warning,
        },
        replay_mode=replay_mode,
    )


def _slice_ticks_to_bars(ticks: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    if ticks is None or ticks.empty or data is None or data.empty or "datetime" not in ticks.columns:
        return ticks
    start = pd.to_datetime(data["datetime"]).min()
    end = pd.to_datetime(data["datetime"]).max()
    if pd.isna(start) or pd.isna(end):
        return ticks
    if len(data) > 1:
        deltas = pd.to_datetime(data["datetime"]).sort_values().diff().dropna()
        if not deltas.empty:
            end = end + deltas.median()
    mask = (pd.to_datetime(ticks["datetime"], errors="coerce") >= start) & (
        pd.to_datetime(ticks["datetime"], errors="coerce") <= end
    )
    return ticks.loc[mask].reset_index(drop=True)


def _build_portfolio_session(
    cfg: dict,
    package_list: list[str],
    output_dir: Path,
    reuse_report: bool,
    replay_mode: str,
) -> dict:
    base_engine = dict(cfg.get("engine", {}))
    if replay_mode != "tick":
        base_engine["execution_mode"] = "candle"
    base_strategy_name = cfg.get("strategy", {}).get("name", "ema_cross")
    base_strategy_params = dict(cfg.get("strategy", {}).get("params", {}))
    portfolio_inputs: dict[str, PortfolioSymbolInput] = {}
    first_data = None
    first_symbol = None
    first_timeframe = None
    broker_labels = []
    package_paths = []
    prepared_by_symbol: dict[str, pd.DataFrame] = {}
    config_by_symbol: dict[str, dict] = {}
    metadata_by_symbol: dict[str, dict] = {}
    load_ticks = replay_mode == "tick"

    for package_path in package_list:
        package = load_mt5_broker_package(package_path, engine_overrides=base_engine, load_ticks=load_ticks)
        data = package["data"]
        ticks = package.get("ticks")
        engine_config = package["engine_config"] | base_engine
        symbol = package["symbol_spec"].get("symbol", Path(package_path).name)
        timeframe = package["symbol_spec"].get("timeframe", "TF")
        account = package.get("account_spec", {})
        broker = account.get("company") or package["symbol_spec"].get("broker") or "MT5"
        symbol_key = symbol
        if symbol_key in portfolio_inputs:
            base_key = f"{symbol}_{timeframe}".strip("_") or f"asset_{len(portfolio_inputs) + 1}"
            symbol_key = base_key
            suffix = 2
            while symbol_key in portfolio_inputs:
                symbol_key = f"{base_key}_{suffix}"
                suffix += 1
        broker_labels.append(broker)
        package_paths.append(str(package_path))
        if first_data is None:
            first_data = data
            first_symbol = symbol_key
            first_timeframe = timeframe
        strategy = STRATEGIES[base_strategy_name](**base_strategy_params)
        prepared = strategy.prepare_indicators(data).reset_index(drop=True)
        signals = strategy.generate_signals(prepared)
        prepared_by_symbol[symbol_key] = prepared
        config_by_symbol[symbol_key] = engine_config
        metadata_by_symbol[symbol_key] = {
            "symbol": symbol_key,
            "underlying_symbol": symbol,
            "timeframe": timeframe,
            "broker": broker,
            "strategy": strategy.name,
            "strategy_id": base_strategy_name,
            "config_path": "",
            "broker_package": str(package_path),
            "output_dir": str(output_dir / symbol_key),
            "source": "portfolio asset",
            "quality_ok": True,
            "quality_message": "portfolio asset session",
            "ticks": 0,
            "portfolio": True,
            "portfolio_asset": True,
        }
        portfolio_inputs[symbol_key] = PortfolioSymbolInput(
            symbol=symbol_key,
            data=prepared,
            signals=signals,
            config=engine_config,
            symbol_spec=package.get("symbol_spec"),
            ticks=ticks,
        )

    portfolio = PortfolioBacktester(portfolio_inputs, config=base_engine | cfg.get("portfolio", {}))
    result = portfolio.run()

    prepared = prepared_by_symbol.get(first_symbol or "") if first_symbol else first_data
    if prepared is None:
        prepared = pd.DataFrame()
    if prepared is not None and not prepared.empty:
        prepared = prepared.reset_index(drop=True)
    session = serialize_session(
        prepared=prepared,
        trades=result.trades,
        ticks=None,
        config=base_engine,
        metrics=compute_metrics(result.trades, float(base_engine.get("initial_capital", 1000.0))),
        metadata={
            "symbol": first_symbol or "PORTFOLIO",
            "timeframe": first_timeframe or "MULTI",
            "broker": " / ".join(sorted(set(broker_labels))) or "MT5",
            "strategy": base_strategy_name,
            "strategy_id": base_strategy_name,
            "config_path": "",
            "broker_package": "",
            "broker_packages": package_paths,
            "output_dir": str(output_dir),
            "source": "portfolio multi-asset",
            "quality_ok": True,
            "quality_message": "portfolio session",
            "ticks": 0,
            "portfolio": True,
        },
        replay_mode="candle",
    )
    session["asset_sessions"] = {}
    for symbol, symbol_prepared in prepared_by_symbol.items():
        symbol_trades = (
            result.trades[result.trades["symbol"] == symbol].copy()
            if result.trades is not None and not result.trades.empty and "symbol" in result.trades.columns
            else pd.DataFrame()
        )
        session["asset_sessions"][symbol] = serialize_session(
            prepared=symbol_prepared,
            trades=symbol_trades,
            ticks=None,
            config=config_by_symbol.get(symbol, base_engine),
            metrics=compute_metrics(symbol_trades, float(base_engine.get("initial_capital", 1000.0))),
            metadata=metadata_by_symbol.get(symbol, {}),
            replay_mode="candle",
        )
    return session


def serialize_session(
    prepared: pd.DataFrame,
    trades: pd.DataFrame,
    ticks: pd.DataFrame | None,
    config: dict,
    metrics: dict,
    metadata: dict,
    replay_mode: str = "candle",
) -> dict:
    candles = _candles(prepared, config)
    overlays = _overlays(prepared)
    boxes = _fvg_boxes(prepared)
    trade_rows = _trades(trades)
    equity = _equity_timeline(prepared, trades, config)
    events = _events(trades)
    replay = _replay_payload(candles, ticks, config, replay_mode)
    initial_capital = float(config.get("initial_capital", 1000.0))

    risk_metrics = {}
    benchmark = {}
    try:
        risk_metrics = _clean(compute_risk_metrics(trades, initial_capital))
    except Exception:
        pass
    try:
        contract_size = float(config.get("contract_size", 1.0) or 1.0)
        benchmark = _clean(buy_and_hold_metrics(prepared, initial_capital, contract_size))
    except Exception:
        pass

    metadata = dict(metadata)
    trade_symbols = []
    if trades is not None and not trades.empty and "symbol" in trades.columns:
        trade_symbols = sorted(str(sym) for sym in trades["symbol"].dropna().unique())
    metadata.update(
        {
            "candles": len(candles),
            "trades": len(trade_rows),
            "replay_mode": replay["mode"],
            "replay_frames": replay["frame_count"],
            "initial_capital": initial_capital,
            "leverage": float(config.get("leverage", 1.0) or 1.0),
            "commission_per_lot": float(config.get("commission_per_lot", 0.0) or 0.0),
            "symbols": trade_symbols or metadata.get("symbols") or [metadata.get("symbol", "")],
        }
    )
    return {
        "metadata": metadata,
        "metrics": _clean(metrics),
        "risk_metrics": risk_metrics,
        "benchmark": benchmark,
        # Asset/broker specs + cost parameters, so the report/export can show them.
        "broker": {
            "symbol": metadata.get("symbol"),
            "timeframe": metadata.get("timeframe"),
            "broker": metadata.get("broker"),
            "contract_size": config.get("contract_size"),
            "point": config.get("point"),
            "leverage": config.get("leverage"),
            "commission_per_lot": config.get("commission_per_lot"),
            "commission_perc": config.get("commission_perc"),
            "swap_long_per_lot": config.get("swap_long_per_lot"),
            "swap_short_per_lot": config.get("swap_short_per_lot"),
            "triple_swap_weekday": config.get("triple_swap_weekday"),
            "use_spread": config.get("use_spread"),
            "spread_column": config.get("spread_column"),
            "fixed_spread_points": config.get("fixed_spread_points"),
        },
        "candles": candles,
        "overlays": overlays,
        "boxes": boxes,
        "trades": trade_rows,
        "events": events,
        "equity": equity,
        "replay": replay,
    }


def _replay_payload(
    candles: list[list],
    ticks: pd.DataFrame | None,
    config: dict,
    replay_mode: str,
) -> dict:
    requested = (replay_mode or "candle").lower()
    if requested != "tick" or ticks is None or ticks.empty or not candles:
        return {
            "mode": "candle",
            "requested": requested,
            "frames": [],
            "frame_count": len(candles),
            "source": "candles",
            "sampled": False,
            "max_frames": MAX_TICK_REPLAY_FRAMES,
        }

    try:
        frames = _tick_replay_frames(candles, ticks, config)
    except Exception:
        traceback.print_exc()
        return {
            "mode": "candle",
            "requested": requested,
            "frames": [],
            "frame_count": len(candles),
            "source": "tick replay build failed",
            "sampled": False,
            "max_frames": MAX_TICK_REPLAY_FRAMES,
        }

    if not frames:
        return {
            "mode": "candle",
            "requested": requested,
            "frames": [],
            "frame_count": len(candles),
            "source": "no usable ticks",
            "sampled": False,
            "max_frames": MAX_TICK_REPLAY_FRAMES,
        }

    return {
        "mode": "tick",
        "requested": requested,
        "frames": frames,
        "frame_count": len(frames),
        "source": "ticks.csv",
        "sampled": len(ticks) > len(frames),
        "max_frames": MAX_TICK_REPLAY_FRAMES,
    }


def _tick_replay_frames(candles: list[list], ticks: pd.DataFrame, config: dict) -> list[list]:
    candle_times = pd.to_datetime([row[0] for row in candles], unit="s")
    candle_ns = candle_times.asi8
    tick_times = pd.to_datetime(ticks["datetime"], errors="coerce")
    valid = tick_times.notna()
    work = ticks.loc[valid].copy()
    if work.empty:
        return []

    tick_ns = tick_times.loc[valid].astype("int64").to_numpy()
    candle_idx = np.searchsorted(candle_ns, tick_ns, side="right") - 1
    mask = (candle_idx >= 0) & (candle_idx < len(candles))
    if not np.any(mask):
        return []

    work = work.iloc[np.where(mask)[0]].copy()
    work["_candle_idx"] = candle_idx[mask]
    work["_tick_seconds"] = tick_ns[mask] / 1_000_000_000.0

    bid = pd.to_numeric(work["bid"], errors="coerce")
    ask = pd.to_numeric(work.get("ask"), errors="coerce") if "ask" in work.columns else pd.Series(np.nan, index=work.index)
    # The candle open exported by MT5 matches bid on most forex feeds, so bid is
    # the primary replay price. If bid is missing, fall back to last/ask.
    price_series = bid.copy()
    if "last" in work.columns:
        last = pd.to_numeric(work["last"], errors="coerce")
        price_series = price_series.fillna(last.where(last > 0))
    price_series = price_series.fillna(ask)
    work["_price"] = price_series
    work = work.dropna(subset=["_price"])
    if work.empty:
        return []

    candle_open = np.array([float(row[1]) for row in candles], dtype=float)
    candle_spread = np.array([float(row[6]) if len(row) > 6 else 0.0 for row in candles], dtype=float)
    point = float(config.get("point") or 0.00001)

    work["_open"] = candle_open[work["_candle_idx"].to_numpy()]
    work["_high"] = work.groupby("_candle_idx")["_price"].cummax()
    work["_low"] = work.groupby("_candle_idx")["_price"].cummin()
    work["_high"] = np.maximum(work["_high"].to_numpy(), work["_open"].to_numpy())
    work["_low"] = np.minimum(work["_low"].to_numpy(), work["_open"].to_numpy())
    work["_volume"] = work.groupby("_candle_idx").cumcount() + 1

    if point > 0 and ask.notna().any():
        spread_points = ((ask - bid) / point).replace([np.inf, -np.inf], np.nan)
        work["_spread"] = spread_points.reindex(work.index).fillna(pd.Series(candle_spread[work["_candle_idx"].to_numpy()], index=work.index))
    else:
        work["_spread"] = candle_spread[work["_candle_idx"].to_numpy()]

    selected_positions = np.arange(len(work))
    sampled = False
    if len(work) > MAX_TICK_REPLAY_FRAMES:
        step = max(1, math.ceil(len(work) / MAX_TICK_REPLAY_FRAMES))
        base = np.arange(0, len(work), step)
        last_per_candle = work.groupby("_candle_idx").tail(1).index
        last_positions = work.index.get_indexer(last_per_candle)
        selected_positions = np.unique(np.concatenate([base, last_positions[last_positions >= 0]]))
        sampled = True

    selected = work.iloc[selected_positions].sort_values(["_tick_seconds", "_candle_idx"])
    if sampled and len(selected) > MAX_TICK_REPLAY_FRAMES:
        keep = np.unique(np.linspace(0, len(selected) - 1, MAX_TICK_REPLAY_FRAMES, dtype=int))
        selected = selected.iloc[keep]

    frames = []
    cols = selected[["_candle_idx", "_tick_seconds", "_open", "_high", "_low", "_price", "_volume", "_spread"]].to_numpy()
    for row in cols:
        frames.append(
            [
                int(row[0]),
                round(float(row[1]), 3),
                _num(row[2]),
                _num(row[3]),
                _num(row[4]),
                _num(row[5]),
                _num(row[6]),
                _num(row[7]),
            ]
        )
    return frames


def _candles(df: pd.DataFrame, config: dict) -> list[list]:
    spread_col = config.get("spread_column", "spread")
    out = []
    for row in df.itertuples(index=False):
        spread = getattr(row, spread_col, 0.0) if hasattr(row, spread_col) else 0.0
        out.append(
            [
                _ts(row.datetime),
                _num(row.open),
                _num(row.high),
                _num(row.low),
                _num(row.close),
                _num(row.volume),
                _num(spread),
            ]
        )
    return out


def _overlays(df: pd.DataFrame) -> dict[str, list[float | None]]:
    out: dict[str, list[float | None]] = {}
    if df.empty:
        return out

    # Round to 6 decimals: raw EMA/SMA floats carry ~17 sig figs, which bloats the
    # JSON payload several MB (and froze the chart on wide displays). 6 dp is well
    # below sub-pip for forex/CFDs.
    def _series(values) -> list[float | None]:
        return [None if pd.isna(v) else round(float(v), 6) for v in values.tolist()]

    # Only send the overlays the strategy actually computed (its real indicators),
    # so e.g. FVG sends just sma60 instead of 4 unused EMAs (~8 MB of clutter).
    present = [c for c in ("ema9", "ema20", "ema50", "ema200", "sma60", "ml_st_line") if c in df.columns]
    if present:
        for col in present:
            out[col] = _series(pd.to_numeric(df[col], errors="coerce"))
        return out

    # Fallback for strategies with no overlay indicators: default EMAs so the chart
    # isn't bare.
    close = pd.to_numeric(df.get("close"), errors="coerce")
    for period in (9, 20, 50, 200):
        out[f"ema{period}"] = _series(close.ewm(span=period, adjust=False).mean())
    return out


def _fvg_boxes(df: pd.DataFrame) -> list[dict]:
    """FVG rectangles for the chart — only when the data carries the FVG indicators."""
    if not {"sma60", "vol_avg"}.issubset(df.columns):
        return []
    try:
        from ..strategies.fvg_imbalance import detect_fvg_boxes

        return detect_fvg_boxes(df)
    except Exception:
        return []


def _trades(trades: pd.DataFrame) -> list[dict]:
    if trades is None or trades.empty:
        return []
    rows = []
    for row in trades.sort_values(["entry_bar_index", "exit_bar_index"]).itertuples(index=False):
        rows.append(
            {
                "id": int(row.id),
                "direction": row.direction,
                "entryIndex": int(row.entry_bar_index),
                "exitIndex": int(row.exit_bar_index),
                "entryTime": _ts(row.entry_time),
                "exitTime": _ts(row.exit_time),
                "entryPrice": _num(row.entry_price),
                "exitPrice": _num(row.exit_price),
                "size": _num(row.size),
                "pnl": _num(row.pnl),
                "grossPnl": _num(getattr(row, "gross_pnl", 0.0)),
                "swap": _num(getattr(row, "swap", 0.0)),
                "commission": _num(getattr(row, "commission_open", 0.0)) + _num(getattr(row, "commission_close", 0.0)),
                "margin": _num(getattr(row, "margin_required", 0.0)),
                "mfe": _num(getattr(row, "max_favor", 0.0)),
                "mae": _num(getattr(row, "max_adverse", 0.0)),
                "riskReward": _num(getattr(row, "risk_reward", 0.0)),
                "durationMinutes": _duration_minutes(
                    getattr(row, "entry_time", None),
                    getattr(row, "exit_time", None),
                ),
                "reason": str(getattr(row, "exit_reason", "")),
                "result": str(getattr(row, "result", "")),
                "symbol": str(getattr(row, "symbol", "")),
            }
        )
    return rows


def _events(trades: pd.DataFrame) -> list[dict]:
    events = []
    if trades is None or trades.empty:
        return events
    for row in trades.itertuples(index=False):
        direction = str(row.direction)
        pnl = _num(row.pnl)
        events.append(
            {
                "index": int(row.entry_bar_index),
                "type": "entry",
                "side": direction,
                "price": _num(row.entry_price),
                "tradeId": int(row.id),
                "symbol": str(getattr(row, "symbol", "")),
            }
        )
        events.append(
            {
                "index": int(row.exit_bar_index),
                "type": "exit",
                "side": direction,
                "price": _num(row.exit_price),
                "tradeId": int(row.id),
                "pnl": pnl,
                "result": "win" if pnl > 0 else "loss" if pnl < 0 else "be",
                "symbol": str(getattr(row, "symbol", "")),
            }
        )
    return sorted(events, key=lambda item: (item["index"], item["type"]))


def _equity_timeline(df: pd.DataFrame, trades: pd.DataFrame, config: dict) -> list[list]:
    initial = float(config.get("initial_capital", 1000.0))
    contract_size = float(config.get("contract_size", 1.0) or 1.0)
    point = float(config.get("point", 0.00001) or 0.00001)
    spread_column = config.get("spread_column", "spread")
    use_spread = bool(config.get("use_spread", True))
    fixed_spread_points = config.get("fixed_spread_points")
    n = len(df)
    balance_delta = np.zeros(n + 1)
    price_coeff_delta = np.zeros(n + 1)
    spread_coeff_delta = np.zeros(n + 1)
    const_delta = np.zeros(n + 1)
    margin_delta = np.zeros(n + 1)
    count_delta = np.zeros(n + 1)

    if trades is not None and not trades.empty:
        for row in trades.itertuples(index=False):
            entry = max(0, min(int(row.entry_bar_index), n - 1))
            exit_idx = max(0, min(int(row.exit_bar_index), n - 1))
            size_value = float(row.size) * contract_size
            entry_price = float(row.entry_price)
            margin = float(getattr(row, "margin_required", 0.0) or 0.0)
            pnl = float(row.pnl)
            direction = str(row.direction)

            balance_delta[exit_idx] += pnl

            active_end = max(entry, exit_idx)
            if active_end <= entry:
                continue

            if direction == "long":
                price_coeff = size_value
                spread_coeff = 0.0
                const = -entry_price * size_value
            else:
                price_coeff = -size_value
                spread_coeff = -size_value
                const = entry_price * size_value

            price_coeff_delta[entry] += price_coeff
            price_coeff_delta[active_end] -= price_coeff
            spread_coeff_delta[entry] += spread_coeff
            spread_coeff_delta[active_end] -= spread_coeff
            const_delta[entry] += const
            const_delta[active_end] -= const
            margin_delta[entry] += margin
            margin_delta[active_end] -= margin
            count_delta[entry] += 1
            count_delta[active_end] -= 1

    close_values = pd.to_numeric(df["close"], errors="coerce").ffill().fillna(0.0).to_numpy()
    if spread_column in df.columns:
        spreads = pd.to_numeric(df[spread_column], errors="coerce").fillna(0.0).to_numpy()
    else:
        spreads = np.zeros(len(df))
    if not use_spread:
        spread_prices = np.zeros(n)
    elif fixed_spread_points is not None:
        spread_prices = np.full(n, float(fixed_spread_points) * point)
    else:
        spread_prices = spreads * point

    balance = initial + np.cumsum(balance_delta[:n])
    price_coeff = np.cumsum(price_coeff_delta[:n])
    spread_coeff = np.cumsum(spread_coeff_delta[:n])
    const = np.cumsum(const_delta[:n])
    margin = np.cumsum(margin_delta[:n])
    open_count = np.cumsum(count_delta[:n])
    open_pnl = close_values * price_coeff + spread_prices * spread_coeff + const
    equity = balance + open_pnl
    peak = np.maximum.accumulate(equity)
    drawdown_pct = np.where(peak != 0, (equity / peak - 1.0) * 100.0, 0.0)

    out = []
    for i, row in enumerate(df.itertuples(index=False)):
        out.append(
            [
                _ts(row.datetime),
                round(float(balance[i]), 5),
                round(float(equity[i]), 5),
                round(float(open_pnl[i]), 5),
                int(max(open_count[i], 0)),
                round(float(drawdown_pct[i]), 5),
                round(float(margin[i]), 5),
            ]
        )
    return out


# ============================================================
# Catalog endpoints (configs / strategies / datasets / reports)
# ============================================================

def list_configs() -> list[dict]:
    out = []
    root = PROJECT_ROOT / "configs"
    if not root.exists():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            out.append({
                "path": str(path.relative_to(PROJECT_ROOT)),
                "name": path.stem,
                "error": str(exc),
            })
            continue
        strategy = payload.get("strategy", {})
        dataset = payload.get("dataset", {})
        engine = payload.get("engine", {})
        dataset_path = None
        dataset_exists = False
        if dataset:
            try:
                if "path" in dataset:
                    dataset_path = Path(dataset["path"])
                else:
                    dataset_path = market_data_path(
                        symbol=dataset["symbol"],
                        timeframe=dataset["timeframe"],
                        filename=dataset.get("filename"),
                        root=dataset.get("root", "data/raw"),
                    )
                dataset_exists = (PROJECT_ROOT / dataset_path).exists() if not dataset_path.is_absolute() else dataset_path.exists()
            except Exception:
                dataset_path = None
                dataset_exists = False
        out.append({
            "path": str(path.relative_to(PROJECT_ROOT)),
            "name": path.stem,
            "strategy": strategy.get("name", "—"),
            "strategy_params": strategy.get("params", {}),
            "engine": engine,
            "dataset": dataset,
            "dataset_path": str(dataset_path) if dataset_path else None,
            "dataset_exists": dataset_exists,
            "needs_broker_package": "dataset" not in payload,
            "output_dir": payload.get("output_dir"),
            "initial_capital": engine.get("initial_capital"),
        })
    return out


ENGINE_FIELDS = [
    # group "account"
    {"key": "initial_capital", "label": "Saldo inicial", "type": "number", "group": "account", "default": 1000.0, "step": 100, "min": 0, "hint": "Capital de partida da conta."},
    {"key": "leverage", "label": "Alavancagem (1:N)", "type": "number", "group": "account", "default": 30.0, "step": 1, "min": 1, "hint": "Ex.: 30 = 1:30. Para forex 100, 500, etc."},
    {"key": "margin_rate", "label": "Margin rate (override)", "type": "number", "group": "account", "default": None, "step": 0.001, "hint": "Opcional. Sobrescreve a alavancagem se preenchido."},
    # group "risk"
    {"key": "risk_per_trade_pct", "label": "Risco por trade %", "type": "number", "group": "risk", "default": 1.0, "step": 0.1, "min": 0, "hint": "Percentual do equity arriscado por trade quando a estratégia usa risk-based sizing."},
    {"key": "fixed_lot", "label": "Lote fixo", "type": "number", "group": "risk", "default": 1.0, "step": 0.01, "min": 0, "hint": "Lote usado quando 'Risco por trade %' = 0 (auditoria de lote fixo)."},
    {"key": "single_position_mode", "label": "Apenas 1 posição por vez", "type": "boolean", "group": "risk", "default": False},
    {"key": "close_on_signal", "label": "Fechar no sinal contrário", "type": "select", "group": "risk", "default": "never", "options": ["never", "opposite", "any"]},
    {"key": "stop_out_level_pct", "label": "Stop-out %", "type": "number", "group": "risk", "default": None, "step": 1, "hint": "Fecha posições se equity/margem cair abaixo. Vazio = desligado."},
    {"key": "max_positions", "label": "Máx. posições", "type": "integer", "group": "risk", "default": None, "step": 1, "min": 0, "hint": "Limite global de posições abertas."},
    {"key": "max_positions_per_symbol", "label": "Máx. posições por símbolo", "type": "integer", "group": "risk", "default": None, "step": 1, "min": 0, "hint": "Limite por ativo quando houver multi-ativo."},
    # group "costs"
    {"key": "commission_per_lot", "label": "Comissão por lote ($)", "type": "number", "group": "costs", "default": 0.0, "step": 0.1, "min": 0, "hint": "Forex/MT5: por lado da operação."},
    {"key": "commission_perc", "label": "Comissão %", "type": "number", "group": "costs", "default": 0.0, "step": 0.0001, "min": 0, "hint": "Útil para cripto/ações."},
    {"key": "slippage", "label": "Slippage (fator)", "type": "number", "group": "costs", "default": 0.0, "step": 0.0001, "min": 0,
     "hint": "Fator multiplicativo sobre o preço de execução. Ex.: 0.0001 ≈ 1 pip em EURUSD. Típico forex: 0 – 0.0005.",
     "warn_above": 0.001,
     "presets": [
         {"label": "Forex", "value": 0.0001, "detail": "≈ 1 pip"},
         {"label": "Commodities", "value": 0.0003, "detail": "Gold/Oil"},
         {"label": "Crypto", "value": 0.0008, "detail": "BTC/ETH"},
         {"label": "Índices", "value": 0.0002, "detail": "US30/NAS"},
     ]},
    {"key": "swap_long_per_lot", "label": "Swap LONG / lote", "type": "number", "group": "costs", "default": 0.0, "step": 0.1},
    {"key": "swap_short_per_lot", "label": "Swap SHORT / lote", "type": "number", "group": "costs", "default": 0.0, "step": 0.1},
    {"key": "triple_swap_weekday", "label": "Swap triplo (dia)", "type": "select", "group": "costs", "default": 2, "options": [0, 1, 2, 3, 4, 5, 6], "hint": "0=seg, 1=ter, 2=qua, 3=qui, 4=sex, 5=sab, 6=dom."},
    # group "instrument"
    {"key": "contract_size", "label": "Tamanho do contrato", "type": "number", "group": "instrument", "default": 1.0, "step": 1, "min": 0, "hint": "Forex: 100000. Cripto/ações: 1."},
    {"key": "point", "label": "Point size", "type": "number", "group": "instrument", "default": 0.00001, "step": 0.00001, "hint": "Tamanho de 1 ponto. EURUSD 5 dígitos = 0.00001."},
    {"key": "use_spread", "label": "Aplicar spread", "type": "boolean", "group": "instrument", "default": True},
    {"key": "fixed_spread_points", "label": "Spread fixo (pontos)", "type": "number", "group": "instrument", "default": None, "step": 0.1, "min": 0,
     "hint": "Em pontos do ativo (point size). EURUSD 5d: 10 pts = 1.0 pip. Vazio = usa coluna do CSV.",
     "warn_above": 100,
     "presets": [
         {"label": "Forex", "value": 10, "detail": "≈ 1 pip"},
         {"label": "Commodities", "value": 30, "detail": "Gold típico"},
         {"label": "Crypto", "value": 1000, "detail": "BTC/ETH"},
         {"label": "Índices", "value": 150, "detail": "US30/NAS"},
     ]},
    # Entrada (market/limit/stop) e saída (SL/TP/trailing) são definidas pela
    # ESTRATÉGIA, não aqui. O motor executa com defaults honestos: entrada a mercado
    # no next_bar_open e desempate intrabar conservador (SL primeiro). Quem precisar
    # ajustar isso (ex.: validar paridade MT5) faz pelo config, não pela UI.
    # (candle vs tick vem do REPLAY na aba Dados; o modelo é sempre realistic.)
    # group "portfolio"
    {"key": "margin_rate", "label": "Margin rate (override)", "type": "number", "group": "portfolio", "default": None, "step": 0.001, "hint": "Opcional. Sobrescreve a alavancagem se preenchido."},
    {"key": "max_exposure_by_symbol", "label": "Exposição por símbolo", "type": "text", "group": "portfolio", "default": None, "hint": "JSON. Ex.: {\"EURUSD\": 100000}"},
    {"key": "max_exposure_by_currency", "label": "Exposição por moeda", "type": "text", "group": "portfolio", "default": None, "hint": "JSON. Ex.: {\"USD\": 250000}"},
]


def list_strategies() -> list[dict]:
    out = []
    seen_classes: set[type] = set()
    cls_to_id: dict[type, str] = {}
    for key, cls in sorted(STRATEGIES.items()):
        if cls in seen_classes:
            continue
        seen_classes.add(cls)
        cls_to_id[cls] = key
        try:
            instance = cls()
            label = getattr(instance, "name", key)
        except Exception:
            label = key
        params = _strategy_params(cls)
        aliases = sorted(k for k, c in STRATEGIES.items() if c is cls and k != key)
        out.append({
            "id": key,
            "name": label,
            "params": params,
            "aliases": aliases,
        })
    return out


def _strategy_params(cls) -> list[dict]:
    """Introspect a strategy class __init__ to expose editable params."""
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return []
    out = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        default = param.default
        if default is inspect.Parameter.empty:
            default = None
        ptype = "text"
        options = None
        if isinstance(default, bool):
            ptype = "boolean"
        elif isinstance(default, int):
            ptype = "integer"
        elif isinstance(default, float):
            ptype = "number"
        elif isinstance(default, str):
            ptype = "text"
        elif default is None:
            # Try to read from annotation
            ann = param.annotation
            if ann in (int,):
                ptype = "integer"
            elif ann in (float,):
                ptype = "number"
            elif ann in (bool,):
                ptype = "boolean"
            elif ann in (str,):
                ptype = "text"
            else:
                ptype = "number"
        # Heuristic: known string params with limited choices
        if pname == "entry_mode":
            options = ["confirmed", "raw"]
            ptype = "select"
        elif pname == "volume_mode":
            options = ["off", "exhaustion", "confirmation"]
            ptype = "select"
        out.append({
            "key": pname,
            "type": ptype,
            "default": default,
            "options": options,
        })
    return out


def list_datasets() -> dict:
    csvs = []
    seen = set()
    broker_root = PROJECT_ROOT / "data" / "broker_exports"
    broker_package_dirs = set()
    if broker_root.exists():
        broker_package_dirs = {path.parent.resolve() for path in broker_root.rglob("export_manifest.json")}

    candidates = [PROJECT_ROOT, PROJECT_ROOT / "data" / "raw", PROJECT_ROOT / "data" / "samples"]
    for root in candidates:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.csv")):
            if path.is_symlink() or any(p.startswith(".") for p in path.parts):
                continue
            resolved_parent = path.parent.resolve()
            if resolved_parent in broker_package_dirs:
                continue
            rel = path.relative_to(PROJECT_ROOT)
            key = str(rel)
            if key in seen:
                continue
            if "reports" in rel.parts or ".venv" in rel.parts or path.name in {"trades.csv", "metrics.csv"}:
                continue
            seen.add(key)
            size_kb = path.stat().st_size / 1024
            source_hint = "mt5" if "mt5" in path.stem.lower() or path.stem.lower().startswith(("eurusd", "gbpusd", "usdjpy", "xauusd")) else "generic"
            label = str(rel)
            csvs.append({
                "path": str(rel),
                "name": path.stem,
                "label": label,
                "size_kb": round(size_kb, 1),
                "source_hint": source_hint,
                "group": "Raiz" if path.parent == PROJECT_ROOT else str(path.parent.relative_to(PROJECT_ROOT)),
            })

    broker_packages = []
    if broker_root.exists():
        for manifest_path in sorted(broker_root.rglob("export_manifest.json")):
            pkg_dir = manifest_path.parent
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
            symbol_path = pkg_dir / manifest.get("files", {}).get("symbol_spec", "symbol_spec.json")
            try:
                symbol_spec = json.loads(symbol_path.read_text(encoding="utf-8")) if symbol_path.exists() else {}
            except Exception:
                symbol_spec = {}
            account_path = pkg_dir / manifest.get("files", {}).get("account_spec", "account_spec.json")
            try:
                account_spec = json.loads(account_path.read_text(encoding="utf-8")) if account_path.exists() else {}
            except Exception:
                account_spec = {}
            try:
                engine_defaults = engine_config_from_symbol_spec(symbol_spec, account_spec)
            except Exception:
                engine_defaults = {}
            rel_parts = list(pkg_dir.relative_to(broker_root).parts)
            if rel_parts and rel_parts[0] == "BacktestCoreExports":
                rel_parts = rel_parts[1:]
            broker = (
                account_spec.get("company")
                or account_spec.get("server")
                or manifest.get("broker")
                or manifest.get("server")
                or (rel_parts[0] if rel_parts else "MT5")
            )
            symbol = manifest.get("symbol") or (rel_parts[-2] if len(rel_parts) >= 2 else None)
            timeframe = manifest.get("timeframe") or (rel_parts[-1] if rel_parts else None)
            files = manifest.get("files", {})
            ticks_name = files.get("ticks", "ticks.csv")
            ticks_path = pkg_dir / ticks_name
            ticks_exported = manifest.get("ticks_exported")
            tick_cap = int(manifest.get("tick_cap") or 0)
            has_ticks = bool(ticks_name and ticks_path.exists())
            if ticks_exported is None:
                ticks_exported = 0
            ticks_capped = bool(tick_cap > 0 and int(ticks_exported or 0) >= tick_cap)
            ticks_label = f"{int(ticks_exported):,} ticks".replace(",", ".") if has_ticks and int(ticks_exported or 0) > 0 else ("com ticks" if has_ticks else "sem ticks")
            if ticks_capped:
                ticks_label += " (cap atingido)"
            bars = manifest.get("bars_exported")
            bars_label = f"{int(bars):,} candles".replace(",", ".") if bars else "candles"
            label_main = " · ".join(part for part in [broker, f"{symbol} {timeframe}".strip()] if part)
            broker_packages.append({
                "path": str(pkg_dir.relative_to(PROJECT_ROOT)),
                "label": f"{label_main} · {bars_label} · {ticks_label}",
                "short_label": f"{symbol} {timeframe}".strip() or pkg_dir.name,
                "symbol": symbol,
                "timeframe": timeframe,
                "broker": broker,
                "bars_exported": bars,
                "ticks_exported": ticks_exported,
                "tick_cap": tick_cap,
                "ticks_capped": ticks_capped,
                "has_ticks": has_ticks,
                "exported_at": manifest.get("exported_at"),
                "engine_defaults": engine_defaults,
            })

    return {"csvs": csvs, "broker_packages": broker_packages}


def list_report_images(output_dir: str | None) -> list[dict]:
    if not output_dir:
        return []
    target = (PROJECT_ROOT / output_dir).resolve()
    try:
        rel = target.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return []
    if not target.exists() or not target.is_dir():
        return []
    # Build URL relative to "reports/" tree.
    parts = list(rel.parts)
    if parts and parts[0] == "reports":
        url_prefix = "/reports/" + "/".join(parts[1:])
    else:
        url_prefix = "/reports/" + "/".join(parts)
    url_prefix = url_prefix.rstrip("/")
    seen = set()
    ordered = []
    for fname in REPORT_ORDER:
        candidate = target / fname
        if candidate.exists():
            seen.add(fname)
            ordered.append({
                "name": fname,
                "title": REPORT_LABELS[fname],
                "url": f"{url_prefix}/{fname}",
            })
    for path in sorted(target.glob("*.png")):
        if path.name in seen:
            continue
        ordered.append({
            "name": path.name,
            "title": path.stem.replace("_", " ").title(),
            "url": f"{url_prefix}/{path.name}",
        })
    return ordered


# ============================================================
# Session loading helpers
# ============================================================

# Instrument-specific cost fields that a broker package's symbol_spec owns. When a
# package is the asset, the config must not impose another asset's values on these.
_INSTRUMENT_COST_FIELDS = (
    "contract_size", "point", "tick_value",
    "commission_per_lot", "commission_perc",
    "swap_long_per_lot", "swap_short_per_lot", "swap_mode", "triple_swap_weekday",
    "use_spread", "spread_column", "fixed_spread_points", "margin_rate",
)


def load_session_with(
    config_path: str | None,
    broker_package: str | None,
    reuse_report: bool,
    broker_packages: list[str] | None = None,
    replay_mode: str = "candle",
    strategy_id: str | None = None,
    strategy_params: dict | None = None,
    engine_overrides: dict | None = None,
    dataset_path: str | None = None,
    dataset_source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    progress_cb=None,
) -> dict:
    base = {}
    if config_path:
        cfg_target = (PROJECT_ROOT / config_path).resolve()
        cfg_target.relative_to(PROJECT_ROOT.resolve())
        base = load_config(cfg_target)

    has_overrides = False

    if strategy_id:
        strategy_cfg = base.setdefault("strategy", {})
        if strategy_cfg.get("name") != strategy_id:
            strategy_cfg["params"] = {}
            reuse_report = False
        strategy_cfg["name"] = strategy_id
        has_overrides = True

    if strategy_params:
        s = base.setdefault("strategy", {})
        existing = dict(s.get("params") or {})
        for k, v in strategy_params.items():
            existing[k] = v
        s["params"] = existing
        reuse_report = False
        has_overrides = True

    # When a broker PACKAGE is the asset, its symbol_spec defines the instrument
    # costs (contract size, point, swap, commission, spread). Drop instrument-cost
    # fields the chosen config carries for a DIFFERENT asset, so e.g. picking US30
    # with an EURUSD config does NOT run US30 with EURUSD's contract size/point.
    # Explicit user overrides (engine_overrides, applied right after) still win.
    if (broker_package or broker_packages) and isinstance(base.get("engine"), dict):
        for field in _INSTRUMENT_COST_FIELDS:
            base["engine"].pop(field, None)

    if engine_overrides:
        engine = base.setdefault("engine", {})
        for k, v in engine_overrides.items():
            engine[k] = v
        reuse_report = False
        has_overrides = True

    if dataset_path:
        dataset = base.get("dataset", {})
        ds_target = (PROJECT_ROOT / dataset_path).resolve()
        ds_target.relative_to(PROJECT_ROOT.resolve())
        dataset = {**dataset, "path": str(ds_target)}
        if dataset_source:
            dataset["source"] = dataset_source
        elif "source" not in dataset:
            head = ""
            try:
                with ds_target.open("r", encoding="utf-8") as fh:
                    head = fh.readline().lower()
            except Exception:
                head = ""
            dataset["source"] = "mt5" if "time," in head and "tick_volume" in head else "generic"
        base["dataset"] = dataset
        broker_package = None
        broker_packages = None
        reuse_report = False
        has_overrides = True

    if start_date or end_date:
        ds = base.setdefault("dataset", {})
        if start_date:
            ds["start_date"] = start_date
        if end_date:
            ds["end_date"] = end_date
        reuse_report = False
        has_overrides = True

    if broker_packages:
        broker_package = None
        reuse_report = False
        has_overrides = True

    if broker_package:
        reuse_report = False
        has_overrides = True

    if not broker_package and not broker_packages and "dataset" not in base:
        raise ValueError("Escolha um pacote MT5 ou CSV em 'Ativo / Dado' para esse config.")

    # When overrides exist, divert output to a sandbox directory so cached reports aren't clobbered.
    if has_overrides:
        try:
            stamp_payload = {
                "config": base,
                "broker_package": broker_package,
                "broker_packages": broker_packages,
                "replay_mode": replay_mode,
            }
            stamp = abs(hash(json.dumps(stamp_payload, sort_keys=True, default=str))) % (10 ** 9)
        except Exception:
            stamp = 0
        base["output_dir"] = f"reports/ui_runs/run_{stamp}"
        return build_session(
            None,
            broker_package,
            broker_packages=broker_packages,
            reuse_report=reuse_report,
            config_override=base,
            replay_mode=replay_mode,
            progress_cb=progress_cb,
        )

    config_for_build = str((PROJECT_ROOT / config_path).resolve()) if config_path else None
    return build_session(
        config_for_build,
        broker_package,
        broker_packages=broker_packages,
        reuse_report=reuse_report,
        replay_mode=replay_mode,
        progress_cb=progress_cb,
    )


def _run_load(payload: dict, progress_cb=None) -> dict:
    """Run a session load from a request payload and commit it to SESSION_STATE.
    Shared by the synchronous and the background-job code paths."""
    broker_package = payload.get("broker_package")
    broker_packages = payload.get("broker_packages") or None
    config_path = payload.get("config_path")
    with SESSION_STATE["lock"]:
        session = load_session_with(
            config_path=config_path,
            broker_package=broker_package,
            broker_packages=broker_packages,
            reuse_report=bool(payload.get("reuse_report", True)),
            replay_mode=payload.get("replay_mode") or "candle",
            strategy_id=payload.get("strategy_id"),
            strategy_params=payload.get("strategy_params") or None,
            engine_overrides=payload.get("engine_overrides") or None,
            dataset_path=payload.get("dataset_path"),
            dataset_source=payload.get("dataset_source"),
            start_date=(payload.get("start_date") or "").strip() or None,
            end_date=(payload.get("end_date") or "").strip() or None,
            progress_cb=progress_cb,
        )
        SESSION_STATE["session"] = session
        SESSION_STATE["config_path"] = config_path
        SESSION_STATE["broker_package"] = broker_package or (broker_packages[0] if broker_packages else None)
        SESSION_STATE["replay_mode"] = session["metadata"].get("replay_mode", payload.get("replay_mode") or "candle")
        SESSION_STATE["output_dir"] = session["metadata"].get("output_dir")
    return session


def _run_load_job(job_id: str, payload: dict) -> None:
    """Worker thread: run the load, streaming coarse progress into JOBS[job_id]."""
    def cb(pct, msg):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job is not None:
                job["progress"] = int(pct)
                job["message"] = str(msg)
    try:
        session = _run_load(payload, progress_cb=cb)
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "done", "progress": 100, "message": "Pronto",
                            "session": session, "error": None}
    except Exception as exc:  # noqa: BLE001 - surfaced to the client
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "error", "progress": 100, "message": "Erro",
                            "session": None, "error": str(exc)}


# ============================================================
# Robustness battery (runs the active session's strategy through analytics/robustness)
# ============================================================

ROBUSTNESS_BARS_CAP = 40000
ROBUSTNESS_MARKETS = [("EURUSD", "H4"), ("XAUUSD", "H1"), ("EURUSD", "D1")]


def _load_dataset_df(dataset: dict) -> pd.DataFrame:
    path = dataset.get("path")
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return load_mt5_csv(p) if dataset.get("source") == "mt5" else load_ohlcv_csv(p)
    dp = market_data_path(symbol=dataset["symbol"], timeframe=dataset["timeframe"],
                          filename=dataset.get("filename"), root=dataset.get("root", "data/raw"))
    return load_mt5_csv(dp) if dataset.get("source") == "mt5" else load_ohlcv_csv(dp)


def _robustness_markets(active_symbol, active_tf, cap: int = 15000) -> list[dict]:
    out: list[dict] = []
    for sym, tf in ROBUSTNESS_MARKETS:
        if sym == active_symbol and tf == active_tf:
            continue
        p = PROJECT_ROOT / "data" / "raw" / sym / tf / f"{sym}_{tf}.csv"
        if not p.exists():
            continue
        try:
            out.append({"symbol": sym, "timeframe": tf,
                        "data": load_mt5_csv(p).tail(cap).reset_index(drop=True)})
        except Exception:
            continue
        if len(out) >= 3:
            break
    return out


def run_robustness_for_session() -> dict:
    cfg_path = SESSION_STATE.get("config_path")
    if not cfg_path:
        return {"ok": False, "error": "Nenhuma sessao baseada em config ativa (robustez precisa de CSV/config)."}
    try:
        cfg = load_config(cfg_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Falha ao ler config: {exc}"}
    dataset = dict(cfg.get("dataset", {}))
    if not dataset:
        return {"ok": False, "error": "Robustez precisa de uma sessao baseada em CSV/config (nao broker package)."}
    strat_cfg = cfg.get("strategy", {})
    name = strat_cfg.get("name", "")
    strat_cls = STRATEGIES.get(name)
    if strat_cls is None:
        return {"ok": False, "error": f"Estrategia '{name}' nao encontrada."}

    base_params = dict(strat_cfg.get("params", {}))
    engine_cfg = dict(cfg.get("engine", {}))
    engine_cfg.setdefault("initial_capital", 10000.0)

    data = _load_dataset_df(dataset)
    full_bars = len(data)
    if full_bars > ROBUSTNESS_BARS_CAP:
        data = data.tail(ROBUSTNESS_BARS_CAP).reset_index(drop=True)
    markets = _robustness_markets(dataset.get("symbol"), dataset.get("timeframe"))

    card = run_battery(strat_cls, data, engine_cfg, base_params, markets=markets)
    card["meta"] = {
        "strategy": name, "params": base_params,
        "bars_used": int(len(data)), "bars_total": int(full_bars),
        "capped": full_bars > ROBUSTNESS_BARS_CAP,
    }

    out_dir = Path(SESSION_STATE.get("output_dir") or cfg.get("output_dir") or "reports/ui_preview")
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    chart_dir = out_dir / "robustness"
    charts = generate_robustness_charts(card, chart_dir)
    images = []
    for chart_name, filename in charts.items():
        try:
            rel = (chart_dir / filename).resolve().relative_to((PROJECT_ROOT / "reports").resolve())
            images.append({"name": chart_name, "url": "/reports/" + str(rel).replace("\\", "/")})
        except ValueError:
            continue
    return {"ok": True, "scorecard": card, "images": images}


def run_propfirm_for_session(preset: str = "ftmo_challenge", account_size: float = 100_000.0,
                             rules_override: dict | None = None) -> dict:
    """Prop-firm evaluation for the active session's strategy. Runs the engine directly
    (candle mode) to capture the per-bar equity track, then scores it against the
    prop-firm rules. Mirrors run_robustness_for_session's config/data handling."""
    cfg_path = SESSION_STATE.get("config_path")
    if not cfg_path:
        return {"ok": False, "error": "Prop-firm precisa de uma sessao baseada em CSV/config."}
    try:
        cfg = load_config(cfg_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Falha ao ler config: {exc}"}
    dataset = dict(cfg.get("dataset", {}))
    if not dataset:
        return {"ok": False, "error": "Prop-firm precisa de uma sessao baseada em CSV/config."}
    strat_cfg = cfg.get("strategy", {})
    name = strat_cfg.get("name", "")
    strat_cls = STRATEGIES.get(name)
    if strat_cls is None:
        return {"ok": False, "error": f"Estrategia '{name}' nao encontrada."}

    base_params = dict(strat_cfg.get("params", {}))
    engine_cfg = dict(cfg.get("engine", {}))
    engine_cfg.setdefault("initial_capital", 10000.0)
    engine_cfg["execution_mode"] = "candle"  # equity track is exported in candle mode

    data = _load_dataset_df(dataset)
    full_bars = len(data)
    if full_bars > ROBUSTNESS_BARS_CAP:
        data = data.tail(ROBUSTNESS_BARS_CAP).reset_index(drop=True)

    strat = strat_cls(**base_params)
    prepared = strat.prepare_indicators(data)
    signals = strat.generate_signals(prepared)
    bt = Backtester(prepared, engine_cfg)
    trades = bt.run(signals)

    card = prop_firm.evaluate(
        bt.equity_curve, trades, float(engine_cfg["initial_capital"]),
        preset=preset, account_size=account_size, rules_override=rules_override or None,
    )
    card["meta"] = {
        "strategy": name, "params": base_params,
        "bars_used": int(len(data)), "bars_total": int(full_bars),
        "trades": int(len(trades)),
    }
    return {"ok": True, "scorecard": card}


def _robustness_charts_for_export() -> list:
    """Pre-rendered robustness PNGs for the active session (if the battery was run)."""
    out_dir = SESSION_STATE.get("output_dir")
    if not out_dir:
        return []
    rdir = Path(out_dir)
    if not rdir.is_absolute():
        rdir = PROJECT_ROOT / rdir
    rdir = rdir / "robustness"
    if not rdir.exists():
        return []
    charts = []
    for name, title in ROBUSTNESS_CHART_TITLES.items():
        p = rdir / f"{name}.png"
        if p.exists():
            charts.append((title, p))
    return charts


# ============================================================
# HTTP handler
# ============================================================

def make_handler():
    class UIHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/session":
                    self._json(SESSION_STATE["session"] or {})
                    return
                if path == "/api/health":
                    self._json({"ok": True})
                    return
                if path == "/api/session/job":
                    jid = (parse_qs(parsed.query).get("id") or [""])[0]
                    with JOBS_LOCK:
                        job = JOBS.get(jid)
                        if job is None:
                            self._json({"ok": False, "error": "job não encontrado"}, status=404)
                            return
                        status, progress, message = job["status"], job["progress"], job["message"]
                        session = job["session"] if status == "done" else None
                        error = job["error"]
                        if status in ("done", "error"):
                            JOBS.pop(jid, None)  # deliver the terminal state once, then free it
                    self._json({"ok": status != "error", "status": status, "progress": progress,
                                "message": message, "session": session, "error": error})
                    return
                if path == "/api/catalog":
                    self._json({
                        "configs": list_configs(),
                        "strategies": list_strategies(),
                        "datasets": list_datasets(),
                        "engine_fields": ENGINE_FIELDS,
                        "current": {
                            "config_path": SESSION_STATE.get("config_path"),
                            "broker_package": SESSION_STATE.get("broker_package"),
                            "replay_mode": SESSION_STATE.get("replay_mode", "candle"),
                            "output_dir": SESSION_STATE.get("output_dir"),
                        },
                    })
                    return
                if path == "/api/report-images":
                    output_dir = SESSION_STATE.get("output_dir")
                    self._json({"output_dir": output_dir, "images": list_report_images(output_dir)})
                    return
                if path == "/api/robustness":
                    # Heavy compute (~30-60s): don't hold the session lock so the
                    # page stays responsive while it runs.
                    self._json(run_robustness_for_session())
                    return
                if path == "/api/propfirm":
                    q = parse_qs(parsed.query)
                    preset = (q.get("preset") or ["ftmo_challenge"])[0]

                    def _qf(key):
                        raw = (q.get(key) or [""])[0]
                        try:
                            return float(raw) if raw != "" else None
                        except ValueError:
                            return None

                    acct = _qf("account_size") or 100_000.0
                    # Rule overrides (any subset) — % fields arrive as percents, stored as fractions.
                    ov = {}
                    for src, dst, frac in (
                        ("profit_target", "profit_target_pct", True),
                        ("max_daily_loss", "max_daily_loss_pct", True),
                        ("max_total_loss", "max_total_loss_pct", True),
                        ("trailing_dd", "trailing_dd_pct", True),
                        ("max_best_day", "max_best_day_pct", True),
                        ("max_days", "max_days", False),
                    ):
                        v = _qf(src)
                        if v is not None:
                            ov[dst] = (v / 100.0) if frac else int(v)
                    md = _qf("min_trading_days")
                    if md is not None:
                        ov["min_trading_days"] = int(md)
                    tmode = (q.get("trailing_mode") or [""])[0]
                    if tmode in ("equity", "balance"):
                        ov["trailing_mode"] = tmode
                    tbasis = (q.get("trailing_basis") or [""])[0]
                    if tbasis in ("peak", "initial"):
                        ov["trailing_basis"] = tbasis
                    for flag in ("forbid_weekend_holding", "require_stop_loss", "trailing_locks_at_initial"):
                        raw = (q.get(flag) or [""])[0]
                        if raw != "":
                            ov[flag] = raw in ("1", "true", "True", "on")
                    self._json(run_propfirm_for_session(preset=preset, account_size=acct,
                                                         rules_override=ov or None))
                    return
                if path == "/api/session/export":
                    self._export_session_html()
                    return
                if path.startswith("/reports/"):
                    self._report(path[len("/reports/"):])
                    return
                if path == "/interactive":
                    # Redirect to trailing slash so the page resolves its assets
                    # against /interactive/ (its base-path logic needs the slash).
                    self.send_response(301)
                    self.send_header("Location", "/interactive/")
                    self.end_headers()
                    return
                if path == "/interactive/":
                    path = "/interactive/index.html"
                elif path.startswith("/interactive/"):
                    # API GET routes are handled here; static assets fall through.
                    if interactive_routes.handle(self, "GET", path):
                        return
                if path == "/":
                    path = "/index.html"
                self._static(path)
            except Exception:
                traceback.print_exc()
                self.send_error(500, "internal error")

        def do_POST(self):
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/api/session/load":
                    length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(body) if body else {}
                    self._handle_load(payload)
                    return
                if parsed.path.startswith("/interactive/"):
                    if interactive_routes.handle(self, "POST", parsed.path):
                        return
                self.send_error(404)
            except Exception as exc:
                traceback.print_exc()
                self._json({"ok": False, "error": str(exc)}, status=500)

        def do_PUT(self):
            self._forward_interactive("PUT")

        def do_DELETE(self):
            self._forward_interactive("DELETE")

        def _forward_interactive(self, method: str):
            try:
                parsed = urlparse(self.path)
                if parsed.path.startswith("/interactive/") and interactive_routes.handle(self, method, parsed.path):
                    return
                self.send_error(404)
            except Exception as exc:
                traceback.print_exc()
                self._json({"ok": False, "error": str(exc)}, status=500)

        def _handle_load(self, payload: dict):
            # Async path: a heavy tick run executes on a worker thread; the client
            # polls /api/session/job. Anything else runs inline as before.
            if payload.get("async"):
                job_id = uuid.uuid4().hex[:12]
                with JOBS_LOCK:
                    JOBS[job_id] = {"status": "running", "progress": 3,
                                    "message": "Iniciando…", "session": None, "error": None}
                threading.Thread(target=_run_load_job, args=(job_id, payload), daemon=True).start()
                self._json({"ok": True, "async": True, "job_id": job_id})
                return
            session = _run_load(payload)
            self._json({"ok": True, "session": session})

        def log_message(self, fmt, *args):
            return

        def _json(self, payload: dict, status: int = 200):
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path: str):
            target = (STATIC_ROOT / path.lstrip("/")).resolve()
            if not str(target).startswith(str(STATIC_ROOT.resolve())) or not target.exists():
                self.send_error(404)
                return
            self._send_file(target)

        def _report(self, rel: str):
            # URL `/reports/<X>` maps to filesystem `reports/<X>` (project-relative).
            target = (PROJECT_ROOT / "reports" / rel).resolve()
            project_resolved = PROJECT_ROOT.resolve()
            reports_root = (PROJECT_ROOT / "reports").resolve()
            try:
                target.relative_to(reports_root)
            except ValueError:
                self.send_error(403)
                return
            if not target.exists() or not target.is_file():
                self.send_error(404)
                return
            self._send_file(target)

        def _send_file(self, target: Path):
            body = target.read_bytes()
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # PNGs from reports/ can be cached; everything else (UI files) should never cache
            if target.suffix.lower() == ".png" and "reports" in target.parts:
                self.send_header("Cache-Control", "public, max-age=60")
            else:
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _send_download(self, body: bytes, filename: str, content_type: str = "application/octet-stream"):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _export_session_html(self):
            session = SESSION_STATE.get("session")
            if not session:
                self.send_error(404, "no session loaded")
                return
            html_bytes, filename = _build_dashboard_export(session)
            self._send_download(html_bytes, filename, "text/html; charset=utf-8")

    return UIHandler


def _read_metrics(path: Path, trades: pd.DataFrame, initial_capital: float) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return compute_metrics(trades, initial_capital)


def _build_dashboard_export(session: dict) -> tuple[bytes, str]:
    metadata = dict(session.get("metadata") or {})
    asset_sessions = session.get("asset_sessions") or {}
    if asset_sessions:
        html_text = _dashboard_export_tabs_html(session)
    else:
        html_text = _dashboard_export_single_html(session)
    filename = _dashboard_export_filename(metadata)
    return html_text.encode("utf-8"), filename


def _dashboard_export_single_html(session: dict, title_override: str | None = None) -> str:
    metadata = dict(session.get("metadata") or {})
    metrics = dict(session.get("metrics") or {})
    candles = pd.DataFrame(session.get("candles") or [], columns=["datetime", "open", "high", "low", "close", "volume", "spread"])
    if not candles.empty:
        candles["datetime"] = pd.to_datetime(candles["datetime"], unit="s", errors="coerce")
        for col in ["open", "high", "low", "close", "volume", "spread"]:
            candles[col] = pd.to_numeric(candles[col], errors="coerce")
        candles = _add_atr(candles, period=14)

    trades = _session_trades_frame(session.get("trades") or [])
    initial_capital = float(metadata.get("initial_capital", 1000.0) or 1000.0)

    export_title = f'{metadata.get("symbol", "Session")} {metadata.get("timeframe", "")} Dashboard Export'.strip()
    if title_override:
        export_title = title_override
    broker = dict(session.get("broker") or {})
    extra_charts = _robustness_charts_for_export()
    if trades.empty:
        html_text = _dashboard_export_empty_html(export_title, metadata, metrics, session)
    else:
        with tempfile.TemporaryDirectory(prefix="backtestcore-export-") as tmpdir:
            report_paths = generate_report_bundle(
                data=candles,
                trades=trades,
                # Pass the asset/broker specs + cost params so the export shows the
                # "Custos & Ativo" panel by default.
                config={"initial_capital": initial_capital, "strategy_name": metadata.get("strategy", "Strategy"), **broker},
                output_dir=tmpdir,
                title=export_title,
                # If the robustness battery was run for this session, embed its charts too.
                extra_charts=extra_charts,
            )
            html_path = Path(report_paths["html"])
            html_text = html_path.read_text(encoding="utf-8")

    return html_text


def _dashboard_export_tabs_html(session: dict) -> str:
    metadata = dict(session.get("metadata") or {})
    export_title = f'{metadata.get("symbol", "Portfolio")} {metadata.get("timeframe", "MULTI")} Dashboard Export'.strip()
    scopes: list[tuple[str, str, dict]] = [("account", "Conta consolidada", session)]
    asset_sessions = session.get("asset_sessions") or {}
    for symbol, asset_session in sorted(asset_sessions.items(), key=lambda item: str(item[0])):
        scopes.append((f"asset-{_slug(symbol)}", str(symbol), asset_session))

    tabs = []
    frames = []
    sources = []
    for idx, (scope_id, label, scope_session) in enumerate(scopes):
        active = " active" if idx == 0 else ""
        trades_count = len(scope_session.get("trades") or [])
        title = f"{export_title} - {label}"
        html_text = _dashboard_export_single_html(scope_session, title_override=title)
        source_id = f"export-source-{idx}"
        frame_id = f"export-frame-{idx}"
        tabs.append(
            f'<button class="tab{active}" type="button" data-tab="{frame_id}">'
            f'<strong>{escape(label)}</strong><span>{trades_count} trades</span></button>'
        )
        frames.append(
            f'<iframe id="{frame_id}" class="report-frame{active}" title="{escape(label)}" '
            f'data-source="{source_id}" loading="lazy"></iframe>'
        )
        source_json = json.dumps(html_text, ensure_ascii=False).replace("</", "<\\/")
        sources.append(f'<script type="application/json" id="{source_id}">{source_json}</script>')

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>{escape(export_title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #070a12;
      --panel: #101725;
      --panel2: #121f32;
      --line: rgba(255,255,255,.10);
      --text: #e9eef7;
      --muted: #9aa8bd;
      --cyan: #00e5ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    header {{ position: sticky; top: 0; z-index: 5; background: rgba(7,10,18,.96); border-bottom: 1px solid var(--line); backdrop-filter: blur(12px); }}
    .head {{ width: min(1440px, calc(100% - 32px)); margin: 0 auto; padding: 16px 0 12px; }}
    h1 {{ margin: 0 0 12px; font-size: 22px; }}
    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .tab {{ border: 1px solid var(--line); background: var(--panel); color: var(--muted); border-radius: 8px; padding: 9px 12px; cursor: pointer; text-align: left; min-width: 130px; }}
    .tab strong {{ display: block; color: inherit; font-size: 12px; }}
    .tab span {{ display: block; margin-top: 3px; font-size: 10px; color: var(--muted); }}
    .tab.active {{ border-color: var(--cyan); color: var(--text); background: linear-gradient(145deg, var(--panel2), var(--panel)); box-shadow: 0 0 18px rgba(0,229,255,.12); }}
    main {{ width: 100%; }}
    .report-frame {{ display: none; width: 100%; height: calc(100vh - 104px); border: 0; background: #fff; }}
    .report-frame.active {{ display: block; }}
    noscript {{ display: block; width: min(900px, calc(100% - 32px)); margin: 24px auto; color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <div class="head">
      <h1>{escape(export_title)}</h1>
      <nav class="tabs" aria-label="Relatorios por ativo">{"".join(tabs)}</nav>
    </div>
  </header>
  <main>{"".join(frames)}</main>
  <noscript>Ative JavaScript para navegar pelos relatórios exportados em abas.</noscript>
  {"".join(sources)}
  <script>
    const loadFrame = (frame) => {{
      if (!frame || frame.dataset.loaded === "1") return;
      const source = document.getElementById(frame.dataset.source);
      if (!source) return;
      frame.srcdoc = JSON.parse(source.textContent);
      frame.dataset.loaded = "1";
    }};
    const activate = (id) => {{
      document.querySelectorAll(".tab").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === id));
      document.querySelectorAll(".report-frame").forEach((frame) => {{
        const active = frame.id === id;
        frame.classList.toggle("active", active);
        if (active) loadFrame(frame);
      }});
    }};
    document.querySelectorAll(".tab").forEach((btn) => {{
      btn.addEventListener("click", () => activate(btn.dataset.tab));
    }});
    loadFrame(document.querySelector(".report-frame.active"));
  </script>
</body>
</html>
"""


def _dashboard_export_filename(metadata: dict) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [
        _slug(metadata.get("symbol", "session")),
        _slug(metadata.get("timeframe", "")),
        _slug(metadata.get("strategy", "strategy")),
        stamp,
    ]
    name = "_".join([part for part in parts if part]) or "dashboard_export"
    return f"{name}.html"


def _dashboard_export_empty_html(title: str, metadata: dict, metrics: dict, session: dict) -> str:
    summary = "".join(
        f"<div class=\"metric\"><span>{escape(key)}</span><strong>{escape(str(value))}</strong><small>Sem trades fechados</small></div>"
        for key, value in [
            ("Symbol", metadata.get("symbol", "—")),
            ("Timeframe", metadata.get("timeframe", "—")),
            ("Strategy", metadata.get("strategy", "—")),
            ("Broker", metadata.get("broker", "—")),
        ]
    )
    payload_json = json.dumps(
        {
            "metadata": metadata,
            "metrics": metrics,
            "candles": session.get("candles") or [],
            "overlays": session.get("overlays") or {},
            "trades": session.get("trades") or [],
            "events": session.get("events") or [],
            "equity": session.get("equity") or [],
        },
        indent=2,
        ensure_ascii=False,
        default=str,
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #070a12;
      --panel: #101725;
      --panel2: #121f32;
      --text: #e9eef7;
      --muted: #9aa8bd;
      --cyan: #00e5ff;
      --green: #00c853;
      --red: #ff5252;
      --amber: #ffab00;
      --violet: #b388ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(1240px, calc(100% - 32px)); margin: 28px auto 60px; }}
    h1 {{ margin: 0; font-size: 28px; }}
    .subtitle {{ color: var(--muted); margin-top: 8px; font-size: 14px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 22px 0 26px; }}
    .metric {{ background: linear-gradient(145deg, var(--panel), var(--panel2)); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 16px; min-height: 104px; }}
    .metric span {{ display: block; color: var(--muted); text-transform: uppercase; font-size: 11px; letter-spacing: .08em; margin-bottom: 8px; }}
    .metric strong {{ font-size: 24px; }}
    .metric small {{ display: block; color: var(--muted); margin-top: 8px; }}
    .chart-card {{ background: var(--panel); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 16px; }}
    .chart-card h2 {{ font-size: 16px; margin: 0 0 12px; color: #f6f8fb; }}
    .chart-card pre {{ white-space: pre-wrap; word-break: break-word; max-height: 640px; overflow: auto; background: #050812; border: 1px solid rgba(255,255,255,.08); border-radius: 8px; padding: 16px; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>{escape(title)}</h1>
        <div class="subtitle">Export da sessão atual do dashboard</div>
      </div>
    </header>
    <section class="metrics">{summary}</section>
    <section class="chart-card">
      <h2>Dashboard Export</h2>
      <details open>
        <summary style="cursor:pointer;font-weight:600;margin-bottom:12px;">Full session JSON</summary>
        <pre>{escape(payload_json)}</pre>
      </details>
    </section>
  </main>
</body>
</html>
"""


def _session_trades_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).copy()
    rename = {
        "entryTime": "entry_time",
        "exitTime": "exit_time",
        "entryIndex": "entry_bar_index",
        "exitIndex": "exit_bar_index",
        "entryPrice": "entry_price",
        "exitPrice": "exit_price",
        "riskReward": "risk_reward",
        "grossPnl": "gross_pnl",
        "mfe": "max_favor",
        "mae": "max_adverse",
        "durationMinutes": "duration_minutes",
        "commission": "commission_total",
        "margin": "margin_required",
    }
    df = df.rename(columns=rename)
    if "entry_time" in df.columns:
        df["entry_time"] = pd.to_datetime(df["entry_time"], unit="s", errors="coerce")
    if "exit_time" in df.columns:
        df["exit_time"] = pd.to_datetime(df["exit_time"], unit="s", errors="coerce")
    if "duration_minutes" in df.columns:
        df["duration"] = pd.to_timedelta(df["duration_minutes"], unit="m")
    if "commission_total" in df.columns:
        df["commission_open"] = pd.to_numeric(df["commission_total"], errors="coerce").fillna(0.0)
        df["commission_close"] = 0.0
    for col in ["entry_price", "exit_price", "size", "pnl", "gross_pnl", "swap", "margin_required", "max_favor", "max_adverse", "risk_reward"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    prev_close = out["close"].shift(1).fillna(out["close"])
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(period).mean()
    return out


def _fmt_money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "-"


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return "-"
    if not math.isfinite(num):
        return "-"
    return f"{num:+.2f}%"


def _fmt_value(value) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    if not math.isfinite(num):
        return "-"
    return f"{num:.2f}"


def _slug(value) -> str:
    text = str(value or "").strip().lower()
    out = []
    for char in text:
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "_":
            out.append("_")
    slug = "".join(out).strip("_")
    return slug or "session"


def _ts(value) -> int:
    return int(pd.to_datetime(value).timestamp())


def _num(value) -> float:
    try:
        out = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(out):
        return 0.0
    return out


def _maybe_num(value) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _duration_minutes(start, end) -> float:
    try:
        delta = pd.to_datetime(end) - pd.to_datetime(start)
        return max(float(delta.total_seconds()) / 60.0, 0.0)
    except Exception:
        return 0.0


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


if __name__ == "__main__":
    main()
