from __future__ import annotations

import argparse
import json
from pathlib import Path

from .brokers.mt5 import load_mt5_broker_package
from .core import run_strategy_backtest
from .data import load_market_csv, load_mt5_csv, load_ohlcv_csv, market_data_path, validate_ohlcv
from .strategies import STRATEGIES, build_strategy, discover_strategies

discover_strategies()


def load_config(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Run a BacktestCore strategy from a JSON config.")
    parser.add_argument("--config", help="Path to JSON config.")
    parser.add_argument("--broker-package", help="Path to an exported MT5 broker package folder.")
    parser.add_argument("--execution-mode", choices=["candle", "tick"], help="Override execution mode.")
    parser.add_argument("--entry-timing", choices=["signal_close", "next_bar_open"], help="Override signal entry timing.")
    args = parser.parse_args(argv)

    discover_strategies()
    config_path = args.config or (None if args.broker_package else "configs/demo.json")
    cfg = load_config(config_path) if config_path else {}
    engine = cfg.get("engine", {})
    if args.execution_mode:
        engine["execution_mode"] = args.execution_mode
    if args.entry_timing:
        engine["entry_timing"] = args.entry_timing
    output_dir = cfg.get("output_dir", "reports/backtest_report")

    if args.broker_package:
        package = load_mt5_broker_package(args.broker_package, engine_overrides=engine)
        data = package["data"]
        ticks = package.get("ticks")
        engine = package["engine_config"] | engine
        symbol = package["symbol_spec"].get("symbol", "UNKNOWN")
        timeframe = package["symbol_spec"].get("timeframe", "TF")
        cfg_dataset = cfg.get("dataset", {})
        cfg_matches_package = (
            cfg_dataset.get("symbol") == symbol
            and str(cfg_dataset.get("timeframe", "")).upper() == str(timeframe).upper()
        )
        output_dir = cfg.get("output_dir") if cfg_matches_package else None
        output_dir = output_dir or f"reports/{symbol}_{timeframe}_broker_package"
        dataset = {
            "symbol": symbol,
            "timeframe": timeframe,
            "expected_freq": None,
        }
    else:
        ticks = None
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
        if not data_path.exists():
            raise SystemExit(
                "CSV not found.\n"
                f"Expected: {data_path}\n"
                "Place your OHLCV file there or edit the config JSON."
            )

        if "path" in dataset:
            data = load_mt5_csv(data_path) if dataset.get("source") == "mt5" else load_ohlcv_csv(data_path)
        else:
            data = load_market_csv(
                symbol=dataset["symbol"],
                timeframe=dataset["timeframe"],
                filename=dataset.get("filename"),
                root=dataset.get("root", "data/raw"),
                source=dataset.get("source", "generic"),
            )

    quality = validate_ohlcv(data, expected_freq=dataset.get("expected_freq"))
    if not quality.ok:
        print(f"[quality] warning: {quality}")

    strategy = build_strategy(cfg)
    # Asset/broker labels travel in the config so the report's "Custos & Ativo"
    # panel can show them (the engine ignores unknown config keys).
    asset_meta = {
        "strategy_name": strategy.name,
        "symbol": dataset.get("symbol"),
        "timeframe": dataset.get("timeframe"),
        "broker": dataset.get("broker") or dataset.get("source"),
    }
    result = run_strategy_backtest(
        data=data,
        strategy=strategy,
        config=engine | asset_meta,
        ticks=ticks,
        output_dir=output_dir,
    )

    trades = result["trades"]
    print(f"Trades: {0 if trades is None else len(trades)}")
    if "report" in result:
        print("Report:")
        for key, value in result["report"].items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
