from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


MONTE_CARLO_MODES = (
    "shuffle",
    "bootstrap",
    "block_bootstrap",
    "execution_stress",
)


@dataclass(frozen=True)
class MonteCarloStats:
    mode: str
    final_balance_mean: float
    final_balance_p05: float
    final_balance_p50: float
    final_balance_p95: float
    max_drawdown_mean: float
    max_drawdown_p05: float
    max_drawdown_p95: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "mode": self.mode,
            "final_balance_mean": self.final_balance_mean,
            "final_balance_p05": self.final_balance_p05,
            "final_balance_p50": self.final_balance_p50,
            "final_balance_p95": self.final_balance_p95,
            "max_drawdown_mean": self.max_drawdown_mean,
            "max_drawdown_p05": self.max_drawdown_p05,
            "max_drawdown_p95": self.max_drawdown_p95,
        }


def monte_carlo_equity(
    trades: pd.DataFrame,
    initial_capital: float,
    n_sims: int = 1000,
    mode: str = "shuffle",
    *,
    seed: int | None = None,
    block_size: int = 5,
) -> np.ndarray:
    pnl = _trade_pnl(trades)
    if pnl.size == 0 or n_sims <= 0:
        return np.empty((0, 0), dtype=float)

    rng = np.random.default_rng(seed)
    sims = np.empty((n_sims, pnl.size), dtype=float)
    for idx in range(n_sims):
        sample = _sample_pnl(
            pnl,
            mode=mode,
            rng=rng,
            block_size=block_size,
        )
        sims[idx] = float(initial_capital) + np.cumsum(sample)
    return sims


def monte_carlo_summary(
    trades: pd.DataFrame,
    initial_capital: float,
    n_sims: int = 1000,
    mode: str = "bootstrap",
    *,
    seed: int | None = None,
    block_size: int = 5,
) -> dict:
    sims = monte_carlo_equity(
        trades,
        initial_capital,
        n_sims=n_sims,
        mode=mode,
        seed=seed,
        block_size=block_size,
    )
    if sims.size == 0:
        return MonteCarloStats(
            mode=mode,
            final_balance_mean=float(initial_capital),
            final_balance_p05=float(initial_capital),
            final_balance_p50=float(initial_capital),
            final_balance_p95=float(initial_capital),
            max_drawdown_mean=0.0,
            max_drawdown_p05=0.0,
            max_drawdown_p95=0.0,
        ).to_dict()

    return _summary_from_sims(sims, mode).to_dict()


def monte_carlo_suite_summary(
    trades: pd.DataFrame,
    initial_capital: float,
    n_sims: int = 1000,
    *,
    seed: int | None = None,
    block_size: int = 5,
    modes: tuple[str, ...] = MONTE_CARLO_MODES,
) -> dict[str, dict]:
    return {
        mode: monte_carlo_summary(
            trades,
            initial_capital,
            n_sims=n_sims,
            mode=mode,
            seed=seed,
            block_size=block_size,
        )
        for mode in modes
    }


def _trade_pnl(trades: pd.DataFrame) -> np.ndarray:
    if trades is None or trades.empty or "pnl" not in trades.columns:
        return np.empty(0, dtype=float)
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").dropna().to_numpy(dtype=float)
    return pnl


def _sample_pnl(
    pnl: np.ndarray,
    *,
    mode: str,
    rng: np.random.Generator,
    block_size: int,
) -> np.ndarray:
    if mode == "shuffle":
        return rng.permutation(pnl)
    if mode == "bootstrap":
        return rng.choice(pnl, size=pnl.size, replace=True)
    if mode == "block_bootstrap":
        return _block_bootstrap_sample(pnl, rng=rng, block_size=block_size)
    if mode == "execution_stress":
        return _execution_stress_sample(pnl, rng=rng)
    raise ValueError(f"Unsupported Monte Carlo mode: {mode}")


def _block_bootstrap_sample(
    pnl: np.ndarray,
    *,
    rng: np.random.Generator,
    block_size: int,
) -> np.ndarray:
    block = max(1, min(int(block_size or 1), pnl.size))
    chunks: list[np.ndarray] = []
    while sum(len(chunk) for chunk in chunks) < pnl.size:
        start = int(rng.integers(0, pnl.size))
        end = start + block
        if end <= pnl.size:
            chunk = pnl[start:end]
        else:
            chunk = np.concatenate((pnl[start:], pnl[: end - pnl.size]))
        chunks.append(chunk)
    return np.concatenate(chunks)[: pnl.size]


def _execution_stress_sample(
    pnl: np.ndarray,
    *,
    rng: np.random.Generator,
) -> np.ndarray:
    base = rng.permutation(pnl).astype(float, copy=True)
    abs_base = np.abs(base)
    median_abs = float(np.median(abs_base[abs_base > 0])) if np.any(abs_base > 0) else 1.0
    sigma = float(np.std(base)) if base.size > 1 else median_abs
    random_noise = rng.normal(0.0, max(sigma, median_abs) * 0.08, size=base.size)
    extra_cost = rng.uniform(0.0, median_abs * 0.06, size=base.size) + abs_base * rng.uniform(0.0, 0.03, size=base.size)
    return base + random_noise - extra_cost


def _summary_from_sims(sims: np.ndarray, mode: str) -> MonteCarloStats:
    final_balance = sims[:, -1]
    max_drawdowns = np.array([_max_drawdown(equity) for equity in sims], dtype=float)
    return MonteCarloStats(
        mode=mode,
        final_balance_mean=float(final_balance.mean()),
        final_balance_p05=float(np.percentile(final_balance, 5)),
        final_balance_p50=float(np.percentile(final_balance, 50)),
        final_balance_p95=float(np.percentile(final_balance, 95)),
        max_drawdown_mean=float(max_drawdowns.mean()),
        max_drawdown_p05=float(np.percentile(max_drawdowns, 5)),
        max_drawdown_p95=float(np.percentile(max_drawdowns, 95)),
    )


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float((equity - peak).min())
