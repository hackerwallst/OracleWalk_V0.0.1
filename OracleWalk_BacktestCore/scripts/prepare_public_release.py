from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT.parent.parent / "BacktesterCore_Public"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".claude",
    "__pycache__",
    "backtest_core.egg-info",
    "backups",
    "reports",
    "strategy_source_mql5",
    "validation_cases",
}

EXCLUDED_FILES = {
    ".DS_Store",
    "CLAUDE_HANDOFF.md",
    "CODEX_HANDOFF.md",
    "Estrategia Retorno As Médias.md",
    "package.json",
    "install.bat",
    "install.command",
    "run_ui.bat",
    "run_ui.command",
}

EXCLUDED_PATHS = {
    Path("backtest_core/interactive"),
    Path("backtest_core/ui"),
    Path("backtest_core/strategies/fvg_imbalance.py"),
    Path("backtest_core/strategies/mean_reversion_m1.py"),
    Path("backtest_core/strategies/ml_rsi_zeiierman.py"),
    Path("backtest_core/strategies/local.py"),
    Path("configs"),
    Path("data/raw"),
    Path("data/processed"),
    Path("data/broker_exports"),
    Path("data/samples"),
    Path("docs/mt5_validation.md"),
    Path("examples/run_optimization_demo.py"),
    Path("examples/run_risk_demo.py"),
    Path("scripts/prepare_public_release.py"),
    Path("tests/interactive"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a clean public backtester-only release.")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="Destination folder.")
    parser.add_argument("--project-name", default="backtester-core", help="Public Python package name.")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    copy_tree(ROOT, target)
    write_public_files(target, args.project_name)
    print(f"Public release ready: {target}")


def copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if should_exclude(rel, path):
            continue
        dest = target / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)


def should_exclude(rel: Path, path: Path) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDED_DIRS:
        return True
    if path.name in EXCLUDED_FILES:
        return True
    return any(rel == item or rel.is_relative_to(item) for item in EXCLUDED_PATHS)


def write_public_files(target: Path, project_name: str) -> None:
    write_readme(target, project_name)
    write_gitignore(target)
    write_demo_config(target)
    write_sample_data(target)
    patch_pyproject(target, project_name)


def write_readme(target: Path, project_name: str) -> None:
    (target / "README.md").write_text(
        f"""# {project_name}

Backtester-only Python core extracted from a private research workspace.

This public package includes:

- OHLCV and MT5 data loading;
- candle and tick-aware execution;
- costs, spread, slippage, swaps, margin and leverage settings;
- report generation and analytics;
- plug-in strategy registration;
- native indicators plus an optional large indicator pack.

The interactive replay UI, private strategies, research logs, broker exports and generated reports are intentionally not included.

## Install

```bash
python -m pip install -e .
```

Optional large indicator catalog:

```bash
python -m pip install -e ".[indicators]"
```

## Run Demo

```bash
python -m backtest_core.cli --config configs/demo.json
```

## Strategy Plug-ins

See `docs/strategies.md`.

## Indicators

See `docs/indicators.md`.
""",
        encoding="utf-8",
    )


def write_gitignore(target: Path) -> None:
    (target / ".gitignore").write_text(
        """.venv/
__pycache__/
*.pyc
.DS_Store
reports/*
!reports/.gitkeep
data/raw/*
!data/raw/.gitkeep
data/processed/*
!data/processed/.gitkeep
data/broker_exports/*
!data/broker_exports/.gitkeep
""",
        encoding="utf-8",
    )
    for keep in ("reports/.gitkeep", "data/raw/.gitkeep", "data/processed/.gitkeep", "data/broker_exports/.gitkeep"):
        path = target / keep
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def write_demo_config(target: Path) -> None:
    config = {
        "dataset": {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "path": "data/samples/EURUSD_M15_sample.csv",
            "source": "generic",
            "expected_freq": "15min",
        },
        "strategy": {
            "name": "ema_cross",
            "params": {
                "fast": 12,
                "slow": 36,
                "atr_period": 14,
                "stop_atr": 1.5,
                "take_atr": 3.0,
            },
        },
        "engine": {
            "initial_capital": 1000.0,
            "risk_per_trade_pct": 1.0,
            "commission_perc": 0.0,
            "commission_per_lot": 0.0,
            "contract_size": 100000.0,
            "leverage": 30.0,
            "use_spread": False,
            "slippage": 0.0,
            "single_position_mode": True,
            "close_on_signal": "opposite",
        },
        "output_dir": "reports/EURUSD_M15_ema_cross",
    }
    configs = target / "configs"
    configs.mkdir(exist_ok=True)
    for path in configs.glob("*.json"):
        path.unlink()
    (configs / "demo.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (configs / ".gitkeep").touch()


def write_sample_data(target: Path) -> None:
    samples = target / "data" / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    rows = ["datetime,open,high,low,close,volume"]
    price = 1.0800
    for i in range(240):
        day = 1 + i // 96
        hour = (i % 96) // 4
        minute = (i % 4) * 15
        drift = ((i % 24) - 12) * 0.00003
        open_ = price
        close = price + drift
        high = max(open_, close) + 0.00035
        low = min(open_, close) - 0.00035
        volume = 100 + (i % 30) * 7
        rows.append(f"2024-01-{day:02d} {hour:02d}:{minute:02d}:00,{open_:.5f},{high:.5f},{low:.5f},{close:.5f},{volume}")
        price = close
    (samples / "EURUSD_M15_sample.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (samples / ".gitkeep").touch()


def patch_pyproject(target: Path, project_name: str) -> None:
    pyproject = target / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    text = text.replace('name = "backtest-core"', f'name = "{project_name}"')
    text = text.replace(
        "Slim backtest engine and report exporter extracted from OracleWalk research.",
        "Backtester-only Python core with reports, analytics, costs and plug-in strategies.",
    )
    pyproject.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
