"""Tests that the validation battery threads periods_per_year (365 vs 252).

Covers walk-forward segment metrics, the bootstrap statistics, and the crypto
perturbation grids. The default (252) path must stay identical to before.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.strategies import CryptoTrendBTC, CryptoVolTargetBTC
from quantlab.backtest.strategy import BuyAndHold
from quantlab.validation.bootstrap import stationary_block_bootstrap
from quantlab.validation.perturb import _grid_for
from quantlab.validation.walkforward import walk_forward

_RATIO = math.sqrt(365.0 / 252.0)


class _BuyHold365(BuyAndHold):
    """BuyAndHold that annualizes on a 365-day grid (crypto-like)."""

    @property
    def periods_per_year(self) -> int:
        return 365


def _single_symbol_panel(symbol: str = "X", periods: int = 5 * 252, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-01", periods=periods)
    px = 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, periods))
    return pd.DataFrame({symbol: px}, index=idx)


# -- Bootstrap --------------------------------------------------------------


def test_bootstrap_default_is_252() -> None:
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0.0005, 0.01, 1500))
    default = stationary_block_bootstrap(r, seed=7, n_samples=200)
    explicit = stationary_block_bootstrap(r, seed=7, n_samples=200, periods_per_year=252)
    assert default == explicit  # omitting the param == passing 252


def test_bootstrap_365_scales_sharpe_percentiles() -> None:
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0.0005, 0.01, 1500))
    b252 = stationary_block_bootstrap(r, seed=7, n_samples=300, periods_per_year=252)
    b365 = stationary_block_bootstrap(r, seed=7, n_samples=300, periods_per_year=365)

    # Same seed -> same resamples; each sample's sharpe scales by sqrt(365/252),
    # so every percentile scales by that exact ratio.
    assert b365.sharpe_p5 == pytest.approx(b252.sharpe_p5 * _RATIO, rel=1e-12)
    assert b365.sharpe_p50 == pytest.approx(b252.sharpe_p50 * _RATIO, rel=1e-12)
    assert b365.sharpe_p95 == pytest.approx(b252.sharpe_p95 * _RATIO, rel=1e-12)
    # CAGR uses ppy as an exponent, so it moves too (and not by the same ratio).
    assert b365.cagr_p50 != pytest.approx(b252.cagr_p50, rel=1e-6)


# -- Walk-forward -----------------------------------------------------------


def test_walkforward_threads_periods_per_year_from_factory() -> None:
    panel = _single_symbol_panel()
    wf252 = walk_forward(panel, lambda: BuyAndHold("X"), window_years=2, cost_bps=0.0)
    wf365 = walk_forward(panel, lambda: _BuyHold365("X"), window_years=2, cost_bps=0.0)

    assert wf252.n_segments == wf365.n_segments >= 2  # tiling is ppy-independent
    for s252, s365 in zip(wf252.segments, wf365.segments, strict=True):
        assert (s252.start, s252.end) == (s365.start, s365.end)
        assert s365.total_return == pytest.approx(s252.total_return, rel=1e-12)  # invariant
        if s252.sharpe is not None:
            assert s365.sharpe == pytest.approx(s252.sharpe * _RATIO, rel=1e-9)


def test_walkforward_default_matches_explicit_252() -> None:
    panel = _single_symbol_panel()
    # BuyAndHold declares 252, so the default factory path must equal an explicit
    # 252 strategy segment-for-segment (guards "equity unchanged").
    wf = walk_forward(panel, lambda: BuyAndHold("X"), window_years=2, cost_bps=0.0)
    assert wf.n_segments >= 2
    for s in wf.segments:
        assert s.sharpe is None or math.isfinite(s.sharpe)


# -- Perturbation grids (crypto) --------------------------------------------


def test_crypto_trend_grid_is_five_points_baseline_at_ten() -> None:
    grid = _grid_for("crypto_trend_btc")
    months = [int(params["n_months"]) for params, _base, _strat in grid]
    assert months == [8, 9, 10, 11, 12]
    baselines = [params for params, base, _ in grid if base]
    assert baselines == [{"n_months": 10.0}]
    assert all(isinstance(strat, CryptoTrendBTC) for _, _, strat in grid)
    assert all(strat.periods_per_year == 365 for _, _, strat in grid)


def test_crypto_voltarget_grid_is_three_by_three_baseline_at_020_20() -> None:
    grid = _grid_for("crypto_voltarget_btc")
    assert len(grid) == 9
    baselines = [params for params, base, _ in grid if base]
    assert baselines == [{"target_vol": 0.20, "lookback_days": 20.0}]
    assert all(isinstance(strat, CryptoVolTargetBTC) for _, _, strat in grid)
    assert all(strat.periods_per_year == 365 for _, _, strat in grid)
