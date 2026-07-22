"""Stationary block bootstrap (Politis & Romano, 1994) for return series.

REPORT-ONLY (see the package docstring): the resampled distribution characterizes
uncertainty in the historical track record; it never alters a parameter.

The stationary bootstrap resamples with geometrically-distributed block lengths
(mean ``avg_block_len``, so restart probability ``p = 1/avg_block_len``) and
wrap-around indexing, preserving short-range serial dependence while keeping the
resample stationary. Every resample has the SAME length as the input and the run
is fully deterministic given ``seed`` (a local numpy Generator, no global state).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

_ANN = 252


class BootstrapReport(BaseModel):
    """Percentile summary of resampled cagr / sharpe / max-drawdown."""

    n_samples: int
    avg_block_len: int
    seed: int
    sample_length: int
    cagr_p5: float
    cagr_p50: float
    cagr_p95: float
    sharpe_p5: float
    sharpe_p50: float
    sharpe_p95: float
    max_drawdown_p5: float
    max_drawdown_p50: float
    max_drawdown_p95: float
    prob_negative_cagr: float
    prob_drawdown_worse_than_30pct: float


def _resample_indices(n: int, p: float, rng: np.random.Generator) -> np.ndarray:
    """One stationary-bootstrap index vector of length ``n`` (geometric blocks)."""
    pieces: list[np.ndarray] = []
    filled = 0
    while filled < n:
        start = int(rng.integers(0, n))
        length = int(rng.geometric(p))  # >= 1
        block = (start + np.arange(length)) % n
        pieces.append(block)
        filled += length
    return np.concatenate(pieces)[:n]


def _sample_metrics(
    returns: np.ndarray, periods_per_year: int = _ANN
) -> tuple[float, float, float]:
    """(cagr, sharpe, max_drawdown) for one resampled return path."""
    n = len(returns)
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    total_growth = float(equity[-1])
    cagr = total_growth ** (periods_per_year / n) - 1.0 if total_growth > 0.0 else -1.0

    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * np.sqrt(periods_per_year)) if std > 0.0 else 0.0

    peak = np.maximum.accumulate(equity)
    max_dd = float((equity / peak - 1.0).min())
    return cagr, sharpe, max_dd


def stationary_block_bootstrap(
    returns: pd.Series,
    *,
    seed: int,
    n_samples: int = 1000,
    avg_block_len: int = 20,
    periods_per_year: int = _ANN,
) -> BootstrapReport:
    """Resample ``returns`` ``n_samples`` times and summarize the metric spread.

    Deterministic for a given ``seed``. ``avg_block_len`` sets the geometric mean
    block length (restart probability ``1/avg_block_len``). ``periods_per_year``
    is the annualization factor (default 252; crypto callers pass 365) — it never
    changes the resampling, only how each sample's cagr/sharpe is annualized.
    """
    clean = returns.dropna().to_numpy(dtype=float)
    n = len(clean)
    if n < 2:
        raise ValueError("stationary_block_bootstrap needs at least 2 returns")
    if avg_block_len < 1:
        raise ValueError("avg_block_len must be >= 1")

    p = 1.0 / avg_block_len
    rng = np.random.default_rng(seed)

    cagrs = np.empty(n_samples, dtype=float)
    sharpes = np.empty(n_samples, dtype=float)
    max_dds = np.empty(n_samples, dtype=float)
    for i in range(n_samples):
        idx = _resample_indices(n, p, rng)
        cagrs[i], sharpes[i], max_dds[i] = _sample_metrics(clean[idx], periods_per_year)

    return BootstrapReport(
        n_samples=n_samples,
        avg_block_len=avg_block_len,
        seed=seed,
        sample_length=n,
        cagr_p5=float(np.percentile(cagrs, 5)),
        cagr_p50=float(np.percentile(cagrs, 50)),
        cagr_p95=float(np.percentile(cagrs, 95)),
        sharpe_p5=float(np.percentile(sharpes, 5)),
        sharpe_p50=float(np.percentile(sharpes, 50)),
        sharpe_p95=float(np.percentile(sharpes, 95)),
        max_drawdown_p5=float(np.percentile(max_dds, 5)),
        max_drawdown_p50=float(np.percentile(max_dds, 50)),
        max_drawdown_p95=float(np.percentile(max_dds, 95)),
        prob_negative_cagr=float(np.mean(cagrs < 0.0)),
        prob_drawdown_worse_than_30pct=float(np.mean(max_dds < -0.30)),
    )


__all__ = ["stationary_block_bootstrap", "BootstrapReport"]
