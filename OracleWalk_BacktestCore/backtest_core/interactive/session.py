"""Orchestrates one interactive replay session: data + engine + zones + report.

Holds the single source of truth for a replay. The HTTP layer (routes.py) is a
thin shell over this; everything testable lives here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..analytics.advanced import benchmark_block, build_full_metrics, monte_carlo_block
from ..analytics.metrics import compute_metrics
from ..analytics.zone_edge import build_zone_analytics
from ..cli import load_config
from ..data import load_market_csv, load_mt5_csv, load_ohlcv_csv, market_data_path
from ..report import generate_report_bundle
from .engine import InteractiveBacktester
from .strategy_base import InteractiveStrategyBase
from .strategies import FVGStrategy, SRQuantStrategy
from .stub import ZoneTouchStub
from .zones import ZoneStore


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_ROOT = PROJECT_ROOT / "reports"
DATA_RAW = PROJECT_ROOT / "data" / "raw"

# Per-instrument engine params (the ones that actually change PnL/sizing).
# Picking a symbol applies the right point/contract_size so a gold backtest
# isn't sized like a forex one. Extend as more instruments get data.
INSTRUMENT_SPECS: dict[str, dict[str, Any]] = {
    "EURUSD": {"point": 0.00001, "contract_size": 100000.0, "commission_per_lot": 3.5, "leverage": 30.0},
    "XAUUSD": {"point": 0.01, "contract_size": 100.0, "commission_per_lot": 0.0, "leverage": 100.0},
}

# Sane defaults so a session created from the UI selector (symbol/timeframe, no
# config file) can actually open trades. Without leverage the required margin
# (notional × 1) dwarfs the equity and every entry is silently rejected.
DEFAULT_INITIAL_CAPITAL = 10000.0
DEFAULT_LEVERAGE = 30.0


# Timeframe ladder. In a backtest we can only resample the base data UP (coarser),
# never down. So a session derives every TF coarser than its base — that's exactly
# what the zone-driven logic needs: a zone may live on any TF >= base, and its
# exhaustion is read there. (The trigger/SMA TF is one step BELOW the zone TF; it
# only exists when it's still >= base — see GATILHO in the strategy.)
TF_RESAMPLE_RULES: dict[str, str] = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
}
TF_ORDER: list[str] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


def coarser_tfs(base_tf: str) -> dict[str, str]:
    """Every standard timeframe coarser than `base_tf` (name -> resample rule)."""
    base = str(base_tf or "").upper()
    if base not in TF_ORDER:
        return {}
    return {tf: TF_RESAMPLE_RULES[tf] for tf in TF_ORDER[TF_ORDER.index(base) + 1 :]}


def _sort_tfs(timeframes: list[str] | tuple[str, ...]) -> list[str]:
    values = {str(tf or "").upper() for tf in timeframes if tf}
    return sorted(values, key=lambda tf: TF_ORDER.index(tf) if tf in TF_ORDER else 999)


def list_interactive_datasets() -> list[dict[str, Any]]:
    """Available symbol/timeframe CSVs under data/raw (for the UI selector)."""
    out: list[dict[str, Any]] = []
    if not DATA_RAW.exists():
        return out
    for sym_dir in sorted(p for p in DATA_RAW.iterdir() if p.is_dir()):
        for tf_dir in sorted(p for p in sym_dir.iterdir() if p.is_dir()):
            csvs = sorted(tf_dir.glob("*.csv"))
            if not csvs:
                continue
            out.append(
                {
                    "symbol": sym_dir.name,
                    "timeframe": tf_dir.name,
                    "path": str(csvs[0].relative_to(PROJECT_ROOT)),
                }
            )
    return out


def _dataset_for(symbol: str, timeframe: str) -> dict[str, Any] | None:
    sym = str(symbol).upper()
    tf = str(timeframe).upper()
    for ds in list_interactive_datasets():
        if ds["symbol"].upper() == sym and ds["timeframe"].upper() == tf:
            return {"symbol": ds["symbol"], "timeframe": ds["timeframe"], "path": ds["path"], "source": "mt5"}
    return None


class InteractiveSession:
    def __init__(
        self,
        data: pd.DataFrame,
        strategy: InteractiveStrategyBase,
        config: dict[str, Any],
        symbol: str = "SESSION",
        timeframe: str = "TF",
        output_dir: str | Path | None = None,
        session_id: str = "s1",
        higher_timeframes: dict[str, str] | None = None,
        display_timeframe: str | None = None,
        zone_timeframes: list[str] | None = None,
        timeframe_data: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        self.base_tf = str(timeframe or "").upper()
        self.higher_tfs = {k.upper(): v for k, v in (higher_timeframes or {}).items()}
        self.display_tf = str(display_timeframe or timeframe or "").upper()
        self.zone_tfs = _sort_tfs(zone_timeframes or ([self.base_tf] + list(self.higher_tfs.keys())))
        self.engine = InteractiveBacktester(
            data,
            strategy,
            config,
            base_timeframe=self.base_tf,
            higher_timeframes=self.higher_tfs,
            timeframe_data=timeframe_data,
        )
        self.zones = ZoneStore()
        self.config = dict(config)
        self.symbol = symbol
        self.timeframe = timeframe
        self.session_id = session_id
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path(output_dir) if output_dir else REPORTS_ROOT / f"interactive_{symbol}_{timeframe}_{stamp}"
        self.engine.start()

    # --------------------------------------------------------------- factory
    @classmethod
    def from_config(
        cls,
        config_path: str | None,
        strategy: str = "sr_quant",
        mode: str = "SEM",
        symbol: str | None = None,
        timeframe: str | None = None,
        session_id: str = "s1",
        engine: dict[str, Any] | None = None,
    ) -> "InteractiveSession":
        cfg = load_config(config_path) if config_path else {}
        dataset = dict(cfg.get("dataset", {}))
        engine_cfg = dict(cfg.get("engine", {}))

        # Symbol selector (UI). The selected timeframe is the replay BASE. This
        # keeps "EURUSD + D1" honest as a daily backtest instead of silently using
        # a finer CSV underneath. Coarser TFs are still derived from that base when
        # available in the standard ladder.
        display_tf = None
        zone_tfs = None
        external_tf_data: dict[str, pd.DataFrame] = {}
        if symbol:
            available = [d for d in list_interactive_datasets() if d["symbol"].upper() == str(symbol).upper()]
            if not available:
                raise ValueError(f"no dataset for {symbol} under data/raw")
            wanted_tf = str(timeframe or "").upper()
            base_ds = next((d for d in available if d["timeframe"].upper() == wanted_tf), None)
            if base_ds is None:
                available.sort(key=lambda d: TF_ORDER.index(d["timeframe"].upper()) if d["timeframe"].upper() in TF_ORDER else 99)
                base_ds = available[0]
            dataset = {"symbol": symbol, "timeframe": base_ds["timeframe"], "path": base_ds["path"], "source": "mt5"}
            display_tf = str(base_ds["timeframe"]).upper()
            spec = INSTRUMENT_SPECS.get(str(symbol).upper())
            if spec:
                engine_cfg.update(spec)
            zone_tfs = _sort_tfs([d["timeframe"] for d in available])

        data = _load_dataset(dataset)
        if symbol:
            for ds in available:
                tf_name = str(ds["timeframe"]).upper()
                if tf_name == str(dataset.get("timeframe", "")).upper():
                    continue
                external_tf_data[tf_name] = _load_dataset({"path": ds["path"], "source": "mt5"})

        # User-supplied engine params (from the setup window) win over the config
        # file and the instrument spec — but a None/blank field means "leave default".
        if engine:
            for key, value in engine.items():
                if value is not None and value != "":
                    engine_cfg[key] = value

        strat = _build_strategy(strategy, mode)
        # Let the strategy declare the engine settings it expects (risk %, single
        # vs multi position) without overriding anything the config/user set on purpose.
        overrides = strat.engine_overrides() if hasattr(strat, "engine_overrides") else {}
        for key, value in overrides.items():
            engine_cfg.setdefault(key, value)

        # Sane account defaults so margin never silently blocks entries when the
        # session comes from the UI selector (no config file with leverage/capital).
        engine_cfg.setdefault("initial_capital", DEFAULT_INITIAL_CAPITAL)
        engine_cfg.setdefault("leverage", DEFAULT_LEVERAGE)

        sym = symbol or dataset.get("symbol", "SESSION")
        tf = dataset.get("timeframe", "TF") if symbol else (timeframe or dataset.get("timeframe", "TF"))
        higher = coarser_tfs(tf)
        return cls(
            data=data,
            strategy=strat,
            config=engine_cfg | {"strategy_name": strat.name},
            symbol=sym,
            timeframe=tf,
            session_id=session_id,
            higher_timeframes=higher,
            display_timeframe=display_tf or tf,
            zone_timeframes=zone_tfs,
            timeframe_data=external_tf_data,
        )

    # --------------------------------------------------------------- replay
    def history(self) -> list[dict[str, Any]]:
        return [self.engine.bar_dict(i) for i in range(self.engine.cursor + 1)]

    def step(self, n: int = 1) -> dict[str, Any]:
        new_bars: list[dict[str, Any]] = []
        closed: list[dict[str, Any]] = []
        for _ in range(max(1, int(n))):
            advanced, closed_now = self.engine.step_one(self.zones)
            if not advanced:
                break
            new_bars.append(self.engine.bar_dict(self.engine.cursor))
            closed.extend(closed_now)
        return self.snapshot(new_bars=new_bars, closed=closed)

    def reset(self) -> dict[str, Any]:
        """Rewind the engine to warmup while preserving the causal zone log."""
        self.engine.reset()
        info = self.session_info()
        info["reset"] = True
        return info

    def seek(self, target_bar: int) -> dict[str, Any]:
        """Jump the replay to an absolute bar (for a draggable timeline/scrubber).

        Forward = just step. Backward = reset then replay (deterministic, since the
        zone mutation log is causal). Returns the snapshot at the target.
        """
        target = max(self.engine.warmup - 1, min(int(target_bar), self.engine.n - 1))
        if target < self.engine.cursor:
            self.engine.reset()
        while self.engine.cursor < target:
            advanced, _ = self.engine.step_one(self.zones)
            if not advanced:
                break
        return self.snapshot()

    def series(self, tf: str | None = None) -> dict[str, Any]:
        """OHLCV + indicator arrays up to the cursor (for sub-panes / TF switch)."""
        return self.engine.series_at(self.engine.cursor, tf)

    def snapshot(self, new_bars: list | None = None, closed: list | None = None) -> dict[str, Any]:
        idx = self.engine.cursor
        return {
            "session_id": self.session_id,
            "cursor": idx,
            "total_bars": self.engine.n,
            "done": idx >= self.engine.n - 1,
            "bars": new_bars if new_bars is not None else [],
            "indicators": self.engine.indicators_at(idx) if idx >= 0 else {},
            "indicator_thresholds": self.indicator_thresholds(),
            "equity": self.engine.equity(),
            "balance": self.engine.capital,
            "open_trades": self.engine.open_trades_public(),
            "closed_now": [self.engine.trade_public(t) for t in (closed or [])],
            "zones": self._zones_at(idx),
            "tf_indicators": self.engine.tf_indicators_at(idx) if idx >= 0 else {},
            # Live analytics for the replay HUD (sparkline + risk/DD gauges).
            "equity_point": self.engine.equity_point(),
            "hud": self.engine.hud(),
        }

    def _zones_at(self, idx: int) -> list[dict[str, Any]]:
        """User-drawn zones plus any auto rectangles the strategy exposes (e.g. the
        FVG strategy's live gap boxes), so the existing overlay renders both."""
        zones = list(self.zones.active_zones(idx))
        strat = self.engine.strategy
        if idx >= 0 and hasattr(strat, "boxes_at"):
            zones.extend(strat.boxes_at(idx))
        return zones

    def session_info(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_bars": self.engine.n,
            "warmup_bars": self.engine.warmup,
            "cursor": self.engine.cursor,
            "base_timeframe": self.base_tf,
            "display_timeframe": self.display_tf or self.base_tf,
            "zone_timeframes": self.zone_tfs,
            "indicators": self.engine.indicators_at(self.engine.cursor) if self.engine.cursor >= 0 else {},
            "tf_indicators": self.engine.tf_indicators_at(self.engine.cursor) if self.engine.cursor >= 0 else {},
            "indicator_thresholds": self.indicator_thresholds(),
            "indicators_meta": self.indicators_meta(),
            "history": self.history(),
            "zones": self._zones_at(self.engine.cursor),
            "balance": self.engine.capital,
            "equity": self.engine.equity(),
            "open_trades": self.engine.open_trades_public(),
            "done": self.engine.cursor >= self.engine.n - 1,
        }

    def indicator_thresholds(self) -> dict[str, dict[str, float]]:
        if hasattr(self.engine.strategy, "indicator_thresholds"):
            return self.engine.strategy.indicator_thresholds()
        return {}

    def indicators_meta(self) -> dict[str, Any]:
        """Tell the UI which indicators are price overlays vs oscillator sub-panes."""
        cols = list(getattr(self.engine.strategy, "indicator_columns", []) or [])
        thresholds = self.indicator_thresholds()
        overlays: list[str] = []
        panes: list[dict[str, Any]] = []
        for col in cols:
            if col in thresholds:
                panes.append({"key": col, "range": [0, 100], **thresholds[col]})
            else:
                overlays.append(col)
        return {"overlays": overlays, "panes": panes}

    # ---------------------------------------------------------------- zones
    def add_zone(self, price_low: float, price_high: float, side: str, timeframe: str = "") -> dict[str, Any]:
        tf = (timeframe or self.base_tf).upper()
        zid = self.zones.create(self.engine.cursor, price_low, price_high, side, timeframe=tf)
        return self.zones.get(zid, self.engine.cursor) or {"id": zid, "state": "active"}

    def update_zone(self, zid: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.zones.update(zid, self.engine.cursor, fields)
        return self.zones.get(zid, self.engine.cursor) or {"id": zid, "state": "deleted"}

    def delete_zone(self, zid: str) -> dict[str, Any]:
        self.zones.delete(zid, self.engine.cursor)
        return {"id": zid, "state": "deleted"}

    def active_zones(self) -> list[dict[str, Any]]:
        return self.zones.active_zones(self.engine.cursor)

    # --------------------------------------------------------------- report
    def finish(self) -> dict[str, Any]:
        trades = self.engine.finish()
        initial_capital = float(self.config.get("initial_capital", 1000.0) or 1000.0)
        n_bars = self.engine.cursor + 1
        data = self.engine.data.iloc[: self.engine.cursor + 1].copy()
        contract_size = float(self.config.get("contract_size", 100_000.0) or 100_000.0)
        point = float(self.config.get("point", 0.00001) or 0.00001)

        # Pillar 1 — institutional metric suite + robustness + benchmark (works
        # even with zero trades; the sections just come back empty/None).
        metrics_full = build_full_metrics(trades, initial_capital, n_bars=n_bars)
        monte_carlo = monte_carlo_block(trades, initial_capital)
        benchmark = benchmark_block(trades, data, initial_capital, contract_size=contract_size, point=point)
        # Pillar 2 — which zones actually had edge (the product's differentiator).
        zone_analytics = build_zone_analytics(
            trades, self.zones, self.engine.data, n_bars, mode=getattr(self.engine.strategy, "mode", None)
        )

        if trades is None or trades.empty:
            return {
                "report_dir": None,
                "report_html": None,
                "metrics": {"trades": 0},
                "metrics_full": metrics_full,
                "zone_analytics": zone_analytics,
                "benchmark": benchmark,
                "monte_carlo": monte_carlo,
                "images": [],
            }

        title = f"{self.config.get('strategy_name', 'Interactive')} Report"
        paths = generate_report_bundle(
            data=data,
            trades=trades,
            config={**self.config, "initial_capital": initial_capital},
            output_dir=self.output_dir,
            title=title,
            zone_analytics=zone_analytics,
        )
        metrics = compute_metrics(trades, initial_capital)
        return {
            "report_dir": str(self.output_dir),
            "report_html": _report_url(paths.get("html")),
            "metrics": _slim_metrics(metrics, len(trades)),
            # Sectioned full metrics + PNG chart URLs (grouped) so the UI can render
            # the report INLINE as institutional-grade panels.
            "metrics_full": metrics_full,
            "zone_analytics": zone_analytics,
            "benchmark": benchmark,
            "monte_carlo": monte_carlo,
            "images": _report_images(self.output_dir),
        }


def _build_strategy(name: str, mode: str) -> InteractiveStrategyBase:
    key = str(name or "sr_quant").strip().lower()
    if key in ("sr_quant", "srquant", "sr", "s&r"):
        return SRQuantStrategy(mode=mode)
    if key in ("fvg", "gap", "imbalance"):
        return FVGStrategy()
    if key == "stub":
        return ZoneTouchStub()
    raise ValueError(f"unknown interactive strategy '{name}' (use 'sr_quant', 'fvg' or 'stub')")


def _load_dataset(dataset: dict[str, Any]) -> pd.DataFrame:
    if not dataset:
        raise ValueError("config has no 'dataset' block")
    if "path" in dataset:
        path = Path(dataset["path"])
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"dataset CSV not found: {path}")
        return load_mt5_csv(path) if dataset.get("source") == "mt5" else load_ohlcv_csv(path)
    return load_market_csv(
        symbol=dataset["symbol"],
        timeframe=dataset["timeframe"],
        filename=dataset.get("filename"),
        root=dataset.get("root", "data/raw"),
        source=dataset.get("source", "generic"),
    )


# Friendly labels + display order for the PNG charts the report bundle emits.
# Mirrors backtest_core/ui/server.py REPORT_LABELS so the inline report shows the
# same set the classic dashboard does.
_REPORT_IMAGE_LABELS: dict[str, str] = {
    "equity_total.png": "Equity total",
    "drawdown_curve.png": "Drawdown",
    "underwater.png": "Underwater (DD %)",
    "rolling_sharpe.png": "Rolling Sharpe",
    "strategy_vs_buyhold.png": "Estrategia x Buy & Hold",
    "drawdown_monthly.png": "Drawdown mensal",
    "zsharp.png": "Z-Sharp (Z-Score do close)",
    "monthly_profit.png": "Lucro mensal",
    "monthly_returns_table.png": "Retornos mensais (calendario)",
    "yearly_profit.png": "Lucro anual",
    "profit_factor_month.png": "Profit Factor por mes",
    "heatmap.png": "Heatmap (hora x dia)",
    "boxplot_hour.png": "Boxplot por hora",
    "boxplot_weekday.png": "Boxplot por dia da semana",
    "histograms.png": "Histogramas (PnL, R, duracao)",
    "returns_qq.png": "QQ-plot (PnL x normal)",
    "r_multiples.png": "R-multiples",
    "scatter.png": "Scatter (MFE/MAE/duracao x PnL)",
    "best_worst.png": "Melhores x piores trades",
    "zone_edge.png": "Edge por zona",
    "zone_respect.png": "Respeito por zona",
    "atr_volume_price.png": "ATR / Volume / Preco",
    "volatility_vs_pnl.png": "Volatilidade x PnL",
    "monte_carlo_shuffle.png": "Monte Carlo - Shuffle",
    "monte_carlo_bootstrap.png": "Monte Carlo - Bootstrap",
    "monte_carlo_block_bootstrap.png": "Monte Carlo - Block Bootstrap",
    "monte_carlo_fan.png": "Monte Carlo - Fan (P05-P95)",
    "monte_carlo_distribution.png": "Monte Carlo - Distribuicao",
}

# Section each PNG belongs to, so the inline dashboard can tab/group them.
_REPORT_IMAGE_GROUPS: dict[str, str] = {
    "equity_total.png": "equity", "drawdown_curve.png": "equity", "underwater.png": "equity",
    "rolling_sharpe.png": "equity", "strategy_vs_buyhold.png": "equity",
    "drawdown_monthly.png": "risk",
    "histograms.png": "distribution", "returns_qq.png": "distribution",
    "r_multiples.png": "distribution", "scatter.png": "distribution", "best_worst.png": "distribution",
    "monthly_profit.png": "calendar", "monthly_returns_table.png": "calendar",
    "profit_factor_month.png": "calendar", "yearly_profit.png": "calendar",
    "heatmap.png": "calendar", "boxplot_hour.png": "calendar", "boxplot_weekday.png": "calendar",
    "monte_carlo_shuffle.png": "montecarlo", "monte_carlo_bootstrap.png": "montecarlo",
    "monte_carlo_block_bootstrap.png": "montecarlo", "monte_carlo_fan.png": "montecarlo",
    "monte_carlo_distribution.png": "montecarlo",
    "zone_edge.png": "zones", "zone_respect.png": "zones",
    "zsharp.png": "market", "atr_volume_price.png": "market", "volatility_vs_pnl.png": "market",
}


def _report_images(output_dir: str | Path) -> list[dict[str, Any]]:
    """List the report's PNG charts as {name,title,url} for inline rendering."""
    out: list[dict[str, Any]] = []
    target = Path(output_dir)
    try:
        rel = target.resolve().relative_to(REPORTS_ROOT.resolve())
    except ValueError:
        return out
    prefix = "/reports/" + str(rel).replace("\\", "/")
    seen: set[str] = set()
    for name, title in _REPORT_IMAGE_LABELS.items():
        if (target / name).exists():
            seen.add(name)
            out.append({"name": name, "title": title, "url": f"{prefix}/{name}",
                        "group": _REPORT_IMAGE_GROUPS.get(name, "market")})
    for path in sorted(target.glob("*.png")):
        if path.name in seen:
            continue
        out.append({"name": path.name, "title": path.stem.replace("_", " ").title(),
                    "url": f"{prefix}/{path.name}", "group": _REPORT_IMAGE_GROUPS.get(path.name, "market")})
    return out


def _report_url(html_path: str | None) -> str | None:
    if not html_path:
        return None
    try:
        rel = Path(html_path).resolve().relative_to(REPORTS_ROOT.resolve())
    except ValueError:
        return None
    return "/reports/" + str(rel).replace("\\", "/")


def _slim_metrics(metrics: dict[str, Any], trade_count: int) -> dict[str, Any]:
    keys = ("net_profit", "profit_factor", "max_drawdown", "win_rate", "expectancy", "sharpe")
    out = {k: metrics[k] for k in keys if k in metrics}
    out["trades"] = trade_count
    return out
