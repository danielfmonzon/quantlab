"""Phase 5 validation battery: walk-forward, perturbation, block bootstrap (Batch 7).

These tests pin the REPORT-ONLY contract's mechanics: segment tiling and warmup,
the fixed perturbation grids and fragility rule, and deterministic bootstrapping.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.strategies import DualMomentum, TrendSMA10, VolTarget
from quantlab.backtest.strategy import BuyAndHold
from quantlab.validation.bootstrap import stationary_block_bootstrap
from quantlab.validation.perturb import (
    _DUALMOM_LOOKBACK,
    _TREND_N_MONTHS,
    _VOLTARGET_LOOKBACKS,
    _VOLTARGET_TARGETS,
    GridPoint,
    _assess_fragility,
    perturb,
)
from quantlab.validation.walkforward import walk_forward

# --------------------------------------------------------------------------- #
# Panel builders                                                              #
# --------------------------------------------------------------------------- #

def _const_growth_panel(
    symbol: str, start: str, end: str, daily_rate: float,
    extra: dict[str, float] | None = None,
) -> pd.DataFrame:
    """A panel where ``symbol`` compounds at a fixed daily rate; extras are flat."""
    dates = pd.bdate_range(start, end)
    n = len(dates)
    data = {symbol: 100.0 * (1.0 + daily_rate) ** np.arange(n)}
    for sym, level in (extra or {}).items():
        data[sym] = np.full(n, level, dtype=float)
    return pd.DataFrame(data, index=dates)


def _multi_symbol_panel(periods: int = 1300, seed: int = 1) -> pd.DataFrame:
    """A clean SPY/EFA/IEF panel (no gaps) long enough to warm up every grid."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2005-01-03", periods=periods)
    out: dict[str, np.ndarray] = {}
    for sym, mu, sd in [("SPY", 0.0004, 0.010), ("EFA", 0.0003, 0.011), ("IEF", 0.0001, 0.004)]:
        r = rng.normal(mu, sd, periods)
        out[sym] = 100.0 * np.cumprod(1.0 + r)
    return pd.DataFrame(out, index=dates)


# --------------------------------------------------------------------------- #
# Walk-forward                                                                #
# --------------------------------------------------------------------------- #

def test_nine_year_panel_splits_into_three_segments() -> None:
    panel = _const_growth_panel("A", "2000-01-03", "2008-12-31", 0.0003)
    report = walk_forward(panel, lambda: BuyAndHold("A"), window_years=3, cost_bps=0.0)
    assert report.n_segments == 3
    # 3-year edges land on Jan-3, so segments start 2000/2003/2006-01-03.
    assert [s.start.year for s in report.segments] == [2000, 2003, 2006]
    # Full coverage: first segment opens on the panel's first session, last closes
    # on its last, and segments are contiguous and non-overlapping.
    assert report.segments[0].start == panel.index[0].date()
    assert report.segments[-1].end == panel.index[-1].date()
    for earlier, later in zip(report.segments, report.segments[1:], strict=False):
        assert earlier.end < later.start
    # Each window spans ~3 calendar years (the tail is truncated by the panel end).
    assert all(2 <= s.end.year - s.start.year <= 3 for s in report.segments)


def test_segment_metrics_use_only_segment_returns() -> None:
    # A compounds at a constant daily rate, so each fully-invested segment's CAGR
    # must equal the annualized constant rate (metrics see the segment only).
    g = 0.0004
    panel = _const_growth_panel("A", "2000-01-03", "2008-12-31", g)
    report = walk_forward(panel, lambda: BuyAndHold("A"), window_years=3, cost_bps=0.0)
    analytic_cagr = (1.0 + g) ** 252 - 1.0
    for seg in report.segments:
        assert seg.cagr == pytest.approx(analytic_cagr, rel=2e-2)
    assert report.pct_segments_positive_return == 1.0
    assert report.pct_segments_beat_cash == 1.0


def test_warmup_buffer_makes_second_segment_live_from_first_session() -> None:
    # A rises; B (safe) is flat. Segment 0 starts cold (no prior data), so its
    # warmup months sit in the flat safe asset. Segment 1 (0-indexed) has a full
    # prior segment as warmup, so the SMA is live from its first session -- it
    # matches segment 2 (also warmed) and strictly beats the cold segment 0.
    panel = _const_growth_panel("A", "2000-01-03", "2008-12-31", 0.0005, extra={"B": 100.0})
    report = walk_forward(
        panel, lambda: TrendSMA10(risk_symbol="A", safe_symbol="B"),
        window_years=3, cost_bps=0.0,
    )
    assert report.n_segments == 3
    seg0, seg1, seg2 = report.segments
    assert seg1.total_return == pytest.approx(seg2.total_return, rel=0.05)  # both warmed
    assert seg0.total_return < seg1.total_return * 0.98  # cold start drags segment 0


# --------------------------------------------------------------------------- #
# Perturbation                                                                #
# --------------------------------------------------------------------------- #

def test_grids_are_exactly_the_specified_constants() -> None:
    assert _TREND_N_MONTHS == (8, 10, 12)
    assert _DUALMOM_LOOKBACK == (9, 12, 15)
    assert _VOLTARGET_TARGETS == (0.08, 0.10, 0.12)
    assert _VOLTARGET_LOOKBACKS == (15, 20, 25)


def test_perturb_marks_exactly_one_baseline() -> None:
    panel = _multi_symbol_panel()
    for name, expected in [
        ("trend", {"n_months": 10.0}),
        ("dualmom", {"lookback_months": 12.0}),
        ("voltarget", {"target_vol": 0.10, "lookback_days": 20.0}),
    ]:
        report = perturb(name, panel, cost_bps=5.0)
        baselines = [g for g in report.grid if g.is_baseline]
        assert len(baselines) == 1
        assert baselines[0].params == expected


def test_voltarget_grid_is_the_full_three_by_three() -> None:
    panel = _multi_symbol_panel()
    report = perturb("voltarget", panel, cost_bps=5.0)
    assert len(report.grid) == 9


def test_trend_and_dualmom_grids_have_three_points() -> None:
    panel = _multi_symbol_panel()
    assert len(perturb("trend", panel).grid) == 3
    assert len(perturb("dualmom", panel).grid) == 3


def _gp(sharpe: float | None, cagr: float, baseline: bool) -> GridPoint:
    return GridPoint(
        params={"x": 1.0}, is_baseline=baseline, cagr=cagr,
        sharpe=sharpe, max_drawdown=-0.1,
    )


def test_fragility_triggers_when_baseline_sharpe_dominates() -> None:
    baseline = _gp(1.00, 0.10, True)
    grid = [_gp(0.50, 0.09, False), baseline, _gp(0.60, 0.11, False)]
    flag, reason = _assess_fragility(baseline, grid)
    assert flag is True
    assert "beats best neighbor" in reason


def test_fragility_triggers_on_cagr_sign_flip() -> None:
    baseline = _gp(0.70, 0.10, True)
    grid = [_gp(0.68, -0.05, False), baseline, _gp(0.72, 0.11, False)]
    flag, reason = _assess_fragility(baseline, grid)
    assert flag is True
    assert "sign differs" in reason


def test_fragility_false_on_flat_grid() -> None:
    baseline = _gp(0.70, 0.10, True)
    grid = [_gp(0.68, 0.09, False), baseline, _gp(0.72, 0.11, False)]
    flag, reason = _assess_fragility(baseline, grid)
    assert flag is False
    assert "robust" in reason


def test_parameter_injection_preserves_literature_defaults() -> None:
    assert TrendSMA10().n_months == 10
    assert TrendSMA10().name == "trend_sma10"
    assert DualMomentum().lookback_months == 12
    assert VolTarget().target_vol == 0.10
    assert VolTarget().lookback_days == 20
    # Injection still works (this is what perturb relies on) without touching defaults.
    assert TrendSMA10(n_months=8).n_months == 8
    assert VolTarget(target_vol=0.12, lookback_days=25).lookback_days == 25


# --------------------------------------------------------------------------- #
# Block bootstrap                                                             #
# --------------------------------------------------------------------------- #

def _iid_returns(n: int, mu: float, sd: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mu, sd, n))


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    r = _iid_returns(1500, 0.0004, 0.01, seed=0)
    a = stationary_block_bootstrap(r, seed=7, n_samples=200)
    b = stationary_block_bootstrap(r, seed=7, n_samples=200)
    assert a == b  # exact structural equality


def test_bootstrap_differs_across_seeds() -> None:
    r = _iid_returns(1500, 0.0004, 0.01, seed=0)
    a = stationary_block_bootstrap(r, seed=7, n_samples=200)
    c = stationary_block_bootstrap(r, seed=8, n_samples=200)
    assert a != c


def test_bootstrap_preserves_sample_length() -> None:
    r = _iid_returns(1234, 0.0004, 0.01, seed=3)
    report = stationary_block_bootstrap(r, seed=1, n_samples=100)
    assert report.sample_length == 1234


def test_bootstrap_sharpe_interval_brackets_analytic() -> None:
    # iid N(0.0004, 0.01) -> analytic annualized Sharpe = 0.0004/0.01*sqrt(252).
    r = _iid_returns(4000, 0.0004, 0.01, seed=11)
    report = stationary_block_bootstrap(r, seed=42, n_samples=500)
    analytic = 0.0004 / 0.01 * np.sqrt(252)
    assert report.sharpe_p5 <= analytic <= report.sharpe_p95
    assert 0.0 <= report.prob_negative_cagr <= 1.0


def test_bootstrap_requires_seed_and_enough_data() -> None:
    with pytest.raises(ValueError):
        stationary_block_bootstrap(pd.Series([0.01]), seed=1)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def test_validate_strategy_rejects_unknown_name() -> None:
    from quantlab.cli import cmd_validate_strategy
    from quantlab.config import ConfigError

    args = argparse.Namespace(strategy="bogus", start=None, cost_bps=5.0, seed=42)
    with pytest.raises(ConfigError, match="validate-strategy supports"):
        cmd_validate_strategy(args)
