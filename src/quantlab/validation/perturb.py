"""Parameter-perturbation robustness: full-period metrics on a neighbor grid.

REPORT-ONLY (see the package docstring). The grids below are FIXED constants —
not arguments — precisely so no caller can widen them, tune within them, or feed
the "best" neighbor back into the strategy. The literature baseline is marked and
always stands; the grid exists only to FLAG fragility, never to pick a winner.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.metrics import compute_metrics
from quantlab.backtest.strategies import (
    CryptoTrendBTC,
    CryptoVolTargetBTC,
    DualMomentum,
    TrendSMA10,
    VolTarget,
)
from quantlab.backtest.strategy import Strategy
from quantlab.data import DataError

# --- FIXED neighbor grids (immutable; the baseline is the cited constant) ------
_TREND_N_MONTHS = (8, 10, 12)  # Faber baseline: 10
_DUALMOM_LOOKBACK = (9, 12, 15)  # Antonacci baseline: 12
_VOLTARGET_TARGETS = (0.08, 0.10, 0.12)  # baseline: 0.10
_VOLTARGET_LOOKBACKS = (15, 20, 25)  # baseline: 20

# Crypto research strategies. The iron rule forbids TUNING, not robustness testing:
# these grids only probe a sensible neighborhood around the pre-registered values
# to FLAG fragility. The pre-registered baselines (SMA 10; 20% target vol, 20-day
# window) stand regardless of what any neighbor shows.
_CRYPTO_TREND_N_MONTHS = (8, 9, 10, 11, 12)  # pre-registered baseline: 10
_CRYPTO_VOLTARGET_TARGETS = (0.15, 0.20, 0.25)  # pre-registered baseline: 0.20
_CRYPTO_VOLTARGET_LOOKBACKS = (15, 20, 25)  # pre-registered baseline: 20

# A baseline neighbor whose Sharpe beats every neighbor by more than this margin
# is the signature of a parameter that would have been overfit had we tuned it.
_SHARPE_FRAGILITY_MARGIN = 0.15


class GridPoint(BaseModel):
    """One grid point's full-period metrics."""

    params: dict[str, float]
    is_baseline: bool
    cagr: float
    sharpe: float | None
    max_drawdown: float


class PerturbReport(BaseModel):
    """Neighbor-grid metrics and the fragility verdict for one strategy."""

    strategy: str
    grid: list[GridPoint]
    baseline_sharpe: float | None
    baseline_cagr: float | None
    fragility_flag: bool
    fragility_reason: str


def _grid_for(strategy_name: str) -> list[tuple[dict[str, float], bool, Strategy]]:
    """Return (params, is_baseline, strategy) for every point in the fixed grid."""
    if strategy_name == "trend":
        return [
            ({"n_months": float(n)}, n == 10, TrendSMA10(n_months=n))
            for n in _TREND_N_MONTHS
        ]
    if strategy_name == "dualmom":
        return [
            ({"lookback_months": float(n)}, n == 12, DualMomentum(lookback_months=n))
            for n in _DUALMOM_LOOKBACK
        ]
    if strategy_name == "voltarget":
        points: list[tuple[dict[str, float], bool, Strategy]] = []
        for tv in _VOLTARGET_TARGETS:
            for ld in _VOLTARGET_LOOKBACKS:
                params = {"target_vol": tv, "lookback_days": float(ld)}
                is_base = tv == 0.10 and ld == 20
                points.append((params, is_base, VolTarget(target_vol=tv, lookback_days=ld)))
        return points
    if strategy_name == "crypto_trend_btc":
        return [
            ({"n_months": float(n)}, n == 10, CryptoTrendBTC(n_months=n))
            for n in _CRYPTO_TREND_N_MONTHS
        ]
    if strategy_name == "crypto_voltarget_btc":
        cpoints: list[tuple[dict[str, float], bool, Strategy]] = []
        for tv in _CRYPTO_VOLTARGET_TARGETS:
            for ld in _CRYPTO_VOLTARGET_LOOKBACKS:
                params = {"target_vol": tv, "lookback_days": float(ld)}
                is_base = tv == 0.20 and ld == 20
                cpoints.append(
                    (params, is_base, CryptoVolTargetBTC(target_vol=tv, lookback_days=ld))
                )
        return cpoints
    raise DataError(f"perturb: no fixed grid for strategy {strategy_name!r}")


def perturb(strategy_name: str, panel: pd.DataFrame, cost_bps: float = 5.0) -> PerturbReport:
    """Backtest every fixed-grid neighbor over the full ``panel`` and flag fragility."""
    grid: list[GridPoint] = []
    baseline: GridPoint | None = None
    for params, is_baseline, strategy in _grid_for(strategy_name):
        result = run_backtest(panel, strategy, cost_bps=cost_bps)
        m = compute_metrics(
            result.daily_returns, result.equity,
            periods_per_year=strategy.periods_per_year,
        )
        point = GridPoint(
            params=params,
            is_baseline=is_baseline,
            cagr=m.cagr,
            sharpe=m.sharpe,
            max_drawdown=m.max_drawdown,
        )
        grid.append(point)
        if is_baseline:
            baseline = point

    flag, reason = _assess_fragility(baseline, grid)
    return PerturbReport(
        strategy=strategy_name,
        grid=grid,
        baseline_sharpe=baseline.sharpe if baseline else None,
        baseline_cagr=baseline.cagr if baseline else None,
        fragility_flag=flag,
        fragility_reason=reason,
    )


def _assess_fragility(baseline: GridPoint | None, grid: list[GridPoint]) -> tuple[bool, str]:
    if baseline is None:
        return False, "no baseline in grid"

    reasons: list[str] = []
    neighbors = [g for g in grid if not g.is_baseline]

    neighbor_sharpes = [g.sharpe for g in neighbors if g.sharpe is not None]
    if baseline.sharpe is not None and neighbor_sharpes:
        best_neighbor = max(neighbor_sharpes)
        if baseline.sharpe - best_neighbor > _SHARPE_FRAGILITY_MARGIN:
            reasons.append(
                f"baseline sharpe {baseline.sharpe:.2f} beats best neighbor "
                f"{best_neighbor:.2f} by > {_SHARPE_FRAGILITY_MARGIN} "
                "(edge concentrated on the exact literature value)"
            )

    base_positive = baseline.cagr > 0.0
    sign_flippers = [g for g in neighbors if (g.cagr > 0.0) != base_positive]
    if sign_flippers:
        flipped = ", ".join(
            f"{g.params} cagr {g.cagr:.2%}" for g in sign_flippers
        )
        reasons.append(
            f"neighbor CAGR sign differs from baseline ({baseline.cagr:.2%}): {flipped}"
        )

    if reasons:
        return True, "; ".join(reasons)
    return False, "robust: neighbors within margin and no CAGR sign change"


__all__ = ["perturb", "PerturbReport", "GridPoint"]
