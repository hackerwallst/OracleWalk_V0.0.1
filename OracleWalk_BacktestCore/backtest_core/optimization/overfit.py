"""Overfitting diagnostics: PBO (CSCV) and the Deflated/Probabilistic Sharpe.

References:
  Bailey, Borwein, Lopez de Prado, Zhu — "The Probability of Backtest
  Overfitting" (CSCV) and "The Deflated Sharpe Ratio".

These read a per-config bucketed returns matrix (from search.optimize) or a
single returns series. They never touch the engine.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

EULER_MASCHERONI = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# --- Probabilistic / Deflated Sharpe -----------------------------------------

def probabilistic_sharpe_ratio(
    observed_sr: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    benchmark_sr: float = 0.0,
) -> float:
    """PSR: probability the true Sharpe exceeds `benchmark_sr`, given non-normality.

    observed_sr / benchmark_sr are per-observation (not annualised).
    """
    if n_obs < 2:
        return float("nan")
    denom = 1.0 - skew * observed_sr + (kurtosis - 1.0) / 4.0 * observed_sr ** 2
    if denom <= 0:
        return float("nan")
    z = (observed_sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return float(_norm_cdf(z))


def deflated_sharpe_ratio(
    observed_sr: float,
    n_obs: int,
    n_trials: int,
    sr_variance: float,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> dict:
    """DSR: PSR using an expected-maximum benchmark from `n_trials` independent trials.

    sr_variance = variance of the trial Sharpe ratios (per-observation scale).
    Returns dict with the deflated benchmark and the DSR probability.
    """
    if n_trials < 1 or sr_variance <= 0:
        return {"expected_max_sr": float("nan"), "dsr": float("nan")}
    sigma = math.sqrt(sr_variance)
    # Expected maximum of n_trials draws (Gumbel approximation).
    z1 = _norm_ppf(1.0 - 1.0 / n_trials)
    z2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    expected_max_sr = sigma * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)
    dsr = probabilistic_sharpe_ratio(observed_sr, n_obs, skew, kurtosis, benchmark_sr=expected_max_sr)
    return {"expected_max_sr": float(expected_max_sr), "dsr": float(dsr)}


def deflated_sharpe_from_matrix(returns_matrix: pd.DataFrame, best_config_id: str | None = None) -> dict:
    """Convenience: compute the DSR for the best column of a returns matrix.

    The number of trials = number of configs; sr_variance = variance across the
    configs' Sharpe ratios. Skew/kurtosis taken from the chosen config's returns.
    """
    if returns_matrix is None or returns_matrix.shape[1] == 0:
        return {"expected_max_sr": float("nan"), "dsr": float("nan"), "observed_sr": float("nan")}
    srs = {}
    for col in returns_matrix.columns:
        r = returns_matrix[col].to_numpy(dtype=float)
        sd = r.std(ddof=1)
        srs[col] = (r.mean() / sd) if sd > 0 and len(r) > 1 else 0.0
    sr_series = pd.Series(srs)
    if best_config_id is None:
        best_config_id = sr_series.idxmax()
    r_best = returns_matrix[best_config_id].to_numpy(dtype=float)
    observed_sr = sr_series[best_config_id]
    sk = float(pd.Series(r_best).skew())
    ku = float(pd.Series(r_best).kurtosis()) + 3.0  # pandas returns excess kurtosis
    out = deflated_sharpe_ratio(
        observed_sr=observed_sr,
        n_obs=len(r_best),
        n_trials=returns_matrix.shape[1],
        sr_variance=float(sr_series.var(ddof=1)) if returns_matrix.shape[1] > 1 else 0.0,
        skew=sk,
        kurtosis=ku,
    )
    out["observed_sr"] = float(observed_sr)
    out["best_config_id"] = best_config_id
    return out


# --- PBO via CSCV ------------------------------------------------------------

def _sharpe_from_stats(sum_, sumsq, n):
    if n < 2:
        return np.zeros(sum_.shape[-1])
    mean = sum_ / n
    var = (sumsq - n * mean ** 2) / (n - 1)
    var = np.where(var <= 0, np.nan, var)
    sr = mean / np.sqrt(var)
    return np.nan_to_num(sr, nan=-np.inf)


def probability_of_backtest_overfitting(returns_matrix: pd.DataFrame, n_splits: int = 16) -> dict:
    """PBO via Combinatorially Symmetric Cross-Validation.

    returns_matrix: rows = time buckets, cols = configs, values = bucketed PnL/returns.
    n_splits (S): even number of disjoint time slices.

    Returns dict with pbo, the logit distribution, and counts.
    """
    M = returns_matrix.to_numpy(dtype=float)
    T, N = M.shape
    if N < 2:
        return {"pbo": float("nan"), "n_combinations": 0, "logits": [], "note": "need >=2 configs"}
    if n_splits % 2 != 0:
        n_splits -= 1
    if n_splits < 2 or n_splits > T:
        n_splits = max(2, min(T - (T % 2), n_splits))
        if n_splits % 2 != 0:
            n_splits -= 1
    if n_splits < 2:
        return {"pbo": float("nan"), "n_combinations": 0, "logits": [], "note": "not enough buckets"}

    slice_size = T // n_splits
    usable = slice_size * n_splits
    Mu = M[:usable]
    slices = Mu.reshape(n_splits, slice_size, N)  # (S, slice_size, N)

    slice_sum = slices.sum(axis=1)               # (S, N)
    slice_sumsq = (slices ** 2).sum(axis=1)      # (S, N)
    slice_n = slice_size

    logits = []
    half = n_splits // 2
    for is_idx in itertools.combinations(range(n_splits), half):
        is_set = list(is_idx)
        oos_set = [s for s in range(n_splits) if s not in is_idx]

        is_sum = slice_sum[is_set].sum(axis=0)
        is_sumsq = slice_sumsq[is_set].sum(axis=0)
        oos_sum = slice_sum[oos_set].sum(axis=0)
        oos_sumsq = slice_sumsq[oos_set].sum(axis=0)
        n_is = slice_n * len(is_set)
        n_oos = slice_n * len(oos_set)

        sr_is = _sharpe_from_stats(is_sum, is_sumsq, n_is)
        sr_oos = _sharpe_from_stats(oos_sum, oos_sumsq, n_oos)

        n_star = int(np.argmax(sr_is))
        # Relative rank of the IS-best config in the OOS ranking (1 = worst, N = best).
        order = np.argsort(sr_oos)
        rank = int(np.where(order == n_star)[0][0]) + 1
        omega = rank / (N + 1.0)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))

    logits = np.array(logits, dtype=float)
    pbo = float(np.mean(logits <= 0.0)) if len(logits) else float("nan")
    return {
        "pbo": pbo,
        "n_combinations": int(len(logits)),
        "n_splits": int(n_splits),
        "n_configs": int(N),
        "logit_mean": float(np.mean(logits)) if len(logits) else float("nan"),
        "logits": logits.tolist(),
    }
